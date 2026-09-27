"""MoSPI Consumer Price Index (CPI) loader for APIx.

Parses a caller-supplied CPI file. This module does not ship an official series.
A previous hardcoded table was labelled source="MoSPI" and contradicted NSO press
notes; it was removed. See BUNDLED_SERIES_STATUS.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import UTC, date, datetime
from datetime import date as DateType
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, Field
from sqlalchemy import Date, DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.app.db.session import Base, SessionLocal

logger = logging.getLogger("ingestion.loaders.mospi_cpi")


# ============================================================================
# Pydantic Schema
# ============================================================================


class MospiCpiRecord(BaseModel):
    """Pydantic model representing a monthly official MoSPI CPI benchmark."""

    year_month: str = Field(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Reporting month in format YYYY-MM (e.g. 2026-03)",
    )
    date: DateType = Field(..., description="First day of reporting month")
    cpi_transport_index: float = Field(
        ...,
        gt=0,
        description="MoSPI CPI for Transport & Communication sub-group (Base 2012=100)",
    )
    airfare_sub_index: float = Field(
        ...,
        gt=0,
        description="MoSPI official sub-index specifically tracking air passenger fares",
    )
    headline_cpi: float = Field(
        ...,
        gt=0,
        description="All-India Headline CPI Combined General Index (Base 2012=100)",
    )
    base_year: str = Field(default="2012=100", description="Base index series period")
    inflation_mom: float | None = Field(
        default=None,
        description="Month-on-Month Transport CPI inflation percentage change",
    )
    inflation_yoy: float | None = Field(
        default=None,
        description="Year-on-Year Transport CPI inflation percentage change",
    )
    published_at: DateType = Field(
        ..., description="Publication date carried by the file, if any"
    )
    source: str = Field(
        default="undeclared",
        description="Provenance. Bare 'MoSPI' is not a citation; a press-note URL is.",
    )

    # Convenience properties for StatsQuantEngineer and econometric analytics
    @property
    def period(self) -> str:
        """Alias for year_month matching econometric_engine conventions."""
        return self.year_month

    @property
    def cpi_transport(self) -> float:
        """Alias for cpi_transport_index."""
        return self.cpi_transport_index

    @property
    def cpi_general(self) -> float:
        """Alias for headline_cpi."""
        return self.headline_cpi

    @property
    def cpi(self) -> float:
        """Shorthand alias for transport CPI benchmark."""
        return self.cpi_transport_index

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary with ISO-formatted date fields."""
        return {
            "year_month": self.year_month,
            "date": self.date.isoformat(),
            "cpi_transport_index": self.cpi_transport_index,
            "airfare_sub_index": self.airfare_sub_index,
            "headline_cpi": self.headline_cpi,
            "base_year": self.base_year,
            "inflation_mom": (
                round(self.inflation_mom, 3) if self.inflation_mom is not None else None
            ),
            "inflation_yoy": (
                round(self.inflation_yoy, 3) if self.inflation_yoy is not None else None
            ),
            "published_at": self.published_at.isoformat(),
            "source": self.source,
        }

    def to_stats_dict(self) -> dict[str, Any]:
        """Convert to format expected by StatsQuantEngineer econometric divergence analytics."""
        return {
            "period": self.year_month,
            "date": self.date.isoformat(),
            "cpi_transport": self.cpi_transport_index,
            "cpi_general": self.headline_cpi,
            "airfare_sub_index": self.airfare_sub_index,
            "cpi": self.cpi_transport_index,
            "base_year": self.base_year,
            "inflation_mom": self.inflation_mom,
            "inflation_yoy": self.inflation_yoy,
        }


# The 2024-01..2026-03 table that used to live here was not a MoSPI release.
# Checked against NSO press notes, then removed rather than patched:
#   January 2024 CPI General Combined is 185.5, not 185.2.
#   January 2024 Transport and communication Combined is 166.8, not 174.5.
#     https://mospi.gov.in/sites/default/files/press_release/CPI_PR_12feb24.pdf
#     released 12 February 2024.
#   December 2025 CPI General Combined is 198.0 on base 2012=100, not 195.8.
#   January 2026 CPI General Combined is 104.46 on base 2024=100, not 196.4 on base 2012=100.
#     https://www.mospi.gov.in/uploads/latestreleasesfiles/1770893247472-Press%20Relase%20of%20CPI%20for%20Jan26.pdf
#     released 12 February 2026.
# Airfare item 6.2.03 and the other months were not verified, so they were not replaced.
UNDECLARED_SOURCE: Final[str] = "undeclared"
BUNDLED_SERIES_STATUS: Final[dict[str, Any]] = {
    "official": False,
    "status": "withdrawn",
    "record_count": 0,
    "reason": (
        "No official MoSPI series is bundled. The previous table contradicted NSO press notes "
        "and was removed. See data/mospi_cpi_historical_2024_2026.json."
    ),
}


def _build_builtin_records() -> list[MospiCpiRecord]:
    """Return no bundled series. The previous table was not official and was withdrawn."""
    return []


# ============================================================================
# MoSPI CPI Loader Class
# ============================================================================


class MospiCpiLoader:
    """Automated parser and loader for official MoSPI Consumer Price Index data."""

    def __init__(self, data_path: str | Path | None = None) -> None:
        """Initialize MoSPI CPI Loader.

        Args:
            data_path: Optional path to external CSV or JSON file containing MoSPI data.
                       If None or file does not exist, defaults to authoritative built-in series.
        """
        self.data_path = Path(data_path) if data_path else None
        self._records: list[MospiCpiRecord] = []
        self._records_by_period: dict[str, MospiCpiRecord] = {}

        if self.data_path and self.data_path.exists():
            if self.data_path.suffix.lower() == ".json":
                self._records = self.parse_json(self.data_path)
            else:
                self._records = self.parse_csv(self.data_path)
        else:
            self._records = _build_builtin_records()

        self._index_records()

    @property
    def provenance(self) -> dict[str, Any]:
        """Whether the loaded rows are a cited MoSPI release. The builtin path is not."""
        if not self.data_path or not self.data_path.exists():
            return dict(BUNDLED_SERIES_STATUS)
        sources = sorted({r.source for r in self._records})
        cited = bool(self._records) and all(
            "https://" in r.source or "http://" in r.source for r in self._records
        )
        status = "cited" if cited else "undeclared"
        return {
            "official": cited,
            "status": status,
            "record_count": len(self._records),
            "sources": sources,
        }

    def _index_records(self) -> None:
        """Sort chronologically and build fast lookup mapping."""
        self._records.sort(key=lambda r: r.year_month)
        self._records_by_period = {r.year_month: r for r in self._records}

    # ------------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------------

    def parse_csv(self, csv_source: str | Path | io.StringIO) -> list[MospiCpiRecord]:
        """Parse MoSPI CPI records from CSV file path, string content, or StringIO buffer.

        Supports various common column header aliases:
        - Period: year_month, period, month, reporting_month, date
        - Transport CPI: cpi_transport_index, transport_cpi, cpi_transport, transport, index_value
        - Airfare: airfare_sub_index, airfare_cpi, airfare, airfare_index
        - Headline: headline_cpi, general_cpi, cpi_general, headline, combined_cpi
        - Published: published_at, publication_date, release_date
        - Source: source, agency, publisher
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

        reader = csv.DictReader(io.StringIO(content.strip()))
        if not reader.fieldnames:
            raise ValueError("CSV is empty or missing headers")

        records: list[MospiCpiRecord] = []
        for row_idx, raw_row in enumerate(reader, start=1):
            row = {k.strip().lower(): v.strip() for k, v in raw_row.items() if k}

            # 1. Resolve period (year_month)
            ym_val = (
                row.get("year_month")
                or row.get("period")
                or row.get("month")
                or row.get("reporting_month")
                or row.get("date")
            )
            if not ym_val:
                continue

            # Normalize to YYYY-MM
            ym_clean = ym_val[:7] if len(ym_val) >= 7 and ym_val[4] == "-" else ym_val
            if (
                len(ym_clean) != 7
                or not ym_clean[:4].isdigit()
                or not ym_clean[5:].isdigit()
            ):
                logger.warning(
                    "Skipping invalid period '%s' at row %d", ym_val, row_idx
                )
                continue

            y_str, m_str = ym_clean.split("-")
            year, month = int(y_str), int(m_str)
            rec_date = date(year, month, 1)

            # 2. Resolve Transport CPI
            t_val_str = (
                row.get("cpi_transport_index")
                or row.get("transport_cpi")
                or row.get("cpi_transport")
                or row.get("transport")
                or row.get("index_value")
            )
            if not t_val_str:
                continue
            cpi_transport = float(t_val_str)

            # 3. Resolve Airfare Sub-index (default to 0.98 * transport if absent)
            a_val_str = (
                row.get("airfare_sub_index")
                or row.get("airfare_cpi")
                or row.get("airfare")
                or row.get("airfare_index")
            )
            airfare_cpi = (
                float(a_val_str) if a_val_str else round(cpi_transport * 0.98, 2)
            )

            # 4. Resolve Headline CPI (default to 1.05 * transport if absent)
            h_val_str = (
                row.get("headline_cpi")
                or row.get("general_cpi")
                or row.get("cpi_general")
                or row.get("headline")
                or row.get("combined_cpi")
            )
            headline_cpi = (
                float(h_val_str) if h_val_str else round(cpi_transport * 1.04, 2)
            )

            # 5. Resolve Publication date
            pub_str = (
                row.get("published_at")
                or row.get("publication_date")
                or row.get("release_date")
            )
            if pub_str:
                pub_date = date.fromisoformat(pub_str[:10])
            else:
                next_m = month + 1
                next_y = year
                if next_m > 12:
                    next_m = 1
                    next_y += 1
                pub_date = date(next_y, next_m, 12)

            base_year = row.get("base_year", "2012=100")
            source = row.get("source") or UNDECLARED_SOURCE

            rec = MospiCpiRecord(
                year_month=ym_clean,
                date=rec_date,
                cpi_transport_index=cpi_transport,
                airfare_sub_index=airfare_cpi,
                headline_cpi=headline_cpi,
                base_year=base_year,
                published_at=pub_date,
                source=source,
            )
            records.append(rec)

        # Sort and recalculate MoM and YoY
        records.sort(key=lambda r: r.year_month)
        transport_map = {r.year_month: r.cpi_transport_index for r in records}
        for r in records:
            y, m = int(r.year_month[:4]), int(r.year_month[5:7])
            # MoM
            pm, py = (12, y - 1) if m == 1 else (m - 1, y)
            prior_ym = f"{py:04d}-{pm:02d}"
            if prior_ym in transport_map:
                r.inflation_mom = (
                    (r.cpi_transport_index - transport_map[prior_ym])
                    / transport_map[prior_ym]
                ) * 100.0

            # YoY
            yoy_ym = f"{y - 1:04d}-{m:02d}"
            if yoy_ym in transport_map:
                r.inflation_yoy = (
                    (r.cpi_transport_index - transport_map[yoy_ym])
                    / transport_map[yoy_ym]
                ) * 100.0

        return records

    def parse_json(
        self, json_source: str | Path | list[dict[str, Any]] | dict[str, Any]
    ) -> list[MospiCpiRecord]:
        """Parse MoSPI CPI records from JSON file path, string, or Python list/dict."""
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

        raw_list = (
            data
            if isinstance(data, list)
            else data.get("records", data.get("data", []))
        )
        if not isinstance(raw_list, list):
            raise ValueError("Expected JSON array of records")

        # Convert using parse_csv or direct dictionary mapping
        records: list[MospiCpiRecord] = []
        for item in raw_list:
            ym = (
                item.get("year_month") or item.get("period") or item.get("date", "")[:7]
            )
            if not ym or len(ym) < 7:
                continue
            ym = ym[:7]
            y, m = int(ym[:4]), int(ym[5:7])
            rec_date = date(y, m, 1)

            t_val = float(
                item.get("cpi_transport_index")
                or item.get("cpi_transport")
                or item.get("transport", 100.0)
            )
            a_val = float(
                item.get("airfare_sub_index") or item.get("airfare", t_val * 0.98)
            )
            h_val = float(
                item.get("headline_cpi") or item.get("cpi_general", t_val * 1.04)
            )

            pub_raw = item.get("published_at")
            if pub_raw:
                pub_date = date.fromisoformat(str(pub_raw)[:10])
            else:
                nm, ny = (1, y + 1) if m == 12 else (m + 1, y)
                pub_date = date(ny, nm, 12)

            rec = MospiCpiRecord(
                year_month=ym,
                date=rec_date,
                cpi_transport_index=t_val,
                airfare_sub_index=a_val,
                headline_cpi=h_val,
                base_year=item.get("base_year", "2012=100"),
                inflation_mom=item.get("inflation_mom"),
                inflation_yoy=item.get("inflation_yoy"),
                published_at=pub_date,
                source=item.get("source") or UNDECLARED_SOURCE,
            )
            records.append(rec)

        records.sort(key=lambda r: r.year_month)
        return records

    # ------------------------------------------------------------------------
    # Data Accessors
    # ------------------------------------------------------------------------

    def get_cpi_series(
        self,
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> list[MospiCpiRecord]:
        """Retrieve slice of MoSPI CPI records filtered by start and end periods (inclusive).

        Args:
            start_period: Optional start period in 'YYYY-MM' format (e.g. '2024-01').
            end_period: Optional end period in 'YYYY-MM' format (e.g. '2026-03').

        Returns:
            List of MospiCpiRecord instances sorted chronologically.
        """
        filtered = self._records
        if start_period:
            s = start_period.strip()[:7]
            filtered = [r for r in filtered if r.year_month >= s]
        if end_period:
            e = end_period.strip()[:7]
            filtered = [r for r in filtered if r.year_month <= e]
        return filtered

    def get_cpi_for_period(self, period: str) -> MospiCpiRecord | None:
        """Lookup specific MoSPI record by reporting month (e.g. '2026-01')."""
        clean_p = period.strip()[:7]
        return self._records_by_period.get(clean_p)

    def get_latest_cpi(self) -> MospiCpiRecord:
        """Return the most recent published MoSPI CPI benchmark record."""
        if not self._records:
            raise ValueError("No MoSPI CPI records loaded")
        return self._records[-1]

    def to_stats_format(
        self,
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return sequence of records conforming to StatsQuantEngineer-4 interface."""
        series = self.get_cpi_series(start_period, end_period)
        return [r.to_stats_dict() for r in series]

    # ------------------------------------------------------------------------
    # Analytical Divergence Calculations
    # ------------------------------------------------------------------------

    def calculate_transport_divergence(
        self,
        airfare_index_value: float,
        period: str | None = None,
    ) -> dict[str, Any]:
        """Compute divergence metrics between an observed airfare price index and MoSPI benchmarks.

        Args:
            airfare_index_value: Observed high-frequency airfare index (e.g. 198.5).
            period: Target reporting month (defaults to latest available MoSPI record).

        Returns:
            Dictionary with divergence in index points and percentage differences.
        """
        record = self.get_cpi_for_period(period) if period else self.get_latest_cpi()
        if not record:
            raise ValueError(f"No MoSPI CPI record available for period '{period}'")

        # Divergence against Transport Sub-group
        transport_pts = airfare_index_value - record.cpi_transport_index
        transport_pct = (transport_pts / record.cpi_transport_index) * 100.0

        # Divergence against Airfare Sub-index
        airfare_pts = airfare_index_value - record.airfare_sub_index
        airfare_pct = (airfare_pts / record.airfare_sub_index) * 100.0

        # Divergence against Headline Combined CPI
        headline_pts = airfare_index_value - record.headline_cpi
        headline_pct = (headline_pts / record.headline_cpi) * 100.0

        return {
            "period": record.year_month,
            "airfare_index_value": round(airfare_index_value, 2),
            "mospi_transport_cpi": record.cpi_transport_index,
            "mospi_airfare_sub_index": record.airfare_sub_index,
            "headline_cpi": record.headline_cpi,
            "divergence_points": round(transport_pts, 2),
            "divergence_pct": round(transport_pct, 2),
            "airfare_divergence_points": round(airfare_pts, 2),
            "airfare_divergence_pct": round(airfare_pct, 2),
            "headline_divergence_points": round(headline_pts, 2),
            "headline_divergence_pct": round(headline_pct, 2),
            "published_at": record.published_at.isoformat(),
            "base_year": record.base_year,
        }

    # ------------------------------------------------------------------------
    # Serialization & Export
    # ------------------------------------------------------------------------

    def export_csv(self, dest_path: str | Path) -> Path:
        """Export all loaded MoSPI records to a CSV file."""
        path = Path(dest_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "year_month",
            "date",
            "cpi_transport_index",
            "airfare_sub_index",
            "headline_cpi",
            "base_year",
            "inflation_mom",
            "inflation_yoy",
            "published_at",
            "source",
        ]

        with open(path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self._records:
                writer.writerow(r.to_dict())

        logger.info(
            "Exported %d MoSPI CPI records to CSV at %s", len(self._records), path
        )
        return path

    def export_json(self, dest_path: str | Path) -> Path:
        """Export all loaded MoSPI records to a JSON file."""
        path = Path(dest_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = [r.to_dict() for r in self._records]
        with open(path, mode="w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(
            "Exported %d MoSPI CPI records to JSON at %s", len(self._records), path
        )
        return path

    # ------------------------------------------------------------------------
    # Database Seeding
    # ------------------------------------------------------------------------

    def seed_database(self, db: Session | None = None) -> int:
        """Seed all loaded MoSPI CPI records into the database.

        Integrates cleanly with DatabaseEngineer-4's `MospiCpiSeries` model and
        `bulk_upsert_mospi_cpi` repository function if present, or falls back to
        direct SQLAlchemy table creation and upserting.

        Returns:
            Count of MoSPI records seeded / upserted.
        """
        session = db or SessionLocal()
        close_session = db is None

        try:
            # 1. Attempt DatabaseEngineer-4's repository function
            try:
                from backend.app.db.econometrics_repo import bulk_upsert_mospi_cpi

                records_data = [
                    {
                        "year_month": r.year_month,
                        "cpi_transport_index": r.cpi_transport_index,
                        "airfare_sub_index": r.airfare_sub_index,
                        "headline_cpi": r.headline_cpi,
                        "published_at": r.published_at,
                        "source": r.source,
                    }
                    for r in self._records
                ]
                count = bulk_upsert_mospi_cpi(
                    db=session, records=records_data, commit=True
                )
                logger.info("Seeded %d MoSPI CPI records via econometrics_repo", count)
                return count

            except (ImportError, AttributeError):
                # 2. Fallback: Direct table creation and merge via SQLAlchemy ORM
                logger.info(
                    "econometrics_repo not yet in branch; using direct MospiCpiSeries fallback"
                )
                return self._seed_database_fallback(session)

        finally:
            if close_session:
                session.close()

    def _seed_database_fallback(self, session: Session) -> int:
        """Fallback seeding directly querying or creating mospi_cpi_series table."""
        # Check if MospiCpiSeries is imported in backend.app.models
        if TYPE_CHECKING:
            from backend.app.models.econometrics import MospiCpiSeries
        else:
            try:
                from backend.app.models.econometrics import MospiCpiSeries
            except (ImportError, ModuleNotFoundError):
                # Define minimal Standalone MospiCpiSeries
                class StandaloneMospiCpi(Base):
                    __tablename__ = "mospi_cpi_series"
                    __table_args__ = ({"extend_existing": True},)

                    id: Mapped[int] = mapped_column(
                        Integer, primary_key=True, autoincrement=True
                    )
                    year_month: Mapped[str] = mapped_column(
                        String(7), nullable=False, unique=True, index=True
                    )
                    cpi_transport_index: Mapped[float] = mapped_column(
                        Float, nullable=False
                    )
                    airfare_sub_index: Mapped[float] = mapped_column(
                        Float, nullable=False
                    )
                    headline_cpi: Mapped[float] = mapped_column(Float, nullable=False)
                    published_at: Mapped[date] = mapped_column(Date, nullable=False)
                    source: Mapped[str] = mapped_column(
                        String(100), nullable=False, default="undeclared"
                    )
                    created_at: Mapped[datetime] = mapped_column(
                        DateTime(timezone=True),
                        nullable=False,
                        default=lambda: datetime.now(UTC),
                    )

                MospiCpiSeries = StandaloneMospiCpi

        # Create table if not present
        Base.metadata.create_all(bind=session.get_bind())

        count = 0
        for r in self._records:
            stmt = select(MospiCpiSeries).where(
                MospiCpiSeries.year_month == r.year_month
            )
            existing = session.execute(stmt).scalar_one_or_none()
            if existing:
                existing.cpi_transport_index = r.cpi_transport_index
                existing.airfare_sub_index = r.airfare_sub_index
                existing.headline_cpi = r.headline_cpi
                existing.published_at = r.published_at
                existing.source = r.source
            else:
                new_rec = MospiCpiSeries(
                    year_month=r.year_month,
                    cpi_transport_index=r.cpi_transport_index,
                    airfare_sub_index=r.airfare_sub_index,
                    headline_cpi=r.headline_cpi,
                    published_at=r.published_at,
                    source=r.source,
                )
                session.add(new_rec)
            count += 1

        session.commit()
        logger.info("Directly seeded %d MoSPI CPI records into database", count)
        return count
