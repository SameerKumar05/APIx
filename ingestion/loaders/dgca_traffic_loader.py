"""DGCA Passenger Traffic Loader for APIx.

Automated parser, historical time-series provider, and dynamic weight calculator
for Directorate General of Civil Aviation (DGCA) monthly city-pair scheduled
domestic passenger traffic reports across 2024-2026.

Calibrates the 10 trunk Indian domestic corridors and dynamically computes
national basket weights (summing to 1.000000) for Paasche, Fisher Ideal,
and Laspeyres airfare index formulation.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.app.db.session import Base, SessionLocal
from backend.app.models.route import Route
from ingestion.loaders.traffic_provenance import (
    declared_token,
    resolve_traffic_provenance,
    split_provenance_directive,
)

logger = logging.getLogger("ingestion.loaders.dgca_traffic")


# ============================================================================
# Corridor Reference Metadata
# ============================================================================

TRUNK_CORRIDORS: list[dict[str, Any]] = [
    {
        "origin": "DEL",
        "destination": "BOM",
        "distance_km": 1148.0,
        "base_pax": 437500,
        "base_weight": 0.175,
    },
    {
        "origin": "BOM",
        "destination": "DEL",
        "distance_km": 1148.0,
        "base_pax": 437500,
        "base_weight": 0.175,
    },
    {
        "origin": "DEL",
        "destination": "BLR",
        "distance_km": 1740.0,
        "base_pax": 312500,
        "base_weight": 0.125,
    },
    {
        "origin": "BLR",
        "destination": "DEL",
        "distance_km": 1740.0,
        "base_pax": 312500,
        "base_weight": 0.125,
    },
    {
        "origin": "BOM",
        "destination": "BLR",
        "distance_km": 842.0,
        "base_pax": 225000,
        "base_weight": 0.090,
    },
    {
        "origin": "BLR",
        "destination": "BOM",
        "distance_km": 842.0,
        "base_pax": 225000,
        "base_weight": 0.090,
    },
    {
        "origin": "DEL",
        "destination": "CCU",
        "distance_km": 1305.0,
        "base_pax": 162500,
        "base_weight": 0.065,
    },
    {
        "origin": "CCU",
        "destination": "DEL",
        "distance_km": 1305.0,
        "base_pax": 162500,
        "base_weight": 0.065,
    },
    {
        "origin": "DEL",
        "destination": "HYD",
        "distance_km": 1253.0,
        "base_pax": 112500,
        "base_weight": 0.045,
    },
    {
        "origin": "HYD",
        "destination": "DEL",
        "distance_km": 1253.0,
        "base_pax": 112500,
        "base_weight": 0.045,
    },
]

CORRIDOR_DISTANCE_MAP: dict[str, float] = {
    f"{c['origin']}-{c['destination']}": c["distance_km"] for c in TRUNK_CORRIDORS
}


# ============================================================================
# Pydantic Schema
# ============================================================================


class DgcaTrafficRecord(BaseModel):
    """Pydantic model representing a single corridor's monthly DGCA traffic statistic."""

    year_month: str = Field(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="DGCA reporting month in format YYYY-MM (e.g. 2026-03)",
    )
    origin: str = Field(
        ..., min_length=3, max_length=3, description="Origin airport IATA code"
    )
    destination: str = Field(
        ..., min_length=3, max_length=3, description="Destination airport IATA code"
    )
    pax_volume: int = Field(
        ..., ge=0, description="Monthly passenger traffic volume recorded by DGCA"
    )
    share_weight: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Corridor normalized share weight of national monitored basket (sums to 1.0)",
    )
    distance_km: float = Field(
        ..., gt=0, description="Great-circle flight distance in kilometers"
    )
    period_rank: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Volume ranking within month (1 = highest)",
    )
    route_code: str = Field(default="", description="IATA corridor code e.g. DEL-BOM")
    is_synthetic: bool = Field(
        default=True,
        description=(
            "True when the volumes were modelled rather than read from a DGCA release. "
            "Modelled weights are usable for development and for asserting index mechanics, "
            "but they are not official statistics and must not be presented as such."
        ),
    )
    provenance: str = Field(
        default="modelled",
        description="File declaration: DGCA, generated, or modelled. Absent means modelled.",
    )
    source: str = Field(
        default="",
        description="Provenance string: the DGCA publication and retrieval date, or the generator name.",
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.route_code:
            self.route_code = f"{self.origin.upper()}-{self.destination.upper()}"
        else:
            self.route_code = self.route_code.upper()

    @property
    def period(self) -> str:
        """Alias for year_month."""
        return self.year_month

    @property
    def route_tuple(self) -> tuple[str, str]:
        """Corridor as (origin, destination) tuple."""
        return (self.origin.upper(), self.destination.upper())

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary."""
        return {
            "year_month": self.year_month,
            "route_code": self.route_code,
            "origin": self.origin,
            "destination": self.destination,
            "pax_volume": self.pax_volume,
            "share_weight": round(self.share_weight, 6),
            "distance_km": self.distance_km,
            "period_rank": self.period_rank,
            "is_synthetic": self.is_synthetic,
            "provenance": self.provenance,
            "source": self.source,
        }

    def to_stats_dict(self) -> dict[str, Any]:
        """Format for econometric engine."""
        return {
            "route_code": self.route_code,
            "period": self.year_month,
            "pax": self.pax_volume,
            "weight": self.share_weight,
            "distance_km": self.distance_km,
        }


# ============================================================================
# Built-in Series Generator (2024-01 to 2026-03)
# ============================================================================

# Monthly seasonality multipliers for Indian domestic civil aviation
MONTHLY_SEASONAL_FACTORS: dict[int, float] = {
    1: 1.01,  # January: winter holidays / corporate travel restart
    2: 0.96,  # February: shorter month (28/29 days)
    3: 1.02,  # March: Q4 financial year-end corporate travel
    4: 1.04,  # April: onset of summer vacation
    5: 1.10,  # May: peak domestic summer holiday rush
    6: 1.07,  # June: summer vacation return travel
    7: 0.91,  # July: monsoon low season
    8: 0.93,  # August: monsoon low, Independence Day long weekend
    9: 0.96,  # September: pre-festive preparation
    10: 1.12,  # October: Durga Puja, Dussehra, Diwali rush
    11: 1.09,  # November: Diwali peak, wedding season
    12: 1.14,  # December: winter vacation, Christmas/New Year peak
}

# Base annual compound growth rate for Indian aviation (2024 to 2026 ~8% CAGR)
ANNUAL_GROWTH_RATE: float = 0.082


def _generate_builtin_dgca_series() -> list[DgcaTrafficRecord]:
    """Generate a MODELLED 27-month city-pair traffic series (2024-01 to 2026-03).

    This is not DGCA data. Volumes are derived from the base corridor figures in
    TRUNK_CORRIDORS multiplied by a secular trend and seasonal factors, then the
    share weights are normalised so each month sums to exactly 1.000000. Every
    record it produces is marked ``is_synthetic=True`` so no downstream consumer
    can mistake these weights for an official DGCA release.

    DGCA does publish real monthly city-pair passenger traffic as free XLSX with no
    login required. Point DgcaTrafficLoader at such a file to obtain sourced weights.
    """
    all_records: list[DgcaTrafficRecord] = []

    # 27 reporting periods
    periods: list[str] = []
    for y in (2024, 2025):
        for m in range(1, 13):
            periods.append(f"{y:04d}-{m:02d}")
    for m in range(1, 4):
        periods.append(f"2026-{m:02d}")

    # Base year reference is 2024-01 (t=0)
    for _t_idx, ym in enumerate(periods):
        year, month = int(ym[:4]), int(ym[5:7])

        # Compounded secular growth factor
        years_elapsed = (year - 2024) + (month - 1) / 12.0
        secular_multiplier = (1.0 + ANNUAL_GROWTH_RATE) ** years_elapsed

        # Seasonal multiplier
        season_multiplier = MONTHLY_SEASONAL_FACTORS.get(month, 1.0)

        # Generate passenger volumes for this period
        period_corridors: list[dict[str, Any]] = []
        for c in TRUNK_CORRIDORS:
            origin = c["origin"]
            dest = c["destination"]
            route_code = f"{origin}-{dest}"

            # Route specific seasonal nuances
            route_season_adj = 1.0
            if "CCU" in (origin, dest) and month in (9, 10):
                # Durga Puja surge for Kolkata corridors
                route_season_adj = 1.08
            elif "BLR" in (origin, dest) and month in (2, 3, 11):
                # Tech / Corporate surge for Bengaluru
                route_season_adj = 1.04

            # Base volume scaled
            raw_pax = int(
                round(
                    c["base_pax"]
                    * secular_multiplier
                    * season_multiplier
                    * route_season_adj
                )
            )
            period_corridors.append(
                {
                    "origin": origin,
                    "destination": dest,
                    "route_code": route_code,
                    "distance_km": c["distance_km"],
                    "pax_volume": raw_pax,
                }
            )

        # Calculate exact total monthly passenger volume
        total_pax = sum(item["pax_volume"] for item in period_corridors)
        if total_pax <= 0:
            total_pax = 1

        # Calculate normalized weights with exact sum = 1.000000
        # Sort by pax descending
        period_corridors.sort(key=lambda x: x["pax_volume"], reverse=True)

        raw_weights: list[float] = [
            round(item["pax_volume"] / total_pax, 6) for item in period_corridors
        ]
        diff = round(1.0 - sum(raw_weights), 6)
        if diff != 0.0:
            # Adjust the highest volume route (index 0) to ensure exact 1.000000 sum
            raw_weights[0] = round(raw_weights[0] + diff, 6)

        # Build DgcaTrafficRecord items
        for rank_idx, (item, weight) in enumerate(
            zip(period_corridors, raw_weights, strict=False), start=1
        ):
            record = DgcaTrafficRecord(
                year_month=ym,
                origin=item["origin"],
                destination=item["destination"],
                route_code=item["route_code"],
                pax_volume=item["pax_volume"],
                share_weight=weight,
                distance_km=item["distance_km"],
                period_rank=rank_idx,
                is_synthetic=True,
                provenance="generated",
                source=(
                    "MODELLED by ingestion/loaders/dgca_traffic_loader.py::_generate_builtin_dgca_series "
                    "(base volumes x secular trend x seasonality, weights normalised to 1.0). "
                    "Not a DGCA release."
                ),
            )
            all_records.append(record)

    return all_records


# ============================================================================
# DGCA Traffic Loader Class
# ============================================================================


class DgcaTrafficLoader:
    """Automated parser and dynamic weight loader for DGCA city-pair traffic reports."""

    def __init__(self, data_path: str | Path | None = None) -> None:
        """Initialize DGCA Traffic Loader.

        Args:
            data_path: Optional path to an external CSV or JSON file of DGCA city-pair traffic.
                       When absent, the loader falls back to a MODELLED series whose records are
                       flagged is_synthetic=True. Check loader.provenance before treating any
                       weight as an official statistic.
        """
        self.data_path = Path(data_path) if data_path else None
        self._records: list[DgcaTrafficRecord] = []
        self._records_by_period: dict[str, list[DgcaTrafficRecord]] = {}
        self._weights_by_period: dict[str, dict[str, float]] = {}

        if self.data_path and self.data_path.exists():
            if self.data_path.suffix.lower() == ".json":
                self._records = self.parse_json(self.data_path)
            else:
                self._records = self.parse_csv(self.data_path)
        else:
            logger.warning(
                "No DGCA traffic file supplied; falling back to MODELLED city-pair weights "
                "(is_synthetic=True). These are not official DGCA statistics. DGCA publishes "
                "monthly city-pair traffic as free XLSX with no login; pass data_path to use it."
            )
            self._records = _generate_builtin_dgca_series()

        self._index_records()

    @property
    def provenance(self) -> dict[str, Any]:
        """Where the loaded weights came from, and whether they are official.

        Downstream consumers and the API should surface this so a modelled series is
        never presented as a DGCA statistic.
        """
        synthetic = {r.is_synthetic for r in self._records}
        sources = sorted({r.source for r in self._records if r.source})
        return {
            "is_synthetic": synthetic == {True},
            "record_count": len(self._records),
            "period_count": len(self._records_by_period),
            "first_period": min((r.year_month for r in self._records), default=None),
            "last_period": max((r.year_month for r in self._records), default=None),
            "sources": sources,
            "data_path": str(self.data_path) if self.data_path else None,
        }

    def _index_records(self) -> None:
        """Organize records by period and precalculate corridor weight maps."""
        self._records.sort(key=lambda r: (r.year_month, -r.pax_volume))
        self._records_by_period = {}
        self._weights_by_period = {}

        for r in self._records:
            self._records_by_period.setdefault(r.year_month, []).append(r)

        # Precompute normalized weight dictionary for each period
        for ym, recs in self._records_by_period.items():
            self._weights_by_period[ym] = {r.route_code: r.share_weight for r in recs}

    # ------------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------------

    def parse_csv(
        self, csv_source: str | Path | io.StringIO
    ) -> list[DgcaTrafficRecord]:
        """Parse DGCA traffic records from CSV file path, string content, or StringIO buffer.

        Automatically computes normalized share weights if missing or not summing to 1.0.
        Supports header aliases:
        - Period: year_month, period, month, reporting_month, date
        - Corridor: route_code, route, corridor, city_pair
        - Origin: origin, source, from, origin_iata
        - Destination: destination, dest, to, dest_iata
        - Passenger volume: pax_volume, pax, passengers, traffic, monthly_pax
        - Distance: distance_km, distance, dist_km
        - Weight: share_weight, weight, basket_weight
        """
        if isinstance(csv_source, Path) or (
            isinstance(csv_source, str)
            and "\n" not in csv_source
            and Path(csv_source).exists()
        ):
            with open(csv_source, encoding="utf-8") as f:
                content = f.read()
        elif isinstance(csv_source, io.StringIO):
            content = csv_source.getvalue()
        else:
            content = str(csv_source)

        file_declared, content = split_provenance_directive(content)
        reader = csv.DictReader(io.StringIO(content.strip()))
        if not reader.fieldnames:
            raise ValueError("CSV is empty or missing headers")

        raw_rows_by_period: dict[str, list[dict[str, Any]]] = {}

        for raw_row in reader:
            row = {k.strip().lower(): v.strip() for k, v in raw_row.items() if k}

            # 1. Period
            ym = (
                row.get("year_month")
                or row.get("period")
                or row.get("month")
                or row.get("date", "")[:7]
            )
            if not ym or len(ym) < 7:
                continue
            ym = ym[:7]

            # 2. Origin & Destination
            route_code = (
                row.get("route_code")
                or row.get("route")
                or row.get("corridor")
                or row.get("city_pair")
            )
            origin = (
                row.get("origin")
                or row.get("source")
                or row.get("from")
                or row.get("origin_iata")
            )
            dest = (
                row.get("destination")
                or row.get("dest")
                or row.get("to")
                or row.get("dest_iata")
            )

            if not origin or not dest:
                if route_code and "-" in route_code:
                    parts = route_code.split("-")
                    origin, dest = parts[0].strip().upper(), parts[1].strip().upper()
                else:
                    continue
            else:
                origin, dest = origin.strip().upper(), dest.strip().upper()
                if not route_code:
                    route_code = f"{origin}-{dest}"

            route_code = route_code.upper()

            # 3. Passenger volume
            pax_str = (
                row.get("pax_volume")
                or row.get("pax")
                or row.get("passengers")
                or row.get("traffic")
                or row.get("monthly_pax")
                or "0"
            )
            pax = int(float(pax_str))

            # 4. Distance
            dist_str = (
                row.get("distance_km") or row.get("distance") or row.get("dist_km")
            )
            distance = (
                float(dist_str)
                if dist_str
                else CORRIDOR_DISTANCE_MAP.get(route_code, 1000.0)
            )

            # 5. Share weight (optional)
            w_str = (
                row.get("share_weight") or row.get("weight") or row.get("basket_weight")
            )
            share_weight = float(w_str) if w_str else None

            token = declared_token(
                row.get("provenance"), row.get("is_synthetic"), file_declared
            )
            prov = resolve_traffic_provenance(token)
            raw_rows_by_period.setdefault(ym, []).append(
                {
                    "origin": origin,
                    "destination": dest,
                    "route_code": route_code,
                    "pax_volume": pax,
                    "distance_km": distance,
                    "share_weight": share_weight,
                    "is_synthetic": prov.is_synthetic,
                    "provenance": prov.label,
                }
            )

        # Process and normalize each period
        records: list[DgcaTrafficRecord] = []
        for ym, items in sorted(raw_rows_by_period.items()):
            items.sort(key=lambda x: x["pax_volume"], reverse=True)
            total_pax = sum(x["pax_volume"] for x in items) or 1

            # Check if existing weights sum to 1.0 within tolerance
            has_valid_weights = (
                all(x["share_weight"] is not None for x in items)
                and abs(sum(x["share_weight"] for x in items) - 1.0) < 0.001
            )

            if not has_valid_weights:
                weights = [round(x["pax_volume"] / total_pax, 6) for x in items]
                diff = round(1.0 - sum(weights), 6)
                if diff != 0.0 and weights:
                    weights[0] = round(weights[0] + diff, 6)
            else:
                weights = [x["share_weight"] for x in items]
            for rank, (item, weight) in enumerate(
                zip(items, weights, strict=False), start=1
            ):
                rec = DgcaTrafficRecord(
                    year_month=ym,
                    origin=item["origin"],
                    destination=item["destination"],
                    route_code=item["route_code"],
                    pax_volume=item["pax_volume"],
                    share_weight=weight,
                    distance_km=item["distance_km"],
                    period_rank=rank,
                    is_synthetic=item["is_synthetic"],
                    provenance=item["provenance"],
                    source=self._source_for(item["provenance"], item["is_synthetic"]),
                )
                records.append(rec)

        return records

    def _source_for(self, provenance: str, is_synthetic: bool) -> str:
        if is_synthetic:
            return f"MODELLED {provenance} file: {self.data_path}. Not a DGCA release."
        return f"DGCA city-pair traffic file: {self.data_path}"

    def parse_json(
        self, json_source: str | Path | list[dict[str, Any]] | dict[str, Any]
    ) -> list[DgcaTrafficRecord]:
        """Parse DGCA traffic records from JSON file path, string, or Python list/dict."""
        if isinstance(json_source, Path) or (
            isinstance(json_source, str)
            and "\n" not in json_source
            and Path(json_source).exists()
        ):
            with open(json_source, encoding="utf-8") as f:
                data = json.load(f)
        elif isinstance(json_source, str):
            data = json.loads(json_source)
        else:
            data = json_source

        file_declared = data.get("provenance") if isinstance(data, dict) else None
        raw_list = (
            data
            if isinstance(data, list)
            else data.get("records", data.get("data", []))
        )
        if not isinstance(raw_list, list):
            raise ValueError("Expected JSON array of traffic records")

        # Reuse parse_csv normalization logic by converting to dict entries
        raw_rows_by_period: dict[str, list[dict[str, Any]]] = {}
        for item in raw_list:
            ym = (
                item.get("year_month") or item.get("period") or item.get("date", "")[:7]
            )
            if not ym or len(ym) < 7:
                continue
            ym = ym[:7]

            origin = item.get("origin")
            dest = item.get("destination")
            route_code = item.get("route_code")
            if not origin or not dest:
                if route_code and "-" in route_code:
                    origin, dest = route_code.split("-", 1)
                else:
                    continue

            origin = origin.strip().upper()
            dest = dest.strip().upper()
            route_code = f"{origin}-{dest}"
            pax = int(item.get("pax_volume") or item.get("pax", 0))
            dist = float(
                item.get("distance_km") or CORRIDOR_DISTANCE_MAP.get(route_code, 1000.0)
            )
            w = item.get("share_weight") or item.get("weight")
            share_weight = float(w) if w is not None else None

            token = declared_token(
                None if item.get("provenance") is None else str(item.get("provenance")),
                (
                    None
                    if item.get("is_synthetic") is None
                    else str(item.get("is_synthetic"))
                ),
                None if file_declared is None else str(file_declared),
            )
            prov = resolve_traffic_provenance(token)
            raw_rows_by_period.setdefault(ym, []).append(
                {
                    "origin": origin,
                    "destination": dest,
                    "route_code": route_code,
                    "pax_volume": pax,
                    "distance_km": dist,
                    "share_weight": share_weight,
                    "is_synthetic": prov.is_synthetic,
                    "provenance": prov.label,
                }
            )

        records: list[DgcaTrafficRecord] = []
        for ym, items in sorted(raw_rows_by_period.items()):
            items.sort(key=lambda x: x["pax_volume"], reverse=True)
            total_pax = sum(x["pax_volume"] for x in items) or 1
            has_valid = (
                all(x["share_weight"] is not None for x in items)
                and abs(sum(x["share_weight"] for x in items) - 1.0) < 0.001
            )
            if not has_valid:
                weights = [round(x["pax_volume"] / total_pax, 6) for x in items]
                diff = round(1.0 - sum(weights), 6)
                if diff != 0.0 and weights:
                    weights[0] = round(weights[0] + diff, 6)
            else:
                weights = [x["share_weight"] for x in items]
            for rank, (item, weight) in enumerate(
                zip(items, weights, strict=False), start=1
            ):
                rec = DgcaTrafficRecord(
                    year_month=ym,
                    origin=item["origin"],
                    destination=item["destination"],
                    route_code=item["route_code"],
                    pax_volume=item["pax_volume"],
                    share_weight=weight,
                    distance_km=item["distance_km"],
                    period_rank=rank,
                    is_synthetic=item["is_synthetic"],
                    provenance=item["provenance"],
                    source=self._source_for(item["provenance"], item["is_synthetic"]),
                )
                records.append(rec)

        return records

    # ------------------------------------------------------------------------
    # Data Accessors & Weight Calculations
    # ------------------------------------------------------------------------

    def get_latest_period(self) -> str:
        """Return the most recent reporting period available (e.g. '2026-03')."""
        if not self._records:
            raise ValueError("No DGCA traffic records loaded")
        return self._records[-1].year_month

    def get_route_weights(self, period: str | None = None) -> dict[str, float]:
        """Retrieve normalized corridor weights for a specific period or latest period.

        Format: {"DEL-BOM": 0.174825, "BOM-DEL": 0.174825, ...}
        Guaranteed to sum to 1.000000.

        Args:
            period: Target reporting month in format 'YYYY-MM'. Defaults to latest.

        Returns:
            Dictionary mapping route code string to normalized float weight.
        """
        target_ym = period.strip()[:7] if period else self.get_latest_period()
        weights = self._weights_by_period.get(target_ym)
        if not weights:
            # Fallback to closest or latest
            target_ym = self.get_latest_period()
            weights = self._weights_by_period.get(target_ym, {})
        return dict(weights)

    def get_tuple_route_weights(
        self, period: str | None = None
    ) -> dict[tuple[str, str], float]:
        """Retrieve weights keyed by (origin, destination) airport IATA tuple.

        Format: {("DEL", "BOM"): 0.174825, ...}
        """
        route_weights = self.get_route_weights(period)
        tuple_weights: dict[tuple[str, str], float] = {}
        for r_code, w in route_weights.items():
            if "-" in r_code:
                orig, dest = r_code.split("-", 1)
                tuple_weights[(orig, dest)] = w
        return tuple_weights

    def get_period_traffic(self, period: str) -> list[DgcaTrafficRecord]:
        """Return all traffic records for a specific reporting month sorted by volume descending."""
        clean_ym = period.strip()[:7]
        return list(self._records_by_period.get(clean_ym, []))

    def get_all_period_weights(self) -> dict[str, dict[str, float]]:
        """Return nested dictionary of weights for all available periods: {period: {route_code: weight}}."""
        return {ym: dict(weights) for ym, weights in self._weights_by_period.items()}

    def get_corridor_growth_rate(
        self, route_code: str, period_from: str, period_to: str
    ) -> float:
        """Calculate percentage growth in passenger traffic volume for a corridor between two periods."""
        r_clean = route_code.strip().upper()
        p_from_recs = {
            r.route_code: r.pax_volume for r in self.get_period_traffic(period_from)
        }
        p_to_recs = {
            r.route_code: r.pax_volume for r in self.get_period_traffic(period_to)
        }

        v_from = p_from_recs.get(r_clean)
        v_to = p_to_recs.get(r_clean)

        if v_from is None or v_to is None or v_from <= 0:
            raise ValueError(
                f"Insufficient traffic data for corridor '{route_code}' between {period_from} and {period_to}"
            )

        return ((v_to - v_from) / v_from) * 100.0

    def get_total_monthly_pax(self, period: str) -> int:
        """Calculate total monitored domestic passenger traffic across all corridors for a period."""
        recs = self.get_period_traffic(period)
        return sum(r.pax_volume for r in recs)

    def get_network_summary(self) -> dict[str, Any]:
        """Return high-level summary of the monitored domestic corridor network."""
        latest_ym = self.get_latest_period()
        latest_recs = self.get_period_traffic(latest_ym)
        total_pax = sum(r.pax_volume for r in latest_recs)

        return {
            "latest_period": latest_ym,
            "total_periods": len(self._records_by_period),
            "corridors_monitored": len(latest_recs),
            "total_monthly_pax": total_pax,
            "top_corridor": latest_recs[0].route_code if latest_recs else None,
            "top_corridor_pax": latest_recs[0].pax_volume if latest_recs else 0,
            "top_corridor_weight": latest_recs[0].share_weight if latest_recs else 0.0,
            "sum_of_weights": round(sum(r.share_weight for r in latest_recs), 6),
        }

    # ------------------------------------------------------------------------
    # Serialization & Export
    # ------------------------------------------------------------------------

    def export_csv(self, dest_path: str | Path) -> Path:
        """Export all loaded DGCA records to a CSV file."""
        path = Path(dest_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "year_month",
            "route_code",
            "origin",
            "destination",
            "pax_volume",
            "share_weight",
            "distance_km",
            "period_rank",
            "is_synthetic",
            "provenance",
            "source",
        ]

        with open(path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self._records:
                writer.writerow(r.to_dict())

        logger.info(
            "Exported %d DGCA traffic records to CSV at %s", len(self._records), path
        )
        return path

    def export_json(self, dest_path: str | Path) -> Path:
        """Export all loaded DGCA records to a JSON file."""
        path = Path(dest_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = [r.to_dict() for r in self._records]
        with open(path, mode="w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(
            "Exported %d DGCA traffic records to JSON at %s", len(self._records), path
        )
        return path

    # ------------------------------------------------------------------------
    # Database Seeding & Active Route Synchronization
    # ------------------------------------------------------------------------

    def seed_database(
        self,
        db: Session | None = None,
        update_active_routes: bool = True,
    ) -> dict[str, int]:
        """Seed DGCA traffic records and synchronize Route basket weights.

        1. Upserts historical monthly records into `dgca_traffic_weights`.
        2. If `update_active_routes=True`, synchronizes the active `Route` table
           (`dgca_monthly_pax` and `weight`) with the latest period's traffic statistics.

        Returns:
            Dictionary with counts: {"weights_upserted": int, "routes_updated": int}
        """
        session = db or SessionLocal()
        close_session = db is None

        weights_upserted = 0
        routes_updated = 0

        try:
            # 1. Attempt repository bulk upsert if econometrics_repo is present
            try:
                from backend.app.db.econometrics_repo import (
                    bulk_upsert_dgca_traffic_weights,
                    update_active_route_weights_from_dgca,
                )

                records_data = [
                    {
                        "route_code": r.route_code,
                        "year_month": r.year_month,
                        "pax_volume": r.pax_volume,
                        "share_weight": r.share_weight,
                    }
                    for r in self._records
                ]
                weights_upserted = bulk_upsert_dgca_traffic_weights(
                    db=session,
                    records=records_data,
                    commit=True,
                )
                logger.info(
                    "Seeded %d DGCA traffic weights via econometrics_repo",
                    weights_upserted,
                )

                if update_active_routes:
                    latest_ym = self.get_latest_period()
                    routes_updated = update_active_route_weights_from_dgca(
                        db=session,
                        year_month=latest_ym,
                        commit=True,
                    )
                    logger.info(
                        "Synchronized %d active routes with period %s",
                        routes_updated,
                        latest_ym,
                    )

                return {
                    "weights_upserted": weights_upserted,
                    "routes_updated": routes_updated,
                }

            except (ImportError, AttributeError):
                # 2. Fallback: Direct table creation and update via SQLAlchemy
                logger.info(
                    "econometrics_repo not in branch; executing standalone DGCA seeding fallback"
                )
                return self._seed_database_fallback(session, update_active_routes)

        finally:
            if close_session:
                session.close()

    def _seed_database_fallback(
        self,
        session: Session,
        update_active_routes: bool,
    ) -> dict[str, int]:
        """Fallback seeding directly into dgca_traffic_weights table and routes table."""
        if TYPE_CHECKING:
            from backend.app.models.econometrics import DgcaTrafficWeight
        else:
            try:
                from backend.app.models.econometrics import DgcaTrafficWeight
            except (ImportError, ModuleNotFoundError):

                class StandaloneDgcaTrafficWeight(Base):
                    __tablename__ = "dgca_traffic_weights"
                    __table_args__ = (
                        UniqueConstraint(
                            "route_code",
                            "year_month",
                            name="uq_dgca_traffic_weights_route_period",
                        ),
                        {"extend_existing": True},
                    )

                    id: Mapped[int] = mapped_column(
                        Integer, primary_key=True, autoincrement=True
                    )
                    route_code: Mapped[str] = mapped_column(
                        String(20), nullable=False, index=True
                    )
                    year_month: Mapped[str] = mapped_column(
                        String(7), nullable=False, index=True
                    )
                    pax_volume: Mapped[int] = mapped_column(
                        Integer, nullable=False, default=0
                    )
                    share_weight: Mapped[float] = mapped_column(
                        Float, nullable=False, default=0.0
                    )
                    created_at: Mapped[datetime] = mapped_column(
                        DateTime(timezone=True),
                        nullable=False,
                        default=lambda: datetime.now(UTC),
                    )

                DgcaTrafficWeight = StandaloneDgcaTrafficWeight

        # Ensure table exists
        Base.metadata.create_all(bind=session.get_bind())

        weights_count = 0
        for r in self._records:
            stmt = select(DgcaTrafficWeight).where(
                DgcaTrafficWeight.route_code == r.route_code,
                DgcaTrafficWeight.year_month == r.year_month,
            )
            existing = session.execute(stmt).scalar_one_or_none()
            if existing:
                existing.pax_volume = r.pax_volume
                existing.share_weight = r.share_weight
            else:
                new_weight = DgcaTrafficWeight(
                    route_code=r.route_code,
                    year_month=r.year_month,
                    pax_volume=r.pax_volume,
                    share_weight=r.share_weight,
                )
                session.add(new_weight)
            weights_count += 1

        session.commit()

        # Update Route table with latest weights
        routes_count = 0
        if update_active_routes:
            latest_ym = self.get_latest_period()
            latest_recs = self.get_period_traffic(latest_ym)
            for r in latest_recs:
                route_stmt = select(Route).where(
                    Route.origin == r.origin,
                    Route.destination == r.destination,
                )
                route_obj = session.execute(route_stmt).scalar_one_or_none()
                if route_obj:
                    route_obj.dgca_monthly_pax = r.pax_volume
                    route_obj.weight = r.share_weight
                    routes_count += 1
            session.commit()

        logger.info(
            "Directly seeded %d traffic weights and updated %d routes",
            weights_count,
            routes_count,
        )
        return {
            "weights_upserted": weights_count,
            "routes_updated": routes_count,
        }
