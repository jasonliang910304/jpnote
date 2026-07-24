from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jpnote_app.quiz.session_models import (
    AnswerSnapshot,
    GeneratedQuestionSnapshot,
    QuestionChoiceSnapshot,
    QuizValidationError,
)
from jpnote_app.quiz.session_store import (
    QUIZ_SCHEMA_VERSION,
    QuizSessionStateError,
    QuizSessionStore,
    QuizStorageUnavailableError,
)


class DeterministicValues:
    def __init__(self) -> None:
        self.time_index = 0
        self.id_index = 0

    def clock(self) -> str:
        self.time_index += 1
        return f"2026-07-24T16:40:{self.time_index:02d}+08:00"

    def id_factory(self, kind: str) -> str:
        self.id_index += 1
        return f"quiz-{kind}:test-{self.id_index}"


def vocab_question(
    *, source_key: str = "vocab:軌跡", prompt: str = "軌跡 的中文意思是？"
) -> GeneratedQuestionSnapshot:
    return GeneratedQuestionSnapshot(
        question_type="vocab_ja_to_zh_mcq",
        generator_version="phase2-test-v1",
        source_kind="vocabulary",
        source_key=source_key,
        prompt=prompt,
        choices=(
            QuestionChoiceSnapshot("1", "軌道、行進留下的路徑"),
            QuestionChoiceSnapshot("2", "奇蹟"),
            QuestionChoiceSnapshot("3", "季節"),
            QuestionChoiceSnapshot("4", "座位"),
        ),
        correct_answer=AnswerSnapshot("1", "軌道、行進留下的路徑"),
    )


def mistake_question() -> GeneratedQuestionSnapshot:
    return GeneratedQuestionSnapshot(
        question_type="mistake_replay_mcq",
        generator_version="phase2-test-v1",
        source_kind="mistake",
        source_key="attempt:stable-event-key",
        prompt="この電車は東京＿＿行きます。",
        choices=(
            QuestionChoiceSnapshot("1", "へ"),
            QuestionChoiceSnapshot("2", "を"),
            QuestionChoiceSnapshot("3", "で"),
            QuestionChoiceSnapshot("4", "と"),
        ),
        correct_answer=AnswerSnapshot("1", "へ"),
    )


@pytest.fixture
def values() -> DeterministicValues:
    return DeterministicValues()


@pytest.fixture
def store(tmp_path: Path, values: DeterministicValues) -> QuizSessionStore:
    return QuizSessionStore(
        tmp_path / "quiz.db", clock=values.clock, id_factory=values.id_factory
    )


def test_uses_independent_schema_and_never_creates_core_tables(
    tmp_path: Path, values: DeterministicValues
) -> None:
    path = tmp_path / "quiz.db"
    QuizSessionStore(path, clock=values.clock, id_factory=values.id_factory)
    with sqlite3.connect(path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    assert version == QUIZ_SCHEMA_VERSION
    assert tables == {"quiz_question_events", "quiz_sessions"}
    assert "entries" not in tables
    assert "attempts" not in tables


def test_create_session_assigns_stable_ids_and_exact_snapshots(
    store: QuizSessionStore,
) -> None:
    created = store.create_session(
        mode="mixed", questions=[vocab_question(), mistake_question()], requested_count=10
    )
    assert created.summary.session_id == "quiz-session:test-1"
    assert created.summary.requested_count == 10
    assert created.summary.question_count == 2
    assert created.summary.state == "active"
    assert [question.question_event_id for question in created.questions] == [
        "quiz-question:test-2",
        "quiz-question:test-3",
    ]
    assert created.questions[0].question.prompt == "軌跡 的中文意思是？"
    assert created.questions[0].question.source_key == "vocab:軌跡"
    assert created.questions[1].question.source_key == "attempt:stable-event-key"
    assert store.get_session(created.summary.session_id) == created


def test_answers_are_saved_one_by_one_and_final_answer_completes_session(
    store: QuizSessionStore,
) -> None:
    session = store.create_session(
        mode="mixed", questions=[vocab_question(), mistake_question()]
    )
    first, second = session.questions

    after_first = store.submit_answer(
        session.summary.session_id,
        first.question_event_id,
        user_answer=AnswerSnapshot("1", "軌道、行進留下的路徑"),
        correct=True,
    )
    assert after_first.summary.state == "active"
    assert after_first.summary.answered_count == 1
    assert after_first.summary.correct_count == 1
    assert store.next_question(session.summary.session_id) == after_first.questions[1]

    completed = store.skip_question(
        session.summary.session_id, second.question_event_id
    )
    assert completed.summary.state == "completed"
    assert completed.summary.answered_count == 2
    assert completed.summary.correct_count == 1
    assert completed.summary.incorrect_count == 0
    assert completed.summary.skipped_count == 1
    assert completed.summary.effective_incorrect_count == 1
    assert completed.summary.accuracy == 0.5
    assert completed.questions[1].result == "skipped"
    assert completed.questions[1].user_answer is None
    assert completed.summary.ended_at is not None


def test_pause_and_resume_preserve_exact_remaining_questions(
    store: QuizSessionStore,
) -> None:
    session = store.create_session(
        mode="vocab", questions=[vocab_question(), mistake_question()]
    )
    first = session.questions[0]
    after_first = store.submit_answer(
        session.summary.session_id,
        first.question_event_id,
        user_answer=AnswerSnapshot("2", "奇蹟"),
        correct=False,
    )
    remaining_before = after_first.remaining_questions

    paused = store.pause_session(session.summary.session_id)
    assert paused.summary.state == "paused"
    with pytest.raises(QuizSessionStateError):
        store.next_question(session.summary.session_id)

    resumed = store.resume_session(session.summary.session_id)
    assert resumed.summary.state == "active"
    assert resumed.remaining_questions == remaining_before
    assert resumed.questions[1].question.prompt == remaining_before[0].question.prompt
    assert resumed.questions[1].question.choices == remaining_before[0].question.choices


def test_interrupted_session_is_resumable_without_regeneration(
    store: QuizSessionStore,
) -> None:
    session = store.create_session(mode="mixed", questions=[vocab_question()])
    interrupted = store.mark_interrupted(session.summary.session_id)
    assert interrupted.summary.state == "interrupted"
    assert interrupted.remaining_questions == session.questions

    resumed = store.resume_session(session.summary.session_id)
    assert resumed.summary.state == "active"
    assert resumed.questions == session.questions


def test_abandoned_session_remains_in_history_but_cannot_resume(
    store: QuizSessionStore,
) -> None:
    session = store.create_session(mode="mixed", questions=[vocab_question()])
    abandoned = store.abandon_session(session.summary.session_id)
    assert abandoned.summary.state == "abandoned"
    assert abandoned.summary.ended_at is not None
    assert store.list_recent_sessions()[0].state == "abandoned"
    assert store.list_recent_sessions(include_abandoned=False) == ()
    with pytest.raises(QuizSessionStateError):
        store.resume_session(session.summary.session_id)


def test_only_next_unanswered_question_can_be_submitted(
    store: QuizSessionStore,
) -> None:
    session = store.create_session(
        mode="mixed", questions=[vocab_question(), mistake_question()]
    )
    with pytest.raises(QuizSessionStateError):
        store.submit_answer(
            session.summary.session_id,
            session.questions[1].question_event_id,
            user_answer=AnswerSnapshot("1", "へ"),
            correct=True,
        )
    unchanged = store.get_session(session.summary.session_id)
    assert unchanged.summary.answered_count == 0
    assert all(question.result is None for question in unchanged.questions)


def test_duplicate_generated_question_is_rejected_before_database_write(
    store: QuizSessionStore,
) -> None:
    question = vocab_question()
    with pytest.raises(QuizValidationError):
        store.create_session(mode="vocab", questions=[question, question])
    assert store.list_recent_sessions() == ()


def test_question_snapshots_do_not_change_when_caller_builds_new_source_data(
    store: QuizSessionStore,
) -> None:
    original = vocab_question()
    session = store.create_session(mode="vocab", questions=[original])
    replacement = vocab_question(
        source_key="vocab:軌跡", prompt="更新後的來源文字，不應回寫舊 session"
    )
    assert replacement.prompt != original.prompt
    reloaded = store.get_session(session.summary.session_id)
    assert reloaded.questions[0].question.prompt == "軌跡 的中文意思是？"


def test_newer_quiz_schema_fails_closed_without_touching_core(
    tmp_path: Path, values: DeterministicValues
) -> None:
    path = tmp_path / "quiz.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(QuizStorageUnavailableError, match="比目前程式新"):
        QuizSessionStore(path, clock=values.clock, id_factory=values.id_factory)


class FailingMigrationStore(QuizSessionStore):
    def _apply_schema_v1(self, conn: sqlite3.Connection) -> None:
        super()._apply_schema_v1(conn)
        raise RuntimeError("simulated migration failure after all DDL")


def test_failed_migration_rolls_back_all_quiz_tables(
    tmp_path: Path, values: DeterministicValues
) -> None:
    path = tmp_path / "quiz.db"
    with pytest.raises(QuizStorageUnavailableError, match="migration"):
        FailingMigrationStore(
            path, clock=values.clock, id_factory=values.id_factory
        )
    with sqlite3.connect(path) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert tables == []
    assert version == 0


def test_unopenable_quiz_path_is_contained_as_optional_storage_failure(
    tmp_path: Path, values: DeterministicValues
) -> None:
    directory_instead_of_db = tmp_path / "not-a-db"
    directory_instead_of_db.mkdir()
    with pytest.raises(QuizStorageUnavailableError):
        QuizSessionStore(
            directory_instead_of_db,
            clock=values.clock,
            id_factory=values.id_factory,
        )
