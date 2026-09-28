"""Health and registry contract for the 11 PS-named portals."""

from __future__ import annotations

from ingestion.config import IngestionConfig
from ingestion.crawlers.portal import PortalScraper
from ingestion.orchestrator import IngestionOrchestrator, build_scraper_registry
from ingestion.sources import source_contract


def test_registry_and_health_count_implemented_sources_and_claim_only_spicejet_live() -> (
    None
):
    contract = source_contract()
    assert contract["ps_named_sources_total"] == 11
    assert contract["ps_named_sources_implemented"] == 11
    assert contract["produces_live_fares"] is True
    assert contract["live_verified_sources"] == ["spicejet"]
    assert len(contract["supported_sources"]) == 11
    registry = build_scraper_registry(IngestionConfig(ingestion_mode="synthetic"))
    for name, kind in contract["source_types"].items():
        assert name in registry
        portal = registry[name]
        if isinstance(portal, PortalScraper):
            assert portal.SOURCE_TYPE == kind
    orchestrator = IngestionOrchestrator(
        config=IngestionConfig(ingestion_mode="synthetic"),
        jitter_range=(0.0, 0.0),
    )
    assert set(contract["supported_sources"]).issubset(orchestrator.scrapers)
