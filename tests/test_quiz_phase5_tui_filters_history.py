from __future__ import annotations

from pathlib import Path
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
        self.exports: list[dict[str, object]] = []
        self.deleted: list[tuple[str, bool]] = []
        self.delete_all_calls: list[bool] = []

    def source_catalog(self):
        return SimpleNamespace(
            levels=("N3", "N5", "unclassified"),
            sources=("TRY! N3", "今日練習", "TRY! N3"),
        )

    def list_resumable_sessions(self, *, limit: int = 20):
        return ()

    def list_recent_sessions(self, *, limit: int = 20):
        return self.recent[:limit]

    def export_history_json(
        self,
        path,
        *,
        session_id=None,
        start_date=None,
        end_date=None,
        include_abandoned=True,
    ):
        call = {
            "path": Path(path),
            "session_id": session_id,
            "start_date": start_date,
            "end_date": end_date,
            "include_abandoned": include_abandoned,
        }
        self.exports.append(call)
        return Path(path)

    def delete_history_session(self, session_id: str, *, include_resumable=False):
        item = next(value for value in self.recent if value.session_id == session_id)
        self.deleted.append((session_id, include_resumable))
        self.recent = tuple(
            value for value in self.recent if value.session_id != session_id
        )
        return item

    def delete_all_history(self, *, include_resumable=False):
        self.delete_all_calls.append(include_resumable)
        ids = tuple(value.session_id for value in self.recent)
        self.recent = ()
        return ids

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
    return QuizTuiController(
        FakeService(),
        seed_factory=lambda: "seed",
        history_export_path_factory=lambda scope: Path(
            f"/tmp/jpnote-quiz-history-{scope}.json"
        ),
    )


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

def test_history_export_all_and_selected_session_use_service_boundary():
    ui = controller()
    service = ui.service
    ui.handle_key("H")

    ui.handle_key("e")
    assert service.exports[-1]["session_id"] is None
    assert service.exports[-1]["path"].name == "jpnote-quiz-history-all.json"
    assert "已匯出" in ui.state.history_notice

    ui.handle_key("ENTER")
    assert ui.state.screen == "history_detail"
    ui.handle_key("e")
    assert service.exports[-1]["session_id"] == "quiz-session:completed"
    assert service.exports[-1]["path"].name == "jpnote-quiz-history-session.json"


def test_history_date_range_export_collects_dates_and_abandoned_toggle():
    ui = controller()
    service = ui.service
    ui.handle_key("H")
    ui.handle_key("r")
    assert ui.state.screen == "history_export_range"

    for char in "2026-07-20":
        ui.handle_key(char)
    ui.handle_key("DOWN")
    for char in "2026-07-24":
        ui.handle_key(char)
    ui.handle_key("a")
    ui.handle_key("ENTER")

    assert ui.state.screen == "history"
    call = service.exports[-1]
    assert call["start_date"] == "2026-07-20"
    assert call["end_date"] == "2026-07-24"
    assert call["include_abandoned"] is False
    assert call["path"].name == "jpnote-quiz-history-range.json"


def test_history_single_delete_requires_explicit_y_and_protects_cancel():
    ui = controller()
    service = ui.service
    ui.handle_key("H")
    ui.handle_key("x")
    assert ui.state.screen == "history_delete_confirm"
    ui.handle_key("ENTER")
    assert ui.state.screen == "history"
    assert service.deleted == []

    ui.handle_key("x")
    ui.handle_key("y")
    assert service.deleted == [("quiz-session:completed", False)]
    assert all(
        item.session_id != "quiz-session:completed"
        for item in ui.state.history_sessions
    )
    assert "已刪除" in ui.state.history_notice


def test_history_resumable_delete_requires_explicit_resumable_permission():
    ui = controller()
    service = ui.service
    ui.handle_key("H")
    ui.state.history_cursor = 1
    ui.handle_key("x")
    assert ui.state.history_pending_delete_include_resumable is True
    rendered = "\n".join(ui.render(100, 30).lines)
    assert "仍可恢復" in rendered
    ui.handle_key("y")
    assert service.deleted == [("quiz-session:paused", True)]


def test_history_delete_all_is_uppercase_and_explicitly_confirmed():
    ui = controller()
    service = ui.service
    ui.handle_key("H")
    ui.handle_key("X")
    assert ui.state.screen == "history_delete_all_confirm"
    ui.handle_key("n")
    assert service.delete_all_calls == []

    ui.handle_key("X")
    ui.handle_key("y")
    assert service.delete_all_calls == [True]
    assert ui.state.history_sessions == ()
    assert "已清除 2 場" in ui.state.history_notice


def test_quiz_service_wraps_store_history_management_methods():
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
            return SourceCatalog(0, 0, (), ())

    class Store:
        def __init__(self):
            self.calls = []

        def write_history_json(self, path, **kwargs):
            self.calls.append(("export", Path(path), kwargs))
            return Path(path)

        def delete_session(self, session_id, **kwargs):
            self.calls.append(("delete", session_id, kwargs))
            return summary(session_id)

        def delete_all_history(self, **kwargs):
            self.calls.append(("delete_all", kwargs))
            return ("quiz-session:one",)

    store = Store()
    service = QuizService(Reader(), store)
    path = service.export_history_json(
        "/tmp/history.json",
        start_date="2026-07-20",
        end_date="2026-07-24",
        include_abandoned=False,
    )
    assert path == Path("/tmp/history.json")
    deleted = service.delete_history_session(
        "quiz-session:one",
        include_resumable=True,
    )
    assert deleted.session_id == "quiz-session:one"
    assert service.delete_all_history(include_resumable=True) == (
        "quiz-session:one",
    )
    assert store.calls == [
        (
            "export",
            Path("/tmp/history.json"),
            {
                "session_id": None,
                "start_date": "2026-07-20",
                "end_date": "2026-07-24",
                "include_abandoned": False,
            },
        ),
        (
            "delete",
            "quiz-session:one",
            {"include_resumable": True},
        ),
        ("delete_all", {"include_resumable": True}),
    ]
