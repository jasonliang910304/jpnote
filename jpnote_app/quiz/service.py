"""Headless Quiz orchestration service.

This module joins the stable public question-source contract, safety-first
question generation/pool selection, and the independent Quiz session store.
It deliberately has no terminal UI dependency and never reads core SQLite
internals.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Sequence

from jpnote_app.study_sources import (
    AttemptReplaySource,
    EntrySnapshot,
    QuestionSourceReader,
    QuestionSourceUnavailableError,
)

from .question_pool import QUIZ_MODES, QuestionPoolBuilder, QuestionPoolPlan
from .session_models import (
    AnswerSnapshot,
    QuestionEventSnapshot,
    QuizQuestionTypeSummary,
    QuizSessionSnapshot,
    QuizSessionSummary,
    QuizValidationError,
)
from .session_store import QuizSessionStore


START_STATUSES = frozenset({"started", "confirmation_required", "no_safe_questions"})
RESUMABLE_SESSION_STATES = frozenset({"active", "paused", "interrupted"})
SOURCE_DETAIL_STATUSES = frozenset({"available", "missing", "unavailable"})


class QuizServiceError(RuntimeError):
    """Base class for headless Quiz orchestration failures."""


class QuizAnswerError(QuizServiceError):
    """A submitted answer cannot be mapped safely to the current question."""


@dataclass(frozen=True, slots=True)
class QuizStartResult:
    """Result of planning or starting one persisted Quiz session."""

    status: str
    plan: QuestionPoolPlan
    session: QuizSessionSnapshot | None = None

    def __post_init__(self) -> None:
        if self.status not in START_STATUSES:
            raise QuizValidationError(f"不支援的 Quiz start status：{self.status}")
        if self.status == "started" and self.session is None:
            raise QuizValidationError("started 結果必須包含 session")
        if self.status != "started" and self.session is not None:
            raise QuizValidationError("尚未開始的結果不可包含 session")

    @property
    def started(self) -> bool:
        return self.status == "started"

    @property
    def requires_confirmation(self) -> bool:
        return self.status == "confirmation_required"


@dataclass(frozen=True, slots=True)
class QuizAnswerFeedback:
    """Persisted answer result and the exact immutable question feedback."""

    session: QuizSessionSnapshot
    question: QuestionEventSnapshot
    correct: bool
    skipped: bool

    @property
    def correct_answer(self) -> AnswerSnapshot:
        return self.question.question.correct_answer

    @property
    def user_answer(self) -> AnswerSnapshot | None:
        return self.question.user_answer


@dataclass(frozen=True, slots=True)
class QuizSessionResult:
    """Headless result view used by history and the future TUI."""

    summary: QuizSessionSummary
    question_types: tuple[QuizQuestionTypeSummary, ...]
    incorrect_questions: tuple[QuestionEventSnapshot, ...]
    details_available: bool

    @property
    def completed_count(self) -> int:
        return self.summary.answered_count

    @property
    def accuracy(self) -> float:
        return self.summary.accuracy


@dataclass(frozen=True, slots=True)
class QuizSourceExample:
    japanese: str
    chinese: str


@dataclass(frozen=True, slots=True)
class QuizSourceDetails:
    """Optional expanded feedback resolved through the stable core read port."""

    status: str
    source_kind: str
    source_key: str
    title: str = ""
    reading: str = ""
    level: str = ""
    meanings: tuple[str, ...] = ()
    examples: tuple[QuizSourceExample, ...] = ()
    aliases: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    prompt: str = ""
    correct_answer: str = ""
    reason: str = ""
    section: str = ""
    before: str = ""
    after: str = ""
    linked_entry_keys: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    message: str = ""

    def __post_init__(self) -> None:
        if self.status not in SOURCE_DETAIL_STATUSES:
            raise QuizValidationError(f"不支援的 source detail status：{self.status}")
        if self.source_kind not in {"vocabulary", "mistake"}:
            raise QuizValidationError(f"不支援的 source_kind：{self.source_kind}")
        if not self.source_key.strip():
            raise QuizValidationError("source_key 不可為空")


class QuizService:
    """Headless, TUI-independent Quiz application service."""

    def __init__(
        self,
        source_reader: QuestionSourceReader,
        session_store: QuizSessionStore,
    ) -> None:
        if not isinstance(source_reader, QuestionSourceReader):
            raise TypeError("source_reader 必須實作 QuestionSourceReader")
        self._source_reader = source_reader
        self._session_store = session_store

    @property
    def source_reader(self) -> QuestionSourceReader:
        return self._source_reader

    @property
    def session_store(self) -> QuizSessionStore:
        return self._session_store

    def plan_session(
        self,
        *,
        mode: str = "mixed",
        requested_count: int = 10,
        levels: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        seed: int | str | bytes | None = None,
    ) -> QuestionPoolPlan:
        """Build an immutable safe pool without modifying Quiz history."""

        if mode not in QUIZ_MODES:
            raise ValueError(f"不支援的 Quiz mode：{mode}")

        entries = ()
        attempts = ()
        if mode in {"mixed", "vocabulary"}:
            entries = self._source_reader.list_entry_snapshots(
                entry_types=("vocabulary",),
                levels=levels,
                sources=sources,
            )
        if mode in {"mixed", "mistake"}:
            attempts = self._source_reader.list_attempt_replay_sources(
                levels=levels,
                sources=sources,
            )

        return QuestionPoolBuilder(seed=seed).build(
            mode=mode,
            requested_count=requested_count,
            entries=entries,
            attempts=attempts,
        )

    def start_session(
        self,
        *,
        mode: str = "mixed",
        requested_count: int = 10,
        levels: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        seed: int | str | bytes | None = None,
        allow_shortage: bool = False,
    ) -> QuizStartResult:
        """Plan and optionally persist a session.

        A shortage never silently changes the requested count.  The caller must
        explicitly opt in with ``allow_shortage=True`` before all available safe
        questions are persisted.
        """

        plan = self.plan_session(
            mode=mode,
            requested_count=requested_count,
            levels=levels,
            sources=sources,
            seed=seed,
        )
        if not plan.report.can_start:
            return QuizStartResult(status="no_safe_questions", plan=plan)
        if plan.report.has_shortage and not allow_shortage:
            return QuizStartResult(status="confirmation_required", plan=plan)

        session = self._session_store.create_session(
            mode=mode,
            questions=plan.questions,
            requested_count=requested_count,
        )
        return QuizStartResult(status="started", plan=plan, session=session)

    def current_question(self, session_id: str) -> QuestionEventSnapshot | None:
        return self._session_store.next_question(session_id)

    def submit_choice(
        self,
        session_id: str,
        question_event_id: str,
        *,
        choice_id: str,
    ) -> QuizAnswerFeedback:
        """Submit one MCQ/true-false choice and determine correctness internally."""

        current = self._require_current_question(session_id, question_event_id)
        if current.question.question_type == "mistake_reorder_4":
            raise QuizAnswerError("重組題必須使用 submit_reorder()")

        matches = [
            choice for choice in current.question.choices if choice.choice_id == choice_id
        ]
        if len(matches) != 1:
            raise QuizAnswerError(f"找不到唯一選項：{choice_id}")
        selected = matches[0]
        user_answer = AnswerSnapshot(answer_id=selected.choice_id, text=selected.text)
        correct = (
            selected.choice_id == current.question.correct_answer.answer_id
            and selected.text == current.question.correct_answer.text
        )
        updated = self._session_store.submit_answer(
            session_id,
            question_event_id,
            user_answer=user_answer,
            correct=correct,
        )
        return self._feedback(updated, question_event_id)

    def submit_reorder(
        self,
        session_id: str,
        question_event_id: str,
        *,
        ordered_choice_ids: Sequence[str],
    ) -> QuizAnswerFeedback:
        """Submit an ordered four-part answer using stable choice IDs."""

        current = self._require_current_question(session_id, question_event_id)
        if current.question.question_type != "mistake_reorder_4":
            raise QuizAnswerError("目前題目不是 reorder_4")

        submitted = tuple(ordered_choice_ids)
        choices_by_id = {
            choice.choice_id: choice for choice in current.question.choices
        }
        if len(submitted) != len(current.question.choices):
            raise QuizAnswerError("重組答案必須包含全部四個選項")
        if len(submitted) != len(set(submitted)):
            raise QuizAnswerError("重組答案不可重複使用選項")
        if set(submitted) != set(choices_by_id):
            raise QuizAnswerError("重組答案包含不存在或缺少的選項")

        answer_id = "-".join(submitted)
        answer_text = "".join(choices_by_id[choice_id].text for choice_id in submitted)
        user_answer = AnswerSnapshot(answer_id=answer_id, text=answer_text)
        correct = (
            answer_id == current.question.correct_answer.answer_id
            and answer_text == current.question.correct_answer.text
        )
        updated = self._session_store.submit_answer(
            session_id,
            question_event_id,
            user_answer=user_answer,
            correct=correct,
        )
        return self._feedback(updated, question_event_id)

    def skip_question(
        self,
        session_id: str,
        question_event_id: str,
    ) -> QuizAnswerFeedback:
        self._require_current_question(session_id, question_event_id)
        updated = self._session_store.skip_question(session_id, question_event_id)
        return self._feedback(updated, question_event_id)

    def pause_session(self, session_id: str) -> QuizSessionSnapshot:
        return self._session_store.pause_session(session_id)

    def resume_session(self, session_id: str) -> QuizSessionSnapshot:
        return self._session_store.resume_session(session_id)

    def abandon_session(self, session_id: str) -> QuizSessionSnapshot:
        return self._session_store.abandon_session(session_id)

    def mark_interrupted(self, session_id: str) -> QuizSessionSnapshot:
        return self._session_store.mark_interrupted(session_id)

    def get_session(self, session_id: str) -> QuizSessionSnapshot:
        return self._session_store.get_session(session_id)

    def list_resumable_sessions(
        self, *, limit: int = 20
    ) -> tuple[QuizSessionSummary, ...]:
        """Return active/paused/interrupted sessions for startup recovery."""

        return self._session_store.list_recent_sessions(
            limit=limit,
            states=tuple(sorted(RESUMABLE_SESSION_STATES)),
        )

    def continue_session(self, session_id: str) -> QuizSessionSnapshot:
        """Continue one saved session without regenerating remaining questions."""

        snapshot = self.get_session(session_id)
        state = snapshot.summary.state
        if state == "active":
            return snapshot
        if state in {"paused", "interrupted"}:
            return self.resume_session(session_id)
        raise QuizServiceError(f"session {state} 已不可恢復")

    def decline_resume(self, session_id: str) -> QuizSessionSnapshot:
        """Reject startup recovery and persist the required abandoned state."""

        snapshot = self.get_session(session_id)
        if snapshot.summary.state not in RESUMABLE_SESSION_STATES:
            raise QuizServiceError(
                f"session {snapshot.summary.state} 不是可恢復狀態"
            )
        return self.abandon_session(session_id)

    def mark_interrupted_if_active(
        self, session_id: str
    ) -> QuizSessionSnapshot | None:
        """Best-effort lifecycle hook used by outer TUI/debug boundaries."""

        try:
            snapshot = self.get_session(session_id)
        except Exception:
            return None
        if snapshot.summary.state != "active":
            return snapshot
        try:
            return self.mark_interrupted(session_id)
        except Exception:
            return None

    @contextmanager
    def interruption_guard(self, session_id: str) -> Iterator[None]:
        """Mark an active session interrupted when an outer app scope aborts.

        This guard belongs around the future TUI event loop, not around each
        expected validation error.  It preserves the original exception even if
        best-effort persistence itself fails.  A hard process kill cannot run
        cleanup, but the still-active session remains discoverable by
        ``list_resumable_sessions()``.
        """

        try:
            yield
        except BaseException:
            try:
                self.mark_interrupted_if_active(session_id)
            except Exception:
                pass
            raise

    def session_result(self, session_id: str) -> QuizSessionResult:
        """Build the v1 result summary without response-time metrics."""

        snapshot = self.get_session(session_id)
        incorrect_questions = tuple(
            event
            for event in snapshot.questions
            if event.result in {"incorrect", "skipped"}
        )
        return QuizSessionResult(
            summary=snapshot.summary,
            question_types=snapshot.summary.question_type_summaries,
            incorrect_questions=incorrect_questions,
            details_available=not snapshot.summary.details_pruned,
        )

    def question_source_details(
        self, session_id: str, question_event_id: str
    ) -> QuizSourceDetails:
        """Resolve optional expanded feedback from the current core source.

        The immutable historical question remains authoritative.  This method
        only supplies optional current metadata such as examples, sources and
        aliases, and therefore fails soft if the source was deleted or cannot be
        read.
        """

        event = self._question_event(session_id, question_event_id)
        question = event.question
        try:
            if question.source_kind == "vocabulary":
                source = self._source_reader.get_entry_snapshot(question.source_key)
                if source is None:
                    return self._missing_source_details(
                        question.source_kind, question.source_key
                    )
                return self._entry_source_details(source)

            source = self._source_reader.get_attempt_replay_source(
                question.source_key
            )
            if source is None:
                return self._missing_source_details(
                    question.source_kind, question.source_key
                )
            return self._attempt_source_details(source)
        except QuestionSourceUnavailableError as exc:
            return QuizSourceDetails(
                status="unavailable",
                source_kind=question.source_kind,
                source_key=question.source_key,
                message=str(exc),
            )

    def _question_event(
        self, session_id: str, question_event_id: str
    ) -> QuestionEventSnapshot:
        snapshot = self.get_session(session_id)
        matches = tuple(
            event
            for event in snapshot.questions
            if event.question_event_id == question_event_id
        )
        if len(matches) == 1:
            return matches[0]
        if snapshot.summary.details_pruned:
            raise QuizServiceError("此 session 的詳細作答紀錄已依容量限制清理")
        raise QuizServiceError(f"找不到 question event：{question_event_id}")

    @staticmethod
    def _missing_source_details(
        source_kind: str, source_key: str
    ) -> QuizSourceDetails:
        return QuizSourceDetails(
            status="missing",
            source_kind=source_kind,
            source_key=source_key,
            message=(
                "原始題目來源目前不存在；已保存的題目快照仍可正常查看"
            ),
        )

    @staticmethod
    def _entry_source_details(source: EntrySnapshot) -> QuizSourceDetails:
        examples = tuple(
            QuizSourceExample(japanese=sense.example_ja, chinese=sense.example_zh)
            for sense in source.senses
            if sense.example_ja.strip() or sense.example_zh.strip()
        )
        return QuizSourceDetails(
            status="available",
            source_kind="vocabulary",
            source_key=source.key,
            title=source.display,
            reading=source.reading,
            level=source.level,
            meanings=tuple(
                sense.meaning for sense in source.senses if sense.meaning.strip()
            ),
            examples=examples,
            aliases=source.aliases,
            sources=source.sources,
        )

    @staticmethod
    def _attempt_source_details(source: AttemptReplaySource) -> QuizSourceDetails:
        return QuizSourceDetails(
            status="available",
            source_kind="mistake",
            source_key=source.event_key,
            title=source.question or source.prompt,
            level=source.linked_levels[0] if len(source.linked_levels) == 1 else "",
            sources=(source.source,) if source.source else (),
            prompt=source.prompt,
            correct_answer=source.correct_answer,
            reason=source.reason,
            section=source.section,
            before=source.before,
            after=source.after,
            linked_entry_keys=source.linked_entry_keys,
            warnings=source.data_warnings,
        )

    def _require_current_question(
        self,
        session_id: str,
        question_event_id: str,
    ) -> QuestionEventSnapshot:
        current = self._session_store.next_question(session_id)
        if current is None:
            raise QuizAnswerError("此 session 已沒有未作答題目")
        if current.question_event_id != question_event_id:
            raise QuizAnswerError("只能提交目前下一題，避免 stale 或跳題作答")
        return current

    @staticmethod
    def _feedback(
        session: QuizSessionSnapshot,
        question_event_id: str,
    ) -> QuizAnswerFeedback:
        matches = [
            question
            for question in session.questions
            if question.question_event_id == question_event_id
        ]
        if len(matches) != 1:
            raise QuizServiceError("保存後找不到唯一的 question event")
        question = matches[0]
        if question.result is None:
            raise QuizServiceError("保存後 question event 仍未作答")
        return QuizAnswerFeedback(
            session=session,
            question=question,
            correct=question.result == "correct",
            skipped=question.result == "skipped",
        )
