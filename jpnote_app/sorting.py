"""Deterministic JLPT and Japanese reading sort helpers."""

from __future__ import annotations

import unicodedata
from typing import Any

LEVEL_ORDER = {"N5": 0, "N4": 1, "N3": 2, "N2": 3, "N1": 4, "": 9}

# Unicode hiragana is mostly ordered by gojuon, but voiced and small kana need a
# stable explicit order for human-facing lists.
_KANA_ORDER = (
    "ぁあぃいぅうぇえぉお"
    "ゕかがきぎくぐけげこご"
    "さざしじすずせぜそぞ"
    "ただちぢっつづてでとど"
    "なにぬねの"
    "はばぱひびぴふぶぷへべぺほぼぽ"
    "まみむめも"
    "ゃやゅゆょよ"
    "らりるれろ"
    "ゎわゐゑを"
    "んゔー"
)
_KANA_WEIGHT = {char: index for index, char in enumerate(_KANA_ORDER)}
_SMALL_TO_NORMAL = str.maketrans("ぁぃぅぇぉっゃゅょゎゕゖ", "あいうえおつやゆよわかけ")


def normalize_level(value: str) -> str:
    normalized = value.strip().upper()
    return normalized if normalized in {"N1", "N2", "N3", "N4", "N5"} else value.strip()


def katakana_to_hiragana(text: str) -> str:
    result: list[str] = []
    for char in unicodedata.normalize("NFKC", text):
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(char)
    return "".join(result)


def reading_sort_key(reading: str) -> tuple[Any, ...]:
    normalized = katakana_to_hiragana(reading.strip())
    if not normalized:
        return (1, ())
    primary = normalized.translate(_SMALL_TO_NORMAL)
    weights = tuple(_KANA_WEIGHT.get(char, 10000 + ord(char)) for char in primary)
    tie = tuple(_KANA_WEIGHT.get(char, 10000 + ord(char)) for char in normalized)
    return (0, weights, tie, normalized)


def entry_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    level = normalize_level(str(entry.get("level") or ""))
    return (
        LEVEL_ORDER.get(level, 8),
        reading_sort_key(str(entry.get("reading") or "")),
        str(entry.get("display") or ""),
        str(entry.get("key") or ""),
    )
