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
    """The bundled CPI table is not an official MoSPI release."""

    def setUp(self) -> None:
        self.loader = MospiCpiLoader()

    def test_bundled_series_is_withdrawn_and_not_labelled_mospi(self) -> None:
        series = self.loader.get_cpi_series()
        self.assertEqual(series, [])
        prov = self.loader.provenance
        self.assertEqual(prov["official"], False)
        self.assertEqual(prov["status"], "withdrawn")
        self.assertEqual(prov["record_count"], 0)
        self.assertTrue(all(rec.source != "MoSPI" for rec in series))

    def test_parsed_file_does_not_default_source_to_mospi(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "cpi.csv"
            csv_path.write_text(
                "year_month,cpi_transport_index,airfare_sub_index,headline_cpi\n"
                "2024-02,10.0,11.0,12.0\n",
                encoding="utf-8",
            )
            rec = MospiCpiLoader(data_path=csv_path).get_cpi_series()[0]
        self.assertEqual(rec.source, "undeclared")
        self.assertNotEqual(rec.source, "MoSPI")

    def test_committed_bundle_does_not_ship_contradicted_values(self) -> None:
        import json

        root = Path(__file__).resolve().parents[1]
        csv_text = (root / "data" / "mospi_cpi_historical_2024_2026.csv").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("174.5", csv_text)
        self.assertNotIn("185.2", csv_text)
        self.assertNotIn("195.8", csv_text)
        self.assertNotIn("196.4", csv_text)
        payload = json.loads(
            (root / "data" / "mospi_cpi_historical_2024_2026.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["official"], False)
        self.assertEqual(payload["status"], "withdrawn")
        self.assertEqual(payload["records"], [])

    def test_default_divergence_does_not_invent_a_mospi_level(self) -> None:
        from backend.app.services.econometric_engine import (
            calculate_mospi_cpi_divergence,
        )

        result = calculate_mospi_cpi_divergence(
            [{"date": "2026-01-01", "index_value": 110.0}]
        )
        self.assertEqual(result.metadata["benchmark_sound"], False)
        self.assertEqual(result.aligned_series, [])
        self.assertEqual(result.latest_mospi_cpi, 0.0)


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
            self.assertAlmostEqual(
                sum(from_csv.get_route_weights().values()), 1.0, places=5
            )

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
                    select(Route).where(
                        Route.origin == "DEL", Route.destination == "BOM"
                    )
                ).scalar_one()
                pax_before = del_bom_before.dgca_monthly_pax

                # Seed MoSPI
                m_count = MospiCpiLoader().seed_database(db=session)
                self.assertEqual(m_count, 0)

                # Seed DGCA
                d_res = DgcaTrafficLoader().seed_database(
                    db=session, update_active_routes=True
                )
                self.assertEqual(d_res["weights_upserted"], 270)
                self.assertEqual(d_res["routes_updated"], 10)

                del_bom_after = session.execute(
                    select(Route).where(
                        Route.origin == "DEL", Route.destination == "BOM"
                    )
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

    def test_file_declaring_dgca_provenance_is_not_synthetic(self, tmp_path) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        csv = tmp_path / "dgca.csv"
        csv.write_text(
            "year_month,origin,destination,pax_volume,distance_km,provenance\n"
            "2026-01,DEL,BOM,437500,1148,DGCA\n"
            "2026-01,BOM,DEL,400000,1148,DGCA\n",
            encoding="utf-8",
        )
        loader = DgcaTrafficLoader(data_path=csv)
        assert loader.provenance["is_synthetic"] is False
        assert loader._records[0].is_synthetic is False
        assert loader._records[0].provenance == "DGCA"
        assert loader._records[0].pax_volume == 437500

    def test_file_without_provenance_is_synthetic(self, tmp_path) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        csv = tmp_path / "weights.csv"
        csv.write_text(
            "year_month,origin,destination,pax_volume,distance_km\n"
            "2026-01,DEL,BOM,437500,1148\n"
            "2026-01,BOM,DEL,400000,1148\n",
            encoding="utf-8",
        )
        loader = DgcaTrafficLoader(data_path=csv)
        assert loader.provenance["is_synthetic"] is True
        assert loader._records[0].is_synthetic is True
        assert loader._records[0].provenance == "modelled"
        assert loader._records[0].pax_volume == 437500

    def test_file_declaring_generated_is_synthetic(self, tmp_path) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        csv = tmp_path / "weights.csv"
        csv.write_text(
            "year_month,origin,destination,pax_volume,distance_km,provenance\n"
            "2026-01,DEL,BOM,441875,1148,generated\n"
            "2026-01,BOM,DEL,400000,1148,generated\n",
            encoding="utf-8",
        )
        loader = DgcaTrafficLoader(data_path=csv)
        record = loader._records[0]
        assert record.is_synthetic is True
        assert record.provenance == "generated"
        assert record.pax_volume == 441875
        exported = record.to_dict()
        assert exported["is_synthetic"] is True
        assert exported["provenance"] == "generated"
        assert exported["source"]

    def test_to_dict_round_trips_provenance(self, tmp_path) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        csv = tmp_path / "official.csv"
        csv.write_text(
            "year_month,origin,destination,pax_volume,distance_km,provenance\n"
            "2026-01,DEL,BOM,100,1148,DGCA\n"
            "2026-01,BOM,DEL,100,1148,DGCA\n",
            encoding="utf-8",
        )
        loader = DgcaTrafficLoader(data_path=csv)
        out = tmp_path / "roundtrip.csv"
        loader.export_csv(out)
        again = DgcaTrafficLoader(data_path=out)
        assert again._records[0].is_synthetic is False
        assert again._records[0].provenance == "DGCA"
        assert again._records[0].pax_volume == 100

    def test_committed_weights_file_carries_calibrated_baseline_provenance(self) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        csv = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "dgca_passenger_traffic_weights.csv"
        )
        loader = DgcaTrafficLoader(data_path=csv)
        january = next(
            rec
            for rec in loader._records
            if rec.year_month == "2024-01" and rec.route_code == "DEL-BOM"
        )
        assert january.pax_volume == 441875
        assert january.is_synthetic is True
        assert january.provenance in {"calibrated_baseline", "modelled_dgca_proxy"}
        assert loader.provenance["is_synthetic"] is True
        assert january.source_url.startswith("https://www.dgca.gov.in")
        assert january.release_date == "2024-02-18"

    def test_weights_still_sum_to_one_per_period(self) -> None:
        from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

        loader = DgcaTrafficLoader()
        for period, weights in loader._weights_by_period.items():
            assert abs(sum(weights.values()) - 1.0) < 1e-5, period
