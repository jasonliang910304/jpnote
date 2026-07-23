"""Terminal presentation helpers for jpnote.

The core and repository layers return structured dictionaries.  This module is
only responsible for turning those records into readable plain text for the
CLI and optional fzf previews.  Keeping presentation here prevents terminal
layout choices from leaking into SQLite, JSON, Markdown, or future Web APIs.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from typing import Any, Iterable

from .terminal_style import style, tone
from .attempt_options import cleaned_prompt_and_options


RESULT_LABELS = {
    "wrong": "錯題",
    "partial": "部分正確",
    "correct": "作答",
    "unknown": "作答",
}


def display_width(text: str) -> int:
    """Return an approximate terminal-cell width for CJK-aware alignment."""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1
    return width


def terminal_width(default: int = 60) -> int:
    """Choose a compact readable width without assuming a specific terminal."""
    columns = shutil.get_terminal_size((default + 4, 24)).columns
    return max(34, min(columns - 2, default))


_ATOMIC_PLACEHOLDER_RE = re.compile(
    r"[（(［\[]\s*[0-9]+\s*[）)］\]]"
)


def _wrap_units(text: str) -> list[str]:
    """Split text into terminal-wrap units while keeping answer slots intact."""
    units: list[str] = []
    position = 0
    for match in _ATOMIC_PLACEHOLDER_RE.finditer(text):
        units.extend(text[position:match.start()])
        units.append(match.group(0))
        position = match.end()
    units.extend(text[position:])
    return units


def _wrap_line(text: str, width: int) -> list[str]:
    """Wrap one logical line with basic Japanese kinsoku and atomic slots."""
    text = str(text)
    if not text:
        return [""]
    result: list[str] = []
    current = ""
    current_width = 0
    forbidden_end = set("（(［[「『【｛{〈《")
    forbidden_start = set("、。）」』】］]｝}〉》！？,.!?;:：；")

    for unit in _wrap_units(text):
        unit_width = display_width(unit)
        if current and current_width + unit_width > width:
            split_at = current.rfind(" ")
            if split_at > 0:
                result.append(current[:split_at].rstrip())
                current = current[split_at + 1 :].lstrip()
                current_width = display_width(current)
            elif unit and unit[0] in forbidden_start:
                # Slightly exceed the target width rather than start a line
                # with Japanese closing punctuation.
                current += unit
                current_width += unit_width
                continue
            else:
                carry = ""
                while current and current[-1] in forbidden_end:
                    carry = current[-1] + carry
                    current = current[:-1]
                if current:
                    result.append(current.rstrip())
                current = carry
                current_width = display_width(current)
        current += unit
        current_width += unit_width
    if current or not result:
        result.append(current.rstrip())
    return result


def wrap_text(text: str, width: int) -> list[str]:
    result: list[str] = []
    for logical in str(text).splitlines() or [""]:
        result.extend(_wrap_line(logical, width))
    return result


def _right_badge(primary: str, badge: str, width: int) -> list[str]:
    if not badge:
        return wrap_text(primary, width)
    needed = display_width(primary) + display_width(badge) + 2
    if needed <= width:
        gap = " " * (width - display_width(primary) - display_width(badge))
        return [f"{primary}{gap}{badge}"]
    lines = wrap_text(primary, width)
    if lines and display_width(lines[-1]) + display_width(badge) + 2 <= width:
        gap = " " * (width - display_width(lines[-1]) - display_width(badge))
        lines[-1] = f"{lines[-1]}{gap}{badge}"
    else:
        lines.append(" " * max(0, width - display_width(badge)) + badge)
    return lines


def boxed_header(
    label: str,
    primary: str,
    secondary: Iterable[str] = (),
    badge: str = "",
    width: int | None = None,
    tone_name: str = "cyan",
) -> str:
    """Render the compact card header, styling only after width calculation."""
    width = width or terminal_width()
    prefix = f"┌─ {label} "
    top_plain = prefix + "─" * max(1, width - display_width(prefix))
    bottom_plain = "└" + "─" * max(1, width - 1)
    inner_width = max(12, width - 2)

    primary_rows = wrap_text(primary, inner_width)
    rendered_rows: list[str] = []
    if badge:
        if len(primary_rows) == 1 and display_width(primary_rows[0]) + display_width(badge) + 2 <= inner_width:
            gap = " " * (inner_width - display_width(primary_rows[0]) - display_width(badge))
            rendered_rows.append(style(primary_rows[0], "bold") + gap + style(badge, "bold", "yellow"))
        else:
            for row in primary_rows[:-1]:
                rendered_rows.append(style(row, "bold"))
            last = primary_rows[-1]
            if display_width(last) + display_width(badge) + 2 <= inner_width:
                gap = " " * (inner_width - display_width(last) - display_width(badge))
                rendered_rows.append(style(last, "bold") + gap + style(badge, "bold", "yellow"))
            else:
                rendered_rows.append(style(last, "bold"))
                rendered_rows.append(" " * max(0, inner_width - display_width(badge)) + style(badge, "bold", "yellow"))
    else:
        rendered_rows.extend(style(row, "bold") for row in primary_rows)

    for value in secondary:
        if value:
            rendered_rows.extend(style(row, "dim") for row in wrap_text(value, inner_width))

    top = tone(top_plain, tone_name, bold=True)
    bottom = tone(bottom_plain, tone_name)
    return "\n".join([top, *(f"{tone('│', tone_name)} {row}" for row in rendered_rows), bottom])


def _section(
    title: str,
    lines: Iterable[str | tuple[str, bool]],
    width: int,
    *,
    title_tone: str = "cyan",
    body_tone: str | None = None,
    dim_body: bool = False,
) -> str:
    body: list[str] = []
    body_width = max(10, width - 2)
    for value in lines:
        line_dim = False
        if isinstance(value, tuple):
            line, line_dim = value
        else:
            line = value
        if line == "":
            body.append("  ")
            continue
        wrapped = wrap_text(line, body_width)
        for piece in wrapped:
            rendered = piece
            if body_tone:
                rendered = tone(rendered, body_tone)
            if dim_body or line_dim:
                rendered = style(rendered, "dim")
            body.append(f"  {rendered}")
    return "\n".join([tone(title, title_tone, bold=True), *body])


def _numbered_values(values: list[str]) -> list[str]:
    if len(values) <= 1:
        return values
    return [f"{index}. {value}" for index, value in enumerate(values, 1)]


def _type_tone(entry_type: str) -> str:
    return "magenta" if entry_type == "grammar" else "blue"


def _result_tone(result: str) -> str:
    return {"wrong": "red", "partial": "yellow", "correct": "green"}.get(result, "cyan")


def _styled_type_label(label: str, entry_type: str) -> str:
    return tone(f"[{label}]", _type_tone(entry_type), bold=True)


def render_entry(entry: dict[str, Any], width: int | None = None) -> str:
    """Render one grammar or vocabulary entry in the B-Compact layout."""
    width = width or terminal_width()
    label = "文法" if entry.get("type") == "grammar" else "單字"
    reading = f"（{entry['reading']}）" if entry.get("reading") else ""
    header = boxed_header(
        label,
        f"{entry.get('display', '')}{reading}",
        [entry.get("key", "")],
        entry.get("level", ""),
        width,
    )
    sections: list[str] = []

    if entry.get("romaji"):
        sections.append(_section("羅馬拼音", [entry["romaji"]], width))

    accent_bits = "・".join(
        value for value in (entry.get("accent", ""), entry.get("accent_type", "")) if value
    )
    if entry.get("accent_display") or accent_bits or entry.get("accent_note"):
        accent_lines: list[str] = []
        if entry.get("accent_display") or accent_bits:
            text = entry.get("accent_display") or entry.get("romaji") or ""
            suffix = f" [{accent_bits}]" if accent_bits else ""
            accent_lines.append(f"{text}{suffix}")
        if entry.get("accent_note"):
            accent_lines.append(entry["accent_note"])
        sections.append(_section("重音", accent_lines, width))

    if entry.get("review_group"):
        sections.append(_section("複習群組", [entry["review_group"]], width))
    if entry.get("aliases"):
        sections.append(_section("相關形式", ["、".join(entry["aliases"])], width))

    if entry.get("origin_type"):
        origin = " ".join(
            value for value in (entry.get("origin_language", ""), entry.get("origin_word", "")) if value
        )
        origin_lines = [entry["origin_type"] + (f"｜{origin}" if origin else "")]
        if entry.get("origin_note"):
            origin_lines.append(entry["origin_note"])
        sections.append(_section("語源", origin_lines, width))

    senses = entry.get("senses", [])
    meanings = [sense.get("meaning", "") for sense in senses if sense.get("meaning")]
    if meanings:
        sense_title = "意思／用法" if entry.get("type") == "grammar" else "意思"
        sections.append(_section(sense_title, _numbered_values(meanings), width))

    examples: list[str | tuple[str, bool]] = []
    with_examples = [sense for sense in senses if sense.get("example_ja") or sense.get("example_zh")]
    for index, sense in enumerate(with_examples, 1):
        prefix = f"{index}. " if len(with_examples) > 1 else ""
        if sense.get("example_ja"):
            examples.append((prefix + sense["example_ja"], False))
            prefix = "   " if len(with_examples) > 1 else ""
        if sense.get("example_zh"):
            examples.append((prefix + sense["example_zh"], True))
    if examples:
        sections.append(_section("例句", examples, width))

    relations: list[str] = []
    for relation in entry.get("related_grammar", []):
        target = relation.get("display") or relation.get("key", "")
        relations.append(f"[{relation.get('relation', '')}] {target}")
        if relation.get("note"):
            relations.append(f"  {relation['note']}")
    if relations:
        sections.append(_section("相關文法", relations, width))

    pending: list[str] = []
    for relation in entry.get("pending_related_grammar", []):
        pending.append(f"[{relation.get('relation_type', '')}] {relation.get('target_key', '')}")
        if relation.get("note"):
            pending.append(f"  {relation['note']}")
    if pending:
        sections.append(_section("尚未收錄的相關文法", pending, width))

    stats = entry.get("attempt_stats") or {}
    if stats.get("attempt_count"):
        strict = stats.get("strict_accuracy", stats.get("accuracy"))
        weighted = stats.get("weighted_accuracy")
        strict_text = "—" if strict is None else f"{strict:.1f}%"
        weighted_text = "—" if weighted is None else f"{weighted:.1f}%"
        stats_lines = [
            f"作答 {stats['attempt_count']}｜答對 {stats['correct_count']}｜"
            f"答錯 {stats['mistake_count']}｜部分正確 {stats['partial_count']}",
            f"嚴格正確率 {strict_text}｜加權正確率 {weighted_text}",
        ]
        if stats.get("last_answered_at"):
            stats_lines.append(f"最近作答：{stats['last_answered_at']}")
        sections.append(_section("作答統計", stats_lines, width))

    if entry.get("sources"):
        sections.append(_section("來源", ["、".join(entry["sources"])], width, dim_body=True))

    return "\n\n".join([header, *sections])


def render_entry_summary(entry: dict[str, Any]) -> str:
    label = "文法" if entry.get("type") == "grammar" else "單字"
    reading = f"（{entry['reading']}）" if entry.get("reading") else ""
    level = f"  {style(entry['level'], 'bold', 'yellow')}" if entry.get("level") else ""
    key = style(f"<{entry.get('key', '')}>", "dim")
    return f"{_styled_type_label(label, entry.get('type', ''))} {style(entry.get('display', '') + reading, 'bold')}{level}  {key}"


def _attempt_heading(attempt: dict[str, Any]) -> str:
    return "｜".join(
        value
        for value in (
            attempt.get("date", ""),
            attempt.get("question", ""),
            attempt.get("result", ""),
        )
        if value
    ) or attempt.get("event_key", "")



def _option_lines(options: list[dict[str, Any]], width: int) -> list[str]:
    """Render numbered choices with hanging indentation for wrapped lines."""
    body_width = max(10, width - 2)
    result: list[str] = []
    for option in options:
        prefix = f"{option.get('id', '')}. "
        text = str(option.get("text") or "")
        content_width = max(8, body_width - display_width(prefix))
        wrapped = wrap_text(text, content_width)
        # Basic Japanese kinsoku handling: avoid beginning a continuation line
        # with closing punctuation by moving one preceding character with it.
        forbidden_start = set("、。）」』】！？,.!?;:：；")
        for index in range(1, len(wrapped)):
            if wrapped[index] and wrapped[index][0] in forbidden_start and wrapped[index - 1]:
                carry = wrapped[index - 1][-1]
                wrapped[index - 1] = wrapped[index - 1][:-1]
                wrapped[index] = carry + wrapped[index]
        if not wrapped:
            continue
        result.append(prefix + wrapped[0])
        result.extend(" " * display_width(prefix) + piece for piece in wrapped[1:])
    return result



def _option_section(options: list[dict[str, Any]], width: int) -> str:
    return "\n".join([tone("選項", "cyan", bold=True), *(f"  {line}" for line in _option_lines(options, width))])


def render_attempt(
    attempt: dict[str, Any],
    include_event_key: bool = False,
    width: int | None = None,
) -> str:
    """Render one attempt/mistake in the compact card layout."""
    width = width or terminal_width()
    result = attempt.get("result", "unknown")
    label = RESULT_LABELS.get(result, "作答")
    context = "｜".join(
        value for value in (attempt.get("source", ""), attempt.get("section", "")) if value
    )
    secondary = [context]
    if include_event_key and attempt.get("event_key"):
        secondary.append(f"event_key: {attempt['event_key']}")
    header = boxed_header(label, _attempt_heading(attempt), secondary, width=width, tone_name=_result_tone(result))
    sections: list[str] = []

    if attempt.get("_data_warnings"):
        sections.append(_section(
            "資料警告",
            [
                "此作答紀錄含損壞的結構化資料；以下以安全降級方式顯示。",
                *[str(value) for value in attempt.get("_data_warnings", [])],
                "請執行 jpnote audit 取得完整診斷。",
            ],
            width,
            title_tone="yellow",
        ))

    if attempt.get("question_type"):
        sections.append(_section("題型", [attempt["question_type"]], width))

    prompt, options, _legacy_action = cleaned_prompt_and_options(
        attempt.get("prompt", ""),
        attempt.get("options") or [],
        parts=attempt.get("parts") or [],
        question_type=attempt.get("question_type", ""),
    )
    # Legacy records may embed choices even when structured options/parts were
    # already imported separately.  Clean only exact duplicate tails so the
    # preview improves without guessing or mutating stored data.
    if prompt:
        sections.append(_section("題目", [prompt], width))
    if options and attempt.get("question_type") != "reorder_4":
        sections.append(_option_section(options, width))

    if attempt.get("question_type") == "reorder_4":
        parts = [f"{part['id']}. {part['text']}" for part in attempt.get("parts", [])]
        if parts:
            sections.append(_section("四格", parts, width))
        user_order = attempt.get("user_order", [])
        sections.append(
            _section(
                "我的順序",
                [" → ".join(map(str, user_order)) if user_order else "未記錄"],
                width,
            )
        )
        correct_order = attempt.get("correct_order", [])
        if correct_order:
            sections.append(_section("正確順序", [" → ".join(map(str, correct_order))], width, body_tone="green"))
        if attempt.get("correct_answer"):
            sections.append(_section("完整答案", [attempt["correct_answer"]], width, body_tone="green"))
    else:
        sections.append(_section("我的答案", [attempt.get("user_answer") or "未記錄"], width, body_tone=_result_tone(result)))
        if attempt.get("correct_answer"):
            sections.append(_section("正確答案", [attempt["correct_answer"]], width, body_tone="green"))

    if attempt.get("reason"):
        sections.append(_section("解析", [attempt["reason"]], width))
    if attempt.get("linked_entries"):
        sections.append(_section("關聯項目", attempt["linked_entries"], width))

    return "\n\n".join([header, *sections])


def render_attempt_summary(attempt: dict[str, Any]) -> str:
    context = "｜".join(
        value
        for value in (
            attempt.get("date", ""),
            attempt.get("source", ""),
            attempt.get("section", ""),
            attempt.get("question", ""),
        )
        if value
    )
    result = attempt.get("result", "unknown")
    status = tone(f"[{result}]", _result_tone(result), bold=True)
    warning = " " + tone("[資料損壞]", "yellow", bold=True) if attempt.get("_data_warnings") else ""
    first = f"{status}{warning} {context or attempt.get('event_key', '')}"
    event_key = style(f"event_key: {attempt.get('event_key', '')}", "dim")
    if attempt.get("prompt"):
        return f"{first}\n  {attempt['prompt']}\n  {event_key}"
    return f"{first}\n  {event_key}"


def render_recent_detail(entry: dict[str, Any], width: int | None = None) -> str:
    width = width or terminal_width()
    action = "新增" if entry.get("action") == "added" else "更新"
    updated = entry.get("updated_at_local") or entry.get("updated_at", "")
    sources = entry.get("recent_sources") or entry.get("sources") or []
    secondary = [f"{action}｜{updated}" if updated else action]
    if sources:
        secondary.append("來源：" + "、".join(sources))
    return boxed_header("近期變更", entry.get("display", ""), secondary, entry.get("level", ""), width, "green" if entry.get("action") == "added" else "cyan")


def _recent_row_lines(entry: dict[str, Any], body_width: int) -> list[str]:
    label = "文法" if entry.get("type") == "grammar" else "單字"
    label_plain = f"[{label}]"
    reading = f"（{entry['reading']}）" if entry.get("reading") else ""
    display_plain = entry.get("display", "") + reading
    level_plain = entry.get("level", "")
    plain = f"{label_plain} {display_plain}" + (f"  {level_plain}" if level_plain else "")
    pieces = wrap_text(plain, body_width)
    rendered: list[str] = []
    for index, piece in enumerate(pieces):
        value = piece
        if index == 0 and value.startswith(label_plain):
            value = tone(label_plain, _type_tone(entry.get("type", "")), bold=True) + value[len(label_plain):]
        if display_plain and display_plain in piece:
            value = value.replace(display_plain, style(display_plain, "bold"), 1)
        if level_plain and piece.endswith(level_plain):
            value = value[:-len(level_plain)] + style(level_plain, "bold", "yellow")
        rendered.append(value)
    return rendered


def render_recent_list(
    entries: list[dict[str, Any]],
    period: str,
    width: int | None = None,
) -> str:
    width = width or terminal_width()
    header = boxed_header("近期變更", period, width=width)
    groups = (("新增", "added", "green"), ("更新", "updated", "cyan"))
    sections: list[str] = []
    body_width = max(10, width - 2)
    for title, action, action_tone in groups:
        rows: list[str] = []
        for entry in entries:
            if entry.get("action") != action:
                continue
            rows.extend(f"  {piece}" for piece in _recent_row_lines(entry, body_width))
        if rows:
            sections.append("\n".join([tone(title, action_tone, bold=True), *rows]))
    return "\n\n".join([header, *sections])

