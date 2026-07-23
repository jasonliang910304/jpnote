"""Optional fzf adapter.

This module maps structured records to stable tokens and returns explicit user
choices.  It never queries or mutates SQLite itself.  All filters also exist in
the core browse API, so fzf remains a convenience rather than a dependency.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .browsing import DEFAULT_TYPES, LEVEL_VALUES, RESULT_VALUES, TYPE_LABELS
from .fzf_filter_helper import SHORTCUT_TOKENS, read_state, render_panel, summary as _panel_summary, write_state
from .presentation import render_attempt, render_entry, render_recent_detail
from .search_normalization import attempt_search_metadata, entry_search_metadata
from .terminal_style import enabled as color_enabled, style, tone


def available() -> bool:
    return shutil.which("fzf") is not None


def _type_tone(entry_type: str) -> str:
    return "magenta" if entry_type == "grammar" else "blue"


def _result_tone(result: str) -> str:
    return {"wrong": "red", "partial": "yellow", "correct": "green"}.get(result, "cyan")


def _one_line(value: str) -> str:
    return " ".join(str(value or "").replace("\t", " ").splitlines()).strip()


def _machine_token(value: str) -> str:
    token = str(value or "")
    if not token or any(ord(char) < 0x20 or ord(char) == 0x7F or 0x80 <= ord(char) <= 0x9F for char in token):
        raise ValueError("fzf machine token 不能是空值或包含控制字元。")
    return token


def _line(token: str, visible: str, metadata: str = "") -> str:
    return f"{_machine_token(token)}\t{_one_line(visible)}\t{_one_line(metadata)}"


def _execute(
    lines: list[str],
    prompt: str,
    *,
    multi: bool,
    previews: dict[str, str] | None = None,
    header: str | None = None,
    expect: Iterable[str] = (),
) -> subprocess.CompletedProcess[str]:
    if not available():
        raise RuntimeError("找不到 fzf；請改用 --all、--format json 等非互動方式。")

    # fzf's --with-nth transforms the presentation and, on real fzf builds,
    # hidden original fields are not reliably available to --nth matching.
    # Keep fzf as a selector only: a tiny jpnote helper filters the original
    # rows on every query change, while --with-nth remains presentation-only.
    with_preview = previews is not None
    with tempfile.TemporaryDirectory(prefix="jpnote-fzf-") as temp_dir:
        root = Path(temp_dir)
        rendered: list[str] = []
        if previews is not None:
            for index, line in enumerate(lines):
                token, visible, metadata = (line.split("\t", 2) + [""])[:3]
                preview_path = root / f"{index}.txt"
                preview_path.write_text(previews.get(token, ""), encoding="utf-8")
                rendered.append(f"{token}\t{preview_path}\t{visible}\t{metadata}")
        else:
            rendered = list(lines)

        dataset_path = root / "records.tsv"
        dataset_path.write_text("\n".join(rendered) + ("\n" if rendered else ""), encoding="utf-8")
        python = shlex.quote(sys.executable)
        module = "jpnote_app.fzf_search_helper"
        dataset_arg = shlex.quote(str(dataset_path))
        reload_command = f"{python} -m {module} {dataset_arg} {{q}}"

        command = [
            "fzf",
            "--delimiter=\t",
            "--with-nth=3" if with_preview else "--with-nth=2",
            "--disabled",
            f"--bind=change:reload({reload_command})",
            f"--prompt={prompt} > ",
            "--info=inline-right",
        ]
        if color_enabled():
            command.append("--ansi")
        if header:
            command.extend(["--header-first", f"--header={header}"])
        expect_values = tuple(expect)
        if expect_values:
            command.append(f"--expect={','.join(expect_values)}")
        if with_preview:
            command.extend([
                "--preview=cat -- {2}",
                "--preview-window=right,55%,wrap,border-left",
            ])
        if multi:
            command.extend([
                "--multi",
                "--bind=space:toggle,ctrl-a:select-all,ctrl-d:deselect-all",
            ])

        return subprocess.run(
            command,
            input="\n".join(rendered),
            text=True,
            capture_output=True,
            check=False,
        )


def _raise_for_fzf_error(result: subprocess.CompletedProcess[str]) -> None:
    # fzf exit codes: 0 success, 1 no match, 2 error, 130 interrupted/Esc.
    if result.returncode in (0, 1, 130):
        return
    detail = (result.stderr or "").strip()
    message = f"fzf 執行失敗（exit {result.returncode}）"
    if detail:
        message += f"：{detail}"
    raise RuntimeError(message)

def _tokens_from_lines(lines: Iterable[str]) -> list[str]:
    return [line.split("\t", 1)[0] for line in lines if line.strip()]


def _run(
    lines: list[str],
    prompt: str,
    multi: bool,
    previews: dict[str, str] | None = None,
    header: str | None = None,
) -> list[str]:
    result = _execute(lines, prompt, multi=multi, previews=previews, header=header)
    _raise_for_fzf_error(result)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return _tokens_from_lines(result.stdout.splitlines())


def _run_action(
    lines: list[str],
    prompt: str,
    *,
    previews: dict[str, str] | None = None,
    header: str | None = None,
    expect: Iterable[str] = (),
) -> tuple[str, list[str]]:
    expected = tuple(expect)
    result = _execute(
        lines,
        prompt,
        multi=False,
        previews=previews,
        header=header,
        expect=expected,
    )
    _raise_for_fzf_error(result)
    if result.returncode != 0:
        return "cancel", []
    output = result.stdout.splitlines()
    if not output:
        return "cancel", []

    first = output[0]
    if first in expected:
        return first, _tokens_from_lines(output[1:])
    # With --expect enabled, ordinary Enter emits an empty first line on modern
    # fzf.  Older releases may omit it, so support both forms.
    if first == "":
        return "enter", _tokens_from_lines(output[1:])
    return "enter", _tokens_from_lines(output)


def select_import(plan: dict[str, Any]) -> tuple[set[str], set[int]]:
    lines: list[str] = []
    for item in plan.get("items", []):
        label = "文法" if item["type"] == "grammar" else "單字"
        suggested = tone("★", "yellow", bold=True) if item.get("suggested") else " "
        details = "／".join(
            value for value in (item.get("reading", ""), item.get("romaji", "")) if value
        )
        visible = (
            f"{suggested} {tone(f'[{label}]', _type_tone(item['type']), bold=True)} "
            f"{style(item['display'], 'bold')}  {details}"
        ).rstrip()
        lines.append(_line(f"item:{item['key']}", visible, entry_search_metadata(item)))
    for index, attempt in enumerate(plan.get("attempts", [])):
        result_label = "錯題" if attempt["result"] in {"wrong", "partial"} else "作答"
        title = "｜".join(
            value
            for value in (
                attempt.get("source", ""),
                attempt.get("section", ""),
                attempt.get("question", ""),
            )
            if value
        )
        visible = (
            f"  {tone(f'[{result_label}]', _result_tone(attempt['result']), bold=True)} "
            f"{title or attempt['event_key']}"
        )
        lines.append(_line(f"attempt:{index}", visible, attempt_search_metadata(attempt)))
    tokens = _run(
        lines,
        "要匯入的資料",
        multi=True,
        header="Space/Tab 選取｜Ctrl+A 全選｜Ctrl+D 清除｜Enter 確認｜Esc 取消",
    )
    item_keys = {token[len("item:") :] for token in tokens if token.startswith("item:")}
    attempt_indices = {
        int(token[len("attempt:") :]) for token in tokens if token.startswith("attempt:")
    }
    return item_keys, attempt_indices


def select_entry(entries: list[dict[str, Any]], prompt: str) -> str | None:
    lines: list[str] = []
    for entry in entries:
        label = "文法" if entry["type"] == "grammar" else "單字"
        detail_values = []
        if entry.get("reading"):
            detail_values.append(entry["reading"])
        if entry.get("level"):
            detail_values.append(style(entry["level"], "bold", "yellow"))
        details = "／".join(detail_values)
        visible = (
            f"{tone(f'[{label}]', _type_tone(entry['type']), bold=True)} "
            f"{style(entry['display'], 'bold')}  {details}"
        ).rstrip()
        lines.append(_line(entry["key"], visible, entry_search_metadata(entry)))
    previews = {entry["key"]: render_entry(entry, width=60) for entry in entries}
    tokens = _run(lines, prompt, multi=False, previews=previews)
    return tokens[0] if tokens else None


def select_attempt(attempts: list[dict[str, Any]], prompt: str) -> str | None:
    """Return one stable event key selected from structured attempt data."""
    lines: list[str] = []
    for attempt in attempts:
        title = "｜".join(
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
        visible = (
            f"{tone(f'[{result}]', _result_tone(result), bold=True)} "
            f"{title or attempt['event_key']}  {attempt.get('prompt', '')}"
        ).rstrip()
        lines.append(_line(attempt["event_key"], visible, attempt_search_metadata(attempt)))
    previews = {
        attempt["event_key"]: render_attempt(attempt, include_event_key=True, width=60)
        for attempt in attempts
    }
    tokens = _run(lines, prompt, multi=False, previews=previews)
    return tokens[0] if tokens else None


def select_recent(entries: list[dict[str, Any]], prompt: str = "選擇近期變更") -> str | None:
    """Return one stable entry key from recent-change summaries."""
    lines: list[str] = []
    for entry in entries:
        label = "文法" if entry["type"] == "grammar" else "單字"
        action = "新增" if entry.get("action") == "added" else "更新"
        time_text = entry.get("updated_at_local", "")
        if "T" in time_text:
            time_text = time_text.split("T", 1)[1][:5]
        detail_values = []
        if entry.get("reading"):
            detail_values.append(entry["reading"])
        if entry.get("level"):
            detail_values.append(style(entry["level"], "bold", "yellow"))
        details = "／".join(detail_values)
        sources = entry.get("recent_sources") or entry.get("sources") or []
        source_text = "、".join(sources[-2:])
        action_tone = "green" if entry.get("action") == "added" else "cyan"
        visible = (
            f"{tone(f'[{action}]', action_tone, bold=True)}"
            f"{tone(f'[{label}]', _type_tone(entry['type']), bold=True)} "
            f"{style(entry['display'], 'bold')}  {details}  {time_text}  {source_text}"
        ).rstrip()
        lines.append(_line(entry["key"], visible, entry_search_metadata(entry)))
    previews = {
        entry["key"]: render_recent_detail(entry, width=60) + "\n\n" + render_entry(entry, width=60)
        for entry in entries
    }
    tokens = _run(lines, prompt, multi=False, previews=previews)
    return tokens[0] if tokens else None


def _filter_values(filters: dict[str, set[str]], key: str) -> set[str]:
    return set(filters.get(key, set()))


def browse_filter_summary(filters: dict[str, set[str]]) -> str:
    return _panel_summary({
        "types": _filter_values(filters, "types"),
        "levels": _filter_values(filters, "levels"),
        "results": _filter_values(filters, "results"),
    })

def _browse_visible(record: dict[str, Any]) -> str:
    if record["record_type"] == "entry":
        entry = record["data"]
        label = "文法" if record["kind"] == "grammar" else "單字"
        detail_values = []
        if entry.get("reading"):
            detail_values.append(entry["reading"])
        if entry.get("level"):
            detail_values.append(style(entry["level"], "bold", "yellow"))
        details = "／".join(detail_values)
        return (
            f"{tone(f'[{label}]', _type_tone(entry['type']), bold=True)} "
            f"{style(entry.get('display', ''), 'bold')}  {details}"
        ).rstrip()

    attempt = record["data"]
    result = attempt.get("result", "unknown")
    date = attempt.get("date", "")
    context = "｜".join(
        value for value in (attempt.get("source", ""), attempt.get("question", "")) if value
    )
    raw_levels = record.get("levels", [])
    levels = "、".join(level or "未分類" for level in raw_levels) or "未分類"
    return (
        f"{tone('[錯題]', 'red', bold=True)} "
        f"{tone(f'[{result}]', _result_tone(result), bold=True)} "
        f"{date}  {context or attempt.get('event_key', '')}  {style(levels, 'bold', 'yellow')}"
    ).rstrip()


def select_browse(
    records: list[dict[str, Any]],
    filters: dict[str, set[str]],
) -> tuple[str, str | None]:
    """Select a browse record or request a filter/help action."""
    lines: list[str] = []
    previews: dict[str, str] = {}
    for record in records:
        token = record["token"]
        lines.append(_line(token, _browse_visible(record), record.get("search_metadata", "")))
        if record["record_type"] == "entry":
            previews[token] = render_entry(record["data"], width=60)
        else:
            previews[token] = render_attempt(record["data"], include_event_key=True, width=60)

    if not lines:
        lines.append(_line("__empty__", "沒有符合目前條件的資料", ""))
        previews["__empty__"] = "可按 Ctrl-F 修改篩選，或按 Ctrl-R 回到預設條件。"

    header = (
        f"篩選：{browse_filter_summary(filters)}\n"
        "直接輸入搜尋｜Ctrl-F 篩選｜Ctrl-R 設定預設｜? 說明｜Enter 查看｜Esc 離開"
    )
    action, tokens = _run_action(
        lines,
        "瀏覽",
        previews=previews,
        header=header,
        expect=("ctrl-f", "ctrl-r", "?"),
    )
    token = tokens[0] if tokens and tokens[0] != "__empty__" else None
    return action, token


def _copy_filter_state(filters: dict[str, set[str]]) -> dict[str, set[str]]:
    return {
        "types": _filter_values(filters, "types"),
        "levels": _filter_values(filters, "levels"),
        "results": _filter_values(filters, "results"),
    }


def select_browse_filters(
    filters: dict[str, set[str]],
    defaults: dict[str, set[str]],
) -> dict[str, set[str]] | None:
    """Open one persistent checkbox-like fzf filter panel.

    Space updates a short-lived state file through fzf ``execute-silent`` and
    reloads only the panel rows.  The fzf process itself stays alive, avoiding
    the full-screen flash caused by closing and relaunching it for every toggle.
    Enter applies the temporary state; Esc discards it.
    """
    if not available():
        raise RuntimeError("找不到 fzf；請改用 --all、--format json 等非互動方式。")

    with tempfile.TemporaryDirectory(prefix="jpnote-filter-") as temp_dir:
        root = Path(temp_dir)
        state_path = root / "state.json"
        defaults_path = root / "defaults.json"
        panel_path = root / "panel.tsv"
        write_state(state_path, _copy_filter_state(filters))
        write_state(defaults_path, _copy_filter_state(defaults))
        render_panel(panel_path, _copy_filter_state(filters))

        python = shlex.quote(sys.executable)
        module = "jpnote_app.fzf_filter_helper"
        state_arg = shlex.quote(str(state_path))
        panel_arg = shlex.quote(str(panel_path))
        defaults_arg = shlex.quote(str(defaults_path))
        toggle_command = (
            f"{python} -m {module} toggle {state_arg} {panel_arg} "
            f"{defaults_arg} {{1}}"
        )
        reset_command = (
            f"{python} -m {module} reset {state_arg} {panel_arg} "
            f"{defaults_arg}"
        )
        reload_command = f"cat -- {panel_arg}"
        shortcut_binds: list[str] = []
        for digit in SHORTCUT_TOKENS:
            shortcut_command = (
                f"{python} -m {module} shortcut {state_arg} {panel_arg} "
                f"{defaults_arg} {digit}"
            )
            shortcut_binds.append(
                f"--bind={digit}:execute-silent({shortcut_command})+reload({reload_command})"
            )

        command = [
            "fzf",
            "--delimiter=\t",
            "--with-nth=2",
            "--nth=2,3",
            "--header-lines=2",
            "--prompt=篩選 > ",
            "--info=inline-right",
            "--no-clear",
            f"--bind=space:execute-silent({toggle_command})+reload({reload_command})",
            f"--bind=ctrl-r:execute-silent({reset_command})+reload({reload_command})",
            *shortcut_binds,
        ]
        result = subprocess.run(
            command,
            input=panel_path.read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            check=False,
        )
        _raise_for_fzf_error(result)
        if result.returncode != 0:
            return None
        return read_state(state_path)

def show_browse_help() -> None:
    """Show a small fzf-native help page, then return to the browser."""
    help_lines = [
        "Ctrl-F  開啟 checkbox 式篩選面板",
        "Ctrl-R  回到設定檔中的預設篩選",
        "輸入文字  即時搜尋；支援日文、假名、羅馬拼音與相關 metadata",
        "Enter   查看目前項目的完整卡片",
        "Esc     離開瀏覽器",
        "",
        "篩選面板：1–0 快速切換常用條件；Space 切換目前項目；Enter 套用；Ctrl-R 回到設定預設；Esc 放棄。",
        "同組 OR、跨組 AND；群組全部未勾選時代表全部。",
        "wrong／partial 只會在明確勾選錯題時出現。",
    ]
    _run(
        [_line(str(index), line, line) for index, line in enumerate(help_lines)],
        "說明",
        multi=False,
        header="按 Enter 或 Esc 返回",
    )
