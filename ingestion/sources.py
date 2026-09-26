"""Problem-statement source contract.

Implemented means a scraper class exists and is registered. It does not mean a
live fare has been read. produces_live_fares stays false until that happens.
"""

from __future__ import annotations

from typing import Dict, List, TypedDict


class SourceContract(TypedDict):
    supported_sources: List[str]
    source_types: Dict[str, str]
    ps_named_sources_total: int
    ps_named_sources_implemented: int
    live_verified_sources: List[str]
    produces_live_fares: bool


PS_SOURCE_TYPES: Dict[str, str] = {
    "makemytrip": "ota",
    "easemytrip": "ota",
    "spicejet": "airline_direct",
    "indigo": "airline_direct",
    "airindia": "airline_direct",
    "airindiaexpress": "airline_direct",
    "akasa": "airline_direct",
    "yatra": "ota",
    "cleartrip": "ota",
    "ixigo": "ota",
    "goibibo": "ota",
}


def source_contract() -> SourceContract:
    """Health fields for the 11 PS-named portals. None are live-verified."""
    names = list(PS_SOURCE_TYPES)
    return {
        "supported_sources": names,
        "source_types": dict(PS_SOURCE_TYPES),
        "ps_named_sources_total": 11,
        "ps_named_sources_implemented": len(names),
        "live_verified_sources": [],
        "produces_live_fares": False,
    }
