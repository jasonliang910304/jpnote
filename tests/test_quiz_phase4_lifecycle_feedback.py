from __future__ import annotations

import json
from pathlib import Path

import pytest

from jpnote_app.quiz.debug_cli import run
from jpnote_app.quiz.service import QuizAnswerError, QuizService, QuizServiceError
from jpnote_app.quiz.session_models import QuizValidationError
from jpnote_app.quiz.session_store import QuizSessionStore
from jpnote_app.study_sources import (
    AttemptCapabilities,
    AttemptReplaySource,
    ChoiceSnapshot,
    EntryCapabilities,
    EntrySnapshot,
    QuestionSourceUnavailableError,
    SenseSnapshot,
    SourceCatalog,
)


def vocab(number: int) -> EntrySnapshot:
    return EntrySnapshot(
        key=f"vocab:語{number}",
        entry_type="vocabulary",
        display=f"語{number}",
        reading=f"よみ{number}",
        romaji=f"yo mi {number}",
        level="N3",
        review_group="",
        aliases=(f"別名{number}",),
        senses=(
            SenseSnapshot(
                meaning=f"意思{number}",
                example_ja=f"語{number}の例文。",
                example_zh=f"詞語{number}的例句。",
            ),
        ),
        sources=("測試來源",),
        capabilities=EntryCapabilities(True, True, True, True),
    )


def attempt(number: int = 1) -> AttemptReplaySource:
    return AttemptReplaySource(
        event_key=f"attempt:mcq-{number}",
        result="wrong",
        attempt_date="2026-07-24",
        source="錯題來源",
        section="第一回",
        question=str(number),
        question_type="multiple_choice",
        prompt="正しいものを選んでください。",
        user_answer="1",
        correct_answer="2",
        reason="助詞選擇錯誤",
        before="私は",
        after="を選びます。",
        parts=(),
        user_order=(),
        correct_order=(),
        options=(
            ChoiceSnapshot(1, "錯誤"),
            ChoiceSnapshot(2, "正解"),
            ChoiceSnapshot(3, "別案"),
            ChoiceSnapshot(4, "その他"),
        ),
        linked_entry_keys=("vocab:語1",),
        linked_levels=("N3",),
        recorded_at="2026-07-24T12:00:00+08:00",
        data_warnings=(),
        capabilities=AttemptCapabilities(
            has_prompt=True,
            has_correct_answer=True,
            has_choices=True,
            has_reorder_parts=False,
            has_sentence_context=True,
            structure_valid=True,
        ),
    )


class FakeReader:
    def __init__(self, *, entries=(), attempts=(), unavailable=False):
        self.entries = tuple(entries)
        self.attempts = tuple(attempts)
        self.unavailable = unavailable

    def list_entry_snapshots(self, **kwargs):
        return self.entries

    def get_entry_snapshot(self, key):
        if self.unavailable:
            raise QuestionSourceUnavailableError("core read failed")
        return next((entry for entry in self.entries if entry.key == key), None)

    def list_attempt_replay_sources(self, **kwargs):
        return self.attempts

    def get_attempt_replay_source(self, event_key):
        if self.unavailable:
            raise QuestionSourceUnavailableError("core read failed")
        return next(
            (source for source in self.attempts if source.event_key == event_key),
            None,
        )

    def source_catalog(self):
        return SourceCatalog(
            entry_count=len(self.entries),
            replayable_attempt_count=len(self.attempts),
            levels=("N3",),
            sources=("測試來源", "錯題來源"),
        )


@pytest.fixture
def service(tmp_path: Path) -> QuizService:
    return QuizService(
        FakeReader(
            entries=tuple(vocab(index) for index in range(1, 7)),
            attempts=(attempt(),),
        ),
        QuizSessionStore(tmp_path / "quiz.db"),
    )


def start(quiz: QuizService, *, mode="mixed", count=2, seed=1):
    result = quiz.start_session(
        mode=mode,
        requested_count=count,
        seed=seed,
        allow_shortage=True,
    )
    assert result.session is not None
    return result.session


def answer_current_correctly(quiz: QuizService, session_id: str):
    event = quiz.current_question(session_id)
    assert event is not None
    return quiz.submit_choice(
        session_id,
        event.question_event_id,
        choice_id=event.question.correct_answer.answer_id,
    )


def test_store_state_filter_returns_only_requested_states(service):
    active = start(service, count=1, seed=10)
    paused = start(service, count=1, seed=11)
    service.pause_session(paused.summary.session_id)
    completed = start(service, count=1, seed=12)
    answer_current_correctly(service, completed.summary.session_id)

    summaries = service.session_store.list_recent_sessions(
        limit=10, states=("active", "paused")
    )
    assert {summary.state for summary in summaries} == {"active", "paused"}
    assert {summary.session_id for summary in summaries} == {
        active.summary.session_id,
        paused.summary.session_id,
    }


def test_store_state_filter_rejects_unknown_state(service):
    with pytest.raises(QuizValidationError, match="不支援"):
        service.session_store.list_recent_sessions(states=("unknown",))


def test_empty_store_state_filter_returns_empty(service):
    assert service.session_store.list_recent_sessions(states=()) == ()


def test_list_resumable_excludes_terminal_sessions(service):
    active = start(service, count=1, seed=20)
    paused = start(service, count=1, seed=21)
    service.pause_session(paused.summary.session_id)
    interrupted = start(service, count=1, seed=22)
    service.mark_interrupted(interrupted.summary.session_id)
    completed = start(service, count=1, seed=23)
    answer_current_correctly(service, completed.summary.session_id)
    abandoned = start(service, count=1, seed=24)
    service.abandon_session(abandoned.summary.session_id)

    resumable = service.list_resumable_sessions(limit=20)
    assert {summary.session_id for summary in resumable} == {
        active.summary.session_id,
        paused.summary.session_id,
        interrupted.summary.session_id,
    }


def test_continue_active_session_keeps_same_question_snapshot(service):
    session = start(service, count=2, seed=30)
    continued = service.continue_session(session.summary.session_id)
    assert continued.summary.state == "active"
    assert continued.remaining_questions == session.remaining_questions


@pytest.mark.parametrize("state", ["paused", "interrupted"])
def test_continue_resumes_saved_nonterminal_session(service, state):
    session = start(service, count=2, seed=f"resume-{state}")
    if state == "paused":
        saved = service.pause_session(session.summary.session_id)
    else:
        saved = service.mark_interrupted(session.summary.session_id)
    continued = service.continue_session(session.summary.session_id)
    assert continued.summary.state == "active"
    assert continued.remaining_questions == saved.remaining_questions


def test_continue_terminal_session_is_rejected(service):
    session = start(service, count=1, seed=31)
    answer_current_correctly(service, session.summary.session_id)
    with pytest.raises(QuizServiceError, match="不可恢復"):
        service.continue_session(session.summary.session_id)


@pytest.mark.parametrize("state", ["active", "paused", "interrupted"])
def test_decline_resume_marks_resumable_session_abandoned(service, state):
    session = start(service, count=2, seed=f"decline-{state}")
    if state == "paused":
        service.pause_session(session.summary.session_id)
    elif state == "interrupted":
        service.mark_interrupted(session.summary.session_id)
    declined = service.decline_resume(session.summary.session_id)
    assert declined.summary.state == "abandoned"


def test_decline_completed_session_is_rejected(service):
    session = start(service, count=1, seed=32)
    answer_current_correctly(service, session.summary.session_id)
    with pytest.raises(QuizServiceError, match="不是可恢復"):
        service.decline_resume(session.summary.session_id)


def test_interruption_guard_marks_keyboard_interrupt(service):
    session = start(service, count=2, seed=40)
    with pytest.raises(KeyboardInterrupt):
        with service.interruption_guard(session.summary.session_id):
            raise KeyboardInterrupt
    assert service.get_session(session.summary.session_id).summary.state == "interrupted"


def test_interruption_guard_marks_unexpected_exception(service):
    session = start(service, count=2, seed=41)
    with pytest.raises(RuntimeError, match="boom"):
        with service.interruption_guard(session.summary.session_id):
            raise RuntimeError("boom")
    assert service.get_session(session.summary.session_id).summary.state == "interrupted"


def test_interruption_guard_preserves_original_error_when_persistence_fails(
    service, monkeypatch
):
    session = start(service, count=2, seed=42)

    def broken(_session_id):
        raise RuntimeError("storage failed")

    monkeypatch.setattr(service, "mark_interrupted_if_active", broken)
    with pytest.raises(ValueError, match="original"):
        with service.interruption_guard(session.summary.session_id):
            raise ValueError("original")


def test_active_session_left_by_hard_crash_is_still_discoverable(service):
    session = start(service, count=2, seed=43)
    assert session.summary.state == "active"
    assert session.summary.session_id in {
        summary.session_id for summary in service.list_resumable_sessions()
    }


def test_session_result_aggregates_question_types_and_wrong_items(service):
    session = start(service, count=3, seed=50)
    first = service.current_question(session.summary.session_id)
    assert first is not None
    service.submit_choice(
        session.summary.session_id,
        first.question_event_id,
        choice_id=first.question.correct_answer.answer_id,
    )
    second = service.current_question(session.summary.session_id)
    assert second is not None
    wrong = next(
        choice
        for choice in second.question.choices
        if choice.choice_id != second.question.correct_answer.answer_id
    )
    service.submit_choice(
        session.summary.session_id,
        second.question_event_id,
        choice_id=wrong.choice_id,
    )
    third = service.current_question(session.summary.session_id)
    assert third is not None
    service.skip_question(session.summary.session_id, third.question_event_id)

    result = service.session_result(session.summary.session_id)
    assert result.completed_count == 3
    assert result.accuracy == pytest.approx(1 / 3)
    assert sum(item.answered_count for item in result.question_types) == 3
    assert sum(item.correct_count for item in result.question_types) == 1
    assert sum(item.incorrect_count for item in result.question_types) == 1
    assert sum(item.skipped_count for item in result.question_types) == 1
    assert [event.result for event in result.incorrect_questions] == [
        "incorrect",
        "skipped",
    ]


def test_session_result_does_not_count_unanswered_questions(service):
    session = start(service, count=3, seed=51)
    answer_current_correctly(service, session.summary.session_id)
    result = service.session_result(session.summary.session_id)
    assert result.completed_count == 1
    assert sum(item.answered_count for item in result.question_types) == 1


def test_vocabulary_source_details_include_examples_aliases_and_sources(service):
    session = start(service, mode="vocabulary", count=1, seed=60)
    event = session.questions[0]
    details = service.question_source_details(
        session.summary.session_id, event.question_event_id
    )
    assert details.status == "available"
    assert details.source_kind == "vocabulary"
    assert details.title.startswith("語")
    assert details.reading.startswith("よみ")
    assert details.meanings and details.examples
    assert details.aliases and details.sources == ("測試來源",)


def test_mistake_source_details_include_original_context(service):
    session = start(service, mode="mistake", count=1, seed=61)
    event = session.questions[0]
    details = service.question_source_details(
        session.summary.session_id, event.question_event_id
    )
    assert details.status == "available"
    assert details.source_kind == "mistake"
    assert details.prompt == "正しいものを選んでください。"
    assert details.reason == "助詞選擇錯誤"
    assert details.before == "私は"
    assert details.after == "を選びます。"
    assert details.linked_entry_keys == ("vocab:語1",)


def test_deleted_source_returns_missing_without_losing_saved_question(tmp_path):
    reader = FakeReader(entries=tuple(vocab(index) for index in range(1, 5)))
    quiz = QuizService(reader, QuizSessionStore(tmp_path / "quiz.db"))
    session = start(quiz, mode="vocabulary", count=1, seed=62)
    event = session.questions[0]
    reader.entries = ()
    details = quiz.question_source_details(session.summary.session_id, event.question_event_id)
    assert details.status == "missing"
    assert quiz.get_session(session.summary.session_id).questions[0] == event


def test_source_read_failure_returns_unavailable_without_breaking_history(tmp_path):
    reader = FakeReader(entries=tuple(vocab(index) for index in range(1, 5)))
    quiz = QuizService(reader, QuizSessionStore(tmp_path / "quiz.db"))
    session = start(quiz, mode="vocabulary", count=1, seed=63)
    event = session.questions[0]
    reader.unavailable = True
    details = quiz.question_source_details(session.summary.session_id, event.question_event_id)
    assert details.status == "unavailable"
    assert "core read failed" in details.message
    assert quiz.get_session(session.summary.session_id).summary.state == "active"


def test_debug_cli_resumable_continue_decline_and_result(service, capsys):
    session = start(service, count=2, seed=70)
    service.pause_session(session.summary.session_id)

    assert run(["resumable"], service=service) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["session_id"] == session.summary.session_id

    assert run(["continue", session.summary.session_id], service=service) == 0
    continued = json.loads(capsys.readouterr().out)
    assert continued["summary"]["state"] == "active"

    answer_current_correctly(service, session.summary.session_id)
    assert run(["result", session.summary.session_id], service=service) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["summary"]["answered_count"] == 1

    assert run(["decline", session.summary.session_id], service=service) == 0
    declined = json.loads(capsys.readouterr().out)
    assert declined["summary"]["state"] == "abandoned"


def test_debug_cli_details_outputs_current_source_metadata(service, capsys):
    session = start(service, mode="vocabulary", count=1, seed=71)
    event = session.questions[0]
    assert run(
        ["details", session.summary.session_id, event.question_event_id],
        service=service,
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "available"
    assert payload["examples"]


def test_debug_cli_keyboard_interrupt_marks_active_session(
    service, monkeypatch
):
    session = start(service, count=2, seed=72)

    def interrupted(_session_id):
        raise KeyboardInterrupt

    monkeypatch.setattr(service, "current_question", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(["next", session.summary.session_id], service=service)
    assert service.get_session(session.summary.session_id).summary.state == "interrupted"


def test_debug_cli_expected_answer_error_keeps_session_active(service):
    session = start(service, count=2, seed=73)
    event = service.current_question(session.summary.session_id)
    assert event is not None
    with pytest.raises(QuizAnswerError):
        run(
            ["answer", session.summary.session_id, event.question_event_id, "missing"],
            service=service,
        )
    assert service.get_session(session.summary.session_id).summary.state == "active"


def test_debug_cli_unexpected_exception_marks_active_session(
    service, monkeypatch
):
    session = start(service, count=2, seed=74)

    def boom(_session_id):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(service, "current_question", boom)
    with pytest.raises(RuntimeError, match="unexpected"):
        run(["next", session.summary.session_id], service=service)
    assert service.get_session(session.summary.session_id).summary.state == "interrupted"


def _create_v1_database(path: Path) -> None:
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            PRAGMA user_version=1;
            CREATE TABLE quiz_sessions (
                session_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                requested_count INTEGER NOT NULL,
                question_count INTEGER NOT NULL,
                state TEXT NOT NULL,
                answered_count INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                incorrect_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                details_pruned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT
            );
            CREATE TABLE quiz_question_events (
                question_event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                question_type TEXT NOT NULL,
                generator_version TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_key TEXT NOT NULL,
                prompt TEXT NOT NULL,
                choices_json TEXT NOT NULL,
                correct_answer_json TEXT NOT NULL,
                user_answer_json TEXT,
                result TEXT,
                answered_at TEXT
            );
            CREATE INDEX idx_quiz_sessions_updated
                ON quiz_sessions(updated_at DESC, session_id);
            CREATE INDEX idx_quiz_question_session_position
                ON quiz_question_events(session_id, position);
            CREATE INDEX idx_quiz_question_session_result
                ON quiz_question_events(session_id, result);
            """
        )
        conn.execute(
            """
            INSERT INTO quiz_sessions (
                session_id, mode, requested_count, question_count, state,
                answered_count, correct_count, incorrect_count, skipped_count,
                details_pruned, created_at, updated_at, started_at, ended_at
            ) VALUES (
                'quiz-session:v1', 'mixed', 2, 2, 'completed',
                2, 1, 0, 1,
                0, '2026-07-24T10:00:00+08:00',
                '2026-07-24T10:01:00+08:00',
                '2026-07-24T10:00:00+08:00',
                '2026-07-24T10:01:00+08:00'
            )
            """
        )
        rows = (
            (
                "quiz-question:v1-1",
                1,
                "vocab_reading_true_false",
                "correct",
                '{"answer_id":"true","text":"正確"}',
            ),
            (
                "quiz-question:v1-2",
                2,
                "mistake_multiple_choice",
                "skipped",
                None,
            ),
        )
        for event_id, position, question_type, result, user_answer_json in rows:
            conn.execute(
                """
                INSERT INTO quiz_question_events (
                    question_event_id, session_id, position, question_type,
                    generator_version, source_kind, source_key, prompt,
                    choices_json, correct_answer_json, user_answer_json,
                    result, answered_at
                ) VALUES (?, 'quiz-session:v1', ?, ?, 'quiz-v1-generator-1',
                          'vocabulary', 'vocab:語1', 'prompt', ?, ?, ?, ?,
                          '2026-07-24T10:01:00+08:00')
                """,
                (
                    event_id,
                    position,
                    question_type,
                    '[{"choice_id":"true","text":"正確"},'
                    '{"choice_id":"false","text":"錯誤"}]',
                    '{"answer_id":"true","text":"正確"}',
                    user_answer_json,
                    result,
                ),
            )


def test_schema_v2_migrates_v1_and_backfills_question_type_summaries(tmp_path):
    import sqlite3

    path = tmp_path / "quiz.db"
    _create_v1_database(path)
    store = QuizSessionStore(path)
    session = store.get_session("quiz-session:v1")
    observed = [
        (item.question_type, item.correct_count, item.skipped_count)
        for item in session.summary.question_type_summaries
    ]
    assert observed == [
        ("mistake_multiple_choice", 0, 1),
        ("vocab_reading_true_false", 1, 0),
    ]
    with sqlite3.connect(path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(quiz_sessions)")
        }
    assert version == 2
    assert "question_type_summary_json" in columns


def test_schema_v2_migration_is_transactional(tmp_path):
    import sqlite3

    path = tmp_path / "quiz.db"
    _create_v1_database(path)

    class FailingV2Store(QuizSessionStore):
        def _apply_schema_v2(self, conn):
            super()._apply_schema_v2(conn)
            raise RuntimeError("fail after v2 migration")

    from jpnote_app.quiz.session_store import QuizStorageUnavailableError

    with pytest.raises(QuizStorageUnavailableError, match="migration"):
        FailingV2Store(path)
    with sqlite3.connect(path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(quiz_sessions)")
        }
    assert version == 1
    assert "question_type_summary_json" not in columns


def test_question_type_summary_updates_atomically_per_answer(service):
    session = start(service, count=2, seed=80)
    first = service.current_question(session.summary.session_id)
    assert first is not None
    answer_current_correctly(service, session.summary.session_id)
    after_first = service.get_session(session.summary.session_id).summary
    assert sum(item.answered_count for item in after_first.question_type_summaries) == 1
    second = service.current_question(session.summary.session_id)
    assert second is not None
    service.skip_question(session.summary.session_id, second.question_event_id)
    after_second = service.get_session(session.summary.session_id).summary
    assert sum(item.answered_count for item in after_second.question_type_summaries) == 2
    assert sum(item.correct_count for item in after_second.question_type_summaries) == 1
    assert sum(item.skipped_count for item in after_second.question_type_summaries) == 1


def test_pruning_details_keeps_permanent_question_type_summary(service):
    session = start(service, count=2, seed=81)
    answer_current_correctly(service, session.summary.session_id)
    second = service.current_question(session.summary.session_id)
    assert second is not None
    service.skip_question(session.summary.session_id, second.question_event_id)
    before = service.session_result(session.summary.session_id)
    assert before.question_types

    pruned = service.session_store.prune_details(cap_bytes=0)
    assert session.summary.session_id in pruned.pruned_session_ids
    after = service.session_result(session.summary.session_id)
    assert not after.details_available
    assert after.incorrect_questions == ()
    assert after.question_types == before.question_types
    assert after.summary.accuracy == before.summary.accuracy


def test_history_export_includes_type_summary_after_details_pruned(service):
    session = start(service, count=1, seed=82)
    answer_current_correctly(service, session.summary.session_id)
    service.session_store.prune_details(cap_bytes=0)
    payload = service.session_store.export_history(
        session_id=session.summary.session_id
    )
    exported = payload["sessions"][0]
    assert exported["summary"]["question_type_summaries"]
    assert exported["details"]["status"] == "pruned"


def test_corrupt_question_type_summary_fails_closed(tmp_path):
    import sqlite3

    quiz = QuizService(
        FakeReader(entries=tuple(vocab(index) for index in range(1, 5))),
        QuizSessionStore(tmp_path / "quiz.db"),
    )
    session = start(quiz, mode="vocabulary", count=1, seed=83)
    answer_current_correctly(quiz, session.summary.session_id)
    with sqlite3.connect(quiz.session_store.path) as conn:
        conn.execute(
            "UPDATE quiz_sessions SET question_type_summary_json='not-json' WHERE session_id=?",
            (session.summary.session_id,),
        )
    from jpnote_app.quiz.session_store import QuizStorageUnavailableError

    with pytest.raises(QuizStorageUnavailableError, match="summary"):
        quiz.get_session(session.summary.session_id)
