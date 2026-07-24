from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jpnote_app.quiz.service import QuizService
from jpnote_app.quiz.session_store import QuizSessionStore
from jpnote_app.quiz.tui import (
    _configure_default_background,
    _normalize_key,
    _run_curses,
)
from jpnote_app.quiz.tui_controller import (
    MAX_QUESTION_COUNT,
    MIN_QUESTION_COUNT,
    QuizTuiController,
    _cell_width,
    _wrap_cells,
)
from jpnote_app.study_sources import (
    AttemptCapabilities,
    AttemptReplaySource,
    EntryCapabilities,
    EntrySnapshot,
    ReorderPartSnapshot,
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

    def list_entry_snapshots(self, **kwargs):
        return self.entries

    def get_entry_snapshot(self, key):
        return next((entry for entry in self.entries if entry.key == key), None)

    def list_attempt_replay_sources(self, **kwargs):
        return self.attempts

    def get_attempt_replay_source(self, event_key):
        return next(
            (attempt for attempt in self.attempts if attempt.event_key == event_key),
            None,
        )

    def source_catalog(self):
        return SourceCatalog(
            entry_count=len(self.entries),
            replayable_attempt_count=len(self.attempts),
            levels=("N3", "N4"),
            sources=("測試來源", "錯題來源"),
        )


def make_service(tmp_path: Path, *, entries=(), attempts=()) -> QuizService:
    return QuizService(
        FakeReader(entries=entries, attempts=attempts),
        QuizSessionStore(tmp_path / "quiz.db"),
    )


def make_controller(tmp_path: Path, *, entries=(), attempts=(), count=2):
    service = make_service(tmp_path, entries=entries, attempts=attempts)
    controller = QuizTuiController(
        service,
        default_count=count,
        seed_factory=lambda: "tui-test-seed",
    )
    return controller, service


def start_from_setup(controller: QuizTuiController, *, mode="vocabulary") -> None:
    controller.state.mode = mode
    controller.state.setup_focus = 2
    controller.handle_key("ENTER")


def test_starts_on_setup_without_resumable_sessions(tmp_path):
    controller, _ = make_controller(tmp_path)
    assert controller.state.screen == "setup"
    assert controller.state.mode == "mixed"
    assert controller.state.requested_count == 2


def test_default_count_validation(tmp_path):
    service = make_service(tmp_path)
    with pytest.raises(ValueError):
        QuizTuiController(service, default_count=0)
    with pytest.raises(ValueError):
        QuizTuiController(service, default_count=101)
    with pytest.raises(TypeError):
        QuizTuiController(service, default_count=True)


def test_setup_mode_and_count_controls_are_bounded(tmp_path):
    controller, _ = make_controller(tmp_path, count=1)
    controller.handle_key("2")
    assert controller.state.mode == "vocabulary"
    controller.state.setup_focus = 1
    controller.handle_key("LEFT")
    assert controller.state.requested_count == MIN_QUESTION_COUNT
    controller.state.requested_count = MAX_QUESTION_COUNT
    controller.handle_key("RIGHT")
    assert controller.state.requested_count == MAX_QUESTION_COUNT


def test_setup_enter_advances_focus_instead_of_changing_values(tmp_path):
    controller, _ = make_controller(tmp_path, count=7)
    original_mode = controller.state.mode
    controller.handle_key("ENTER")
    assert controller.state.setup_focus == 1
    assert controller.state.mode == original_mode
    controller.handle_key("ENTER")
    assert controller.state.setup_focus == 2
    assert controller.state.requested_count == 7


def test_start_enters_question_screen(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    assert controller.state.screen == "question"
    assert controller.state.session_id.startswith("quiz-session:")
    assert controller.state.current_question is not None


def test_shortage_requires_tui_confirmation_and_reuses_seed(tmp_path):
    controller, _ = make_controller(
        tmp_path, attempts=(reorder_attempt(),), count=10
    )
    start_from_setup(controller, mode="mistake")
    assert controller.state.screen == "shortage"
    assert controller.state.shortage_result is not None
    assert controller.state.shortage_result.plan.report.selected_count == 1
    controller.handle_key("ENTER")
    assert controller.state.screen == "question"
    assert controller.state.current_question is not None


def test_no_safe_questions_shows_message(tmp_path):
    controller, _ = make_controller(tmp_path, count=3)
    start_from_setup(controller)
    assert controller.state.screen == "message"
    assert "沒有可安全生成" in controller.state.message
    controller.handle_key("ENTER")
    assert controller.state.screen == "setup"


def test_arrow_space_enter_submits_selected_choice(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    event = controller.state.current_question
    assert event is not None
    controller.handle_key("DOWN")
    selected = event.question.choices[1].choice_id
    controller.handle_key("SPACE")
    assert controller.state.armed_choice_id == selected
    controller.handle_key("ENTER")
    assert controller.state.screen == "feedback"
    assert controller.state.feedback is not None
    assert controller.state.feedback.question.user_answer is not None
    assert controller.state.feedback.question.user_answer.answer_id == selected


def test_numeric_key_directly_submits_choice(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    event = controller.state.current_question
    assert event is not None
    expected = event.question.choices[0].choice_id
    controller.handle_key("1")
    assert controller.state.screen == "feedback"
    assert controller.state.feedback is not None
    assert controller.state.feedback.question.user_answer.answer_id == expected


def test_skip_is_persisted_and_feedback_shows_skip(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=1
    )
    start_from_setup(controller)
    controller.handle_key("s")
    assert controller.state.screen == "feedback"
    assert controller.state.feedback is not None
    assert controller.state.feedback.skipped
    assert controller.state.feedback.question.result == "skipped"


def test_reorder_space_backspace_and_enter(tmp_path):
    controller, _ = make_controller(
        tmp_path, attempts=(reorder_attempt(),), count=1
    )
    start_from_setup(controller, mode="mistake")
    event = controller.state.current_question
    assert event is not None
    assert event.question.question_type == "mistake_reorder_4"
    controller.handle_key("SPACE")
    controller.handle_key("DOWN")
    controller.handle_key("SPACE")
    assert len(controller.state.reorder_choice_ids) == 2
    controller.handle_key("BACKSPACE")
    assert len(controller.state.reorder_choice_ids) == 1
    for key in ("2", "3", "4"):
        controller.handle_key(key)
    controller.handle_key("ENTER")
    assert controller.state.screen == "feedback"
    assert controller.state.feedback is not None
    assert controller.state.feedback.correct


def test_reorder_screen_explains_backspace(tmp_path):
    controller, _ = make_controller(
        tmp_path, attempts=(reorder_attempt(),), count=1
    )
    start_from_setup(controller, mode="mistake")
    screen = controller.render(120, 40)
    assert any("Backspace 退回上一個片段" in line for line in screen.lines)


def test_reorder_enter_before_all_parts_keeps_question(tmp_path):
    controller, _ = make_controller(
        tmp_path, attempts=(reorder_attempt(),), count=1
    )
    start_from_setup(controller, mode="mistake")
    controller.handle_key("SPACE")
    controller.handle_key("ENTER")
    assert controller.state.screen == "question"
    assert "全部四個" in controller.state.message


def test_feedback_details_uses_stable_source_reader(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=1
    )
    start_from_setup(controller)
    controller.handle_key("1")
    controller.handle_key("d")
    assert controller.state.screen == "details"
    assert controller.state.source_details is not None
    assert controller.state.source_details.status == "available"
    assert controller.state.source_details.source_key.startswith("vocab:")
    controller.handle_key("ENTER")
    assert controller.state.screen == "feedback"


def test_feedback_always_shows_useful_correct_vocabulary_content(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=1
    )
    start_from_setup(controller)
    event = controller.state.current_question
    assert event is not None
    correct_id = event.question.correct_answer.answer_id
    controller.handle_key(
        str(
            next(
                index + 1
                for index, choice in enumerate(event.question.choices)
                if choice.choice_id == correct_id
            )
        )
    )
    assert controller.state.screen == "feedback"
    screen = controller.render(120, 40)
    rendered = "\n".join(screen.lines)
    assert "詞彙：" in rendered
    assert "正確意思：" in rendered or "正確讀音：" in rendered


def test_feedback_advance_finishes_last_question(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=1
    )
    start_from_setup(controller)
    controller.handle_key("1")
    controller.handle_key("ENTER")
    assert controller.state.screen == "result"
    assert controller.state.result is not None
    assert controller.state.result.completed_count == 1


def test_exit_menu_pause_persists_resumable_state(tmp_path):
    controller, service = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    session_id = controller.state.session_id
    controller.handle_key("q")
    assert controller.state.screen == "exit_menu"
    controller.handle_key("ENTER")
    assert controller.state.should_exit
    assert service.get_session(session_id).summary.state == "paused"


def test_exit_menu_abandon_persists_terminal_state(tmp_path):
    controller, service = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    session_id = controller.state.session_id
    controller.handle_key("q")
    controller.handle_key("DOWN")
    controller.handle_key("ENTER")
    assert controller.state.should_exit
    assert service.get_session(session_id).summary.state == "abandoned"


def test_exit_menu_cancel_returns_to_question(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    controller.handle_key("q")
    controller.handle_key("3")
    assert controller.state.screen == "question"
    assert not controller.state.should_exit


def test_resume_prompt_continues_original_snapshot(tmp_path):
    service = make_service(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6))
    )
    started = service.start_session(
        mode="vocabulary", requested_count=2, seed=1, allow_shortage=True
    )
    assert started.session is not None
    saved = service.pause_session(started.session.summary.session_id)
    controller = QuizTuiController(service, seed_factory=lambda: "unused")
    assert controller.state.screen == "resume"
    controller.handle_key("ENTER")
    assert controller.state.screen == "question"
    assert controller.state.session_id == saved.summary.session_id
    assert controller.state.current_question == saved.remaining_questions[0]


def test_resume_prompt_can_exit_without_changing_session(tmp_path):
    service = make_service(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6))
    )
    started = service.start_session(
        mode="vocabulary", requested_count=1, seed=3, allow_shortage=True
    )
    assert started.session is not None
    service.pause_session(started.session.summary.session_id)
    controller = QuizTuiController(service)
    controller.handle_key("q")
    assert controller.state.should_exit
    assert service.get_session(started.session.summary.session_id).summary.state == "paused"


def test_resume_prompt_abandon_removes_selected_session(tmp_path):
    service = make_service(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6))
    )
    started = service.start_session(
        mode="vocabulary", requested_count=1, seed=2, allow_shortage=True
    )
    assert started.session is not None
    service.pause_session(started.session.summary.session_id)
    controller = QuizTuiController(service)
    controller.handle_key("a")
    assert controller.state.screen == "setup"
    assert service.get_session(started.session.summary.session_id).summary.state == "abandoned"


def test_interrupt_active_session_is_best_effort(tmp_path):
    controller, service = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    session_id = controller.state.session_id
    controller.interrupt_active_session()
    assert service.get_session(session_id).summary.state == "interrupted"


def test_render_contains_mouse_target_for_each_choice(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    screen = controller.render(100, 40)
    event = controller.state.current_question
    assert event is not None
    targets = {target for _, target in screen.click_targets}
    assert targets == {
        f"choice:{choice.choice_id}" for choice in event.question.choices
    }


def test_render_is_clipped_for_small_terminal(tmp_path):
    controller, _ = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    screen = controller.render(20, 8)
    assert len(screen.lines) <= 8
    assert all(_cell_width(line) <= 20 for line in screen.lines[:-1])


def test_east_asian_cell_width_and_wrapping():
    assert _cell_width("ABC") == 3
    assert _cell_width("資料") == 4
    wrapped = _wrap_cells("資料資料資料", 4)
    assert wrapped == ["資料", "資料", "資料"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (10, "ENTER"),
        (27, "ESC"),
        (127, "BACKSPACE"),
        (" ", "SPACE"),
        ("1", "1"),
    ],
)
def test_curses_key_normalization(raw, expected):
    assert _normalize_key(raw) == expected


def test_default_background_is_enabled_best_effort(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "jpnote_app.quiz.tui.curses.start_color",
        lambda: calls.append("start"),
    )
    monkeypatch.setattr(
        "jpnote_app.quiz.tui.curses.use_default_colors",
        lambda: calls.append("default"),
    )
    _configure_default_background(transparent_background=True)
    assert calls == ["start", "default"]
    calls.clear()
    _configure_default_background(transparent_background=False)
    assert calls == []


class FakeWindow:
    def __init__(self, keys):
        self.keys = iter(keys)
        self.lines: list[tuple[int, str]] = []

    def getmaxyx(self):
        return (30, 100)

    def erase(self):
        self.lines.clear()

    def addnstr(self, row, _column, line, _limit):
        self.lines.append((row, line))

    def refresh(self):
        pass

    def keypad(self, _enabled):
        pass

    def get_wch(self):
        value = next(self.keys)
        if isinstance(value, BaseException):
            raise value
        return value


def test_curses_loop_can_exit_from_setup(tmp_path, monkeypatch):
    controller, _ = make_controller(tmp_path)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.start_color", lambda: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.use_default_colors", lambda: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.curs_set", lambda _value: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.mousemask", lambda _value: None)
    window = FakeWindow(["q"])
    assert _run_curses(window, controller) == 0
    assert controller.state.should_exit
    assert window.lines


def test_curses_loop_marks_active_session_interrupted_on_failure(
    tmp_path, monkeypatch
):
    controller, service = make_controller(
        tmp_path, entries=tuple(vocab(index) for index in range(1, 6)), count=2
    )
    start_from_setup(controller)
    session_id = controller.state.session_id
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.start_color", lambda: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.use_default_colors", lambda: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.curs_set", lambda _value: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.mousemask", lambda _value: None)
    window = FakeWindow([RuntimeError("terminal failed")])
    with pytest.raises(RuntimeError, match="terminal failed"):
        _run_curses(window, controller)
    assert service.get_session(session_id).summary.state == "interrupted"


def test_tui_modules_do_not_import_core_internal_storage_or_cli():
    quiz_dir = Path(__file__).parents[1] / "jpnote_app" / "quiz"
    violations: list[str] = []
    forbidden = {"jpnote_app.db", "jpnote_app.repository", "jpnote_app.cli"}
    for filename in ("tui_controller.py", "tui.py"):
        tree = ast.parse((quiz_dir / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden:
                        violations.append(f"{filename}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "") in forbidden:
                    violations.append(f"{filename}: from {node.module}")
    assert violations == []
