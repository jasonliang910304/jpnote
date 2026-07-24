"""Immutable Quiz session and question history models.

These models belong to the optional Quiz extension.  They intentionally carry
stable public source identifiers and exact generated-question snapshots, never
core SQLite row IDs or references to mutable core records.
"""
from __future__ import annotations

from dataclasses import dataclass

SESSION_STATES = frozenset(
    {"active", "paused", "interrupted", "completed", "abandoned"}
)
TERMINAL_SESSION_STATES = frozenset({"completed", "abandoned"})
QUESTION_RESULTS = frozenset({"correct", "incorrect", "skipped"})
SOURCE_KINDS = frozenset({"vocabulary", "mistake"})


class QuizValidationError(ValueError):
    """Raised when a generated question or session payload is invalid."""


@dataclass(frozen=True, slots=True)
class QuestionChoiceSnapshot:
    choice_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.choice_id.strip():
            raise QuizValidationError("choice_id 不可為空")
        if not self.text.strip():
            raise QuizValidationError("選項文字不可為空")


@dataclass(frozen=True, slots=True)
class AnswerSnapshot:
    answer_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.answer_id.strip() and not self.text.strip():
            raise QuizValidationError("答案 ID 與文字不可同時為空")


@dataclass(frozen=True, slots=True)
class GeneratedQuestionSnapshot:
    """Exact immutable output produced by a future Quiz generator."""

    question_type: str
    generator_version: str
    source_kind: str
    source_key: str
    prompt: str
    choices: tuple[QuestionChoiceSnapshot, ...]
    correct_answer: AnswerSnapshot

    def __post_init__(self) -> None:
        if not self.question_type.strip():
            raise QuizValidationError("question_type 不可為空")
        if not self.generator_version.strip():
            raise QuizValidationError("generator_version 不可為空")
        if self.source_kind not in SOURCE_KINDS:
            raise QuizValidationError(f"不支援的 source_kind：{self.source_kind}")
        if not self.source_key.strip():
            raise QuizValidationError("source_key 不可為空")
        if not self.prompt.strip():
            raise QuizValidationError("題目 prompt 不可為空")

        choice_ids = [choice.choice_id for choice in self.choices]
        choice_texts = [choice.text for choice in self.choices]
        if len(choice_ids) != len(set(choice_ids)):
            raise QuizValidationError("同一題不可有重複 choice_id")
        if len(choice_texts) != len(set(choice_texts)):
            raise QuizValidationError("同一題不可有重複選項文字")

    def identity_tuple(self) -> tuple[object, ...]:
        """Stable duplicate guard for one generated session."""

        return (
            self.question_type,
            self.generator_version,
            self.source_kind,
            self.source_key,
            self.prompt,
            tuple((choice.choice_id, choice.text) for choice in self.choices),
            self.correct_answer.answer_id,
            self.correct_answer.text,
        )


@dataclass(frozen=True, slots=True)
class QuestionEventSnapshot:
    question_event_id: str
    session_id: str
    position: int
    question: GeneratedQuestionSnapshot
    user_answer: AnswerSnapshot | None = None
    result: str | None = None
    answered_at: str | None = None

    @property
    def answered(self) -> bool:
        return self.result is not None


@dataclass(frozen=True, slots=True)
class QuizSessionSummary:
    session_id: str
    mode: str
    requested_count: int
    question_count: int
    state: str
    answered_count: int
    correct_count: int
    incorrect_count: int
    skipped_count: int
    details_pruned: bool
    created_at: str
    updated_at: str
    started_at: str
    ended_at: str | None

    @property
    def effective_incorrect_count(self) -> int:
        """Incorrect answers plus skips, because skip counts as wrong."""

        return self.incorrect_count + self.skipped_count

    @property
    def accuracy(self) -> float:
        """Accuracy ratio from 0.0 to 1.0; skips remain in the denominator."""

        if self.answered_count == 0:
            return 0.0
        return self.correct_count / self.answered_count


@dataclass(frozen=True, slots=True)
class QuizSessionSnapshot:
    summary: QuizSessionSummary
    questions: tuple[QuestionEventSnapshot, ...]

    @property
    def remaining_questions(self) -> tuple[QuestionEventSnapshot, ...]:
        return tuple(question for question in self.questions if not question.answered)
