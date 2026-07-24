from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jpnote_app.quiz.session_models import (
    AnswerSnapshot,
    GeneratedQuestionSnapshot,
    QuestionChoiceSnapshot,
    QuizValidationError,
)
from jpnote_app.quiz.session_store import (
    DEFAULT_DETAIL_CAP_BYTES,
    QUIZ_HISTORY_EXPORT_VERSION,
    QuizSessionNotFoundError,
    QuizSessionStateError,
    QuizSessionStore,
    QuizStorageUnavailableError,
)


class ControlledValues:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 24, 17, 0, tzinfo=timezone(timedelta(hours=8)))
        self.id_index = 0

    def clock(self) -> str:
        return self.current.isoformat(timespec="seconds")

    def set_day(self, day: int) -> None:
        self.current = self.current.replace(day=day)

    def id_factory(self, kind: str) -> str:
        self.id_index += 1
        return f"quiz-{kind}:history-{self.id_index}"


def question(label: str, *, padding: int = 0) -> GeneratedQuestionSnapshot:
    return GeneratedQuestionSnapshot(
        question_type="vocab_ja_to_zh_mcq",
        generator_version="phase2-history-test-v1",
        source_kind="vocabulary",
        source_key=f"vocab:{label}",
        prompt=f"{label} 的意思是？" + ("字" * padding),
        choices=(
            QuestionChoiceSnapshot("1", f"{label}-正解"),
            QuestionChoiceSnapshot("2", f"{label}-誤答A"),
            QuestionChoiceSnapshot("3", f"{label}-誤答B"),
            QuestionChoiceSnapshot("4", f"{label}-誤答C"),
        ),
        correct_answer=AnswerSnapshot("1", f"{label}-正解"),
    )


@pytest.fixture
def values() -> ControlledValues:
    return ControlledValues()


@pytest.fixture
def store(tmp_path: Path, values: ControlledValues) -> QuizSessionStore:
    return QuizSessionStore(
        tmp_path / "quiz.db",
        clock=values.clock,
        id_factory=values.id_factory,
    )


def complete_one(
    store: QuizSessionStore,
    label: str,
    *,
    padding: int = 0,
    correct: bool = True,
):
    session = store.create_session(
        mode="vocab",
        questions=[question(label, padding=padding)],
    )
    event = session.questions[0]
    return store.submit_answer(
        session.summary.session_id,
        event.question_event_id,
        user_answer=AnswerSnapshot("1" if correct else "2", f"{label}-答案"),
        correct=correct,
    )


def test_default_detail_cap_is_100_mib() -> None:
    assert DEFAULT_DETAIL_CAP_BYTES == 100 * 1024 * 1024


def test_prune_removes_oldest_terminal_details_and_preserves_summaries(
    store: QuizSessionStore, values: ControlledValues
) -> None:
    values.set_day(20)
    oldest = complete_one(store, "古い", padding=1500)
    values.set_day(21)
    newer = complete_one(store, "新しい", padding=1500, correct=False)

    before = store.detail_storage_bytes()
    result = store.prune_details(cap_bytes=before - 1)

    assert result.pruned_session_ids == (oldest.summary.session_id,)
    assert result.detail_bytes_before == before
    assert result.detail_bytes_after < before
    assert result.cap_satisfied

    reloaded_old = store.get_session(oldest.summary.session_id)
    assert reloaded_old.summary.details_pruned is True
    assert reloaded_old.questions == ()
    assert reloaded_old.summary.answered_count == 1
    assert reloaded_old.summary.correct_count == 1

    reloaded_new = store.get_session(newer.summary.session_id)
    assert reloaded_new.summary.details_pruned is False
    assert len(reloaded_new.questions) == 1
    assert reloaded_new.summary.incorrect_count == 1


def test_prune_never_damages_active_paused_or_interrupted_sessions(
    store: QuizSessionStore, values: ControlledValues
) -> None:
    values.set_day(20)
    terminal = complete_one(store, "完了")
    active = store.create_session(mode="vocab", questions=[question("作業中")])
    paused = store.create_session(mode="vocab", questions=[question("一時停止")])
    store.pause_session(paused.summary.session_id)
    interrupted = store.create_session(mode="vocab", questions=[question("中断")])
    store.mark_interrupted(interrupted.summary.session_id)

    result = store.prune_details(cap_bytes=0)

    assert result.pruned_session_ids == (terminal.summary.session_id,)
    assert result.cap_satisfied is False
    assert result.protected_detail_bytes == result.detail_bytes_after
    assert store.get_session(active.summary.session_id).summary.state == "active"
    assert len(store.get_session(active.summary.session_id).questions) == 1
    assert store.get_session(paused.summary.session_id).summary.state == "paused"
    assert len(store.get_session(paused.summary.session_id).questions) == 1
    assert (
        store.get_session(interrupted.summary.session_id).summary.state
        == "interrupted"
    )
    assert len(store.get_session(interrupted.summary.session_id).questions) == 1


def test_prune_under_cap_is_noop(store: QuizSessionStore) -> None:
    complete_one(store, "保持")
    before = store.detail_storage_bytes()
    result = store.prune_details(cap_bytes=before)
    assert result.pruned_session_ids == ()
    assert result.detail_bytes_before == result.detail_bytes_after == before
    assert result.cap_satisfied


def test_export_marks_pruned_details_without_inventing_questions(
    store: QuizSessionStore
) -> None:
    old = complete_one(store, "削除済み")
    current = complete_one(store, "保存中")
    store.prune_details(cap_bytes=store.detail_storage_bytes() - 1)

    payload = store.export_history()

    assert payload["format"] == "jpnote-quiz-history"
    assert payload["version"] == QUIZ_HISTORY_EXPORT_VERSION
    sessions = {item["summary"]["session_id"]: item for item in payload["sessions"]}
    assert sessions[old.summary.session_id]["details"] == {
        "status": "pruned",
        "questions": [],
    }
    assert sessions[current.summary.session_id]["details"]["status"] == "available"
    assert len(sessions[current.summary.session_id]["details"]["questions"]) == 1


def test_single_session_export_preserves_exact_question_and_answer_snapshots(
    store: QuizSessionStore
) -> None:
    completed = complete_one(store, "軌跡")
    payload = store.export_history(session_id=completed.summary.session_id)

    assert len(payload["sessions"]) == 1
    item = payload["sessions"][0]
    exported = item["details"]["questions"][0]
    assert exported["question"]["source_key"] == "vocab:軌跡"
    assert exported["question"]["prompt"] == "軌跡 的意思是？"
    assert exported["question"]["correct_answer"] == {
        "answer_id": "1",
        "text": "軌跡-正解",
    }
    assert exported["user_answer"] == {"answer_id": "1", "text": "軌跡-答案"}
    assert exported["result"] == "correct"


def test_export_date_range_is_inclusive(
    store: QuizSessionStore, values: ControlledValues
) -> None:
    values.set_day(20)
    first = complete_one(store, "20日")
    values.set_day(21)
    second = complete_one(store, "21日")
    values.set_day(22)
    complete_one(store, "22日")

    payload = store.export_history(start_date="2026-07-20", end_date="2026-07-21")
    ids = [item["summary"]["session_id"] for item in payload["sessions"]]
    assert ids == [first.summary.session_id, second.summary.session_id]


def test_export_rejects_invalid_or_ambiguous_filters(store: QuizSessionStore) -> None:
    session = complete_one(store, "篩選")
    with pytest.raises(QuizValidationError, match="YYYY-MM-DD"):
        store.export_history(start_date="2026/07/24")
    with pytest.raises(QuizValidationError, match="不可晚於"):
        store.export_history(start_date="2026-07-25", end_date="2026-07-24")
    with pytest.raises(QuizValidationError, match="不可同時"):
        store.export_history(
            session_id=session.summary.session_id,
            start_date="2026-07-24",
        )
    with pytest.raises(QuizSessionNotFoundError):
        store.export_history(session_id="quiz-session:missing")


def test_json_export_is_atomic_valid_and_private(
    store: QuizSessionStore, tmp_path: Path
) -> None:
    complete_one(store, "匯出")
    destination = tmp_path / "exports" / "history.json"

    written = store.write_history_json(destination)

    assert written == destination
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["format"] == "jpnote-quiz-history"
    assert len(payload["sessions"]) == 1
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.parent.stat().st_mode & 0o777 == 0o700
    assert list(destination.parent.glob("*.pending-*")) == []
    assert list(destination.parent.glob(".*.pending-*")) == []


def test_json_export_write_failure_is_contained(
    store: QuizSessionStore, tmp_path: Path
) -> None:
    complete_one(store, "失敗")
    destination = tmp_path / "directory-instead-of-file"
    destination.mkdir()
    with pytest.raises(QuizStorageUnavailableError, match="JSON"):
        store.write_history_json(destination)


def test_delete_terminal_session_removes_summary_and_details(
    store: QuizSessionStore
) -> None:
    completed = complete_one(store, "刪除")
    before = store.detail_storage_bytes()

    deleted = store.delete_session(completed.summary.session_id)

    assert deleted.session_id == completed.summary.session_id
    assert store.detail_storage_bytes() < before
    with pytest.raises(QuizSessionNotFoundError):
        store.get_session(completed.summary.session_id)


def test_delete_resumable_session_requires_explicit_permission(
    store: QuizSessionStore
) -> None:
    active = store.create_session(mode="vocab", questions=[question("保護")])
    with pytest.raises(QuizSessionStateError, match="明確允許"):
        store.delete_session(active.summary.session_id)
    assert store.get_session(active.summary.session_id).summary.state == "active"

    deleted = store.delete_session(
        active.summary.session_id,
        include_resumable=True,
    )
    assert deleted.session_id == active.summary.session_id
    with pytest.raises(QuizSessionNotFoundError):
        store.get_session(active.summary.session_id)


def test_delete_all_history_defaults_to_terminal_only(store: QuizSessionStore) -> None:
    completed = complete_one(store, "完成")
    abandoned = store.create_session(mode="vocab", questions=[question("放棄")])
    store.abandon_session(abandoned.summary.session_id)
    active = store.create_session(mode="vocab", questions=[question("進行中")])

    deleted = store.delete_all_history()

    assert set(deleted) == {completed.summary.session_id, abandoned.summary.session_id}
    assert store.get_session(active.summary.session_id).summary.state == "active"
    assert store.delete_all_history(include_resumable=True) == (
        active.summary.session_id,
    )
    assert store.list_recent_sessions() == ()


def test_pruning_and_deletion_never_create_core_tables(
    store: QuizSessionStore
) -> None:
    complete_one(store, "隔離")
    store.prune_details(cap_bytes=0)
    store.delete_all_history()
    with sqlite3.connect(store.path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    assert tables == {"quiz_question_events", "quiz_sessions"}


def test_export_refuses_incomplete_unpruned_details(store: QuizSessionStore) -> None:
    completed = complete_one(store, "破損")
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "DELETE FROM quiz_question_events WHERE session_id=?",
            (completed.summary.session_id,),
        )
    with pytest.raises(QuizStorageUnavailableError, match="不完整"):
        store.export_history(session_id=completed.summary.session_id)


def test_json_export_does_not_rechmod_existing_parent(
    store: QuizSessionStore, tmp_path: Path
) -> None:
    complete_one(store, "權限")
    parent = tmp_path / "existing-export-dir"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)

    store.write_history_json(parent / "history.json")

    assert parent.stat().st_mode & 0o777 == 0o755
