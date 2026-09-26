"""Whether a MoSPI source string actually cites a press note.

The bare label ``MoSPI`` is not a citation. Rows stamped with it were the
withdrawn bundle, and readers must not plot them as official.
"""

from __future__ import annotations

_BARE_OFFICIAL_LABELS = frozenset({"mospi", "mospi_official", "nso", "official"})


def source_cites_press_note(source: str | None) -> bool:
    """True only when ``source`` contains a press-note URL and is not a bare agency label."""
    if source is None:
        return False
    text = source.strip()
    if not text or text.casefold() in _BARE_OFFICIAL_LABELS:
        return False
    return "https://" in text or "http://" in text
