"""APIx Ingestion Loaders Package.

Provides automated loaders, parsers, historical benchmark datasets, and database seeding
utilities for:
1. MoSPI Consumer Price Index (Transport sub-group & Airfare sub-index 2024-2026).
2. DGCA Monthly City-Pair Passenger Traffic Reports & Corridor Weights.

Exports:
- MospiCpiLoader: Parser and loader for official MoSPI CPI benchmark data.
- MospiCpiRecord: Pydantic model for MoSPI monthly records.
- DgcaTrafficLoader: Parser and dynamic weight loader for DGCA corridor traffic.
- DgcaTrafficRecord: Pydantic model for DGCA corridor traffic records.
- run_cli: Command-line interface runner for ingestion loaders.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from collections.abc import Sequence

from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader, DgcaTrafficRecord
from ingestion.loaders.mospi_cpi_loader import MospiCpiLoader, MospiCpiRecord

__all__ = [
    "MospiCpiLoader",
    "MospiCpiRecord",
    "DgcaTrafficLoader",
    "DgcaTrafficRecord",
    "run_cli",
]

logger = logging.getLogger("ingestion.loaders")


# ============================================================================
# CLI Runner
# ============================================================================


def _setup_logging(verbose: bool = False) -> None:
    """Configure console logging level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_cli(argv: Sequence[str] | None = None) -> int:
    """Execute APIx Ingestion Loaders CLI runner.

    Usage examples:
      python -m ingestion.loaders mospi --summary
      python -m ingestion.loaders mospi --seed --export-csv data/mospi.csv
      python -m ingestion.loaders dgca --summary --period 2026-03
      python -m ingestion.loaders dgca --seed --update-routes
      python -m ingestion.loaders all --seed --update-routes
    """
    parser = argparse.ArgumentParser(
        prog="python -m ingestion.loaders",
        description="APIx Ingestion Benchmark Loaders (MoSPI CPI & DGCA Corridor Traffic)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Loader subcommand to execute")

    # 1. MoSPI CPI subcommand
    mospi_parser = subparsers.add_parser("mospi", help="MoSPI Consumer Price Index loader")
    mospi_parser.add_argument("--data-path", type=str, help="Path to external MoSPI CSV/JSON data file")
    mospi_parser.add_argument("--seed", action="store_true", help="Seed loaded records into database")
    mospi_parser.add_argument("--period", type=str, help="Lookup specific reporting month (e.g. '2026-01')")
    mospi_parser.add_argument("--divergence", type=float, help="Calculate transport divergence for an airfare index value")
    mospi_parser.add_argument("--export-csv", type=str, help="Export loaded MoSPI series to CSV file")
    mospi_parser.add_argument("--export-json", type=str, help="Export loaded MoSPI series to JSON file")
    mospi_parser.add_argument("--summary", action="store_true", default=True, help="Print summary of series")

    # 2. DGCA Traffic subcommand
    dgca_parser = subparsers.add_parser("dgca", help="DGCA City-Pair Passenger Traffic loader")
    dgca_parser.add_argument("--data-path", type=str, help="Path to external DGCA CSV/JSON data file")
    dgca_parser.add_argument("--seed", action="store_true", help="Seed corridor traffic records into database")
    dgca_parser.add_argument("--update-routes", action="store_true", help="Synchronize active Route table weights from latest period")
    dgca_parser.add_argument("--period", type=str, help="Retrieve corridor weights for reporting month (e.g. '2026-03')")
    dgca_parser.add_argument("--export-csv", type=str, help="Export loaded DGCA records to CSV file")
    dgca_parser.add_argument("--export-json", type=str, help="Export loaded DGCA records to JSON file")
    dgca_parser.add_argument("--summary", action="store_true", default=True, help="Print summary of corridor traffic network")

    # 3. All subcommand
    all_parser = subparsers.add_parser("all", help="Execute both MoSPI CPI and DGCA Traffic loaders")
    all_parser.add_argument("--seed", action="store_true", help="Seed both benchmark datasets into database")
    all_parser.add_argument("--update-routes", action="store_true", help="Synchronize active Route weights from latest DGCA period")
    all_parser.add_argument("--export-dir", type=str, help="Directory to export CSV and JSON benchmark files")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "mospi":
        loader = MospiCpiLoader(data_path=args.data_path)
        series = loader.get_cpi_series()
        prov = loader.provenance

        print("=" * 70)
        print("  MoSPI Consumer Price Index")
        print("=" * 70)
        print(f"Official bundled series: {prov.get('official')}")
        print(f"Status                 : {prov.get('status')}")
        if not series:
            print(prov.get("reason", "No CPI records loaded."))
            if args.seed:
                seeded = loader.seed_database()
                print(f"Seeded {seeded} records.")
            return 0
        latest = loader.get_latest_cpi()
        print(f"Total Periods Loaded : {len(series)} ({series[0].year_month} to {series[-1].year_month})")
        print(f"Source               : {latest.source}")
        print(f"Latest Period        : {latest.year_month} (published {latest.published_at})")
        print(f"Transport CPI (2012) : {latest.cpi_transport_index:.2f} (MoM: +{latest.inflation_mom or 0:.2f}%, YoY: +{latest.inflation_yoy or 0:.2f}%)")
        print(f"Airfare Sub-index    : {latest.airfare_sub_index:.2f}")
        print(f"Headline CPI         : {latest.headline_cpi:.2f}")
        print("-" * 70)

        if args.period:
            rec = loader.get_cpi_for_period(args.period)
            if rec:
                print(f"Lookup for {args.period}:")
                print(json.dumps(rec.to_dict(), indent=2))
            else:
                print(f"Error: Period '{args.period}' not found in loaded series.", file=sys.stderr)

        if args.divergence is not None:
            div = loader.calculate_transport_divergence(args.divergence, period=args.period)
            print(f"Divergence Analysis for Airfare Index {args.divergence:.2f}:")
            print(json.dumps(div, indent=2))

        if args.export_csv:
            p = loader.export_csv(args.export_csv)
            print(f"Exported CSV to: {p}")

        if args.export_json:
            p = loader.export_json(args.export_json)
            print(f"Exported JSON to: {p}")

        if args.seed:
            print("Seeding MoSPI CPI records into database...")
            seeded = loader.seed_database()
            print(f"Successfully seeded {seeded} MoSPI CPI records into database.")

        return 0

    if args.command == "dgca":
        loader = DgcaTrafficLoader(data_path=args.data_path)
        summary = loader.get_network_summary()
        target_period = args.period or loader.get_latest_period()
        weights = loader.get_route_weights(target_period)

        print("=" * 70)
        print("  DGCA Domestic City-Pair Passenger Traffic Reports")
        print("=" * 70)
        print(f"Total Periods Loaded : {summary['total_periods']} periods")
        print(f"Corridors Monitored  : {summary['corridors_monitored']} directional trunk routes")
        print(f"Latest Period        : {summary['latest_period']}")
        print(f"Total Monthly Pax    : {summary['total_monthly_pax']:,} passengers")
        print(f"Top Corridor         : {summary['top_corridor']} ({summary['top_corridor_pax']:,} pax, {summary['top_corridor_weight'] * 100:.2f}%)")
        print(f"Basket Weight Sum    : {summary['sum_of_weights']:.6f} (Strict Invariant = 1.000000)")
        print("-" * 70)
        print(f"Corridor Weights for Period {target_period}:")
        for r_code, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            print(f"  {r_code:<10} : {w:8.6f} ({w * 100:6.2f}%)")
        print("-" * 70)

        if args.export_csv:
            p = loader.export_csv(args.export_csv)
            print(f"Exported CSV to: {p}")

        if args.export_json:
            p = loader.export_json(args.export_json)
            print(f"Exported JSON to: {p}")

        if args.seed:
            print("Seeding DGCA traffic records and synchronizing Route weights...")
            res = loader.seed_database(update_active_routes=args.update_routes)
            print(f"Successfully seeded {res['weights_upserted']} traffic weights; synchronized {res['routes_updated']} active routes.")

        return 0

    if args.command == "all":
        mospi_loader = MospiCpiLoader()
        dgca_loader = DgcaTrafficLoader()

        print("=" * 70)
        print("  APIx Benchmark Ingestion: MoSPI CPI & DGCA Traffic Weights")
        print("=" * 70)
        m_series = mospi_loader.get_cpi_series()
        d_summary = dgca_loader.get_network_summary()

        if m_series:
            m_latest = mospi_loader.get_latest_cpi()
            print(f"[MoSPI CPI]  {len(m_series)} months (to {m_latest.year_month}) | source: {m_latest.source}")
        else:
            print(f"[MoSPI CPI]  no official series bundled ({mospi_loader.provenance.get('status')})")
        print(f"[DGCA Pax]   {d_summary['total_periods']} months ({d_summary['corridors_monitored']} corridors) | Latest Pax: {d_summary['total_monthly_pax']:,} | Weight Sum: {d_summary['sum_of_weights']:.6f}")

        if args.export_dir:
            exp_dir = Path(args.export_dir)
            exp_dir.mkdir(parents=True, exist_ok=True)
            m_csv = mospi_loader.export_csv(exp_dir / "mospi_cpi_historical_2024_2026.csv")
            m_json = mospi_loader.export_json(exp_dir / "mospi_cpi_historical_2024_2026.json")
            d_csv = dgca_loader.export_csv(exp_dir / "dgca_passenger_traffic_weights.csv")
            d_json = dgca_loader.export_json(exp_dir / "dgca_passenger_traffic_weights.json")
            print(f"Exported benchmark files to {exp_dir}:\n  {m_csv.name}\n  {m_json.name}\n  {d_csv.name}\n  {d_json.name}")

        if args.seed:
            print("\nSeeding both benchmarks into database...")
            m_count = mospi_loader.seed_database()
            d_res = dgca_loader.seed_database(update_active_routes=args.update_routes)
            print(f"Done! Seeded {m_count} MoSPI records, {d_res['weights_upserted']} DGCA records, updated {d_res['routes_updated']} routes.")

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
