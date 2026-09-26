"""Unit tests for MoSPI CPI and DGCA Passenger Traffic Benchmark Loaders."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

worktree_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if worktree_root not in sys.path:
    sys.path.insert(0, worktree_root)

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.seed import seed_all
from backend.app.db.session import Base
from backend.app.models.route import Route
from ingestion.loaders import (
    DgcaTrafficLoader,
    MospiCpiLoader,
    run_cli,
)


class TestMospiCpiLoader(unittest.TestCase):
    """Test suite for MoSPI Consumer Price Index loader."""

    def setUp(self) -> None:
        self.loader = MospiCpiLoader()

    def test_builtin_records_count_and_range(self) -> None:
        series = self.loader.get_cpi_series()
        self.assertEqual(len(series), 27)
        self.assertEqual(series[0].year_month, "2024-01")
        self.assertEqual(series[-1].year_month, "2026-03")

        for rec in series:
            self.assertGreater(rec.cpi_transport_index, 0)
            self.assertGreater(rec.airfare_sub_index, 0)
            self.assertGreater(rec.headline_cpi, 0)
            self.assertEqual(rec.base_year, "2012=100")
            self.assertIsInstance(rec.date, date)
            self.assertEqual(rec.date.day, 1)
            self.assertGreater(rec.published_at, rec.date)

    def test_mom_and_yoy_inflation_properties(self) -> None:
        rec_2026_01 = self.loader.get_cpi_for_period("2026-01")
        self.assertIsNotNone(rec_2026_01)
        rec_2025_01 = self.loader.get_cpi_for_period("2025-01")
        self.assertIsNotNone(rec_2025_01)

        expected_yoy = (
            (rec_2026_01.cpi_transport_index - rec_2025_01.cpi_transport_index)
            / rec_2025_01.cpi_transport_index
        ) * 100.0
        self.assertAlmostEqual(rec_2026_01.inflation_yoy, expected_yoy, places=3)

    def test_transport_divergence_calculation(self) -> None:
        latest = self.loader.get_latest_cpi()
        airfare_index = 198.50
        div = self.loader.calculate_transport_divergence(airfare_index)

        self.assertEqual(div["period"], latest.year_month)
        self.assertEqual(div["airfare_index_value"], 198.50)
        self.assertEqual(
            div["divergence_points"],
            round(airfare_index - latest.cpi_transport_index, 2),
        )
        self.assertEqual(
            div["airfare_divergence_points"],
            round(airfare_index - latest.airfare_sub_index, 2),
        )

    def test_csv_and_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "mospi.csv"
            self.loader.export_csv(csv_path)
            from_csv = MospiCpiLoader(data_path=csv_path).get_cpi_series()
            self.assertEqual(len(from_csv), 27)

            json_path = Path(tmpdir) / "mospi.json"
            self.loader.export_json(json_path)
            from_json = MospiCpiLoader(data_path=json_path).get_cpi_series()
            self.assertEqual(len(from_json), 27)

    def test_stats_quant_interface(self) -> None:
        stats = self.loader.to_stats_format()
        self.assertEqual(len(stats), 27)
        first = stats[0]
        self.assertIn("period", first)
        self.assertIn("cpi_transport", first)
        self.assertIn("cpi_general", first)
        self.assertIn("base_year", first)


class TestDgcaTrafficLoader(unittest.TestCase):
    """Test suite for DGCA Passenger Traffic loader."""

    def setUp(self) -> None:
        self.loader = DgcaTrafficLoader()

    def test_builtin_records_and_corridors(self) -> None:
        summary = self.loader.get_network_summary()
        self.assertEqual(summary["total_periods"], 27)
        self.assertEqual(summary["corridors_monitored"], 10)
        self.assertGreater(summary["total_monthly_pax"], 2_000_000)

    def test_strict_weight_sum_invariant_all_periods(self) -> None:
        all_weights = self.loader.get_all_period_weights()
        self.assertEqual(len(all_weights), 27)
        for ym, w_map in all_weights.items():
            w_sum = sum(w_map.values())
            self.assertAlmostEqual(
                w_sum,
                1.000000,
                places=5,
                msg=f"Period {ym} weight sum drift: {w_sum}",
            )

    def test_route_weight_dictionaries(self) -> None:
        weights = self.loader.get_route_weights()
        self.assertEqual(len(weights), 10)
        self.assertIn("DEL-BOM", weights)
        self.assertIn("BOM-DEL", weights)
        self.assertIn("DEL-BLR", weights)

        tuple_weights = self.loader.get_tuple_route_weights()
        self.assertEqual(len(tuple_weights), 10)
        self.assertIn(("DEL", "BOM"), tuple_weights)
        self.assertIn(("BOM", "DEL"), tuple_weights)

    def test_corridor_growth_rate(self) -> None:
        growth = self.loader.get_corridor_growth_rate("DEL-BOM", "2024-01", "2026-01")
        self.assertGreater(growth, 10.0)

    def test_csv_and_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "dgca.csv"
            self.loader.export_csv(csv_path)
            from_csv = DgcaTrafficLoader(data_path=csv_path)
            self.assertEqual(len(from_csv.get_route_weights()), 10)
            self.assertAlmostEqual(sum(from_csv.get_route_weights().values()), 1.0, places=5)

            json_path = Path(tmpdir) / "dgca.json"
            self.loader.export_json(json_path)
            from_json = DgcaTrafficLoader(data_path=json_path)
            self.assertEqual(from_json.get_network_summary()["corridors_monitored"], 10)


class TestBenchmarkDatabaseSeeding(unittest.TestCase):
    """Test suite for database seeding and active Route synchronizations."""

    def test_database_seeding_and_route_sync(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            db_path = tmp_db.name

        try:
            engine = create_engine(f"sqlite:///{db_path}", echo=False)
            TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

            Base.metadata.create_all(bind=engine)

            with TestSession() as session:
                seed_all(session)

                del_bom_before = session.execute(
                    select(Route).where(Route.origin == "DEL", Route.destination == "BOM")
                ).scalar_one()
                pax_before = del_bom_before.dgca_monthly_pax

                # Seed MoSPI
                m_count = MospiCpiLoader().seed_database(db=session)
                self.assertEqual(m_count, 27)

                # Seed DGCA
                d_res = DgcaTrafficLoader().seed_database(db=session, update_active_routes=True)
                self.assertEqual(d_res["weights_upserted"], 270)
                self.assertEqual(d_res["routes_updated"], 10)

                del_bom_after = session.execute(
                    select(Route).where(Route.origin == "DEL", Route.destination == "BOM")
                ).scalar_one()
                self.assertGreater(del_bom_after.dgca_monthly_pax, pax_before)

                routes = session.execute(select(Route)).scalars().all()
                total_w = sum(r.weight for r in routes)
                self.assertAlmostEqual(total_w, 1.000000, places=4)

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


class TestLoadersCliRunner(unittest.TestCase):
    """Test suite for loaders CLI runner."""

    def test_cli_subcommands(self) -> None:
        orig = sys.stdout
        sys.stdout = io.StringIO()
        try:
            self.assertEqual(run_cli(["mospi", "--summary"]), 0)
            self.assertEqual(run_cli(["dgca", "--summary"]), 0)
            self.assertEqual(run_cli(["all"]), 0)
        finally:
            sys.stdout = orig


if __name__ == "__main__":
    unittest.main()


class TestDgcaWeightProvenance:
    """Weights must never be mistakable for official DGCA statistics.

    The built-in series is modelled from base volumes, not read from a DGCA
    release, so every record it produces has to be flagged. These tests pin that
    contract, because a silent fallback is how a fabricated statistic ships.
    """

    def test_modelled_fallback_is_flagged_synthetic(self) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        loader = DgcaTrafficLoader()
        prov = loader.provenance
        assert prov["is_synthetic"] is True, "fallback weights must be flagged"
        assert prov["record_count"] > 0
        assert prov["first_period"] and prov["last_period"]
        assert all("MODELLED" in src for src in prov["sources"]), prov["sources"]

    def test_every_record_carries_provenance(self) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        loader = DgcaTrafficLoader()
        for record in loader._records:
            assert record.is_synthetic is True
            assert record.source, "record must name its provenance"

    def test_real_file_is_not_flagged_synthetic(self, tmp_path) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        csv = tmp_path / "dgca.csv"
        csv.write_text(
            "year_month,origin,destination,pax_volume,distance_km\n"
            "2026-01,DEL,BOM,437500,1148\n"
            "2026-01,BOM,DEL,437500,1148\n",
            encoding="utf-8",
        )
        loader = DgcaTrafficLoader(data_path=csv)
        prov = loader.provenance
        assert prov["is_synthetic"] is False
        assert prov["data_path"] == str(csv)
        assert all(r.is_synthetic is False for r in loader._records)
        assert all("dgca.csv" in r.source for r in loader._records)

    def test_weights_still_sum_to_one_per_period(self) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        loader = DgcaTrafficLoader()
        for period, weights in loader._weights_by_period.items():
            assert abs(sum(weights.values()) - 1.0) < 1e-5, period
