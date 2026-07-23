"""Markdown views generated from structured core data."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .config import export_dir
from .fs_utils import atomic_write_text, ensure_private_dir
from .repository import entry_attempt_stats, entry_relations, entry_senses, list_attempts, list_entries
from .attempt_options import parse_legacy_prompt_options
from .sorting import LEVEL_ORDER


def _escape(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def _pronunciation(entry: dict) -> str:
    accent_display = entry.get("accent_display", "")
    romaji = entry.get("romaji", "")
    accent = entry.get("accent", "")
    accent_type = entry.get("accent_type", "")
    base = accent_display or romaji
    label = "・".join(part for part in (accent, accent_type) if part)
    return f"{base} [{label}]" if base and label else base


def export_all(conn: sqlite3.Connection) -> list[Path]:
    directory = ensure_private_dir(export_dir())
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    paths: list[Path] = []

    grammar = list_entries(conn, "grammar")
    lines = ["# 文法總整理", "", f"> 更新時間：{generated}", ""]
    current_level = None
    for entry in grammar:
        level = entry["level"] or "未分類"
        if level != current_level:
            lines.extend([f"## {level}", ""])
            current_level = level
        lines.extend([f"### {entry['display']}", ""])
        if entry["review_group"]:
            lines.append(f"- 複習群組：{entry['review_group']}")
        if entry.get("aliases"):
            lines.append(f"- 相關形式：{'、'.join(entry['aliases'])}")
        if entry["review_group"] or entry.get("aliases"):
            lines.append("")
        for number, sense in enumerate(entry_senses(conn, entry["key"]), 1):
            lines.extend([f"#### {number}. {sense['meaning']}", ""])
            if sense["example_ja"]:
                lines.extend([sense["example_ja"], ""])
            if sense["example_zh"]:
                lines.extend([f"> {sense['example_zh']}", ""])
        relations = entry_relations(conn, entry["key"])
        if relations:
            lines.extend(["#### 相關文法", ""])
            for relation in relations:
                note = f"——{relation['note']}" if relation["note"] else ""
                lines.append(f"- **{relation['relation']}**：{relation['display']} `{relation['key']}`{note}")
            lines.append("")
        stats = entry_attempt_stats(conn, entry["key"])
        if stats["attempt_count"]:
            strict = stats.get("strict_accuracy", stats.get("accuracy"))
            weighted = stats.get("weighted_accuracy")
            strict_text = "—" if strict is None else f"{strict:.1f}%"
            weighted_text = "—" if weighted is None else f"{weighted:.1f}%"
            lines.extend([
                "#### 作答統計", "",
                f"- 作答：{stats['attempt_count']}",
                f"- 答對：{stats['correct_count']}",
                f"- 答錯：{stats['mistake_count']}",
                f"- 部分正確：{stats['partial_count']}",
                f"- 嚴格正確率：{strict_text}",
                f"- 加權正確率：{weighted_text}", "",
            ])
    if not grammar:
        lines.extend(["目前沒有文法資料。", ""])
    path = directory / "文法.md"
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
    paths.append(path)

    groups: dict[str, list[dict]] = {}
    for entry in grammar:
        if entry["review_group"]:
            groups.setdefault(entry["review_group"], []).append(entry)
    lines = ["# 文法群組", "", f"> 更新時間：{generated}", ""]
    for group in sorted(groups):
        lines.extend([f"## {group}", ""])
        for entry in groups[group]:
            lines.append(f"- {entry['display']} (`{entry['key']}`)")
        lines.append("")
    if not groups:
        lines.append("目前沒有文法群組。")
    path = directory / "文法群組.md"
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
    paths.append(path)

    lines = ["# 文法關聯", "", f"> 更新時間：{generated}", ""]
    any_relation = False
    for entry in grammar:
        relations = entry_relations(conn, entry["key"])
        if not relations:
            continue
        any_relation = True
        lines.extend([f"## {entry['display']}", ""])
        for relation in relations:
            note = f"——{relation['note']}" if relation["note"] else ""
            lines.append(f"- {relation['relation']}：{relation['display']} (`{relation['key']}`){note}")
        lines.append("")
    pending = conn.execute("SELECT * FROM pending_grammar_relations ORDER BY source_key, target_key").fetchall()
    if pending:
        lines.extend(["## 尚未收錄的相關文法", ""])
        for row in pending:
            note = f"——{row['note']}" if row["note"] else ""
            lines.append(f"- `{row['source_key']}` → `{row['target_key']}`（{row['relation_type']}）{note}")
        lines.append("")
    if not any_relation and not pending:
        lines.append("目前沒有文法關聯。")
    path = directory / "文法關聯.md"
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
    paths.append(path)

    vocab = list_entries(conn, "vocabulary")
    lines = [
        "# 單字表", "", f"> 更新時間：{generated}", "",
        "| 等級 | 單字 | 讀音 | 羅馬拼音／重音 | 意思 |",
        "|---|---|---|---|---|",
    ]
    for entry in vocab:
        meanings = "；".join(sense["meaning"] for sense in entry_senses(conn, entry["key"]))
        lines.append(
            "| {level} | {display} | {reading} | {pronunciation} | {meanings} |".format(
                level=_escape(entry["level"] or "—"),
                display=_escape(entry["display"]),
                reading=_escape(entry["reading"]),
                pronunciation=_escape(_pronunciation(entry)),
                meanings=_escape(meanings),
            )
        )
    if not vocab:
        lines.append("| — | 目前沒有單字資料 | — | — | — |")
    path = directory / "單字.md"
    atomic_write_text(path, "\n".join(lines) + "\n")
    paths.append(path)

    loanwords = [entry for entry in vocab if entry["origin_type"]]
    lines = [
        "# 外來語與語源", "", f"> 更新時間：{generated}", "",
        "| 單字 | 讀音 | 類型 | 語言 | 原詞 | 補充 |",
        "|---|---|---|---|---|---|",
    ]
    for entry in loanwords:
        lines.append(
            "| {display} | {reading} | {otype} | {language} | {word} | {note} |".format(
                display=_escape(entry["display"]), reading=_escape(entry["reading"]),
                otype=_escape(entry["origin_type"]), language=_escape(entry["origin_language"]),
                word=_escape(entry["origin_word"]), note=_escape(entry["origin_note"]),
            )
        )
    if not loanwords:
        lines.append("| — | — | 目前沒有外來語語源資料 | — | — | — |")
    path = directory / "外來語.md"
    atomic_write_text(path, "\n".join(lines) + "\n")
    paths.append(path)

    mistakes = list_attempts(conn, results=["wrong", "partial"])
    lines = ["# 錯題紀錄", "", f"> 更新時間：{generated}", ""]
    for attempt in mistakes:
        heading = "｜".join(part for part in (attempt["date"], attempt["source"], attempt["section"], attempt["question"]) if part)
        lines.extend([f"## {heading or attempt['event_key']}", ""])
        lines.append(f"- 類型：{attempt['question_type']}")
        lines.append(f"- 結果：{attempt['result']}")
        if attempt.get("_data_warnings"):
            lines.append("- ⚠ 結構化資料損壞，已安全略過無效欄位；請執行 `jpnote audit`。")
            for warning in attempt["_data_warnings"]:
                lines.append(f"  - {_escape(str(warning))}")
        prompt = attempt["prompt"]
        options = list(attempt.get("options") or [])
        if prompt and not options:
            parsed = parse_legacy_prompt_options(prompt)
            if parsed is not None:
                prompt = parsed.prompt
                options = parsed.options
        if prompt:
            lines.append(f"- 題目：{prompt}")
        if options and attempt["question_type"] != "reorder_4":
            lines.append("- 選項：")
            for option in options:
                lines.append(f"  - {option['id']}. {option['text']}")
        if attempt["question_type"] == "reorder_4":
            parts = " / ".join(f"{part['id']}. {part['text']}" for part in attempt["parts"])
            lines.append(f"- 四格：{parts}")
            user_order = attempt.get('user_order', [])
            lines.append("- 我的順序：" + (" → ".join(map(str, user_order)) if user_order else "未記錄"))
            lines.append(f"- 正確順序：{' → '.join(map(str, attempt['correct_order']))}")
        else:
            if attempt["user_answer"]:
                lines.append(f"- 我的答案：{attempt['user_answer']}")
            if attempt["correct_answer"]:
                lines.append(f"- 正確答案：{attempt['correct_answer']}")
        if attempt["reason"]:
            lines.append(f"- 錯誤原因：{attempt['reason']}")
        if attempt["linked_entries"]:
            lines.append(f"- 關聯項目：{'、'.join(f'`{key}`' for key in attempt['linked_entries'])}")
        lines.append("")
    if not mistakes:
        lines.append("目前沒有錯題紀錄。")
    path = directory / "錯題.md"
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
    paths.append(path)

    cutoff = (datetime.now().astimezone() - timedelta(days=7)).isoformat(timespec="seconds")
    recent = conn.execute("SELECT * FROM entries WHERE created_at >= ? ORDER BY created_at DESC", (cutoff,)).fetchall()
    lines = ["# 最近七天新增", "", f"> 更新時間：{generated}", ""]
    for row in recent:
        label = "文法" if row["type"] == "grammar" else "單字"
        lines.append(f"- [{label}] {row['display']}（{row['level'] or '未分類'}）")
    if not recent:
        lines.append("最近七天沒有新增資料。")
    path = directory / "最近新增.md"
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
    paths.append(path)
    return paths
