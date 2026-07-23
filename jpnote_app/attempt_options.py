"""Structured multiple-choice option helpers and conservative legacy migration.

The parser is intentionally conservative. It only rewrites old prompt text
when it can identify a complete ordered option sequence with high confidence.
Ambiguous prompts are left untouched so jpnote never invents or drops learner
content during migration.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ParsedOptions:
    prompt: str
    options: list[dict[str, Any]]
    pattern: str


_EXPLICIT_MARKER_RE = re.compile(r"(?:選択肢|選項|选项)\s*[:：]\s*", re.IGNORECASE)
_OPTION_SUFFIX = r"(?:[.．、:：)）]\s*|\s+)"
_FIRST_INLINE_MARKER_RE = re.compile(
    rf"(?:^|(?<=[\n\r。！？.!?]))\s*1{_OPTION_SUFFIX}",
    re.MULTILINE,
)
_FOLLOWING_INLINE_MARKER_RE = re.compile(
    rf"(?:[\n\r／/])\s*([2-4]){_OPTION_SUFFIX}",
    re.MULTILINE,
)


def _clean_piece(value: str) -> str:
    return re.sub(r"^[\s／/]+|[\s／/]+$", "", value).strip()


def _extract_numbered_sequence(text: str, *, allow_plain_spaces: bool) -> tuple[int, list[dict[str, Any]]] | None:
    """Return start offset and options for a strict 1..4 numbered sequence.

    This parser handles explicit-choice-marker tails and older newline/slash
    layouts. It deliberately avoids treating arbitrary inline numbers in prose
    as option boundaries.
    """
    if allow_plain_spaces:
        marker_re = re.compile(
            r"(?:^|[\n\r／/])\s*([1-9])(?:[.．、:：)）]\s*|\s+)"
            r"|(?<!\d)([1-9])[.．、:：)）]\s*",
            re.MULTILINE,
        )
    else:
        marker_re = re.compile(
            r"(?:^|[\n\r／/])\s*([1-9])(?:[.．、:：)）]\s*|\s+)",
            re.MULTILINE,
        )

    markers = list(marker_re.finditer(text))
    if not markers:
        return None

    for start_index, marker in enumerate(markers):
        if int(marker.group(1) or marker.group(2)) != 1:
            continue
        sequence = [marker]
        expected = 2
        for candidate in markers[start_index + 1 :]:
            number = int(candidate.group(1) or candidate.group(2))
            if number == expected:
                sequence.append(candidate)
                expected += 1
                continue
            if number >= expected:
                break
        if [int(item.group(1) or item.group(2)) for item in sequence[:4]] != [1, 2, 3, 4]:
            continue
        sequence = sequence[:4]
        options: list[dict[str, Any]] = []
        valid = True
        for index, current in enumerate(sequence):
            content_start = current.end()
            content_end = sequence[index + 1].start() if index + 1 < len(sequence) else len(text)
            content = _clean_piece(text[content_start:content_end])
            if not content:
                valid = False
                break
            options.append({"id": index + 1, "text": content})
        if valid:
            return sequence[0].start(), options
    return None


def _extract_inline_slash_sequence(text: str) -> tuple[int, list[dict[str, Any]]] | None:
    """Parse ``...。1 A／2 B／3 C／4 D`` style legacy prompts.

    The first choice must begin at the start of text, after a newline, or
    immediately after sentence-ending punctuation. Choices 2..4 must each be
    introduced by an explicit slash/newline separator. Requiring the complete
    1..4 sequence keeps ordinary numbers in Japanese prose out of this path.
    """
    for first in _FIRST_INLINE_MARKER_RE.finditer(text):
        sequence: list[re.Match[str]] = [first]
        search_pos = first.end()
        expected = 2
        while expected <= 4:
            found: re.Match[str] | None = None
            for candidate in _FOLLOWING_INLINE_MARKER_RE.finditer(text, search_pos):
                number = int(candidate.group(1))
                if number == expected:
                    found = candidate
                    break
                # Seeing a later option number before the expected one makes
                # this candidate sequence incomplete/ambiguous.
                if number > expected:
                    break
            if found is None:
                break
            sequence.append(found)
            search_pos = found.end()
            expected += 1
        if len(sequence) != 4:
            continue

        options: list[dict[str, Any]] = []
        valid = True
        for index, current in enumerate(sequence):
            content_start = current.end()
            content_end = sequence[index + 1].start() if index + 1 < len(sequence) else len(text)
            content = _clean_piece(text[content_start:content_end])
            if not content:
                valid = False
                break
            options.append({"id": index + 1, "text": content})
        if valid:
            return first.start(), options
    return None


def parse_legacy_prompt_options(prompt: str) -> ParsedOptions | None:
    """Parse old ``prompt`` strings that embedded four numbered choices.

    Supported high-confidence forms include an explicit ``選択肢：`` marker,
    newline/slash-numbered choices, and compact workbook forms such as
    ``...。1 A／2 B／3 C／4 D``. The function never mutates input and returns
    ``None`` for ambiguous text.
    """
    text = str(prompt or "").strip()
    if not text:
        return None

    explicit = _EXPLICIT_MARKER_RE.search(text)
    if explicit:
        tail = text[explicit.end() :]
        parsed = _extract_numbered_sequence(tail, allow_plain_spaces=True)
        if parsed:
            _, options = parsed
            stem = text[: explicit.start()].rstrip()
            if stem:
                return ParsedOptions(stem, options, "explicit_marker")

    parsed = _extract_numbered_sequence(text, allow_plain_spaces=False)
    if parsed:
        start, options = parsed
        stem = _clean_piece(text[:start])
        if stem:
            return ParsedOptions(stem, options, "numbered_lines_or_slashes")

    parsed = _extract_inline_slash_sequence(text)
    if parsed:
        start, options = parsed
        stem = _clean_piece(text[:start])
        if stem:
            return ParsedOptions(stem, options, "inline_slash_choices")
    return None


def _compare_text(value: Any) -> str:
    """Normalize only harmless layout differences for duplicate-tail checks."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text).strip()


def options_equivalent(left: Any, right: Any) -> bool:
    """Return True when two structured option/part lists contain the same 1..4 text."""
    try:
        left_items = normalized_options(left)
        right_items = normalized_options(right)
    except ValueError:
        return False
    if [item["id"] for item in left_items] != [item["id"] for item in right_items]:
        return False
    return all(
        _compare_text(a["text"]) == _compare_text(b["text"])
        for a, b in zip(left_items, right_items, strict=True)
    )


def cleaned_prompt_and_options(
    prompt: str,
    options: Any = None,
    *,
    parts: Any = None,
    question_type: str = "",
) -> tuple[str, list[dict[str, Any]], str | None]:
    """Return a display-safe prompt/options view without mutating stored data.

    - Empty ``options``: safely split a high-confidence embedded option tail.
    - Existing ``options``: remove the tail only when it exactly duplicates the
      stored structured options.
    - ``reorder_4``: remove a duplicated numbered tail only when it exactly
      matches the four stored reorder parts.
    """
    clean_prompt = str(prompt or "").strip()
    clean_options = normalized_options(options or [])
    parsed = parse_legacy_prompt_options(clean_prompt)
    if parsed is None:
        return clean_prompt, clean_options, None

    if question_type == "reorder_4":
        if options_equivalent(parts or [], parsed.options):
            return parsed.prompt, clean_options, "clean_reorder_prompt"
        return clean_prompt, clean_options, None

    if not clean_options:
        return parsed.prompt, parsed.options, "split_options"
    if options_equivalent(clean_options, parsed.options):
        return parsed.prompt, clean_options, "clean_prompt"
    return clean_prompt, clean_options, None


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    for char in text:
        code = ord(char)
        if char in {"\n", "\r", "\t"}:
            continue
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            raise ValueError("options 文字包含不允許的終端控制字元。")
    return text


def normalized_options(value: Any) -> list[dict[str, Any]]:
    """Normalize a public options value while accepting convenient input.

    Accepted forms:
    - ``[{"id": 1, "text": "..."}, ...]``
    - ``["...", "...", ...]`` (ids are assigned from 1)
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("options 必須是陣列。")
    result: list[dict[str, Any]] = []
    for index, option in enumerate(value, 1):
        if isinstance(option, str):
            option_id = index
            text = _safe_text(option)
        elif isinstance(option, dict):
            raw_option_id = option.get("id", index)
            if not isinstance(raw_option_id, int) or isinstance(raw_option_id, bool):
                raise ValueError("options.id 必須是正整數。")
            option_id = raw_option_id
            if not isinstance(option.get("text"), str):
                raise ValueError("options.text 必須是字串。")
            text = _safe_text(option.get("text"))
        else:
            raise ValueError("options 每個項目必須是文字或 {id,text} 物件。")
        if option_id <= 0 or not text:
            raise ValueError("options 的 id 必須是正整數且 text 不能為空。")
        result.append({"id": option_id, "text": text})
    ids = [option["id"] for option in result]
    if len(ids) != len(set(ids)):
        raise ValueError("options.id 不能重複。")
    return sorted(result, key=lambda option: option["id"])



def _suspicious_legacy_option_reason(
    prompt: str,
    options: Any,
    *,
    parts: Any = None,
    question_type: str = "",
) -> str | None:
    """Return a conservative reason when a prompt looks option-like but is unsafe to rewrite."""
    text = str(prompt or "").strip()
    if not text:
        return None
    if _EXPLICIT_MARKER_RE.search(text):
        return "explicit_option_marker"

    # Multiple slash/newline numbered boundaries strongly suggest workbook
    # choices, while a single ordinary number is intentionally ignored.
    boundary_re = re.compile(r"(?:^|[\n\r／/])\s*[1-4](?:[.．、:：)）]\s*|\s+)", re.MULTILINE)
    if len(boundary_re.findall(text)) >= 2:
        return "incomplete_numbered_choices"

    normalized_prompt = _compare_text(text)
    candidates = parts if question_type == "reorder_4" else options
    try:
        items = normalized_options(candidates or [])
    except ValueError:
        items = []
    matched = 0
    for item in items:
        piece = _compare_text(item.get("text", ""))
        if piece and piece in normalized_prompt:
            matched += 1
    if matched >= 2:
        return "structured_choice_residue"
    return None


def suspicious_option_migration_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return suspicious legacy attempts that are not safe auto-migration candidates."""
    safe_ids = {item["id"] for item in safe_option_migration_candidates(conn)}
    rows = conn.execute(
        """
        SELECT id, event_key, attempt_date, source, section, question, question_type,
               prompt, parts_json, options_json
        FROM attempts ORDER BY id
        """
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        if row["id"] in safe_ids:
            continue
        try:
            options = json.loads(row["options_json"] or "[]")
            parts = json.loads(row["parts_json"] or "[]")
        except json.JSONDecodeError:
            continue
        reason = _suspicious_legacy_option_reason(
            row["prompt"],
            options,
            parts=parts,
            question_type=row["question_type"],
        )
        if reason is None:
            continue
        preview = re.sub(r"\s+", " ", str(row["prompt"] or "")).strip()
        if len(preview) > 100:
            preview = preview[:97] + "..."
        result.append({
            "id": row["id"],
            "event_key": row["event_key"],
            "date": row["attempt_date"],
            "source": row["source"],
            "section": row["section"],
            "question": row["question"],
            "reason": reason,
            "prompt_preview": preview,
        })
    return result

def safe_option_migration_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return old attempts that can be safely normalized without guessing."""
    rows = conn.execute(
        "SELECT id, event_key, question_type, prompt, parts_json, options_json FROM attempts ORDER BY id"
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            existing_options = json.loads(row["options_json"] or "[]")
            parts = json.loads(row["parts_json"] or "[]")
        except json.JSONDecodeError:
            continue
        if not isinstance(existing_options, list) or not isinstance(parts, list):
            continue
        prompt, options, action = cleaned_prompt_and_options(
            row["prompt"],
            existing_options,
            parts=parts,
            question_type=row["question_type"],
        )
        if action is None:
            continue
        result.append({
            "id": row["id"],
            "event_key": row["event_key"],
            "old_prompt": row["prompt"],
            "prompt": prompt,
            "options": options,
            "pattern": action,
        })
    return result


def apply_safe_option_migrations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Apply only high-confidence prompt/option normalizations and return a report."""
    candidates = safe_option_migration_candidates(conn)
    with conn:
        for item in candidates:
            conn.execute(
                "UPDATE attempts SET prompt=?, options_json=? WHERE id=? AND prompt=?",
                (
                    item["prompt"],
                    json.dumps(item["options"], ensure_ascii=False),
                    item["id"],
                    item["old_prompt"],
                ),
            )
    return candidates
