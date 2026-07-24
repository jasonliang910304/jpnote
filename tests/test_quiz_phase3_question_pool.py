from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError

import pytest

from jpnote_app.quiz.question_pool import QuestionPoolBuilder
from jpnote_app.study_sources import (
    AttemptCapabilities,
    AttemptReplaySource,
    ChoiceSnapshot,
    EntryCapabilities,
    EntrySnapshot,
    ReorderPartSnapshot,
    SenseSnapshot,
)


def vocab(
    number: int,
    *,
    meaning: str | None = None,
    reading: str | None = None,
    display: str | None = None,
) -> EntrySnapshot:
    meaning = meaning if meaning is not None else f"意思{number}"
    reading = reading if reading is not None else f"よみ{number}"
    senses = (SenseSnapshot(meaning=meaning),) if meaning else ()
    return EntrySnapshot(
        key=f"vocab:語{number}",
        entry_type="vocabulary",
        display=display or f"語{number}",
        reading=reading,
        romaji="",
        level="N3",
        review_group="",
        aliases=(),
        senses=senses,
        sources=("測試",),
        capabilities=EntryCapabilities(
            has_meaning=bool(meaning),
            has_reading=bool(reading),
            has_example=False,
            has_aliases=False,
        ),
    )


def grammar() -> EntrySnapshot:
    return EntrySnapshot(
        key="grammar:ので",
        entry_type="grammar",
        display="ので",
        reading="",
        romaji="",
        level="N4",
        review_group="",
        aliases=(),
        senses=(SenseSnapshot(meaning="因為"),),
        sources=("測試",),
    )


def multiple_choice_attempt(number: int, *, valid: bool = True) -> AttemptReplaySource:
    options = (
        ChoiceSnapshot(option_id=1, text="選項甲"),
        ChoiceSnapshot(option_id=2, text="選項乙"),
        ChoiceSnapshot(option_id=3, text="選項丙"),
        ChoiceSnapshot(option_id=4, text="選項丁"),
    )
    return AttemptReplaySource(
        event_key=f"attempt:mcq-{number}",
        result="wrong",
        attempt_date="2026-07-24",
        source="測試",
        section="第一回",
        question=f"問題{number}",
        question_type="multiple_choice",
        prompt=f"請選出正確答案 {number}",
        user_answer="1",
        correct_answer="2",
        reason="",
        before="私は",
        after="を選びます。",
        parts=(),
        user_order=(),
        correct_order=(),
        options=options,
        linked_entry_keys=(f"vocab:語{number}",),
        linked_levels=("N3",),
        recorded_at="2026-07-24T12:00:00+08:00",
        data_warnings=() if valid else ("broken",),
        capabilities=AttemptCapabilities(
            has_prompt=valid,
            has_correct_answer=valid,
            has_choices=valid,
            has_reorder_parts=False,
            has_sentence_context=valid,
            structure_valid=valid,
        ),
    )


def reorder_attempt(number: int) -> AttemptReplaySource:
    return AttemptReplaySource(
        event_key=f"attempt:reorder-{number}",
        result="wrong",
        attempt_date="2026-07-24",
        source="測試",
        section="第二回",
        question=f"重組{number}",
        question_type="reorder_4",
        prompt="請排列句子",
        user_answer="",
        correct_answer="",
        reason="",
        before="",
        after="",
        parts=tuple(
            ReorderPartSnapshot(part_id=index, text=text)
            for index, text in enumerate(("私", "は", "学生", "です"), start=1)
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


def identities(plan):
    return tuple(question.identity_tuple() for question in plan.questions)


def truth_answers(plan) -> list[str]:
    answers: list[str] = []
    for question in plan.questions:
        if {choice.choice_id for choice in question.choices} == {"true", "false"}:
            answers.append(question.correct_answer.answer_id)
    return answers


def test_rejects_unknown_mode_and_invalid_count():
    builder = QuestionPoolBuilder(seed=1)
    with pytest.raises(ValueError, match="mode"):
        builder.build(mode="grammar", requested_count=10)
    for value in (0, -1, False, 1.5):
        with pytest.raises(ValueError, match="requested_count"):
            builder.build(mode="vocabulary", requested_count=value)


def test_vocabulary_mode_uses_unique_sources_before_alternate_types():
    entries = tuple(vocab(index) for index in range(1, 7))
    plan = QuestionPoolBuilder(seed=3).build(
        mode="vocabulary",
        requested_count=6,
        entries=entries,
    )
    assert len(plan.questions) == 6
    assert len({question.source_key for question in plan.questions}) == 6


def test_vocabulary_mode_may_reuse_source_after_unique_sources_exhausted():
    entries = tuple(vocab(index) for index in range(1, 5))
    plan = QuestionPoolBuilder(seed=4).build(
        mode="vocabulary",
        requested_count=8,
        entries=entries,
    )
    assert len(plan.questions) == 8
    assert len({question.source_key for question in plan.questions[:4]}) == 4
    assert len({question.source_key for question in plan.questions}) < 8
    assert len(set(identities(plan))) == 8


def test_grammar_entries_are_not_vocabulary_sources():
    plan = QuestionPoolBuilder(seed=5).build(
        mode="vocabulary",
        requested_count=3,
        entries=(grammar(),),
    )
    assert plan.questions == ()
    assert plan.report.vocabulary_source_count == 0
    assert plan.report.has_shortage


def test_duplicate_entry_keys_are_collapsed():
    source = vocab(1)
    plan = QuestionPoolBuilder(seed=6).build(
        mode="vocabulary",
        requested_count=2,
        entries=(source, source),
    )
    assert plan.report.vocabulary_source_count == 1


def test_mistake_mode_replays_multiple_choice_and_reorder():
    attempts = (multiple_choice_attempt(1), reorder_attempt(2))
    plan = QuestionPoolBuilder(seed=7).build(
        mode="mistake",
        requested_count=2,
        attempts=attempts,
    )
    assert {question.source_key for question in plan.questions} == {
        "attempt:mcq-1",
        "attempt:reorder-2",
    }
    assert {question.source_kind for question in plan.questions} == {"mistake"}


def test_malformed_attempt_is_skipped_and_reported():
    plan = QuestionPoolBuilder(seed=8).build(
        mode="mistake",
        requested_count=3,
        attempts=(multiple_choice_attempt(1, valid=False),),
    )
    assert plan.questions == ()
    assert plan.report.skipped_mistake_source_count == 1
    assert plan.report.available_count == 0


def test_duplicate_attempt_event_keys_are_collapsed():
    source = multiple_choice_attempt(1)
    plan = QuestionPoolBuilder(seed=9).build(
        mode="mistake",
        requested_count=2,
        attempts=(source, source),
    )
    assert plan.report.mistake_source_count == 1


def test_mixed_mode_includes_both_source_kinds_when_possible():
    plan = QuestionPoolBuilder(seed=10).build(
        mode="mixed",
        requested_count=2,
        entries=tuple(vocab(index) for index in range(1, 5)),
        attempts=(multiple_choice_attempt(1),),
    )
    assert {question.source_kind for question in plan.questions} == {
        "vocabulary",
        "mistake",
    }


def test_mixed_mode_does_not_require_an_unsafe_kind():
    plan = QuestionPoolBuilder(seed=11).build(
        mode="mixed",
        requested_count=3,
        entries=tuple(vocab(index) for index in range(1, 5)),
        attempts=(multiple_choice_attempt(1, valid=False),),
    )
    assert len(plan.questions) == 3
    assert {question.source_kind for question in plan.questions} == {"vocabulary"}


def test_linked_vocabulary_and_mistake_can_both_appear():
    entry = vocab(1)
    attempt = multiple_choice_attempt(1)
    plan = QuestionPoolBuilder(seed=12).build(
        mode="mixed",
        requested_count=2,
        entries=(entry,),
        attempts=(attempt,),
    )
    assert {question.source_kind for question in plan.questions} == {
        "vocabulary",
        "mistake",
    }


def test_shortage_report_exposes_requested_and_safe_available_counts():
    plan = QuestionPoolBuilder(seed=13).build(
        mode="mistake",
        requested_count=20,
        attempts=(reorder_attempt(1),),
    )
    assert plan.report.requested_count == 20
    assert plan.report.available_count == 1
    assert plan.report.selected_count == 1
    assert plan.report.shortage_count == 19
    assert plan.report.has_shortage
    assert plan.report.can_start


def test_empty_pool_cannot_start():
    plan = QuestionPoolBuilder(seed=14).build(
        mode="mixed",
        requested_count=10,
    )
    assert not plan.report.can_start
    assert plan.report.shortage_count == 10


def test_report_counts_available_questions_by_source_kind():
    plan = QuestionPoolBuilder(seed=15).build(
        mode="mixed",
        requested_count=1,
        entries=tuple(vocab(index) for index in range(1, 5)),
        attempts=(reorder_attempt(1),),
    )
    assert plan.report.available_count == (
        plan.report.vocabulary_available_count
        + plan.report.mistake_available_count
    )
    assert plan.report.vocabulary_available_count > 0
    assert plan.report.mistake_available_count == 1


def test_same_seed_reproduces_exact_question_snapshots():
    entries = tuple(vocab(index) for index in range(1, 7))
    attempts = (multiple_choice_attempt(1), reorder_attempt(2))
    first = QuestionPoolBuilder(seed="repeatable").build(
        mode="mixed",
        requested_count=8,
        entries=entries,
        attempts=attempts,
    )
    second = QuestionPoolBuilder(seed="repeatable").build(
        mode="mixed",
        requested_count=8,
        entries=entries,
        attempts=attempts,
    )
    assert first == second


def test_same_seed_is_stable_when_input_order_changes():
    entries = tuple(vocab(index) for index in range(1, 7))
    attempts = (multiple_choice_attempt(1), reorder_attempt(2))
    first = QuestionPoolBuilder(seed=16).build(
        mode="mixed",
        requested_count=8,
        entries=entries,
        attempts=attempts,
    )
    second = QuestionPoolBuilder(seed=16).build(
        mode="mixed",
        requested_count=8,
        entries=reversed(entries),
        attempts=reversed(attempts),
    )
    assert first == second


def test_selected_questions_never_repeat_exact_snapshot():
    entries = tuple(vocab(index) for index in range(1, 5))
    attempts = (multiple_choice_attempt(1), multiple_choice_attempt(2))
    plan = QuestionPoolBuilder(seed=17).build(
        mode="mixed",
        requested_count=50,
        entries=entries,
        attempts=attempts,
    )
    assert len(identities(plan)) == len(set(identities(plan)))
    assert len(plan.questions) == plan.report.available_count


def test_true_false_soft_constraint_avoids_extreme_ratio_when_alternatives_exist():
    # Reading-only entries generate true/false variants but no meaning MCQs.
    entries = tuple(
        vocab(index, meaning="", reading=f"よみ{index}")
        for index in range(1, 9)
    )
    plan = QuestionPoolBuilder(seed=18).build(
        mode="vocabulary",
        requested_count=12,
        entries=entries,
    )
    answers = truth_answers(plan)
    assert len(answers) >= 5
    counts = Counter(answers)
    assert set(counts) == {"true", "false"}
    assert max(counts.values()) / len(answers) <= 0.80


def test_requested_one_in_mixed_mode_has_no_forced_quota():
    plan = QuestionPoolBuilder(seed=19).build(
        mode="mixed",
        requested_count=1,
        entries=tuple(vocab(index) for index in range(1, 5)),
        attempts=(multiple_choice_attempt(1),),
    )
    assert len(plan.questions) == 1
    assert plan.questions[0].source_kind in {"vocabulary", "mistake"}


def test_question_plan_is_immutable_tuple_data():
    plan = QuestionPoolBuilder(seed=20).build(
        mode="mistake",
        requested_count=1,
        attempts=(reorder_attempt(1),),
    )
    assert isinstance(plan.questions, tuple)
    with pytest.raises(FrozenInstanceError):
        plan.questions += plan.questions
