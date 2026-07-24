"""Pure state machine and renderer for the optional Quiz TUI.

The controller has no dependency on ``curses``.  It translates semantic key
names into calls to the headless :class:`QuizService`, while the renderer emits
plain terminal lines plus mouse click targets.  Keeping this layer pure makes
all required keyboard flows testable without opening a real terminal.
"""
from __future__ import annotations

import secrets
import textwrap
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .service import (
    QuizAnswerFeedback,
    QuizServiceError,
    QuizSessionResult,
    QuizSourceDetails,
    QuizStartResult,
)
from .session_models import QuestionEventSnapshot, QuizSessionSummary


MODE_ORDER = ("mixed", "vocabulary", "mistake")
MODE_LABELS = {
    "mixed": "混合測驗",
    "vocabulary": "單字測驗",
    "mistake": "錯題測驗",
}
SCREEN_NAMES = frozenset(
    {
        "resume",
        "setup",
        "shortage",
        "question",
        "feedback",
        "details",
        "exit_menu",
        "result",
        "message",
    }
)
MIN_QUESTION_COUNT = 1
MAX_QUESTION_COUNT = 100


class QuizTuiService(Protocol):
    def list_resumable_sessions(
        self, *, limit: int = 20
    ) -> tuple[QuizSessionSummary, ...]: ...

    def continue_session(self, session_id: str): ...

    def decline_resume(self, session_id: str): ...

    def start_session(
        self,
        *,
        mode: str = "mixed",
        requested_count: int = 10,
        levels: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        seed: int | str | bytes | None = None,
        allow_shortage: bool = False,
    ) -> QuizStartResult: ...

    def current_question(self, session_id: str) -> QuestionEventSnapshot | None: ...

    def submit_choice(
        self, session_id: str, question_event_id: str, *, choice_id: str
    ) -> QuizAnswerFeedback: ...

    def submit_reorder(
        self,
        session_id: str,
        question_event_id: str,
        *,
        ordered_choice_ids: Sequence[str],
    ) -> QuizAnswerFeedback: ...

    def skip_question(
        self, session_id: str, question_event_id: str
    ) -> QuizAnswerFeedback: ...

    def pause_session(self, session_id: str): ...

    def abandon_session(self, session_id: str): ...

    def mark_interrupted_if_active(self, session_id: str): ...

    def session_result(self, session_id: str) -> QuizSessionResult: ...

    def question_source_details(
        self, session_id: str, question_event_id: str
    ) -> QuizSourceDetails: ...


@dataclass(frozen=True, slots=True)
class RenderedScreen:
    lines: tuple[str, ...]
    click_targets: tuple[tuple[int, str], ...] = ()

    def target_for_row(self, row: int) -> str | None:
        for target_row, target in self.click_targets:
            if target_row == row:
                return target
        return None


@dataclass(slots=True)
class QuizTuiState:
    screen: str = "setup"
    mode: str = "mixed"
    requested_count: int = 10
    levels: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    setup_focus: int = 0
    choice_cursor: int = 0
    armed_choice_id: str = ""
    reorder_choice_ids: list[str] = field(default_factory=list)
    resumable_sessions: tuple[QuizSessionSummary, ...] = ()
    resume_cursor: int = 0
    shortage_result: QuizStartResult | None = None
    session_id: str = ""
    current_question: QuestionEventSnapshot | None = None
    feedback: QuizAnswerFeedback | None = None
    source_details: QuizSourceDetails | None = None
    result: QuizSessionResult | None = None
    exit_cursor: int = 0
    return_screen: str = "question"
    message: str = ""
    seed: str = ""
    should_exit: bool = False

    def __post_init__(self) -> None:
        if self.screen not in SCREEN_NAMES:
            raise ValueError(f"不支援的 TUI screen：{self.screen}")


class QuizTuiController:
    """Semantic keyboard controller for the future curses adapter."""

    def __init__(
        self,
        service: QuizTuiService,
        *,
        default_mode: str = "mixed",
        default_count: int = 10,
        default_levels: Sequence[str] = (),
        default_sources: Sequence[str] = (),
        seed_factory: Callable[[], str] | None = None,
    ) -> None:
        if default_mode not in MODE_ORDER:
            raise ValueError(f"不支援的 default_mode：{default_mode}")
        if not isinstance(default_count, int) or isinstance(default_count, bool):
            raise TypeError("default_count 必須是整數")
        if not MIN_QUESTION_COUNT <= default_count <= MAX_QUESTION_COUNT:
            raise ValueError(
                f"default_count 必須介於 {MIN_QUESTION_COUNT} 到 {MAX_QUESTION_COUNT}"
            )
        levels = tuple(
            dict.fromkeys(
                str(value).strip() for value in default_levels if str(value).strip()
            )
        )
        sources = tuple(
            dict.fromkeys(
                str(value).strip() for value in default_sources if str(value).strip()
            )
        )
        self.service = service
        self.state = QuizTuiState(
            mode=default_mode,
            requested_count=default_count,
            levels=levels,
            sources=sources,
        )
        self._seed_factory = seed_factory or (lambda: secrets.token_hex(8))
        self.refresh_startup()

    @property
    def active_session_id(self) -> str:
        return self.state.session_id

    def refresh_startup(self) -> None:
        sessions = self.service.list_resumable_sessions(limit=20)
        self.state.resumable_sessions = sessions
        self.state.resume_cursor = 0
        self.state.screen = "resume" if sessions else "setup"
        self.state.message = ""

    def handle_key(self, key: str) -> None:
        normalized = key.upper() if len(key) > 1 else key
        handlers = {
            "resume": self._handle_resume,
            "setup": self._handle_setup,
            "shortage": self._handle_shortage,
            "question": self._handle_question,
            "feedback": self._handle_feedback,
            "details": self._handle_details,
            "exit_menu": self._handle_exit_menu,
            "result": self._handle_result,
            "message": self._handle_message,
        }
        handlers[self.state.screen](normalized)

    def handle_click(self, target: str) -> None:
        if target.startswith("setup-focus:"):
            self.state.setup_focus = int(target.split(":", 1)[1])
            return
        if target.startswith("mode:"):
            mode = target.split(":", 1)[1]
            if mode in MODE_ORDER:
                self.state.mode = mode
                self.state.setup_focus = 0
            return
        if target.startswith("choice:") and self.state.screen == "question":
            choice_id = target.split(":", 1)[1]
            self._direct_choice(choice_id)
            return
        if target.startswith("resume:") and self.state.screen == "resume":
            session_id = target.split(":", 1)[1]
            for index, summary in enumerate(self.state.resumable_sessions):
                if summary.session_id == session_id:
                    self.state.resume_cursor = index
                    self._resume_selected()
                    return
        if target.startswith("exit:") and self.state.screen == "exit_menu":
            action = target.split(":", 1)[1]
            self._apply_exit_action(action)

    def interrupt_active_session(self) -> None:
        if not self.state.session_id:
            return
        try:
            self.service.mark_interrupted_if_active(self.state.session_id)
        except Exception:
            pass

    def render(self, width: int, height: int) -> RenderedScreen:
        width = max(20, width)
        height = max(8, height)
        renderers = {
            "resume": self._render_resume,
            "setup": self._render_setup,
            "shortage": self._render_shortage,
            "question": self._render_question,
            "feedback": self._render_feedback,
            "details": self._render_details,
            "exit_menu": self._render_exit_menu,
            "result": self._render_result,
            "message": self._render_message,
        }
        screen = renderers[self.state.screen](width)
        if len(screen.lines) <= height:
            return screen
        clipped = list(screen.lines[: max(1, height - 1)])
        clipped.append("…畫面內容超出目前終端高度，請放大視窗")
        targets = tuple((row, target) for row, target in screen.click_targets if row < height - 1)
        return RenderedScreen(tuple(clipped), targets)

    # -- screen handlers -------------------------------------------------
    def _handle_resume(self, key: str) -> None:
        if not self.state.resumable_sessions:
            self.state.screen = "setup"
            return
        if key in {"UP", "k"}:
            self.state.resume_cursor = (self.state.resume_cursor - 1) % len(
                self.state.resumable_sessions
            )
        elif key in {"DOWN", "j"}:
            self.state.resume_cursor = (self.state.resume_cursor + 1) % len(
                self.state.resumable_sessions
            )
        elif key in {"ENTER", "SPACE", "c"}:
            self._resume_selected()
        elif key in {"a", "x"}:
            summary = self.state.resumable_sessions[self.state.resume_cursor]
            self.service.decline_resume(summary.session_id)
            self.refresh_startup()
        elif key in {"q", "ESC"}:
            self.state.should_exit = True

    def _handle_setup(self, key: str) -> None:
        if key in {"UP", "k"}:
            self.state.setup_focus = (self.state.setup_focus - 1) % 3
            return
        if key in {"DOWN", "j"}:
            self.state.setup_focus = (self.state.setup_focus + 1) % 3
            return
        if key in {"1", "2", "3"}:
            self.state.mode = MODE_ORDER[int(key) - 1]
            self.state.setup_focus = 0
            return
        if key in {"LEFT", "h"}:
            if self.state.setup_focus == 0:
                self._cycle_mode(-1)
            elif self.state.setup_focus == 1:
                self._change_count(-1)
            return
        if key in {"RIGHT", "l"}:
            if self.state.setup_focus == 0:
                self._cycle_mode(1)
            elif self.state.setup_focus == 1:
                self._change_count(1)
            return
        if key in {"+", "="}:
            self._change_count(1)
            return
        if key in {"-", "_"}:
            self._change_count(-1)
            return
        if key in {"ENTER", "SPACE"}:
            if self.state.setup_focus < 2:
                self.state.setup_focus += 1
            else:
                self._start_session(allow_shortage=False)
        elif key == "q":
            self.state.should_exit = True

    def _handle_shortage(self, key: str) -> None:
        if key in {"ENTER", "SPACE", "y"}:
            self._start_session(allow_shortage=True)
        elif key in {"q", "ESC", "n"}:
            self.state.shortage_result = None
            self.state.screen = "setup"

    def _handle_question(self, key: str) -> None:
        event = self.state.current_question
        if event is None:
            self._finish_session()
            return
        choices = event.question.choices
        if key in {"UP", "k"}:
            self.state.choice_cursor = (self.state.choice_cursor - 1) % len(choices)
            return
        if key in {"DOWN", "j"}:
            self.state.choice_cursor = (self.state.choice_cursor + 1) % len(choices)
            return
        if key in {"1", "2", "3", "4"}:
            index = int(key) - 1
            if index < len(choices):
                self._direct_choice(choices[index].choice_id)
            return
        if key == "SPACE":
            choice_id = choices[self.state.choice_cursor].choice_id
            if event.question.question_type == "mistake_reorder_4":
                self._append_reorder_choice(choice_id)
            else:
                self.state.armed_choice_id = choice_id
            return
        if key in {"BACKSPACE", "DELETE"}:
            if event.question.question_type == "mistake_reorder_4":
                if self.state.reorder_choice_ids:
                    self.state.reorder_choice_ids.pop()
            else:
                self.state.armed_choice_id = ""
            return
        if key == "ENTER":
            if event.question.question_type == "mistake_reorder_4":
                if len(self.state.reorder_choice_ids) == len(choices):
                    self._submit_reorder()
                else:
                    self.state.message = "請先選完全部四個片段"
            else:
                choice_id = self.state.armed_choice_id or choices[
                    self.state.choice_cursor
                ].choice_id
                self._submit_choice(choice_id)
            return
        if key == "s":
            self._skip_current()
        elif key == "q":
            self.state.return_screen = "question"
            self.state.exit_cursor = 0
            self.state.screen = "exit_menu"

    def _handle_feedback(self, key: str) -> None:
        if key in {"ENTER", "SPACE", "n"}:
            self._advance_after_feedback()
        elif key == "d":
            self._show_details()
        elif key == "q":
            self.state.return_screen = "feedback"
            self.state.exit_cursor = 0
            self.state.screen = "exit_menu"

    def _handle_details(self, key: str) -> None:
        if key in {"ENTER", "SPACE", "d", "q", "ESC"}:
            self.state.screen = "feedback"

    def _handle_exit_menu(self, key: str) -> None:
        if key in {"UP", "k"}:
            self.state.exit_cursor = (self.state.exit_cursor - 1) % 3
        elif key in {"DOWN", "j"}:
            self.state.exit_cursor = (self.state.exit_cursor + 1) % 3
        elif key in {"1", "2", "3"}:
            self.state.exit_cursor = int(key) - 1
            self._apply_exit_action(("pause", "abandon", "cancel")[self.state.exit_cursor])
        elif key in {"ENTER", "SPACE"}:
            self._apply_exit_action(("pause", "abandon", "cancel")[self.state.exit_cursor])
        elif key in {"q", "ESC"}:
            self.state.screen = self.state.return_screen

    def _handle_result(self, key: str) -> None:
        if key in {"ENTER", "SPACE", "q", "ESC"}:
            self.state.should_exit = True

    def _handle_message(self, key: str) -> None:
        if key in {"ENTER", "SPACE", "q", "ESC"}:
            self.state.message = ""
            self.state.screen = "setup"

    # -- state transitions ----------------------------------------------
    def _cycle_mode(self, delta: int) -> None:
        index = MODE_ORDER.index(self.state.mode)
        self.state.mode = MODE_ORDER[(index + delta) % len(MODE_ORDER)]

    def _change_count(self, delta: int) -> None:
        self.state.requested_count = min(
            MAX_QUESTION_COUNT,
            max(MIN_QUESTION_COUNT, self.state.requested_count + delta),
        )

    def _start_session(self, *, allow_shortage: bool) -> None:
        if not self.state.seed:
            self.state.seed = self._seed_factory()
        result = self.service.start_session(
            mode=self.state.mode,
            requested_count=self.state.requested_count,
            levels=self.state.levels or None,
            sources=self.state.sources or None,
            seed=self.state.seed,
            allow_shortage=allow_shortage,
        )
        if result.status == "confirmation_required":
            self.state.shortage_result = result
            self.state.screen = "shortage"
            return
        if result.status == "no_safe_questions":
            self.state.message = "沒有可安全生成的題目，請更換模式或篩選條件。"
            self.state.screen = "message"
            self.state.seed = ""
            return
        assert result.session is not None
        self._load_session(result.session.summary.session_id)

    def _resume_selected(self) -> None:
        summary = self.state.resumable_sessions[self.state.resume_cursor]
        session = self.service.continue_session(summary.session_id)
        self._load_session(session.summary.session_id)

    def _load_session(self, session_id: str) -> None:
        self.state.session_id = session_id
        self.state.shortage_result = None
        self.state.feedback = None
        self.state.source_details = None
        self.state.result = None
        self.state.seed = ""
        self._load_current_question()

    def _load_current_question(self) -> None:
        event = self.service.current_question(self.state.session_id)
        self.state.current_question = event
        self.state.choice_cursor = 0
        self.state.armed_choice_id = ""
        self.state.reorder_choice_ids.clear()
        self.state.message = ""
        if event is None:
            self._finish_session()
        else:
            self.state.screen = "question"

    def _direct_choice(self, choice_id: str) -> None:
        event = self.state.current_question
        if event is None:
            return
        if event.question.question_type == "mistake_reorder_4":
            self._append_reorder_choice(choice_id)
        else:
            self._submit_choice(choice_id)

    def _append_reorder_choice(self, choice_id: str) -> None:
        if choice_id not in self.state.reorder_choice_ids:
            self.state.reorder_choice_ids.append(choice_id)

    def _submit_choice(self, choice_id: str) -> None:
        event = self.state.current_question
        if event is None:
            return
        feedback = self.service.submit_choice(
            self.state.session_id,
            event.question_event_id,
            choice_id=choice_id,
        )
        self._set_feedback(feedback)

    def _submit_reorder(self) -> None:
        event = self.state.current_question
        if event is None:
            return
        feedback = self.service.submit_reorder(
            self.state.session_id,
            event.question_event_id,
            ordered_choice_ids=tuple(self.state.reorder_choice_ids),
        )
        self._set_feedback(feedback)

    def _skip_current(self) -> None:
        event = self.state.current_question
        if event is None:
            return
        feedback = self.service.skip_question(
            self.state.session_id, event.question_event_id
        )
        self._set_feedback(feedback)

    def _set_feedback(self, feedback: QuizAnswerFeedback) -> None:
        self.state.feedback = feedback
        self.state.source_details = None
        try:
            self.state.source_details = self.service.question_source_details(
                self.state.session_id,
                feedback.question.question_event_id,
            )
        except Exception:
            # Feedback remains usable even when the optional source expansion
            # cannot be resolved temporarily.
            self.state.source_details = None
        self.state.screen = "feedback"

    def _show_details(self) -> None:
        feedback = self.state.feedback
        if feedback is None:
            return
        if self.state.source_details is None:
            self.state.source_details = self.service.question_source_details(
                self.state.session_id, feedback.question.question_event_id
            )
        self.state.screen = "details"

    def _advance_after_feedback(self) -> None:
        feedback = self.state.feedback
        self.state.feedback = None
        self.state.source_details = None
        if feedback is not None and feedback.session.summary.state == "completed":
            self._finish_session()
            return
        self._load_current_question()

    def _finish_session(self) -> None:
        self.state.current_question = None
        self.state.feedback = None
        self.state.result = self.service.session_result(self.state.session_id)
        self.state.screen = "result"

    def _apply_exit_action(self, action: str) -> None:
        if action == "pause":
            self.service.pause_session(self.state.session_id)
            self.state.should_exit = True
        elif action == "abandon":
            self.service.abandon_session(self.state.session_id)
            self.state.should_exit = True
        elif action == "cancel":
            self.state.screen = self.state.return_screen
        else:
            raise ValueError(f"不支援的 exit action：{action}")

    # -- renderers -------------------------------------------------------
    def _render_resume(self, width: int) -> RenderedScreen:
        lines = ["jpnote Quiz｜恢復未完成測驗", ""]
        targets: list[tuple[int, str]] = []
        for index, summary in enumerate(self.state.resumable_sessions):
            marker = "▶" if index == self.state.resume_cursor else " "
            accuracy = f"{summary.accuracy * 100:.0f}%"
            row = len(lines)
            lines.append(
                f"{marker} {summary.mode}｜{summary.answered_count}/{summary.question_count}｜{summary.state}｜{accuracy}"
            )
            targets.append((row, f"resume:{summary.session_id}"))
        lines.extend(["", "Enter/Space 繼續｜a 放棄所選 session"])
        return self._screen(lines, width, targets)

    def _render_setup(self, width: int) -> RenderedScreen:
        focus = self.state.setup_focus
        lines = ["jpnote Quiz", ""]
        targets: list[tuple[int, str]] = []
        mode_bits = []
        for mode in MODE_ORDER:
            selected = "●" if mode == self.state.mode else "○"
            mode_bits.append(f"{selected} {MODE_LABELS[mode]}")
        row = len(lines)
        lines.append(("▶ " if focus == 0 else "  ") + "模式：" + "  ".join(mode_bits))
        targets.append((row, "setup-focus:0"))
        row = len(lines)
        lines.append(("▶ " if focus == 1 else "  ") + f"題數：{self.state.requested_count}")
        targets.append((row, "setup-focus:1"))
        level_text = "、".join(self.state.levels) or "全部"
        source_text = "、".join(self.state.sources) or "全部"
        lines.append(f"  JLPT：{level_text}")
        lines.append(f"  來源：{source_text}")
        row = len(lines)
        lines.append(("▶ " if focus == 2 else "  ") + "開始測驗")
        targets.append((row, "setup-focus:2"))
        lines.extend(
            [
                "",
                "↑/↓ 移動｜←/→ 調整｜1–3 選模式｜Enter 下一項/開始｜q 離開",
                "JLPT／來源可由 jpnote config 或 jpnote quiz 參數設定。",
            ]
        )
        return self._screen(lines, width, targets)

    def _render_shortage(self, width: int) -> RenderedScreen:
        assert self.state.shortage_result is not None
        report = self.state.shortage_result.plan.report
        lines = [
            "安全題庫不足",
            "",
            f"要求題數：{report.requested_count}",
            f"可安全生成：{report.selected_count}",
            f"缺少題數：{report.shortage_count}",
            "",
            "Enter/Space 以所有安全題目開始｜q 返回設定",
        ]
        return self._screen(lines, width)

    def _render_question(self, width: int) -> RenderedScreen:
        event = self.state.current_question
        assert event is not None
        question = event.question
        lines = [
            f"jpnote Quiz｜第 {event.position} 題",
            "",
            question.prompt,
            "",
        ]
        targets: list[tuple[int, str]] = []
        selected_order = {choice_id: index + 1 for index, choice_id in enumerate(self.state.reorder_choice_ids)}
        for index, choice in enumerate(question.choices):
            cursor = "▶" if index == self.state.choice_cursor else " "
            if question.question_type == "mistake_reorder_4":
                suffix = (
                    f"  [順序 {selected_order[choice.choice_id]}]"
                    if choice.choice_id in selected_order
                    else ""
                )
                marker = "●" if choice.choice_id in selected_order else "○"
            else:
                suffix = ""
                marker = "●" if choice.choice_id == self.state.armed_choice_id else "○"
            row = len(lines)
            lines.append(f"{cursor} {index + 1}. {marker} {choice.text}{suffix}")
            targets.append((row, f"choice:{choice.choice_id}"))
        if question.question_type == "mistake_reorder_4":
            order_text = " → ".join(
                next(
                    choice.text
                    for choice in question.choices
                    if choice.choice_id == choice_id
                )
                for choice_id in self.state.reorder_choice_ids
            )
            lines.extend(
                [
                    "",
                    f"目前順序：{order_text or '尚未選擇'}",
                    "重組操作：Space/1–4 加入｜Backspace 退回上一個片段｜Enter 送出",
                ]
            )
        if self.state.message:
            lines.extend(["", f"提示：{self.state.message}"])
        lines.extend(
            [
                "",
                "↑/↓ 移動｜Space 選取｜Enter 確認｜1–4 直接選｜s 跳過｜q 暫停/退出",
            ]
        )
        return self._screen(lines, width, targets)

    def _render_feedback(self, width: int) -> RenderedScreen:
        feedback = self.state.feedback
        assert feedback is not None
        if feedback.skipped:
            headline = "↷ 已跳過（計為答錯）"
        elif feedback.correct:
            headline = "✓ 正確"
        else:
            headline = "× 錯誤"
        lines = [headline, ""]
        lines.extend(self._feedback_answer_lines(feedback))
        if feedback.user_answer is not None and not feedback.correct:
            lines.append(f"你的答案：{feedback.user_answer.text}")
        lines.extend(["", "Enter 下一題｜d 展開詳細資訊｜q 暫停/退出"])
        return self._screen(lines, width)

    def _feedback_answer_lines(
        self,
        feedback: QuizAnswerFeedback,
    ) -> list[str]:
        question = feedback.question.question
        details = self.state.source_details
        lines: list[str] = []

        if question.choices and {
            choice.choice_id for choice in question.choices
        } == {"true", "false"}:
            lines.append(f"題目判定：{feedback.correct_answer.text}")

        if (
            details is not None
            and details.status == "available"
            and details.source_kind == "vocabulary"
        ):
            title = details.title
            if details.reading and details.reading != title:
                title = f"{title}（{details.reading}）"
            if title:
                lines.append(f"詞彙：{title}")
            if question.question_type.startswith("vocab_reading"):
                if details.reading:
                    lines.append(f"正確讀音：{details.reading}")
            elif details.meanings:
                lines.append("正確意思：" + "；".join(details.meanings))
            if len(lines) > 1:
                return lines

        lines.append(f"正解：{feedback.correct_answer.text}")
        return lines

    def _render_details(self, width: int) -> RenderedScreen:
        details = self.state.source_details
        assert details is not None
        lines = ["題目來源詳細資訊", ""]
        if details.status != "available":
            lines.append(details.message or details.status)
        elif details.source_kind == "vocabulary":
            title = details.title
            if details.reading:
                title += f"（{details.reading}）"
            lines.append(title)
            if details.level:
                lines.append(f"JLPT：{details.level}")
            if details.meanings:
                lines.append("意思：" + "；".join(details.meanings))
            if details.aliases:
                lines.append("別名：" + "、".join(details.aliases))
            for example in details.examples:
                lines.append(f"例：{example.japanese}")
                if example.chinese:
                    lines.append(f"　　{example.chinese}")
            if details.sources:
                lines.append("來源：" + "、".join(details.sources))
        else:
            if details.prompt:
                lines.append("原題：" + details.prompt)
            if details.correct_answer:
                lines.append("正解：" + details.correct_answer)
            if details.reason:
                lines.append("原因：" + details.reason)
            if details.before or details.after:
                lines.append(f"句子：{details.before}＿{details.after}")
            if details.sources:
                lines.append("來源：" + "、".join(details.sources))
        lines.extend(["", "Enter/d 返回"])
        return self._screen(lines, width)

    def _render_exit_menu(self, width: int) -> RenderedScreen:
        actions = (
            ("pause", "暫停並於下次繼續"),
            ("abandon", "結束並標記為 abandoned"),
            ("cancel", "返回測驗"),
        )
        lines = ["離開目前測驗", ""]
        targets: list[tuple[int, str]] = []
        for index, (action, label) in enumerate(actions):
            marker = "▶" if index == self.state.exit_cursor else " "
            row = len(lines)
            lines.append(f"{marker} {index + 1}. {label}")
            targets.append((row, f"exit:{action}"))
        lines.extend(["", "↑/↓ 移動｜Enter 確認｜q 返回"])
        return self._screen(lines, width, targets)

    def _render_result(self, width: int) -> RenderedScreen:
        result = self.state.result
        assert result is not None
        summary = result.summary
        lines = [
            "Quiz 完成",
            "",
            f"完成題數：{result.completed_count}",
            f"答對：{summary.correct_count}",
            f"答錯：{summary.incorrect_count}",
            f"跳過：{summary.skipped_count}",
            f"正確率：{result.accuracy * 100:.1f}%",
        ]
        if result.question_types:
            lines.extend(["", "各題型表現"])
            for item in result.question_types:
                lines.append(
                    f"{item.question_type}：{item.correct_count}/{item.answered_count}（{item.accuracy * 100:.0f}%）"
                )
        lines.extend(["", "Enter/q 離開"])
        return self._screen(lines, width)

    def _render_message(self, width: int) -> RenderedScreen:
        return self._screen(
            ["jpnote Quiz", "", self.state.message, "", "Enter 返回設定"], width
        )

    @staticmethod
    def _screen(
        lines: Sequence[str],
        width: int,
        targets: Sequence[tuple[int, str]] = (),
    ) -> RenderedScreen:
        wrapped: list[str] = []
        row_map: dict[int, str] = dict(targets)
        wrapped_targets: list[tuple[int, str]] = []
        for original_row, line in enumerate(lines):
            target = row_map.get(original_row)
            pieces = _wrap_cells(line, max(1, width - 1)) or [""]
            if target is not None:
                wrapped_targets.append((len(wrapped), target))
            wrapped.extend(pieces)
        return RenderedScreen(tuple(wrapped), tuple(wrapped_targets))


def _cell_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def _slice_cells(text: str, limit: int) -> str:
    result: list[str] = []
    used = 0
    for char in text:
        char_width = 0 if unicodedata.combining(char) else (
            2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        )
        if used + char_width > limit:
            break
        result.append(char)
        used += char_width
    return "".join(result)


def _wrap_cells(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    if _cell_width(text) <= width:
        return [text]
    # ``textwrap`` first respects word boundaries; each resulting piece is then
    # split by terminal cell width so Japanese text without spaces remains safe.
    rough = textwrap.wrap(
        text,
        width=max(1, width),
        replace_whitespace=False,
        drop_whitespace=False,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [text]
    result: list[str] = []
    for piece in rough:
        remaining = piece
        while remaining:
            chunk = _slice_cells(remaining, width)
            if not chunk:
                chunk = remaining[0]
            result.append(chunk.rstrip())
            remaining = remaining[len(chunk) :]
        if piece == "":
            result.append("")
    return result
