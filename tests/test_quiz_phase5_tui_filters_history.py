from __future__ import annotations

from types import SimpleNamespace

from jpnote_app.quiz.service import QuizSessionResult
from jpnote_app.quiz.session_models import QuizSessionSnapshot, QuizSessionSummary
from jpnote_app.quiz.tui_controller import QuizTuiController
from jpnote_app.quiz.tui_menus import ordered_levels, session_line, toggle_selected


def summary(
    session_id: str,
    *,
    state: str = "completed",
    answered: int = 2,
    correct: int = 1,
    incorrect: int = 1,
    skipped: int = 0,
) -> QuizSessionSummary:
    return QuizSessionSummary(
        session_id=session_id,
        mode="mixed",
        requested_count=2,
        question_count=2,
        state=state,
        answered_count=answered,
        correct_count=correct,
        incorrect_count=incorrect,
        skipped_count=skipped,
        details_pruned=False,
        created_at="2026-07-24T20:00:00+08:00",
        updated_at="2026-07-24T20:02:00+08:00",
        started_at="2026-07-24T20:00:00+08:00",
        ended_at=None if state in {"active", "paused", "interrupted"} else "2026-07-24T20:02:00+08:00",
    )


class FakeService:
    def __init__(self) -> None:
        self.recent = (
            summary("quiz-session:completed"),
            summary(
                "quiz-session:paused",
                state="paused",
                answered=1,
                correct=1,
                incorrect=0,
            ),
        )
        self.continued: list[str] = []

    def source_catalog(self):
        return SimpleNamespace(
            levels=("N3", "N5", "unclassified"),
            sources=("TRY! N3", "今日練習", "TRY! N3"),
        )

    def list_resumable_sessions(self, *, limit: int = 20):
        return ()

    def list_recent_sessions(self, *, limit: int = 20):
        return self.recent[:limit]

    def session_result(self, session_id: str):
        item = next(value for value in self.recent if value.session_id == session_id)
        return QuizSessionResult(
            summary=item,
            question_types=(),
            incorrect_questions=(),
            details_available=True,
        )

    def continue_session(self, session_id: str):
        self.continued.append(session_id)
        item = next(value for value in self.recent if value.session_id == session_id)
        active = summary(
            item.session_id,
            state="active",
            answered=item.answered_count,
            correct=item.correct_count,
            incorrect=item.incorrect_count,
            skipped=item.skipped_count,
        )
        return QuizSessionSnapshot(summary=active, questions=())

    def current_question(self, session_id: str):
        return None

    def start_session(self, **kwargs):
        raise AssertionError("本測試不應開始新 session")

    def decline_resume(self, session_id: str):
        raise AssertionError("本測試不應放棄 session")

    def mark_interrupted_if_active(self, session_id: str):
        return None


def controller() -> QuizTuiController:
    return QuizTuiController(FakeService(), seed_factory=lambda: "seed")


def test_menu_helpers_preserve_stable_level_order_and_toggle():
    assert ordered_levels(("N3", "N5", "N3", "unclassified")) == (
        "N5",
        "N3",
        "unclassified",
    )
    assert toggle_selected(("N3",), "N5") == ("N3", "N5")
    assert toggle_selected(("N3", "N5"), "N3") == ("N5",)


def test_setup_enter_flow_remains_mode_count_start_compatible():
    ui = controller()
    assert ui.state.setup_focus == 0
    ui.handle_key("ENTER")
    assert ui.state.setup_focus == 1
    ui.handle_key("ENTER")
    assert ui.state.setup_focus == 2


def test_level_filter_is_discovered_and_selectable_from_setup():
    ui = controller()
    assert ui.state.available_levels == ("N5", "N3", "unclassified")

    ui.handle_key("f")
    assert ui.state.screen == "level_filter"
    ui.handle_key("SPACE")
    assert ui.state.levels == ("N5",)
    ui.handle_key("DOWN")
    ui.handle_key("SPACE")
    assert ui.state.levels == ("N5", "N3")
    ui.handle_key("ENTER")
    assert ui.state.screen == "setup"


def test_source_filter_is_sorted_deduplicated_and_clearable():
    ui = controller()
    assert ui.state.available_sources == ("TRY! N3", "今日練習")

    ui.handle_key("o")
    assert ui.state.screen == "source_filter"
    ui.handle_key("SPACE")
    assert ui.state.sources == ("TRY! N3",)
    ui.handle_key("c")
    assert ui.state.sources == ()
    ui.handle_key("ENTER")
    assert ui.state.screen == "setup"


def test_history_browser_opens_summary_without_touching_core_data():
    ui = controller()
    ui.handle_key("H")
    assert ui.state.screen == "history"
    assert len(ui.state.history_sessions) == 2

    screen = ui.render(100, 30)
    assert any("已完成" in line for line in screen.lines)
    ui.handle_key("ENTER")
    assert ui.state.screen == "history_detail"
    assert ui.state.history_result is not None
    detail = ui.render(100, 30)
    assert any("正確率：50.0%" in line for line in detail.lines)
    ui.handle_key("q")
    assert ui.state.screen == "history"


def test_history_continue_rejects_terminal_session_and_resumes_paused_session():
    ui = controller()
    service = ui.service
    ui.handle_key("H")

    ui.handle_key("c")
    assert ui.state.screen == "message"
    assert "已結束" in ui.state.message

    ui.state.screen = "history"
    ui.state.history_cursor = 1
    ui.handle_key("c")
    assert service.continued == ["quiz-session:paused"]
    assert ui.state.screen == "result"


def test_history_and_filter_rows_are_clickable():
    ui = controller()
    setup = ui.render(100, 30)
    level_row = next(row for row, target in setup.click_targets if target == "open-level-filter")
    assert setup.target_for_row(level_row) == "open-level-filter"

    ui.handle_click("open-level-filter")
    ui.handle_click("level:N3")
    assert ui.state.levels == ("N3",)

    ui.state.screen = "setup"
    ui.handle_click("open-history")
    ui.handle_click("history:quiz-session:completed")
    assert ui.state.screen == "history_detail"


def test_session_line_uses_human_readable_state():
    assert "已暫停" in session_line(summary("quiz-session:x", state="paused", answered=1, correct=1, incorrect=0))


def test_history_filters_problem_sessions_and_abandoned_visibility():
    ui = controller()
    ui.state.screen = "history"
    ui.state.history_sessions = (
        summary(
            "quiz-session:clean",
            answered=2,
            correct=2,
            incorrect=0,
        ),
        summary("quiz-session:problem"),
        summary("quiz-session:abandoned", state="abandoned"),
    )

    initial = ui.render(100, 30)
    assert not any("已放棄" in line for line in initial.lines)

    ui.handle_key("w")
    problem_only = ui.render(100, 30)
    assert any("50%" in line for line in problem_only.lines)
    assert not any("100%" in line for line in problem_only.lines)

    ui.handle_key("a")
    with_abandoned = ui.render(100, 30)
    assert any("已放棄" in line for line in with_abandoned.lines)


def test_quiz_service_exposes_catalog_and_recent_history_without_tui_dependency():
    from jpnote_app.quiz.service import QuizService
    from jpnote_app.study_sources import SourceCatalog

    class Reader:
        def list_entry_snapshots(self, **kwargs):
            return ()

        def get_entry_snapshot(self, key):
            return None

        def list_attempt_replay_sources(self, **kwargs):
            return ()

        def get_attempt_replay_source(self, event_key):
            return None

        def source_catalog(self):
            return SourceCatalog(0, 0, ("N3",), ("TRY! N3",))

    class Store:
        def list_recent_sessions(self, *, limit=20):
            return (summary("quiz-session:one"),)[:limit]

    service = QuizService(Reader(), Store())
    assert service.source_catalog().levels == ("N3",)
    assert service.list_recent_sessions(limit=1)[0].session_id == "quiz-session:one"
