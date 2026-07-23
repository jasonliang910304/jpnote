"""Kana-to-spaced-Hepburn conversion used by safe repair operations.

This intentionally converts an already supplied kana reading.  It never tries
to guess the reading of kanji, and it never invents pitch accent data.
"""

from __future__ import annotations

from .sorting import katakana_to_hiragana

_BASE = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o", "ん": "n",
    "ゔ": "vu",
}
_DIGRAPH = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "いぇ": "ye",
    "きぇ": "kye", "ぎぇ": "gye",
    "くぁ": "kwa", "くぃ": "kwi", "くぇ": "kwe", "くぉ": "kwo",
    "ぐぁ": "gwa", "ぐぃ": "gwi", "ぐぇ": "gwe", "ぐぉ": "gwo",
    "しぇ": "she", "じぇ": "je", "ちぇ": "che",
    "すぃ": "si", "ずぃ": "zi",
    "つぁ": "tsa", "つぃ": "tsi", "つぇ": "tse", "つぉ": "tso",
    "てぃ": "ti", "てゅ": "tyu", "でぃ": "di", "でゅ": "dyu",
    "とぅ": "tu", "どぅ": "du",
    "にぇ": "nye", "ひぇ": "hye", "びぇ": "bye", "ぴぇ": "pye",
    "みぇ": "mye", "りぇ": "rye",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo", "ふゅ": "fyu",
    "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo", "ゔゅ": "vyu",
}
_MACRON = {"a": "ā", "i": "ī", "u": "ū", "e": "ē", "o": "ō"}


def _last_vowel(token: str) -> str:
    for char in reversed(token):
        plain = {"ā": "a", "ī": "i", "ū": "u", "ē": "e", "ō": "o"}.get(char, char)
        if plain in "aeiou":
            return plain
    return ""


def _lengthen(token: str) -> str:
    vowel = _last_vowel(token)
    if not vowel:
        return token
    index = max(token.rfind(vowel), *(token.rfind(mark) for mark in _MACRON.values()))
    if index < 0:
        return token
    return token[:index] + _MACRON[vowel] + token[index + 1 :]


def _initial_consonant(token: str) -> str:
    if token.startswith("ch"):
        return "t"
    if token.startswith("sh"):
        return "s"
    if token.startswith("ts"):
        return "t"
    return token[0] if token and token[0] not in "aeiou" else ""


def spaced_hepburn(reading: str) -> str:
    kana = katakana_to_hiragana(reading.strip())
    raw: list[str] = []
    index = 0
    pending_sokuon = False
    while index < len(kana):
        char = kana[index]
        if char.isspace() or char in {"・", "･"}:
            index += 1
            continue
        if char == "っ":
            pending_sokuon = True
            index += 1
            continue
        if char == "ー":
            if not raw or pending_sokuon:
                return ""
            raw[-1] = _lengthen(raw[-1])
            index += 1
            continue
        pair = kana[index : index + 2]
        if pair in _DIGRAPH:
            token = _DIGRAPH[pair]
            index += 2
        elif char in _BASE:
            token = _BASE[char]
            index += 1
        else:
            # Safe repair must never persist mixed kana/Latin output.  Return
            # an empty result when the converter does not fully understand the
            # reading; a later romaji audit can request human review instead.
            return ""
        if pending_sokuon:
            # Small tsu cannot safely geminate the moraic nasal or a vowel.
            if token == "n":
                return ""
            consonant = _initial_consonant(token)
            if not consonant:
                return ""
            raw.append(consonant)
            pending_sokuon = False
        raw.append(token)

    if pending_sokuon:
        return ""

    # Collapse common orthographic long-vowel sequences into a macron while
    # preserving mora separation elsewhere.
    result: list[str] = []
    for token in raw:
        if result and token in {"u", "o"} and _last_vowel(result[-1]) == "o":
            result[-1] = _lengthen(result[-1])
        elif result and token == "u" and _last_vowel(result[-1]) == "u":
            result[-1] = _lengthen(result[-1])
        elif result and token == "i" and _last_vowel(result[-1]) == "e":
            result[-1] = _lengthen(result[-1])
        elif result and token in {"a", "i", "u", "e", "o"} and _last_vowel(result[-1]) == token:
            result[-1] = _lengthen(result[-1])
        else:
            result.append(token)
    return " ".join(result)
