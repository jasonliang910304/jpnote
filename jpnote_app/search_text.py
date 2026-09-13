"""Lightweight text normalization shared by core search and fzf helpers.

Keep this module stdlib-only and cheap to import: fzf starts the reload helper on
query changes, so pulling in romaji/search metadata construction on every
keystroke defeats the purpose of the small helper process.
"""

from __future__ import annotations

import re
import unicodedata

SEPARATORS = re.compile(r"[\s\-‐‑‒–—―_'’`]+")


def fold_text(value: str) -> str:
    """Case-fold and compatibility-normalize text without discarding macrons."""
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def compact_folded_text(folded: str) -> str:
    """Compact text that has already passed through :func:`fold_text`."""
    decomposed = unicodedata.normalize("NFKD", folded)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return SEPARATORS.sub("", without_marks)


def compact_text(value: str) -> str:
    """Create a separator- and diacritic-insensitive search token."""
    return compact_folded_text(fold_text(value))
