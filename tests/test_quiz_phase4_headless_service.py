from __future__ import annotations

import json
from pathlib import Path

import pytest

from jpnote_app.quiz.debug_cli import run
from jpnote_app.quiz.service import QuizAnswerError, QuizService
from jpnote_app.quiz.session_store import QuizSessionStore
from jpnote_app.study_sources import (
    AttemptCapabilities,
    AttemptReplaySource,
    ChoiceSnapshot,
    EntryCapabilities,
    EntrySnapshot,
    ReorderPartSnapshot,
    SenseSnapshot,
    SourceCatalog,
)


def vocab(number: int, *, meaning: str | None = None) -> EntrySnapshot:
    return EntrySnapshot(
        key=f"vocab:語{number}",
        entry_type="vocabulary",
        display=f"語{number}",
        reading=f"よみ{number}",
        romaji="",
        level="N3",
        review_group="",
        aliases=(),
        senses=(SenseSnapshot(meaning=meaning or f"意思{number}"),),
        sources=("測試來源",),
        capabilities=EntryCapabilities(True, True, False, False),
    )


def multiple_choice_attempt(number: int = 1) -> AttemptReplaySource:
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
        reason="",
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


def reorder_attempt() -> AttemptReplaySource:
    return AttemptReplaySource(
        event_key="attempt:reorder",
        result="wrong",
        attempt_date="2026-07-24",
        source="錯題來源",
        section="第二回",
        question="1",
        question_type="reorder_4",
        prompt="正しい順番に並べてください。",
        user_answer="",
        correct_answer="",
        reason="",
        before="",
        after="",
        parts=(
            ReorderPartSnapshot(1, "私"),
            ReorderPartSnapshot(2, "は"),
            ReorderPartSnapshot(3, "学生"),
            ReorderPartSnapshot(4, "です"),
        ),
        user_order=(2, 1, 4, 3),
        correct_order=(1, 2, 3, 4),
        options=(),
        linked_entry_keys=(),
        linked_levels=("N4",),
        recorded_at="2026-07-24T12:00:00+08:00",
        data_warnings=(),
        capabilities=AttemptCapabilities(
            has_prompt=True,
            has_correct_answer=False,
            has_choices=False,
            has_reorder_parts=True,
            has_sentence_context=False,
            structure_valid=True,
        ),
    )


class FakeReader:
    def __init__(self, *, entries=(), attempts=()):
        self.entries = tuple(entries)
        self.attempts = tuple(attempts)
        self.entry_calls: list[dict[str, object]] = []
        self.attempt_calls: list[dict[str, object]] = []

    def list_entry_snapshots(self, **kwargs):
        self.entry_calls.append(kwargs)
        levels = set(kwargs.get("levels") or ())
        sources = set(kwargs.get("sources") or ())
        return tuple(
            entry
            for entry in self.entries
            if (not levels or entry.level in levels)
            and (not sources or sources.intersection(entry.sources))
        )

    def get_entry_snapshot(self, key):
        return next((entry for entry in self.entries if entry.key == key), None)

    def list_attempt_replay_sources(self, **kwargs):
        self.attempt_calls.append(kwargs)
        levels = set(kwargs.get("levels") or ())
        sources = set(kwargs.get("sources") or ())
        return tuple(
            attempt
            for attempt in self.attempts
            if (not levels or levels.intersection(attempt.linked_levels))
            and (not sources or attempt.source in sources)
        )

    def get_attempt_replay_source(self, event_key):
        return next(
            (attempt for attempt in self.attempts if attempt.event_key == event_key),
            None,
        )

    def source_catalog(self):
        return SourceCatalog(
            len(self.entries),
            len(self.attempts),
            tuple(sorted({entry.level for entry in self.entries if entry.level})),
            tuple(
                sorted(
                    {source for entry in self.entries for source in entry.sources}
                    | {attempt.source for attempt in self.attempts}
                )
            ),
        )


@pytest.fixture
def service(tmp_path: Path) -> QuizService:
    reader = FakeReader(
        entries=tuple(vocab(index) for index in range(1, 7)),
        attempts=(multiple_choice_attempt(), reorder_attempt()),
    )
    return QuizService(reader, QuizSessionStore(tmp_path / "quiz.db"))


def test_vocabulary_plan_reads_only_vocabulary_sources(tmp_path):
    reader = FakeReader(entries=tuple(vocab(index) for index in range(1, 5)))
    quiz = QuizService(reader, QuizSessionStore(tmp_path / "quiz.db"))
    plan = quiz.plan_session(
        mode="vocabulary",
        requested_count=3,
        levels=("N3",),
        sources=("測試來源",),
        seed=1,
    )
    assert len(plan.questions) == 3
    assert reader.entry_calls == [
        {
            "entry_types": ("vocabulary",),
            "levels": ("N3",),
            "sources": ("測試來源",),
        }
    ]
    assert reader.attempt_calls == []


def test_mistake_plan_reads_only_attempt_sources(tmp_path):
    reader = FakeReader(attempts=(multiple_choice_attempt(),))
    quiz = QuizService(reader, QuizSessionStore(tmp_path / "quiz.db"))
    plan = quiz.plan_session(mode="mistake", requested_count=1, seed=2)
    assert len(plan.questions) == 1
    assert reader.entry_calls == []
    assert len(reader.attempt_calls) == 1


def test_mixed_plan_passes_filters_to_both_source_kinds(tmp_path):
    reader = FakeReader(entries=(vocab(1),), attempts=(multiple_choice_attempt(),))
    quiz = QuizService(reader, QuizSessionStore(tmp_path / "quiz.db"))
    quiz.plan_session(
        mode="mixed",
        requested_count=2,
        levels=("N3",),
        sources=("測試來源",),
        seed=3,
    )
    assert reader.entry_calls[0]["levels"] == ("N3",)
    assert reader.attempt_calls[0]["levels"] == ("N3",)
    assert reader.entry_calls[0]["sources"] == ("測試來源",)
    assert reader.attempt_calls[0]["sources"] == ("測試來源",)


def test_no_safe_questions_does_not_create_session(tmp_path):
    store = QuizSessionStore(tmp_path / "quiz.db")
    result = QuizService(FakeReader(), store).start_session(
        mode="mixed", requested_count=10
    )
    assert result.status == "no_safe_questions"
    assert not result.started
    assert store.list_recent_sessions() == ()


def test_shortage_requires_explicit_confirmation(tmp_path):
    store = QuizSessionStore(tmp_path / "quiz.db")
    quiz = QuizService(FakeReader(attempts=(reorder_attempt(),)), store)
    result = quiz.start_session(mode="mistake", requested_count=10, seed=4)
    assert result.requires_confirmation
    assert result.plan.report.selected_count == 1
    assert store.list_recent_sessions() == ()


def test_allow_shortage_persists_only_safe_questions(tmp_path):
    quiz = QuizService(
        FakeReader(attempts=(reorder_attempt(),)),
        QuizSessionStore(tmp_path / "quiz.db"),
    )
    result = quiz.start_session(
        mode="mistake",
        requested_count=10,
        seed=5,
        allow_shortage=True,
    )
    assert result.started
    assert result.session is not None
    assert result.session.summary.requested_count == 10
    assert result.session.summary.question_count == 1


def test_start_persists_exact_planned_question_snapshots(service):
    plan = service.plan_session(mode="mixed", requested_count=5, seed="same")
    result = service.start_session(
        mode="mixed", requested_count=5, seed="same", allow_shortage=True
    )
    assert result.session is not None
    persisted = tuple(event.question for event in result.session.questions)
    assert persisted == plan.questions


def _start_single_mcq(tmp_path: Path) -> tuple[QuizService, object]:
    quiz = QuizService(
        FakeReader(attempts=(multiple_choice_attempt(),)),
        QuizSessionStore(tmp_path / "quiz.db"),
    )
    result = quiz.start_session(mode="mistake", requested_count=1, seed=7)
    assert result.session is not None
    question = result.session.questions[0]
    return quiz, question


def test_submit_choice_determines_correctness_from_snapshot(tmp_path):
    quiz, event = _start_single_mcq(tmp_path)
    correct_id = event.question.correct_answer.answer_id
    feedback = quiz.submit_choice(
        event.session_id, event.question_event_id, choice_id=correct_id
    )
    assert feedback.correct
    assert feedback.question.result == "correct"
    assert feedback.user_answer == feedback.correct_answer
    assert feedback.session.summary.state == "completed"


def test_submit_choice_records_wrong_answer_without_caller_correct_flag(tmp_path):
    quiz, event = _start_single_mcq(tmp_path)
    wrong = next(
        choice
        for choice in event.question.choices
        if choice.choice_id != event.question.correct_answer.answer_id
    )
    feedback = quiz.submit_choice(
        event.session_id, event.question_event_id, choice_id=wrong.choice_id
    )
    assert not feedback.correct
    assert feedback.question.result == "incorrect"
    assert feedback.user_answer.answer_id == wrong.choice_id


def test_unknown_choice_is_rejected_without_persisting_answer(tmp_path):
    quiz, event = _start_single_mcq(tmp_path)
    with pytest.raises(QuizAnswerError, match="唯一選項"):
        quiz.submit_choice(
            event.session_id, event.question_event_id, choice_id="missing"
        )
    assert quiz.get_session(event.session_id).summary.answered_count == 0


def test_stale_question_event_is_rejected(tmp_path):
    quiz, event = _start_single_mcq(tmp_path)
    with pytest.raises(QuizAnswerError, match="目前下一題"):
        quiz.submit_choice(event.session_id, "quiz-question:stale", choice_id="1")


def _start_reorder(tmp_path: Path) -> tuple[QuizService, object]:
    quiz = QuizService(
        FakeReader(attempts=(reorder_attempt(),)),
        QuizSessionStore(tmp_path / "quiz.db"),
    )
    result = quiz.start_session(mode="mistake", requested_count=1, seed=8)
    assert result.session is not None
    event = result.session.questions[0]
    assert event.question.question_type == "mistake_reorder_4"
    return quiz, event


def test_reorder_answer_builds_stable_ordered_snapshot(tmp_path):
    quiz, event = _start_reorder(tmp_path)
    correct_ids = event.question.correct_answer.answer_id.split("-")
    feedback = quiz.submit_reorder(
        event.session_id,
        event.question_event_id,
        ordered_choice_ids=correct_ids,
    )
    assert feedback.correct
    assert feedback.user_answer.answer_id == "1-2-3-4"
    assert feedback.user_answer.text == "私は学生です"


@pytest.mark.parametrize(
    "submitted",
    [
        ("1", "2", "3"),
        ("1", "2", "2", "4"),
        ("1", "2", "3", "missing"),
    ],
)
def test_invalid_reorder_answers_are_rejected(tmp_path, submitted):
    quiz, event = _start_reorder(tmp_path)
    with pytest.raises(QuizAnswerError):
        quiz.submit_reorder(
            event.session_id,
            event.question_event_id,
            ordered_choice_ids=submitted,
        )
    assert quiz.get_session(event.session_id).summary.answered_count == 0


def test_single_choice_api_rejects_reorder_question(tmp_path):
    quiz, event = _start_reorder(tmp_path)
    with pytest.raises(QuizAnswerError, match="submit_reorder"):
        quiz.submit_choice(
            event.session_id,
            event.question_event_id,
            choice_id="1",
        )


def test_skip_returns_correct_answer_and_counts_as_wrong(tmp_path):
    quiz, event = _start_single_mcq(tmp_path)
    feedback = quiz.skip_question(event.session_id, event.question_event_id)
    assert feedback.skipped
    assert not feedback.correct
    assert feedback.user_answer is None
    assert feedback.correct_answer == event.question.correct_answer
    assert feedback.session.summary.skipped_count == 1
    assert feedback.session.summary.effective_incorrect_count == 1


def test_pause_resume_uses_same_remaining_snapshot(service):
    result = service.start_session(mode="mixed", requested_count=4, seed=9)
    assert result.session is not None
    before = result.session.remaining_questions
    paused = service.pause_session(result.session.summary.session_id)
    assert paused.summary.state == "paused"
    resumed = service.resume_session(result.session.summary.session_id)
    assert resumed.summary.state == "active"
    assert resumed.remaining_questions == before


def test_debug_cli_plan_outputs_json_without_saving(service, capsys):
    exit_code = run(
        ["plan", "--mode", "vocabulary", "--count", "2", "--seed", "10"],
        service=service,
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["selected_count"] == 2
    assert service.session_store.list_recent_sessions() == ()


def test_debug_cli_shortage_uses_distinct_exit_code(tmp_path, capsys):
    quiz = QuizService(
        FakeReader(attempts=(reorder_attempt(),)),
        QuizSessionStore(tmp_path / "quiz.db"),
    )
    exit_code = run(
        ["start", "--mode", "mistake", "--count", "10"],
        service=quiz,
    )
    assert exit_code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "confirmation_required"
    assert quiz.session_store.list_recent_sessions() == ()


def test_debug_cli_can_start_show_and_answer(tmp_path, capsys):
    quiz = QuizService(
        FakeReader(attempts=(multiple_choice_attempt(),)),
        QuizSessionStore(tmp_path / "quiz.db"),
    )
    assert run(
        ["start", "--mode", "mistake", "--count", "1", "--seed", "11"],
        service=quiz,
    ) == 0
    start_payload = json.loads(capsys.readouterr().out)
    session_id = start_payload["session"]["summary"]["session_id"]
    event = quiz.current_question(session_id)
    assert event is not None

    assert run(["next", session_id], service=quiz) == 0
    next_payload = json.loads(capsys.readouterr().out)
    assert next_payload["question_event_id"] == event.question_event_id

    assert run(
        [
            "answer",
            session_id,
            event.question_event_id,
            event.question.correct_answer.answer_id,
        ],
        service=quiz,
    ) == 0
    answer_payload = json.loads(capsys.readouterr().out)
    assert answer_payload["correct"] is True
    assert answer_payload["session"]["summary"]["state"] == "completed"
