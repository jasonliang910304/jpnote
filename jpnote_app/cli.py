"""Command-line adapter for jpnote core services."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import ui_fzf
from .attempt_services import delete_attempt_data, replace_attempt_data
from .attempt_options import safe_option_migration_candidates, apply_safe_option_migrations, suspicious_option_migration_candidates
from .browsing import DEFAULT_TYPES, TYPE_LABELS, browse_json, browse_records
from .audit import apply_safe_repairs, run_audit
from .config import BACKUP_MAX_BYTES, VERSION, backup_dir, db_path, export_dir
from .preferences import (
    browse_default_filters,
    config_path as preferences_path,
    ensure_preferences,
    load_preferences,
    validate_preferences,
    write_preferences,
)
from .db import (
    active_backups,
    active_backup_bytes,
    connect,
    connect_preflight,
    create_backup,
    create_recovery_snapshot,
    move_used_backup,
    mutation_backup,
    restore_database_from,
)
from .export_markdown import export_all
from .fs_utils import atomic_write_text, ensure_private_dir
from .import_resolution import resolve_import_plan
from .import_safe_fixes import apply_safe_import_fixes
from .import_preflight import build_preflight_report, render_preflight_json, render_preflight_text
from .romaji_maintenance import romaji_audit_records, safe_romaji_candidates, apply_safe_romaji_normalization
from .repository import (
    find_exact_entry,
    get_attempt,
    get_entry,
    get_entries_by_keys,
    list_attempts,
    list_entries,
    list_recent_entries,
    search_entries,
    stats,
)
from .services import (
    apply_import,
    duplicate_candidates,
    filter_import_plan,
    merge_entries,
    prepare_import,
    replace_entry_data,
)
from .presentation import (
    render_attempt,
    render_attempt_summary,
    render_entry,
    render_entry_summary,
    render_recent_detail,
    render_recent_list,
)
from .validation import (
    canonical_key, normalize_sources, parse_payload, validate_attempt, validate_attempt_edit_fields,
    validate_entry_edit_fields, validate_item,
)
from .terminal_style import configure as configure_color


def _json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _entry_label(entry: dict[str, Any]) -> str:
    return "文法" if entry["type"] == "grammar" else "單字"


def _print_entry_summary(entry: dict[str, Any]) -> None:
    print(render_entry_summary(entry))


def _print_entry(entry: dict[str, Any]) -> None:
    print(render_entry(entry))


def _print_attempt(attempt: dict[str, Any], include_event_key: bool = False) -> None:
    print(render_attempt(attempt, include_event_key=include_event_key))


def _resolve_entry_key(query: str | None, allow_fzf: bool = True) -> str | None:
    with connect() as conn:
        if query:
            exact = find_exact_entry(conn, query)
            if exact is not None:
                return exact["key"]
            candidates = search_entries(conn, query)
        else:
            candidates = list_entries(conn)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["key"]
    if allow_fzf and ui_fzf.available() and sys.stdin.isatty():
        with connect() as conn:
            entry_map = get_entries_by_keys(conn, [entry["key"] for entry in candidates])
            full_candidates = [entry_map.get(entry["key"], entry) for entry in candidates]
        return ui_fzf.select_entry(full_candidates, "選擇項目")
    print("找到多個項目，請改用完整 key：", file=sys.stderr)
    for entry in candidates:
        _print_entry_summary(entry)
    return None


def _read_clipboard() -> str:
    if shutil.which("wl-paste") is None:
        raise RuntimeError("找不到 wl-paste；請使用 jpnote import FILE。")
    result = subprocess.run(
        ["wl-paste", "--no-newline"], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "無法讀取剪貼簿。")
    return result.stdout


def _write_clipboard(text: str) -> None:
    if shutil.which("wl-copy") is None:
        raise RuntimeError("找不到 wl-copy，無法複製預檢報告。")
    result = subprocess.run(["wl-copy"], input=text, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "無法寫入剪貼簿。")


def _emit_preflight(report: dict[str, Any], args: argparse.Namespace) -> int:
    rendered = render_preflight_json(report) if args.format == "json" else render_preflight_text(report)
    if getattr(args, "output", None):
        atomic_write_text(Path(args.output).expanduser(), rendered)
    if getattr(args, "copy_report", False):
        _write_clipboard(rendered)
    sys.stdout.write(rendered)
    return 0


def _print_import_warnings(plan: Any, *, file: Any = None) -> None:
    output = sys.stdout if file is None else file
    for note in plan.notes:
        print(f"注意：{note}", file=output)
    if plan.warnings:
        print("可能重複的項目：", file=output)
        for warning in plan.warnings:
            print(
                f"- {warning.incoming_key} ↔ {warning.other_key}｜{warning.reason}",
                file=output,
            )


def _canonical_cli_key(value: str) -> str:
    """Normalize one explicit CLI key without guessing its entry type."""
    text = value.strip()
    if text.startswith("grammar:"):
        return canonical_key(text, "grammar")
    if text.startswith(("vocab:", "vocabulary:")):
        return canonical_key(text, "vocabulary")
    raise ValueError(f"key 必須包含 grammar: 或 vocab: 前綴：{value}")


def _parse_key_mappings(values: list[str]) -> dict[str, str]:
    mappings: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--map-key 格式必須是 SOURCE=TARGET：{value}")
        source, target = value.split("=", 1)
        mappings[_canonical_cli_key(source)] = _canonical_cli_key(target)
    return mappings


def _plan_item(plan: Any, key: str) -> dict[str, Any] | None:
    return next((item for item in plan.items if item["key"] == key), None)


def _print_duplicate_detail(plan: Any, warning: Any, *, file: Any = None) -> None:
    output = sys.stdout if file is None else file
    incoming = _plan_item(plan, warning.incoming_key)
    other = _plan_item(plan, warning.other_key)
    if other is None:
        with connect() as conn:
            other = get_entry(conn, warning.other_key, include_attempts=False)
    print("\n疑似重複：", file=output)
    if incoming:
        print(
            f"  本次資料：[{_entry_label(incoming)}] {incoming['display']} "
            f"<{incoming['key']}>",
            file=output,
        )
    if other:
        side = "同批另一筆" if warning.scope == "batch" else "既有資料"
        print(f"  {side}：[{_entry_label(other)}] {other['display']} <{other['key']}>", file=output)
    print(f"  原因：{warning.reason}", file=output)


def _interactive_resolve_warnings(plan: Any, *, file: Any = None) -> tuple[Any | None, bool]:
    """Resolve duplicate warnings without parsing display text.

    Every mutation is delegated to ``resolve_import_plan`` using stable keys.
    The terminal loop only gathers the user's decision, so a future Web UI can
    provide the same key-map/skip structure directly.
    """
    output = sys.stdout if file is None else file
    current = plan
    accepted_pairs: set[tuple[str, str]] = set()
    while True:
        pending = [
            warning for warning in current.warnings
            if tuple(sorted((warning.incoming_key, warning.other_key))) not in accepted_pairs
        ]
        if not pending:
            return current, True
        warning = pending[0]
        _print_duplicate_detail(current, warning, file=output)
        if warning.scope == "batch":
            print(
                "  [m] 本次資料沿用另一筆 key｜[r] 反向沿用｜"
                "[k] 確認為不同項目｜[s] 跳過本次資料｜[x] 取消",
                file=output,
            )
        else:
            print(
                "  [m] 沿用既有 key 並合併本次資料｜"
                "[k] 確認為不同項目｜[s] 跳過本次資料｜[x] 取消",
                file=output,
            )
        print("選擇：", end="", file=output, flush=True)
        answer = input().strip().lower()
        if answer == "x":
            return None, False
        if answer == "k":
            accepted_pairs.add(tuple(sorted((warning.incoming_key, warning.other_key))))
            continue
        with connect() as conn:
            if answer == "m":
                current = resolve_import_plan(
                    conn,
                    current,
                    {warning.incoming_key: warning.other_key},
                    set(),
                )
            elif answer == "r" and warning.scope == "batch":
                current = resolve_import_plan(
                    conn,
                    current,
                    {warning.other_key: warning.incoming_key},
                    set(),
                )
            elif answer == "s":
                current = resolve_import_plan(
                    conn,
                    current,
                    {},
                    {warning.incoming_key},
                )
            else:
                print("無效選項，請重新選擇。", file=output)


def _confirm_yes_no(prompt: str) -> bool:
    print(prompt, end="", flush=True)
    answer = input().strip().lower()
    return answer in {"y", "yes"}


def _print_apply_preflight(report: dict[str, Any], args: argparse.Namespace, *, heading: str = "") -> None:
    output = sys.stderr if args.format == "json" else sys.stdout
    if heading and args.format != "json":
        print(heading, file=output)
    rendered = render_preflight_json(report) if args.format == "json" else render_preflight_text(report)
    output.write(rendered)
    output.flush()


def _blocking_preflight_messages(report: dict[str, Any]) -> list[str]:
    summary = report["summary"]
    messages: list[str] = []
    if summary.get("conflicting_attempts", 0):
        messages.append(f"{summary['conflicting_attempts']} 筆作答 identity 衝突")
    if summary.get("attempts_with_missing_links", 0):
        messages.append(f"{summary['attempts_with_missing_links']} 筆作答缺少 linked_entries")
    if summary.get("pending_relation_conflicts", 0):
        messages.append(f"{summary['pending_relation_conflicts']} 筆 pending relation note 衝突")
    return messages


def _run_import_text(text: str, args: argparse.Namespace) -> int:
    if args.check and args.dry_run:
        raise ValueError("--check 與 --dry-run 請擇一使用。")
    payload = parse_payload(text)
    with connect_preflight() as conn:
        plan = prepare_import(conn, payload)

    # v0.6.6.3: normal paste/import defaults to the complete payload. Explicit
    # selectors still support advanced partial imports; --all remains as a
    # compatibility/documentation flag rather than a safety bypass.
    if args.item_key or args.attempt_index:
        selected = filter_import_plan(
            plan,
            set(args.item_key) if args.item_key else set(),
            set(args.attempt_index) if args.attempt_index else set(),
        )
    else:
        selected = plan

    key_map = _parse_key_mappings(args.map_key)
    skip_keys = {_canonical_cli_key(key) for key in args.skip_item}
    if key_map or skip_keys:
        with connect_preflight() as conn:
            selected = resolve_import_plan(conn, selected, key_map, skip_keys)

    if args.check:
        with connect_preflight() as conn:
            report = build_preflight_report(conn, selected)
        return _emit_preflight(report, args)

    if args.dry_run:
        _json(selected.to_dict()) if args.format == "json" else _print_import_warnings(selected)
        return 0

    if not selected.items and not selected.attempts:
        if args.format == "json":
            _json({"result": "no_selection", "modified": False})
        else:
            print("沒有選取任何資料，未修改資料庫。")
        return 0

    warning_stream = sys.stderr if args.format == "json" else sys.stdout

    # Every real import first runs the same complete read-only preflight that
    # --check uses. Nothing below may write before the final confirmation.
    with connect_preflight() as conn:
        report = build_preflight_report(conn, selected)
    _print_apply_preflight(report, args, heading="=== 正式匯入前完整預檢 ===")

    if args.format == "json" and not args.yes:
        raise RuntimeError(
            "--format json 的正式匯入請搭配 --yes；preflight 仍已輸出至 stderr，"
            "validation 與 blocking conflict 不會被略過。"
        )

    if report.get("safe_fixes"):
        if args.yes:
            apply_fixes = True
        elif not sys.stdin.isatty():
            raise RuntimeError(
                "預檢發現可安全整理的匯入資料；非互動環境請加 --yes 自動套用，"
                "或先使用 --check --all 檢視。"
            )
        else:
            apply_fixes = _confirm_yes_no("是否先套用安全修正並重新檢查？[y/N] ")
        if apply_fixes:
            with connect_preflight() as conn:
                selected, fix_actions = apply_safe_import_fixes(conn, selected)
                report = build_preflight_report(conn, selected)
            if args.format != "json":
                print(f"已對本次匯入計畫套用 {len(fix_actions)} 組安全整理；尚未修改資料庫。")
            _print_apply_preflight(report, args, heading="=== 安全整理後重新預檢 ===")
        elif args.format != "json":
            print("未套用安全整理；仍可在最後確認是否依原資料匯入。")

    _print_import_warnings(selected, file=warning_stream)
    if selected.warnings and not args.accept_warnings:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "存在可能重複項目；請使用 --map-key、--skip-item，或確認不同項目後加上 --accept-warnings。"
            )
        selected, confirmed = _interactive_resolve_warnings(selected, file=warning_stream)
        if not confirmed or selected is None:
            print("已取消，未修改資料庫。", file=warning_stream)
            return 0
        if not selected.items and not selected.attempts:
            print("所有資料都已跳過，未修改資料庫。", file=warning_stream)
            return 0
        with connect_preflight() as conn:
            report = build_preflight_report(conn, selected)
        _print_apply_preflight(report, args, heading="=== 重複項目處理後重新預檢 ===")

        # A merge/key remap can expose a new deterministic cleanup opportunity.
        if report.get("safe_fixes"):
            if args.yes:
                apply_fixes = True
            else:
                apply_fixes = _confirm_yes_no("是否套用處理重複項目後新發現的安全修正？[y/N] ")
            if apply_fixes:
                with connect_preflight() as conn:
                    selected, fix_actions = apply_safe_import_fixes(conn, selected)
                    report = build_preflight_report(conn, selected)
                if args.format != "json":
                    print(f"已再套用 {len(fix_actions)} 組安全整理；尚未修改資料庫。")
                _print_apply_preflight(report, args, heading="=== 最終安全整理後預檢 ===")

    blocking = _blocking_preflight_messages(report)
    if blocking:
        raise RuntimeError(
            "預檢仍有不能以 yes 強行略過的問題：" + "；".join(blocking)
            + "。請先修正輸入資料或使用 --check --all 匯出報告。"
        )

    if not args.yes:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "非互動正式匯入需要 --yes；此選項只略過確認，不會略過 validation 或完整 preflight。"
            )
        if not _confirm_yes_no("是否正式匯入？[y/N] "):
            print("已取消，未修改資料庫。", file=warning_stream)
            return 0

    with mutation_backup("import") as backup:
        with connect() as conn:
            before_changes = conn.total_changes
            result = apply_import(conn, selected)
            modified = conn.total_changes > before_changes
            backup.mark_changed(modified)
            if modified:
                export_all(conn)
    if args.format == "json":
        _json({"result": result.to_dict(), "backup": str(backup) if backup else ""})
    else:
        print(
            "匯入完成：新增 {added_entries}、更新 {updated_entries}、未變更 {unchanged_entries} 個項目；"
            "新增 {added_attempts}、略過 {skipped_attempts} 筆作答；"
            "建立 {added_relations}、待補 {pending_relations} 個文法關聯。".format(
                **result.to_dict()
            )
        )
        if backup:
            print(f"自動備份：{backup}")
        if modified:
            print(f"Markdown 已更新：{export_dir()}")
        else:
            print("資料內容未變更；未建立新備份，也未重新產生 Markdown。")
    return 0

def command_init(_: argparse.Namespace) -> int:
    with connect() as conn:
        export_all(conn)
    settings = ensure_preferences()
    print(f"已建立／升級資料庫：{db_path()}")
    print(f"匯出目錄：{export_dir()}")
    print(f"設定檔：{settings}")
    return 0


def command_config_show(args: argparse.Namespace) -> int:
    config = load_preferences()
    if args.format == "json":
        _json(config)
    else:
        browse = config["browse"]
        print(f"設定檔：{preferences_path()}")
        type_text = '、'.join(TYPE_LABELS[value] for value in browse['types']) or '全部'
        print(f"預設類型：{type_text}")
        print(f"預設等級：{'、'.join(browse['levels']) or '全部'}")
        results = browse["results"]
        print(f"預設錯題結果：{'、'.join(results) or '全部'}")
    return 0


def command_config_path(_: argparse.Namespace) -> int:
    print(preferences_path())
    return 0


def command_config_reset(_: argparse.Namespace) -> int:
    path = write_preferences({
        "browse": {
            "types": list(DEFAULT_TYPES),
            "levels": [],
            "results": [],
        }
    })
    print(f"已恢復預設設定：{path}")
    return 0


def command_config_edit(_: argparse.Namespace) -> int:
    ensure_preferences()
    current = load_preferences()
    editor = shlex.split(os.environ.get("EDITOR") or "nvim") or ["nvim"]
    fd, temp_name = tempfile.mkstemp(prefix="jpnote-config-", suffix=".json")
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if subprocess.run([*editor, str(temp)], check=False).returncode != 0:
            print("編輯器非正常結束，設定未修改。")
            return 1
        raw = json.loads(temp.read_text(encoding="utf-8"))
        normalized = validate_preferences(raw)
        path = write_preferences(normalized)
        print(f"已更新設定：{path}")
        return 0
    finally:
        temp.unlink(missing_ok=True)


def command_import(args: argparse.Namespace) -> int:
    return _run_import_text(Path(args.file).expanduser().read_text(encoding="utf-8"), args)


def command_paste(args: argparse.Namespace) -> int:
    return _run_import_text(_read_clipboard(), args)


def command_list(args: argparse.Namespace) -> int:
    entry_type = "grammar" if args.kind == "grammar" else "vocabulary"
    with connect() as conn:
        entries = list_entries(conn, entry_type, args.level)
    if args.select:
        with connect() as conn:
            full_entries = [get_entry(conn, entry["key"]) or entry for entry in entries]
        key = ui_fzf.select_entry(full_entries, f"選擇{args.kind}")
        if key:
            entry = next((item for item in full_entries if item["key"] == key), None)
            if entry:
                _json(entry) if args.format == "json" else _print_entry(entry)
        return 0
    if args.format == "json":
        _json(entries)
    else:
        for entry in entries:
            _print_entry_summary(entry)
    return 0


def _browse_filter_state(
    args: argparse.Namespace,
    defaults: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Resolve CLI overrides on top of user-configured browse defaults."""
    return {
        "types": set(args.kind) if args.kind else set(defaults["types"]),
        "levels": set(args.level) if args.level else set(defaults["levels"]),
        "results": set(args.result) if args.result else set(defaults["results"]),
    }


def _print_browse_records(records: list[dict[str, Any]]) -> None:
    for index, record in enumerate(records):
        if index:
            print()
        if record["record_type"] == "entry":
            print(render_entry_summary(record["data"]))
        else:
            print(render_attempt_summary(record["data"]))


def command_browse(args: argparse.Namespace) -> int:
    """Browse entries and mistakes through one structured filter layer."""
    defaults = browse_default_filters()
    filters = _browse_filter_state(args, defaults)
    use_fzf = (
        not args.all
        and not args.no_fzf
        and args.format != "json"
        and ui_fzf.available()
        and sys.stdin.isatty()
    )

    while True:
        with connect() as conn:
            records = browse_records(
                conn,
                types=tuple(filters["types"]),
                levels=tuple(filters["levels"]),
                results=tuple(filters["results"]),
                query=args.query,
            )

        if args.format == "json":
            _json(browse_json(records))
            return 0 if records else 1
        if not use_fzf:
            if not records:
                print("沒有符合條件的資料。")
                return 1
            _print_browse_records(records)
            return 0

        action, token = ui_fzf.select_browse(records, filters)
        if action == "ctrl-f":
            updated = ui_fzf.select_browse_filters(filters, defaults)
            if updated is not None:
                filters = updated
            continue
        if action == "ctrl-r":
            filters = {key: set(value) for key, value in defaults.items()}
            continue
        if action == "?":
            ui_fzf.show_browse_help()
            continue
        if action == "cancel" or token is None:
            return 0

        selected = next((record for record in records if record["token"] == token), None)
        if selected is None:
            return 1
        if selected["record_type"] == "entry":
            _print_entry(selected["data"])
        else:
            _print_attempt(selected["data"], include_event_key=True)
        return 0


def _recent_period(args: argparse.Namespace) -> str:
    if args.date:
        return args.date
    if args.since:
        return f"{args.since} 以後"
    return datetime.now().astimezone().date().isoformat()


def command_recent(args: argparse.Namespace) -> int:
    entry_type = None
    if args.kind == "grammar":
        entry_type = "grammar"
    elif args.kind == "vocab":
        entry_type = "vocabulary"
    with connect() as conn:
        entries = list_recent_entries(conn, args.date, args.since, entry_type, args.source)
    if args.format == "json":
        _json(entries)
        return 0 if entries else 1
    if not entries:
        print(f"{_recent_period(args)}沒有新增或更新項目。")
        return 1

    use_fzf = not args.all and not args.no_fzf and ui_fzf.available() and sys.stdin.isatty()
    if use_fzf:
        with connect() as conn:
            entry_map = get_entries_by_keys(conn, [summary["key"] for summary in entries])
            enriched: list[dict[str, Any]] = []
            for summary in entries:
                full = entry_map.get(summary["key"], dict(summary))
                full.update({
                    "action": summary.get("action"),
                    "updated_at_local": summary.get("updated_at_local", ""),
                    "recent_sources": summary.get("recent_sources", []),
                })
                enriched.append(full)
        key = ui_fzf.select_recent(enriched)
        if not key:
            return 0
        selected = next((entry for entry in enriched if entry["key"] == key), None)
        if selected:
            print(render_recent_detail(selected))
            print()
            _print_entry(selected)
        return 0

    print(render_recent_list(entries, _recent_period(args)))
    return 0


def command_search(args: argparse.Namespace) -> int:
    with connect() as conn:
        summaries = search_entries(conn, args.query)
        entry_map = get_entries_by_keys(conn, [entry["key"] for entry in summaries])
        entries = [entry_map[entry["key"]] for entry in summaries if entry["key"] in entry_map]
    if args.select and entries:
        key = ui_fzf.select_entry(entries, "選擇搜尋結果")
        selected = next((entry for entry in entries if entry["key"] == key), None)
        if selected:
            _json(selected) if args.format == "json" else _print_entry(selected)
        return 0
    if args.format == "json":
        _json(entries)
    else:
        for index, entry in enumerate(entries):
            if index:
                print()
            _print_entry(entry)
    return 0 if entries else 1



def _editable_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        field: entry.get(field, "")
        for field in (
            "key", "type", "display", "reading", "romaji", "accent", "accent_type",
            "accent_display", "accent_note", "level", "review_group", "aliases",
            "origin_type", "origin_language", "origin_word", "origin_note", "senses",
            "sources",
        )
    } | {
        "related_grammar": [
            {"key": relation["key"], "relation": relation["relation"], "note": relation["note"]}
            for relation in entry.get("related_grammar", [])
        ]
    }


def command_edit(args: argparse.Namespace) -> int:
    key = _resolve_entry_key(args.query)
    if not key:
        return 1
    with connect() as conn:
        entry = get_entry(conn, key)
    if not entry:
        return 1
    editor = shlex.split(os.environ.get("EDITOR") or "nvim") or ["nvim"]
    fd, temp_name = tempfile.mkstemp(prefix="jpnote-edit-", suffix=".json")
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(json.dumps(_editable_entry(entry), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if subprocess.run([*editor, str(temp)], check=False).returncode != 0:
            print("編輯器非正常結束，未修改資料庫。")
            return 1
        raw = json.loads(temp.read_text(encoding="utf-8"))
        validate_entry_edit_fields(raw)
        normalized = validate_item(raw)
        normalized["sources"] = normalize_sources(raw.get("sources"))
        with mutation_backup("edit") as backup:
            with connect() as conn:
                before_changes = conn.total_changes
                updated = replace_entry_data(conn, key, normalized)
                modified = conn.total_changes > before_changes
                backup.mark_changed(modified)
                if modified:
                    export_all(conn)
        if modified:
            print(f"已更新：{updated.get('display', key)}")
        else:
            print(f"內容未變更：{updated.get('display', key)}")
        if backup:
            print(f"自動備份：{backup}")
        return 0
    finally:
        temp.unlink(missing_ok=True)


def command_delete(args: argparse.Namespace) -> int:
    key = _resolve_entry_key(args.query)
    if not key:
        return 1
    with connect() as conn:
        entry = get_entry(conn, key, include_attempts=False)
    if not entry:
        return 1
    if not args.yes:
        answer = input(f"確定刪除 [{_entry_label(entry)}] {entry['display']}？輸入 yes：").strip()
        if answer != "yes":
            print("已取消。")
            return 0
    with mutation_backup("delete") as backup:
        with connect() as conn:
            before_changes = conn.total_changes
            with conn:
                conn.execute("DELETE FROM entries WHERE key = ?", (key,))
            modified = conn.total_changes > before_changes
            backup.mark_changed(modified)
            if modified:
                export_all(conn)
    print(f"已刪除：{entry['display']}")
    if backup:
        print(f"自動備份：{backup}")
    return 0


def command_mistakes(args: argparse.Namespace) -> int:
    entry_key = None
    if args.entry:
        entry_key = _resolve_entry_key(args.entry, allow_fzf=False)
        if not entry_key:
            return 1
    with connect() as conn:
        attempts = list_attempts(conn, ["wrong", "partial"], entry_key, args.level)
    if args.format == "json":
        _json(attempts)
    else:
        for index, attempt in enumerate(attempts):
            if index:
                print()
            _print_attempt(attempt)
    return 0 if attempts else 1


def _resolve_attempt_event_key(query: str | None, allow_fzf: bool = True) -> str | None:
    with connect() as conn:
        if query:
            exact = get_attempt(conn, query)
            if exact is not None:
                return exact["event_key"]
        attempts = list_attempts(conn)
    if query:
        needle = query.casefold()
        attempts = [
            attempt for attempt in attempts
            if any(
                needle in str(attempt.get(field, "")).casefold()
                for field in ("event_key", "source", "section", "question", "prompt")
            )
        ]
    if not attempts:
        return None
    if len(attempts) == 1:
        return attempts[0]["event_key"]
    if allow_fzf and ui_fzf.available() and sys.stdin.isatty():
        return ui_fzf.select_attempt(attempts, "選擇作答紀錄")
    print("找到多筆作答紀錄，請改用完整 event_key：", file=sys.stderr)
    for attempt in attempts:
        _print_attempt(attempt)
        print(f"  event_key：{attempt['event_key']}")
    return None


def command_attempts_list(args: argparse.Namespace) -> int:
    entry_key = None
    if args.entry:
        entry_key = _resolve_entry_key(args.entry, allow_fzf=False)
        if not entry_key:
            return 1
    results = args.result or None
    with connect() as conn:
        attempts = list_attempts(conn, results, entry_key, args.level)
    if args.format == "json":
        _json(attempts)
    else:
        for index, attempt in enumerate(attempts):
            if index:
                print()
            print(render_attempt_summary(attempt))
    return 0 if attempts else 1


def command_attempts_show(args: argparse.Namespace) -> int:
    event_key = _resolve_attempt_event_key(args.query, allow_fzf=not args.no_fzf)
    if not event_key:
        print("找不到唯一作答紀錄。", file=sys.stderr)
        return 1
    with connect() as conn:
        attempt = get_attempt(conn, event_key)
    if attempt is None:
        return 1
    if args.format == "json":
        _json(attempt)
    else:
        _print_attempt(attempt, include_event_key=True)
    return 0


def _editable_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        field: attempt.get(field, "")
        for field in (
            "event_key", "result", "date", "source", "section", "question",
            "question_type", "prompt", "user_answer", "correct_answer", "reason",
            "before", "after", "parts", "user_order", "correct_order", "options", "linked_entries",
        )
    }


def command_attempts_edit(args: argparse.Namespace) -> int:
    event_key = _resolve_attempt_event_key(args.query)
    if not event_key:
        return 1
    with connect() as conn:
        attempt = get_attempt(conn, event_key)
    if attempt is None:
        return 1

    editor = shlex.split(os.environ.get("EDITOR") or "nvim") or ["nvim"]
    fd, temp_name = tempfile.mkstemp(prefix="jpnote-attempt-edit-", suffix=".json")
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(
            json.dumps(_editable_attempt(attempt), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if subprocess.run([*editor, str(temp)], check=False).returncode != 0:
            print("編輯器非正常結束，未修改資料庫。")
            return 1
        raw = json.loads(temp.read_text(encoding="utf-8"))
        validate_attempt_edit_fields(raw)
        raw["event_key"] = event_key
        validate_attempt(raw)
        with mutation_backup("attempt-edit") as backup:
            with connect() as conn:
                before_changes = conn.total_changes
                updated = replace_attempt_data(conn, event_key, raw)
                modified = conn.total_changes > before_changes
                backup.mark_changed(modified)
                if modified:
                    export_all(conn)
        if modified:
            print(f"已更新作答紀錄：{updated['event_key']}")
        else:
            print(f"作答紀錄內容未變更：{updated['event_key']}")
        if backup:
            print(f"自動備份：{backup}")
        return 0
    finally:
        temp.unlink(missing_ok=True)


def command_attempts_migrate_options(args: argparse.Namespace) -> int:
    """Preview or apply conservative legacy prompt/options cleanup."""
    with connect() as conn:
        candidates = safe_option_migration_candidates(conn)
    if not args.apply:
        if args.format == "json":
            _json(candidates)
        else:
            print(f"可安全整理 {len(candidates)} 筆舊錯題。")
            for item in candidates:
                print(f"- {item['event_key']}｜{item['pattern']}")
                print(f"  題目：{item['prompt']}")
                for option in item['options']:
                    print(f"  {option['id']}. {option['text']}")
            if candidates:
                print("使用 --apply 寫入；未辨識或有歧義的題目會保持原樣。")
        return 0

    if not candidates:
        with connect() as conn:
            unresolved = suspicious_option_migration_candidates(conn)
        if args.format == "json":
            _json({"migrated": 0, "items": [], "unresolved_suspicious": unresolved, "backup": ""})
        else:
            print("沒有可安全自動整理的舊錯題。")
            if unresolved:
                print(f"另有 {len(unresolved)} 筆疑似包含舊格式選項／殘留內容，但無法安全自動整理：")
                for item in unresolved:
                    identity = "｜".join(
                        value for value in (item.get("date", ""), item.get("source", ""), item.get("section", ""), item.get("question", "")) if value
                    ) or item["event_key"]
                    print(f"- {identity}")
                    print(f"  event_key: {item['event_key']}")
                    if item.get("prompt_preview"):
                        print(f"  題目：{item['prompt_preview']}")
        return 0
    with mutation_backup("attempt-options-migration") as backup:
        with connect() as conn:
            before_changes = conn.total_changes
            applied = apply_safe_option_migrations(conn)
            unresolved = suspicious_option_migration_candidates(conn)
            modified = conn.total_changes > before_changes
            backup.mark_changed(modified)
            if modified:
                export_all(conn)
    if args.format == "json":
        _json({
            "migrated": len(applied),
            "items": applied,
            "unresolved_suspicious": unresolved,
            "backup": str(backup) if backup else "",
        })
    else:
        print(f"已安全整理 {len(applied)} 筆舊錯題的題幹／選項。")
        if unresolved:
            print(f"另有 {len(unresolved)} 筆疑似包含舊格式選項／殘留內容，但無法安全自動整理：")
            for item in unresolved:
                identity = "｜".join(
                    value for value in (item.get("date", ""), item.get("source", ""), item.get("section", ""), item.get("question", "")) if value
                ) or item["event_key"]
                print(f"- {identity}")
                print(f"  event_key: {item['event_key']}")
                if item.get("prompt_preview"):
                    print(f"  題目：{item['prompt_preview']}")
        if backup:
            print(f"自動備份：{backup}")
    return 0


def command_attempts_delete(args: argparse.Namespace) -> int:
    event_key = _resolve_attempt_event_key(args.query)
    if not event_key:
        return 1
    with connect() as conn:
        attempt = get_attempt(conn, event_key)
    if attempt is None:
        return 1
    if not args.yes:
        title = "｜".join(
            value for value in (
                attempt.get("date", ""), attempt.get("source", ""),
                attempt.get("section", ""), attempt.get("question", ""),
            ) if value
        ) or event_key
        answer = input(f"確定刪除作答紀錄 {title}？輸入 yes：").strip()
        if answer != "yes":
            print("已取消。")
            return 0
    with mutation_backup("attempt-delete") as backup:
        with connect() as conn:
            before_changes = conn.total_changes
            deleted = delete_attempt_data(conn, event_key)
            modified = conn.total_changes > before_changes
            backup.mark_changed(modified)
            if modified:
                export_all(conn)
    if not deleted:
        print("找不到作答紀錄。", file=sys.stderr)
        return 1
    print(f"已刪除作答紀錄：{event_key}")
    if backup:
        print(f"自動備份：{backup}")
    return 0


def command_romaji_audit(args: argparse.Namespace) -> int:
    with connect() as conn:
        records = romaji_audit_records(conn)
    if not args.include_ok:
        records = [record for record in records if record["status"] != "ok"]
    if args.format == "json":
        _json(records)
    else:
        if not records:
            print("羅馬拼音皆符合目前可安全判定的標準格式。")
            return 0
        labels = {
            "missing_reading": "缺少讀音",
            "unsupported_reading": "讀音暫不支援",
            "missing_romaji": "可補齊",
            "format_only": "可正規化",
            "mismatch": "需確認",
            "ok": "正常",
        }
        for record in records:
            print(f"- [{labels.get(record['status'], record['status'])}] {record['key']}｜{record['display']}")
            print(f"  reading: {record['reading'] or '(空)'}")
            print(f"  romaji: {record['stored_romaji'] or '(空)'}")
            if record['canonical_romaji']:
                print(f"  建議: {record['canonical_romaji']}")
    return 0


def command_romaji_normalize(args: argparse.Namespace) -> int:
    with connect() as conn:
        candidates = safe_romaji_candidates(conn)
    if not args.apply:
        if args.format == "json":
            _json(candidates)
        else:
            print(f"可安全正規化 {len(candidates)} 筆羅馬拼音。")
            for record in candidates:
                print(f"- {record['key']}｜{record['stored_romaji'] or '(空)'} → {record['canonical_romaji']}")
            if candidates:
                print("使用 --apply 寫入；讀音不支援或與現有羅馬拼音不一致的項目不會自動修改。")
        return 0
    if not candidates:
        print("沒有可安全正規化的羅馬拼音。") if args.format == "text" else _json({"normalized": 0, "items": [], "backup": ""})
        return 0
    with mutation_backup("romaji-normalize") as backup:
        with connect() as conn:
            before_changes = conn.total_changes
            applied = apply_safe_romaji_normalization(conn)
            modified = conn.total_changes > before_changes
            backup.mark_changed(modified)
            if modified:
                export_all(conn)
    if args.format == "json":
        _json({"normalized": len(applied), "items": applied, "backup": str(backup) if backup else ""})
    else:
        print(f"已安全正規化 {len(applied)} 筆羅馬拼音。")
        if backup:
            print(f"自動備份：{backup}")
    return 0


def command_duplicates(args: argparse.Namespace) -> int:
    with connect() as conn:
        candidates = duplicate_candidates(conn)
    if args.format == "json":
        _json(candidates)
    else:
        if not candidates:
            print("未發現保守規則可判定的疑似重複。")
        for candidate in candidates:
            print(f"- {candidate['left_key']} ↔ {candidate['right_key']}｜{candidate['reason']}")
    return 0


def command_merge(args: argparse.Namespace) -> int:
    if not args.yes:
        answer = input(f"將 {args.source} 合併到 {args.target} 並刪除來源？輸入 yes：").strip()
        if answer != "yes":
            print("已取消。")
            return 0
    with mutation_backup("merge") as backup:
        with connect() as conn:
            before_changes = conn.total_changes
            entry = merge_entries(conn, args.source, args.target)
            modified = conn.total_changes > before_changes
            backup.mark_changed(modified)
            if modified:
                export_all(conn)
    _json(entry) if args.format == "json" else print(f"已合併到：{entry.get('display', args.target)}")
    if backup and args.format != "json":
        print(f"自動備份：{backup}")
    return 0


def command_audit(args: argparse.Namespace) -> int:
    with connect() as conn:
        issues = run_audit(conn)
    if not args.include_info:
        issues = [issue for issue in issues if issue.severity != "info"]
    data = [issue.to_dict() for issue in issues]
    if args.export:
        directory = ensure_private_dir(export_dir())
        atomic_write_text(directory / "待補資料.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        md = ["# 待補資料", ""]
        for issue in data:
            md.append(f"- [{issue['severity']}] `{issue['key']}`：{issue['message']}")
        atomic_write_text(directory / "待補資料.md", "\n".join(md) + "\n")
    if args.format == "json":
        _json(data)
    else:
        for issue in data:
            auto = "可修" if issue["fixable"] else "需確認"
            print(f"- [{issue['severity']}｜{auto}] {issue['key']}：{issue['message']}")
        if args.export:
            print(f"已輸出：{export_dir() / '待補資料.json'}")
    return 0


def command_repair(args: argparse.Namespace) -> int:
    if not args.yes:
        answer = input("repair 只會執行可確定的修正。輸入 yes：").strip()
        if answer != "yes":
            print("已取消。")
            return 0
    with mutation_backup("repair") as backup:
        with connect() as conn:
            before_changes = conn.total_changes
            actions = apply_safe_repairs(conn)
            option_actions = apply_safe_option_migrations(conn)
            romaji_actions = apply_safe_romaji_normalization(conn)
            unresolved = [
                issue.to_dict() for issue in run_audit(conn)
                if issue.severity in {"critical", "needs_input", "review"} and not issue.fixable
            ]
            modified = conn.total_changes > before_changes
            backup.mark_changed(modified)
            if modified:
                export_all(conn)
    if args.format == "json":
        _json({
            "actions": actions,
            "option_migrations": option_actions,
            "romaji_normalizations": romaji_actions,
            "unresolved": unresolved,
            "backup": str(backup) if backup else "",
        })
    else:
        total = len(actions) + len(option_actions) + len(romaji_actions)
        print(f"已完成安全修復，共 {total} 組變更。")
        for action in actions:
            print(f"- {action}")
        if option_actions:
            print(f"- 安全整理舊錯題題幹／選項：{len(option_actions)} 筆")
        if romaji_actions:
            print(f"- 安全正規化羅馬拼音：{len(romaji_actions)} 筆")
        if unresolved:
            print("")
            print(f"仍有 {len(unresolved)} 項無法安全自動修正，請人工確認：")
            for issue in unresolved:
                print(f"- [{issue['severity']}] {issue['key']}｜{issue['code']}：{issue['message']}")
                if issue.get("details"):
                    print("  details: " + json.dumps(issue["details"], ensure_ascii=False))
        else:
            print("沒有剩餘需要人工確認的資料衝突。")
        if backup:
            print(f"自動備份：{backup}")
    return 0


def command_export(args: argparse.Namespace) -> int:
    with connect() as conn:
        paths = export_all(conn)
    if args.format == "json":
        _json([str(path) for path in paths])
    else:
        print(f"Markdown 已更新：{export_dir()}")
    return 0


def command_stats(args: argparse.Namespace) -> int:
    with connect() as conn:
        data = stats(conn)
    if args.format == "json":
        _json(data)
    else:
        print(f"總項目：{data['total']}")
        print(f"文法：{data['grammar']}")
        print(f"單字：{data['vocabulary']}")
        print(f"  已有羅馬拼音：{data['with_romaji']}")
        print(f"  已有重音資料：{data['with_accent']}")
        print(f"  外來語語源：{data['loanwords']}")
        print(f"意思／用法：{data['senses']}")
        print(f"作答紀錄：{data['attempts']}（錯題／部分正確：{data['mistakes']}）")
        print(f"文法關聯：{data['relations']}（待補：{data['pending_relations']}）")
        if data["levels"]:
            print("各等級：")
            for row in sorted(data["levels"], key=lambda row: row["name"]):
                print(f"  {row['name']}：{row['count']}")
    return 0


def command_backup(args: argparse.Namespace) -> int:
    path = create_backup(args.label or "manual")
    if not path:
        print("資料庫尚未建立。")
        return 1
    print(f"已建立備份：{path}")
    return 0


def command_backups(_: argparse.Namespace) -> int:
    backups = list(reversed(active_backups()))
    if not backups:
        print("目前沒有可供 undo 的備份。")
        return 0
    total_mib = active_backup_bytes() / (1024 * 1024)
    cap_mib = BACKUP_MAX_BYTES / (1024 * 1024)
    print(f"可供 undo 的備份（總容量 {total_mib:.1f} / {cap_mib:.0f} MiB）：")
    for path in backups:
        print(f"- {path.name}  ({path.stat().st_size / (1024 * 1024):.1f} MiB)")
    return 0


def command_undo(_: argparse.Namespace) -> int:
    backups = active_backups()
    if not backups:
        print("沒有可復原的備份。")
        return 1
    target = backups[-1]
    recovery = create_recovery_snapshot("before-undo")
    restore_database_from(target)
    used = move_used_backup(target)
    with connect() as conn:
        export_all(conn)
    print(f"已復原：{used.name}")
    if recovery:
        print(f"復原前狀態：{recovery}")
    return 0


def command_architecture(args: argparse.Namespace) -> int:
    data = {
        "core_requires_fzf": False,
        "fzf_module": "jpnote_app.ui_fzf",
        "fzf_used_for": [
            "optional import selection",
            "optional entry selection",
            "optional attempt selection",
            "optional unified browse and checkbox-style filters",
        ],
        "noninteractive_formats": ["text", "json"],
        "web_reusable_modules": [
            "validation", "repository", "services", "attempt_services",
            "browsing", "search_normalization", "import_resolution",
            "attempt_options", "audit", "import_preflight", "romaji_maintenance", "export_markdown", "db"
        ],
        "note": "核心模組不匯入 ui_fzf；Web API 可直接呼叫結構化函式。",
    }
    if args.format == "json":
        _json(data)
    else:
        for key, value in data.items():
            print(f"{key}：{value}")
    return 0


def command_manual(args: argparse.Namespace) -> int:
    guide = Path(__file__).resolve().parents[1] / "docs" / "USER_GUIDE.md"
    if not guide.is_file():
        raise RuntimeError(f"找不到操作手冊：{guide}")
    if args.path:
        print(guide)
    else:
        text = guide.read_text(encoding="utf-8")
        sys.stdout.write(text)
        if not text.endswith("\n"):
            print()
    return 0


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json"), default="text")


def _add_import_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="明確指定整批資料；v0.6.6.3 起正常 import/paste 已預設整批")
    parser.add_argument("--item-key", action="append", default=[], help="指定要匯入的穩定 key，可重複")
    parser.add_argument("--attempt-index", action="append", type=int, default=[], help="指定 attempts 的 0 起算索引，可重複")
    parser.add_argument(
        "--map-key",
        action="append",
        default=[],
        metavar="SOURCE=TARGET",
        help="將本次匯入項目沿用另一個穩定 key，可重複",
    )
    parser.add_argument(
        "--skip-item",
        action="append",
        default=[],
        metavar="KEY",
        help="跳過指定匯入項目，可重複",
    )
    parser.add_argument("--accept-warnings", action="store_true", help="確認疑似重複仍應以不同 key 匯入；不會自動合併")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="非互動地同意安全整理與正式匯入；仍會完整執行 validation/preflight，不能略過衝突",
    )
    parser.add_argument("--dry-run", action="store_true", help="只輸出匯入計畫，不寫入")
    parser.add_argument("--check", action="store_true", help="非破壞性預檢；預設掃描整批資料，不修改資料庫")
    parser.add_argument("--copy-report", action="store_true", help="將 --check 報告複製到 Wayland 剪貼簿")
    parser.add_argument("--output", help="將 --check 報告另存到指定檔案")
    _add_format(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jpnote", description=f"日文學習資料管理器 v{VERSION}")
    parser.add_argument("--version", action="version", version=f"jpnote {VERSION}")
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default=None,
        help="ANSI 顏色模式；預設採 JPNOTE_COLOR 或 auto",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="建立或升級資料庫")
    p.set_defaults(func=command_init)

    p = sub.add_parser("manual", help="顯示完整 jpnote 操作手冊")
    p.add_argument("--path", action="store_true", help="只顯示手冊檔案路徑")
    p.set_defaults(func=command_manual)

    p = sub.add_parser("config", help="查看或修改 jpnote 本機設定")
    config_sub = p.add_subparsers(dest="config_command", required=True)

    cp = config_sub.add_parser("show", help="顯示目前設定")
    _add_format(cp)
    cp.set_defaults(func=command_config_show)

    cp = config_sub.add_parser("path", help="顯示設定檔路徑")
    cp.set_defaults(func=command_config_path)

    cp = config_sub.add_parser("edit", help="使用 $EDITOR（預設 nvim）編輯設定")
    cp.set_defaults(func=command_config_edit)

    cp = config_sub.add_parser("reset", help="恢復 jpnote 預設設定")
    cp.set_defaults(func=command_config_reset)

    p = sub.add_parser("import", help="從 JSON 檔案匯入")
    p.add_argument("file")
    _add_import_options(p)
    p.set_defaults(func=command_import)

    p = sub.add_parser("paste", help="從 Wayland 剪貼簿匯入")
    _add_import_options(p)
    p.set_defaults(func=command_paste)

    p = sub.add_parser("list", help="列出文法或單字")
    p.add_argument("kind", choices=("grammar", "vocab"))
    p.add_argument("--level")
    p.add_argument("--select", action="store_true", help="使用可選 fzf 介面選一項")
    _add_format(p)
    p.set_defaults(func=command_list)

    p = sub.add_parser("browse", help="以結構化篩選瀏覽文法、單字與錯題")
    p.add_argument(
        "--type",
        dest="kind",
        action="append",
        choices=("grammar", "vocab", "mistake"),
        default=[],
        help="資料類型，可重複；未指定時使用設定檔",
    )
    p.add_argument(
        "--level",
        action="append",
        choices=("N5", "N4", "N3", "N2", "N1", "unclassified"),
        default=[],
        help="JLPT 等級，可重複；未指定時使用設定檔，unclassified 表示未分類",
    )
    p.add_argument(
        "--result",
        action="append",
        choices=("wrong", "partial"),
        default=[],
        help="錯題結果，可重複；只有明確選擇 mistake 時生效，空值表示全部",
    )
    p.add_argument("--query", help="先套用文字／羅馬拼音搜尋")
    p.add_argument("--all", action="store_true", help="直接列出全部結果，不開 fzf")
    p.add_argument("--no-fzf", action="store_true", help="停用 fzf，直接列出")
    _add_format(p)
    p.set_defaults(func=command_browse)

    p = sub.add_parser("recent", help="查看今天或指定日期範圍內新增／更新的項目")
    p.add_argument("--type", dest="kind", choices=("grammar", "vocab"), help="只看文法或單字")
    p.add_argument("--source", help="只看具有指定來源標籤的項目（完全比對）")
    p.add_argument("--date", help="只看指定本地日期（YYYY-MM-DD）；預設今天")
    p.add_argument("--since", help="查看指定本地日期起的變更（YYYY-MM-DD）")
    p.add_argument("--all", action="store_true", help="直接列出全部結果，不開 fzf")
    p.add_argument("--no-fzf", action="store_true", help="停用 fzf，直接列出")
    _add_format(p)
    p.set_defaults(func=command_recent)

    p = sub.add_parser("search", help="搜尋資料")
    p.add_argument("query")
    p.add_argument("--select", action="store_true")
    _add_format(p)
    p.set_defaults(func=command_search)

    p = sub.add_parser("edit", help="使用 $EDITOR（預設 nvim）編輯")
    p.add_argument("query", nargs="?")
    p.set_defaults(func=command_edit)

    p = sub.add_parser("delete", help="刪除項目")
    p.add_argument("query", nargs="?")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=command_delete)

    p = sub.add_parser("mistakes", help="列出錯題與部分正確紀錄")
    p.add_argument("--entry")
    p.add_argument("--level")
    _add_format(p)
    p.set_defaults(func=command_mistakes)

    p = sub.add_parser("attempts", help="查看、編輯或刪除所有作答紀錄")
    attempt_sub = p.add_subparsers(dest="attempt_command", required=True)

    ap = attempt_sub.add_parser("list", help="列出作答紀錄")
    ap.add_argument(
        "--result",
        action="append",
        choices=("correct", "wrong", "partial", "unknown"),
        default=[],
        help="依結果篩選，可重複",
    )
    ap.add_argument("--entry", help="依關聯文法或單字篩選")
    ap.add_argument("--level")
    _add_format(ap)
    ap.set_defaults(func=command_attempts_list)

    ap = attempt_sub.add_parser("show", help="查看單筆作答紀錄")
    ap.add_argument("query", nargs="?")
    ap.add_argument("--no-fzf", action="store_true")
    _add_format(ap)
    ap.set_defaults(func=command_attempts_show)

    ap = attempt_sub.add_parser("edit", help="使用 $EDITOR（預設 nvim）編輯作答紀錄")
    ap.add_argument("query", nargs="?")
    ap.set_defaults(func=command_attempts_edit)

    ap = attempt_sub.add_parser("migrate-options", help="檢查或安全拆分舊錯題內嵌的選項")
    ap.add_argument("--apply", action="store_true", help="套用高信心可自動拆分的資料；預設只預覽")
    _add_format(ap)
    ap.set_defaults(func=command_attempts_migrate_options)

    ap = attempt_sub.add_parser("delete", help="刪除作答紀錄")
    ap.add_argument("query", nargs="?")
    ap.add_argument("--yes", action="store_true")
    ap.set_defaults(func=command_attempts_delete)

    p = sub.add_parser("romaji", help="檢查或安全正規化單字羅馬拼音")
    romaji_sub = p.add_subparsers(dest="romaji_command", required=True)

    rp = romaji_sub.add_parser("audit", help="檢查既有羅馬拼音格式與讀音一致性")
    rp.add_argument("--include-ok", action="store_true", help="連同格式正常項目一起顯示")
    _add_format(rp)
    rp.set_defaults(func=command_romaji_audit)

    rp = romaji_sub.add_parser("normalize", help="預覽或套用可安全判定的羅馬拼音正規化")
    rp.add_argument("--apply", action="store_true", help="建立備份後寫入安全可正規化項目")
    _add_format(rp)
    rp.set_defaults(func=command_romaji_normalize)

    p = sub.add_parser("duplicates", help="列出保守規則找到的疑似重複")
    _add_format(p)
    p.set_defaults(func=command_duplicates)

    p = sub.add_parser("merge", help="合併兩個穩定 key")
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("--yes", action="store_true")
    _add_format(p)
    p.set_defaults(func=command_merge)

    p = sub.add_parser("audit", help="檢查既有資料")
    p.add_argument("--export", action="store_true")
    p.add_argument("--include-info", action="store_true", help="包含缺少重音等資訊性提醒")
    _add_format(p)
    p.set_defaults(func=command_audit)

    p = sub.add_parser("repair", help="套用可確定的安全修正")
    p.add_argument("--yes", action="store_true")
    _add_format(p)
    p.set_defaults(func=command_repair)

    p = sub.add_parser("export", help="重新產生 Markdown")
    _add_format(p)
    p.set_defaults(func=command_export)

    p = sub.add_parser("stats", help="顯示統計")
    _add_format(p)
    p.set_defaults(func=command_stats)

    p = sub.add_parser("backup", help="手動備份")
    p.add_argument("label", nargs="?")
    p.set_defaults(func=command_backup)

    p = sub.add_parser("backups", help="列出 undo 備份")
    p.set_defaults(func=command_backups)

    p = sub.add_parser("undo", help="復原最近一次修改")
    p.set_defaults(func=command_undo)

    p = sub.add_parser("architecture", help="檢查核心與 fzf 耦合")
    _add_format(p)
    p.set_defaults(func=command_architecture)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        configure_color(
            args.color,
            output_format=getattr(args, "format", "text"),
            stream=sys.stdout,
        )
        return int(args.func(args))
    except json.JSONDecodeError as exc:
        print(f"錯誤：JSON 第 {exc.lineno} 行、第 {exc.colno} 欄格式錯誤。", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
