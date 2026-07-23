"""Search-only normalization helpers.

Stored romaji remains authoritative display data.  These helpers generate
relaxed ASCII variants at query time so users can search without switching an
IME or typing macrons.  The variants must never be used for stable keys,
merging, or duplicate detection because long-vowel spellings are ambiguous.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

_SEPARATORS = re.compile(r"[\s\-‐‑‒–—―_'’`]+")
_MACRON_OPTIONS = {
    "ā": ("a", "aa"),
    "ī": ("i", "ii"),
    "ū": ("u", "uu"),
    "ē": ("e", "ei", "ee"),
    "ō": ("o", "ou", "oo"),
}
_MACRON_BASE = str.maketrans({"ā": "a", "ī": "i", "ū": "u", "ē": "e", "ō": "o"})


def fold_text(value: str) -> str:
    """Case-fold and compatibility-normalize text without discarding macrons."""
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def compact_text(value: str) -> str:
    """Create a separator- and diacritic-insensitive search token."""
    folded = fold_text(value)
    decomposed = unicodedata.normalize("NFKD", folded)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _SEPARATORS.sub("", without_marks)


def compact_romaji(value: str, *, keep_macrons: bool = False) -> str:
    folded = fold_text(value)
    compact = _SEPARATORS.sub("", folded)
    if keep_macrons:
        return compact
    return compact.translate(_MACRON_BASE)


def _expand_macrons(compact: str, limit: int = 96) -> set[str]:
    """Expand macrons into common keyboard spellings, with a small safety cap."""
    variants: set[str] = {""}
    for char in compact:
        options = _MACRON_OPTIONS.get(char, (char,))
        expanded: set[str] = set()
        for prefix in variants:
            for option in options:
                expanded.add(prefix + option)
                if len(expanded) >= limit:
                    break
            if len(expanded) >= limit:
                break
        variants = expanded
    return variants


def _assimilation_variants(value: str) -> set[str]:
    """Accept Hepburn n/m variation before b, p, and m."""
    variants = {value}
    variants.add(re.sub(r"n(?=[bmp])", "m", value))
    variants.add(re.sub(r"m(?=[bmp])", "n", value))
    return {variant for variant in variants if variant}


def romaji_variants(value: str) -> set[str]:
    """Return compact ASCII variants for one stored romaji spelling.

    Examples:
      ``kyō shi tsu`` -> ``kyoshitsu``, ``kyoushitsu``, ``kyooshitsu``
      ``ko n pyū tā`` -> ``konpyuta``, ``konpyuuta``, ``konpyuutaa``
    """
    compact = compact_romaji(value, keep_macrons=True)
    if not compact:
        return set()
    variants: set[str] = set()
    for expanded in _expand_macrons(compact):
        variants.update(_assimilation_variants(compact_text(expanded)))
    # Always include the simplest no-diacritic form even if a cap was reached.
    variants.update(_assimilation_variants(compact_text(compact)))
    return variants


def entry_search_metadata(entry: dict[str, Any]) -> str:
    """Build hidden fzf/search metadata without changing visible presentation."""
    values: list[str] = []
    for field in (
        "key", "display", "reading", "romaji", "level", "review_group",
        "origin_type", "origin_language", "origin_word", "origin_note",
    ):
        value = str(entry.get(field) or "").strip()
        if value:
            values.append(value)
    values.extend(str(value) for value in entry.get("aliases", []) if str(value).strip())
    values.extend(sorted(romaji_variants(str(entry.get("romaji") or ""))))
    for source in entry.get("sources", []):
        value = str(source or "").strip()
        if value:
            values.append(value)
    for sense in entry.get("senses", []):
        for field in ("meaning", "example_ja", "example_zh"):
            value = str(sense.get(field) or "").strip()
            if value:
                values.append(value)
    for relation in [
        *entry.get("related_grammar", []),
        *entry.get("pending_related_grammar", []),
    ]:
        if not isinstance(relation, dict):
            continue
        for field in ("key", "display", "relation", "relation_type", "note", "source"):
            value = str(relation.get(field) or "").strip()
            if value:
                values.append(value)
    return " ".join(dict.fromkeys(values))


def attempt_search_metadata(
    attempt: dict[str, Any],
    linked_entries: Iterable[dict[str, Any]] = (),
) -> str:
    values: list[str] = []
    for field in (
        "event_key", "result", "date", "source", "section", "question",
        "question_type", "prompt", "user_answer", "correct_answer", "reason",
        "before", "after",
    ):
        value = str(attempt.get(field) or "").strip()
        if value:
            values.append(value)
    for option in attempt.get("options", []):
        value = str(option.get("text") or "").strip() if isinstance(option, dict) else str(option).strip()
        if value:
            values.append(value)
    for entry in linked_entries:
        values.append(entry_search_metadata(entry))
    return " ".join(value for value in values if value)


def entry_match_score(entry: dict[str, Any], query: str, *, sql_match: bool = False) -> int | None:
    """Rank one entry for search while keeping relaxed matches below exact ones."""
    raw = fold_text(query)
    if not raw:
        return 100 if sql_match else None
    compact_query = compact_text(query)

    key = fold_text(str(entry.get("key") or ""))
    display = fold_text(str(entry.get("display") or ""))
    reading = fold_text(str(entry.get("reading") or ""))
    aliases = [fold_text(str(value)) for value in entry.get("aliases", [])]
    romaji = fold_text(str(entry.get("romaji") or ""))

    if raw == key:
        return 0
    if raw == display:
        return 1
    if raw == reading or raw in aliases:
        return 2
    if raw == romaji:
        return 3

    if compact_query:
        compact_original = compact_text(romaji)
        if compact_query == compact_original:
            return 4
        variants = romaji_variants(romaji)
        if compact_query in variants:
            return 5
        if any(compact_query in variant for variant in variants):
            return 7

    ordinary_values = [
        key,
        display,
        reading,
        romaji,
        *aliases,
        fold_text(str(entry.get("level") or "")),
        fold_text(str(entry.get("review_group") or "")),
        fold_text(str(entry.get("origin_word") or "")),
        fold_text(str(entry.get("origin_note") or "")),
    ]
    if any(raw in value for value in ordinary_values if value):
        return 10
    if compact_query and any(
        compact_query in compact_text(value) for value in ordinary_values if value
    ):
        return 12

    # The enriched metadata document is shared with interactive browse/fzf.  It
    # includes meanings/examples, sources, relation notes/sources, aliases and
    # romaji variants, so core search and browse cannot silently diverge.
    metadata = entry_search_metadata(entry)
    folded_metadata = fold_text(metadata)
    if raw and raw in folded_metadata:
        return 20
    if compact_query and compact_query in compact_text(metadata):
        return 22
    return 30 if sql_match else None
