from __future__ import annotations

import json
from pathlib import Path

import pytest

from jpnote_app.audit import run_audit
from jpnote_app.db import connect
from jpnote_app.export_markdown import export_all
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.quiz.service import QuizService
from jpnote_app.quiz.session_store import QuizSessionStore
from jpnote_app.romaji_maintenance import romaji_audit_records
from jpnote_app.services import apply_import, prepare_import
from jpnote_app.study_sources import StudySourceService
from jpnote_app.validation import parse_payload
from jpnote_app.relation_integrity import relation_integrity_issues


def _select_count(conn, operation) -> int:
    selects: list[str] = []
    conn.set_trace_callback(
        lambda sql: selects.append(sql)
        if sql.lstrip().upper().startswith("SELECT") else None
    )
    try:
        operation()
    finally:
        conn.set_trace_callback(None)
    return len(selects)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(root))
    return root


def _seed_vocab(count: int = 120) -> None:
    payload = {
        "source": "v0.7.5.1 bulk regression",
        "items": [
            {
                "key": f"vocab:語{i}",
                "type": "vocabulary",
                "display": f"語{i}",
                "reading": f"ご{i}",
                "romaji": "go",
                "meanings": [f"意思{i}"],
            }
            for i in range(count)
        ],
    }
    with connect() as conn:
        apply_import(conn, prepare_import(conn, payload))


def _seed_attempts(count: int = 120) -> None:
    payload = {
        "attempts": [
            {
                "event_key": f"attempt:seed-{i}",
                "date": "2026-09-12",
                "source": "效能測試",
                "section": "第一回",
                "question": f"問題{i}",
                "question_type": "multiple_choice",
                "prompt": f"題目 {i}",
                "user_answer": "1",
                "correct_answer": "2",
                "result": "wrong",
                "linked_entries": [f"vocab:語{i % 120}"],
            }
            for i in range(count)
        ],
    }
    with connect() as conn:
        apply_import(conn, prepare_import(conn, payload))


def test_romaji_audit_is_single_entry_scan(data_dir: Path) -> None:
    _seed_vocab()
    with connect() as conn:
        records: list[dict] = []
        count = _select_count(conn, lambda: records.extend(romaji_audit_records(conn)))
    assert len(records) == 120
    assert count <= 1


def test_full_audit_query_count_does_not_scale_with_attempt_links(data_dir: Path) -> None:
    _seed_vocab()
    _seed_attempts()
    with connect() as conn:
        issues = []
        count = _select_count(conn, lambda: issues.extend(run_audit(conn)))
    assert isinstance(issues, list)
    assert count <= 24


def test_markdown_export_reuses_bulk_entry_hydration(data_dir: Path) -> None:
    _seed_vocab()
    _seed_attempts(20)
    with connect() as conn:
        paths: list[Path] = []
        count = _select_count(conn, lambda: paths.extend(export_all(conn)))
    assert len(paths) == 7
    assert all(path.exists() for path in paths)
    assert count <= 12


def test_preflight_bulk_items_and_generated_attempts_use_bounded_reads(data_dir: Path) -> None:
    _seed_vocab()
    _seed_attempts()
    payload = {
        "source": "v0.7.5.1 preflight",
        "items": [
            {
                "key": f"vocab:語{i}",
                "type": "vocabulary",
                "display": f"語{i}",
                "reading": f"ご{i}",
                "romaji": "go",
                "meanings": [f"意思{i}", f"追加{i}"],
            }
            for i in range(20)
        ],
        "attempts": [
            {
                "date": "2026-09-13",
                "source": "新題",
                "section": "第一回",
                "question": f"問題{i}",
                "question_type": "multiple_choice",
                "prompt": f"新題 {i}",
                "user_answer": "1",
                "correct_answer": "2",
                "result": "wrong",
                "linked_entries": [f"vocab:語{i}"],
            }
            for i in range(20)
        ],
    }
    with connect() as conn:
        plan = prepare_import(conn, payload)
        reports: list[dict] = []
        count = _select_count(
            conn,
            lambda: reports.append(build_preflight_report(conn, plan)),
        )
    report = reports[0]
    assert report["summary"]["update_items"] == 20
    assert report["summary"]["new_attempts"] == 20
    assert count <= 14


def test_preflight_preserves_raw_alias_json_normalization_semantics(data_dir: Path) -> None:
    _seed_vocab(1)
    with connect() as conn:
        conn.execute(
            "UPDATE entries SET aliases_json='[ \"別名\" ]' WHERE key='vocab:語0'"
        )
        plan = prepare_import(conn, {
            "items": [{
                "key": "vocab:語0",
                "type": "vocabulary",
                "display": "語0",
                "aliases": ["別名"],
            }],
        })
        report = build_preflight_report(conn, plan)
    assert report["summary"]["update_items"] == 1


def test_relation_integrity_bulk_grouping_preserves_logical_key_order(data_dir: Path) -> None:
    with connect() as conn:
        apply_import(conn, prepare_import(conn, {
            "items": [
                {"key": "grammar:A", "type": "grammar", "display": "A"},
                {"key": "grammar:B", "type": "grammar", "display": "B"},
                {"key": "grammar:C", "type": "grammar", "display": "C"},
            ]
        }))
        rows = [
            ("grammar:C", "grammar:A", "similar", "x", "test", "2026-01-01"),
            ("grammar:C", "grammar:A", "similar", "y", "test", "2026-01-02"),
            ("grammar:A", "grammar:B", "similar", "m", "test", "2026-01-03"),
            ("grammar:A", "grammar:B", "similar", "n", "test", "2026-01-04"),
        ]
        conn.executemany(
            "INSERT INTO pending_grammar_relations("
            "source_key,target_key,relation_type,note,source,created_at"
            ") VALUES(?,?,?,?,?,?)",
            rows,
        )
        issues = [
            issue for issue in relation_integrity_issues(conn)
            if issue["code"] == "conflicting_relation_notes"
        ]
    assert [issue["key"] for issue in issues] == ["grammar:A", "grammar:C"]


def test_parse_payload_recovers_after_unmatched_surrounding_brace() -> None:
    payload = parse_payload('prefix { broken {"items": []} suffix')
    assert payload == {"items": []}


def test_parse_payload_recovers_after_unmatched_surrounding_quote() -> None:
    payload = parse_payload('prefix " broken {"items": []} suffix')
    assert payload == {"items": []}


def test_parse_payload_malformed_context_still_rejects_two_payloads() -> None:
    text = 'prefix " broken {"items": []} middle {"attempts": []}'
    with pytest.raises(ValueError, match="多份不同"):
        parse_payload(text)


def test_parse_payload_nested_scan_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    original = json.JSONDecoder.raw_decode
    calls = 0

    def counted(self, value, idx=0):
        nonlocal calls
        calls += 1
        return original(self, value, idx)

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", counted)
    wrapper = {
        "noise": [{"index": i, "inner": {"value": i}} for i in range(1500)],
        "wrapped": {"items": [{"key": "vocab:猫", "type": "vocabulary", "display": "猫"}]},
    }
    parsed = parse_payload("prefix\n" + json.dumps(wrapper, ensure_ascii=False) + "\nsuffix")
    assert parsed["items"][0]["key"] == "vocab:猫"
    assert calls <= 4


def test_parse_payload_still_rejects_two_distinct_embedded_payloads() -> None:
    text = (
        'before {"items":[{"key":"vocab:A","type":"vocabulary","display":"A"}]} '
        'middle {"items":[{"key":"vocab:B","type":"vocabulary","display":"B"}]} after'
    )
    with pytest.raises(ValueError, match="多份不同"):
        parse_payload(text)


class _CountingCore:
    def __init__(self) -> None:
        self.browse_calls = 0

    def browse(self, types=None, levels=None, results=None, query=None):
        self.browse_calls += 1
        records = []
        selected = set(types or ("grammar", "vocab"))
        if "vocab" in selected:
            for index in range(4):
                records.append({
                    "kind": "vocab",
                    "token": f"entry:vocab:語{index}",
                    "data": {
                        "key": f"vocab:語{index}",
                        "type": "vocabulary",
                        "display": f"語{index}",
                        "reading": f"よみ{index}",
                        "level": "N3",
                        "aliases": [],
                        "senses": [{"meaning": f"意思{index}", "example_ja": "", "example_zh": ""}],
                        "sources": ["共用來源"],
                    },
                })
        if "grammar" in selected:
            records.append({
                "kind": "grammar",
                "token": "entry:grammar:ため",
                "data": {
                    "key": "grammar:ため",
                    "type": "grammar",
                    "display": "ため",
                    "level": "N3",
                    "aliases": [],
                    "senses": [{"meaning": "因為", "example_ja": "", "example_zh": ""}],
                    "sources": ["共用來源"],
                },
            })
        if "mistake" in selected:
            records.append({
                "kind": "mistake",
                "token": "attempt:one",
                "levels": ["N3"],
                "data": {
                    "event_key": "attempt:one",
                    "result": "wrong",
                    "date": "2026-09-12",
                    "source": "錯題來源",
                    "question_type": "multiple_choice",
                    "prompt": "題目",
                    "correct_answer": "2",
                    "options": [
                        {"id": 1, "text": "錯"},
                        {"id": 2, "text": "對"},
                    ],
                    "linked_entries": ["vocab:語0"],
                },
            })
        return records

    def get(self, key):
        return None

    def get_attempt(self, event_key):
        return None


def test_source_catalog_and_mixed_quiz_use_one_bulk_browse(tmp_path: Path) -> None:
    core = _CountingCore()
    reader = StudySourceService(core)
    catalog = reader.source_catalog()
    assert catalog.entry_count == 5
    assert catalog.replayable_attempt_count == 1
    assert core.browse_calls == 1

    quiz = QuizService(reader, QuizSessionStore(tmp_path / "quiz.db"))
    plan = quiz.plan_session(mode="mixed", requested_count=2, seed="bulk")
    assert plan.report.selected_count == 2
    assert core.browse_calls == 2
