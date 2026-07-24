"""Small public facade intended for a future mimir Web API.

Web/PWA code can call this class without importing the CLI or fzf adapter.
Methods return JSON-serializable structures and leave presentation to callers.
"""

from __future__ import annotations

from typing import Any

from .attempt_services import delete_attempt_data, replace_attempt_data
from .browsing import browse_json, browse_records
from .audit import apply_safe_repairs, run_audit
from .db import connect, connect_preflight
from .import_resolution import resolve_import_plan
from .repository import get_attempt, get_entry, list_attempts, list_entries, list_recent_entries, search_entries, stats
from .services import apply_import, duplicate_candidates, merge_entries, prepare_import
from .import_preflight import blocking_preflight_messages, build_preflight_report
from .mutations import execute_safe_mutation
from .romaji_maintenance import romaji_audit_records, apply_safe_romaji_normalization
from .attempt_options import apply_safe_option_migrations


class JpnoteCore:
    def list_entries(self, entry_type: str | None = None, level: str | None = None) -> list[dict[str, Any]]:
        with connect() as conn:
            return list_entries(conn, entry_type, level)

    def search(self, query: str) -> list[dict[str, Any]]:
        with connect() as conn:
            return search_entries(conn, query)

    def browse(
        self,
        types: list[str] | None = None,
        levels: list[str] | None = None,
        results: list[str] | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            return browse_json(browse_records(
                conn, types=types, levels=levels, results=results, query=query
            ))

    def recent(
        self,
        target_date: str | None = None,
        since_date: str | None = None,
        entry_type: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            return list_recent_entries(conn, target_date, since_date, entry_type, source)

    def get(self, key: str) -> dict[str, Any] | None:
        with connect() as conn:
            return get_entry(conn, key)

    def prepare_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        with connect_preflight() as conn:
            return prepare_import(conn, payload).to_dict()

    def preflight_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        with connect_preflight() as conn:
            plan = prepare_import(conn, payload)
            return build_preflight_report(conn, plan)

    def romaji_audit(self) -> list[dict[str, Any]]:
        with connect() as conn:
            return romaji_audit_records(conn)

    def normalize_romaji(self) -> list[dict[str, Any]]:
        return execute_safe_mutation(
            "romaji-normalize",
            apply_safe_romaji_normalization,
        ).value

    def resolve_import(
        self,
        payload: dict[str, Any],
        key_map: dict[str, str] | None = None,
        skip_item_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """Prepare and resolve an import without relying on any UI adapter."""
        with connect_preflight() as conn:
            plan = prepare_import(conn, payload)
            return resolve_import_plan(conn, plan, key_map, skip_item_keys).to_dict()

    def apply_import(
        self,
        payload: dict[str, Any],
        key_map: dict[str, str] | None = None,
        skip_item_keys: set[str] | None = None,
        *,
        accept_warnings: bool = False,
    ) -> dict[str, Any]:
        """Apply a validated import through the shared safe mutation boundary.

        Duplicate warnings require an explicit opt-in. Blocking preflight
        conflicts can never be bypassed. The plan is rebuilt against the same
        connection used for the transaction so public callers cannot skip the
        CLI's safety rules.
        """
        def operation(conn: Any) -> tuple[Any, dict[str, Any]]:
            plan = prepare_import(conn, payload)
            if key_map or skip_item_keys:
                plan = resolve_import_plan(conn, plan, key_map, skip_item_keys)
            report = build_preflight_report(conn, plan)
            blocking = blocking_preflight_messages(report)
            if blocking:
                raise ValueError("預檢存在不可略過的問題：" + "；".join(blocking))
            if plan.warnings and not accept_warnings:
                raise ValueError(
                    "匯入存在疑似重複項目；請先 resolve_import，或明確傳入 accept_warnings=True。"
                )
            return apply_import(conn, plan), report

        execution = execute_safe_mutation("import", operation)
        result, report = execution.value
        return {
            **result.to_dict(),
            "modified": execution.modified,
            "backup": str(execution.backup or ""),
            "preflight": report,
        }

    def mistakes(self, entry_key: str | None = None, level: str | None = None) -> list[dict[str, Any]]:
        with connect() as conn:
            return list_attempts(conn, ["wrong", "partial"], entry_key, level)

    def attempts(
        self,
        results: list[str] | None = None,
        entry_key: str | None = None,
        level: str | None = None,
    ) -> list[dict[str, Any]]:
        with connect() as conn:
            return list_attempts(conn, results, entry_key, level)

    def get_attempt(self, event_key: str) -> dict[str, Any] | None:
        with connect() as conn:
            return get_attempt(conn, event_key)

    def update_attempt(self, event_key: str, attempt: dict[str, Any]) -> dict[str, Any]:
        return execute_safe_mutation(
            "attempt-edit",
            lambda conn: replace_attempt_data(conn, event_key, attempt),
        ).value

    def delete_attempt(self, event_key: str) -> bool:
        return execute_safe_mutation(
            "attempt-delete",
            lambda conn: delete_attempt_data(conn, event_key),
        ).value

    def audit(self) -> list[dict[str, Any]]:
        with connect() as conn:
            return [issue.to_dict() for issue in run_audit(conn)]

    def repair(self) -> dict[str, Any]:
        def operation(conn: Any) -> dict[str, Any]:
            actions = apply_safe_repairs(conn)
            option_migrations = apply_safe_option_migrations(conn)
            romaji_normalizations = apply_safe_romaji_normalization(conn)
            unresolved = [
                issue.to_dict() for issue in run_audit(conn)
                if issue.severity in {"critical", "needs_input", "review"} and not issue.fixable
            ]
            return {
                "actions": actions,
                "option_migrations": option_migrations,
                "romaji_normalizations": romaji_normalizations,
                "unresolved": unresolved,
            }
        return execute_safe_mutation("repair", operation).value

    def duplicates(self) -> list[dict[str, Any]]:
        with connect() as conn:
            return duplicate_candidates(conn)

    def merge(self, source_key: str, target_key: str) -> dict[str, Any]:
        return execute_safe_mutation(
            "merge",
            lambda conn: merge_entries(conn, source_key, target_key),
        ).value

    def stats(self) -> dict[str, Any]:
        with connect() as conn:
            return stats(conn)
