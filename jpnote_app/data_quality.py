"""Deterministic data-quality helpers shared by import, audit, and repair."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def entry_key_head(key: str) -> str:
    """Return the user-facing stable-key suffix without guessing its type."""
    return str(key or "").split(":", 1)[1] if ":" in str(key or "") else str(key or "")


def clean_aliases(
    key: str,
    display: str,
    reading: str,
    aliases: Iterable[Any],
) -> list[str]:
    """Strip/dedupe aliases and remove identities already indexed elsewhere.

    display, reading, and the stable-key head are all searched directly, so an
    exact alias copy only adds presentation noise and can be removed safely.
    """
    excluded = {str(display or "").strip(), str(reading or "").strip(), entry_key_head(key).strip()}
    excluded.discard("")
    result: list[str] = []
    seen: set[str] = set()
    for raw in aliases:
        if not isinstance(raw, str):
            continue
        alias = raw.strip()
        if not alias or alias in excluded or alias in seen:
            continue
        seen.add(alias)
        result.append(alias)
    return result


def sense_is_blank(sense: dict[str, Any]) -> bool:
    return not str(sense.get("example_ja") or "").strip() and not str(sense.get("example_zh") or "").strip()


def safe_clean_senses(senses: Iterable[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Apply only lossless/dominance-based sense cleanup.

    - exact duplicate triples collapse to the first occurrence;
    - when the same meaning has a richer example-bearing row, a fully blank
      example row is redundant and removed;
    - distinct non-empty examples are preserved.
    """
    normalized: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = []
    seen_signatures: set[tuple[str, str, str]] = set()
    for raw in senses:
        sense = {
            "meaning": str(raw.get("meaning") or ""),
            "example_ja": str(raw.get("example_ja") or ""),
            "example_zh": str(raw.get("example_zh") or ""),
        }
        signature = (sense["meaning"], sense["example_ja"], sense["example_zh"])
        if signature in seen_signatures:
            actions.append({"kind": "exact_duplicate_sense", "meaning": sense["meaning"]})
            continue
        seen_signatures.add(signature)
        normalized.append(sense)

    rich_meanings = {
        sense["meaning"] for sense in normalized if not sense_is_blank(sense)
    }
    cleaned: list[dict[str, str]] = []
    for sense in normalized:
        if sense_is_blank(sense) and sense["meaning"] in rich_meanings:
            actions.append({"kind": "blank_sense_shadowed", "meaning": sense["meaning"]})
            continue
        cleaned.append(sense)
    return cleaned, actions


def meaning_groups(senses: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sense in senses:
        groups[str(sense.get("meaning") or "")].append(dict(sense))
    return dict(groups)
