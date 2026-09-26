"""File-declared provenance for city-pair traffic weights.

A file is official only when it says so. An absent declaration, or a declaration
that the file was generated, is modelled. A boolean is_synthetic=false on its
own is not a DGCA declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never


class TrafficProvenanceKind(StrEnum):
    """How a traffic file says it was produced."""

    DGCA = "DGCA"
    GENERATED = "generated"
    MODELLED = "modelled"


@dataclass(frozen=True, slots=True)
class TrafficProvenance:
    """Parsed provenance. is_synthetic is derived from kind."""

    kind: TrafficProvenanceKind

    @property
    def is_synthetic(self) -> bool:
        match self.kind:
            case TrafficProvenanceKind.DGCA:
                return False
            case TrafficProvenanceKind.GENERATED | TrafficProvenanceKind.MODELLED:
                return True
            case unreachable:
                assert_never(unreachable)

    @property
    def label(self) -> str:
        return self.kind.value


def split_provenance_directive(content: str) -> tuple[str | None, str]:
    """Split an optional '# provenance: TOKEN' first line from the rest of a text file."""
    lines = content.splitlines()
    if not lines:
        return None, content
    head = lines[0].lstrip()
    marker = "# provenance:"
    if not head.lower().startswith(marker):
        return None, content
    token = head.split(":", 1)[1].strip()
    rest = "\n".join(lines[1:])
    return (token or None), rest


def declared_token(
    row_provenance: str | None,
    is_synthetic_cell: str | None,
    file_declared: str | None,
) -> str | None:
    """Pick the declaration a row actually made."""
    if row_provenance and row_provenance.strip():
        return row_provenance.strip()
    if file_declared and file_declared.strip():
        return file_declared.strip()
    cell = (is_synthetic_cell or "").strip().casefold()
    if cell in {"true", "1", "yes", "generated", "synthetic"}:
        return "generated"
    return None


def resolve_traffic_provenance(declared: str | None) -> TrafficProvenance:
    """Map a declaration token to a provenance. Unknown and blank tokens are modelled."""
    token = (declared or "").strip().casefold()
    if token == "dgca":
        kind = TrafficProvenanceKind.DGCA
    elif token in {"generated", "synthetic"}:
        kind = TrafficProvenanceKind.GENERATED
    else:
        kind = TrafficProvenanceKind.MODELLED
    return TrafficProvenance(kind)
