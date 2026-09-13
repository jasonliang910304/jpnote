from __future__ import annotations

import inspect
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from jpnote_app.quiz.question_pool import QuestionPoolPlan, QuestionPoolReport
from jpnote_app.quiz.service import (
    QUIZ_PROGRESS_BUILDING_QUESTIONS,
    QUIZ_PROGRESS_CREATING_SESSION,
    QUIZ_PROGRESS_LOADING_SOURCES,
    QUIZ_PROGRESS_OPENING_QUESTION,
    QuizService,
)
from jpnote_app.quiz.session_models import (
    AnswerSnapshot,
    GeneratedQuestionSnapshot,
    QuestionChoiceSnapshot,
)
from jpnote_app.quiz.session_store import QuizSessionStore
from jpnote_app.quiz.tui import _run_curses
from jpnote_app.quiz.tui_controller import QuizTuiController, RenderedScreen
from jpnote_app.study_sources import SourceCatalog


PROGRESS_STAGES = (
    QUIZ_PROGRESS_LOADING_SOURCES,
    QUIZ_PROGRESS_BUILDING_QUESTIONS,
    QUIZ_PROGRESS_CREATING_SESSION,
    QUIZ_PROGRESS_OPENING_QUESTION,
)


class EmptyReader:
    def list_entry_snapshots(self, **_kwargs):
        return ()

    def get_entry_snapshot(self, _key):
        return None

    def list_attempt_replay_sources(self, **_kwargs):
        return ()

    def get_attempt_replay_source(self, _event_key):
        return None

    def source_catalog(self):
        return SourceCatalog(0, 0, (), ())


class FakeWindow:
    def __init__(self, keys):
        self.keys = iter(keys)
        self.frames: list[tuple[str, ...]] = []
        self._current: list[str] = []
        self.thread_ids: list[int] = []

    def _record_thread(self) -> None:
        self.thread_ids.append(threading.get_ident())

    def getmaxyx(self):
        self._record_thread()
        return (30, 100)

    def erase(self):
        self._record_thread()
        self._current = []

    def addnstr(self, _row, _column, line, _limit):
        self._record_thread()
        self._current.append(line)

    def refresh(self):
        self._record_thread()
        self.frames.append(tuple(self._current))

    def keypad(self, _enabled):
        self._record_thread()

    def get_wch(self):
        self._record_thread()
        value = next(self.keys)
        if isinstance(value, BaseException):
            raise value
        return value


class ProgressService:
    def __init__(self) -> None:
        self.reporter = None

    @contextmanager
    def progress_reporting(self, reporter):
        previous = self.reporter
        self.reporter = reporter
        try:
            yield
        finally:
            self.reporter = previous

    def report(self, stage: str) -> None:
        assert self.reporter is not None
        self.reporter(stage)


class ProgressController:
    def __init__(self, *, fail: bool = False, shortage: bool = False) -> None:
        self.service = ProgressService()
        self.fail = fail
        self.shortage = shortage
        self.worker_thread_id: int | None = None
        self.interrupted = False
        self.state = SimpleNamespace(
            should_exit=False,
            screen="shortage" if shortage else "setup",
            setup_focus=2,
        )

    def render(self, _width: int, _height: int) -> RenderedScreen:
        return RenderedScreen(lines=("設定畫面",))

    def handle_key(self, key: str) -> None:
        assert key == "ENTER"
        self.worker_thread_id = threading.get_ident()
        stages = (
            (QUIZ_PROGRESS_CREATING_SESSION, QUIZ_PROGRESS_OPENING_QUESTION)
            if self.shortage
            else PROGRESS_STAGES
        )
        for stage in stages:
            self.service.report(stage)
        if self.fail:
            raise RuntimeError("worker failed")
        self.state.should_exit = True

    def interrupt_active_session(self) -> None:
        self.interrupted = True


def _patch_curses(monkeypatch) -> None:
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.start_color", lambda: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.use_default_colors", lambda: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.curs_set", lambda _value: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.mousemask", lambda _value: None)


def _one_question_plan() -> QuestionPoolPlan:
    question = GeneratedQuestionSnapshot(
        question_type="vocab_meaning_true_false",
        generator_version="test",
        source_kind="vocabulary",
        source_key="vocab:試験",
        prompt="試験の意味はテストですか。",
        choices=(
            QuestionChoiceSnapshot("true", "○"),
            QuestionChoiceSnapshot("false", "×"),
        ),
        correct_answer=AnswerSnapshot("true", "○"),
    )
    return QuestionPoolPlan(
        questions=(question,),
        report=QuestionPoolReport(
            mode="vocabulary",
            requested_count=1,
            available_count=1,
            selected_count=1,
            vocabulary_source_count=1,
            mistake_source_count=0,
            vocabulary_available_count=1,
            mistake_available_count=0,
            skipped_vocabulary_source_count=0,
            skipped_mistake_source_count=0,
        ),
    )


def test_dynamic_loading_keeps_curses_on_main_thread(monkeypatch) -> None:
    _patch_curses(monkeypatch)
    main_thread_id = threading.get_ident()
    controller = ProgressController()
    window = FakeWindow(["\n"])

    assert _run_curses(window, controller) == 0
    assert controller.worker_thread_id is not None
    assert controller.worker_thread_id != main_thread_id
    assert window.thread_ids
    assert set(window.thread_ids) == {main_thread_id}

    rendered = "\n".join(line for frame in window.frames for line in frame)
    for label in ("讀取題庫", "生成安全題目", "建立測驗紀錄", "開啟第一題"):
        assert label in rendered


def test_shortage_confirmation_uses_loading_worker(monkeypatch) -> None:
    _patch_curses(monkeypatch)
    controller = ProgressController(shortage=True)
    window = FakeWindow(["\n"])

    assert _run_curses(window, controller) == 0
    rendered = "\n".join(line for frame in window.frames for line in frame)
    assert "建立測驗紀錄" in rendered
    assert "開啟第一題" in rendered
    assert "讀取題庫" not in rendered
    assert "生成安全題目" not in rendered


def test_worker_exception_propagates_and_preserves_interruption_hook(monkeypatch) -> None:
    _patch_curses(monkeypatch)
    controller = ProgressController(fail=True)
    window = FakeWindow(["\n"])

    with pytest.raises(RuntimeError, match="worker failed"):
        _run_curses(window, controller)
    assert controller.interrupted


def test_real_quiz_store_can_be_started_from_worker_thread(tmp_path) -> None:
    service = QuizService(EmptyReader(), QuizSessionStore(tmp_path / "quiz.db"))
    plan = _one_question_plan()
    stages: list[str] = []
    errors: list[BaseException] = []
    result = []

    def worker() -> None:
        try:
            with service.progress_reporting(stages.append):
                started = service.start_planned_session(plan)
                assert started.session is not None
                result.append(started)
                assert service.current_question(started.session.summary.session_id) is not None
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert errors == []
    assert len(result) == 1
    assert stages == [QUIZ_PROGRESS_CREATING_SESSION, QUIZ_PROGRESS_OPENING_QUESTION]
    session_id = result[0].session.summary.session_id
    assert service.get_session(session_id).summary.state == "active"



def test_persisted_session_is_marked_interrupted_if_first_question_load_fails(
    tmp_path, monkeypatch
) -> None:
    _patch_curses(monkeypatch)
    service = QuizService(EmptyReader(), QuizSessionStore(tmp_path / "quiz.db"))
    plan = _one_question_plan()
    controller = QuizTuiController(
        service,
        default_mode="vocabulary",
        default_count=1,
        seed_factory=lambda: "dynamic-loading-test",
    )
    controller.state.setup_focus = 2

    def start_from_prebuilt_plan(**_kwargs):
        return service.start_planned_session(plan)

    original_current_question = service.current_question

    def fail_after_open(session_id: str):
        original_current_question(session_id)
        raise RuntimeError("first question load failed")

    monkeypatch.setattr(service, "start_session", start_from_prebuilt_plan)
    monkeypatch.setattr(service, "current_question", fail_after_open)

    with pytest.raises(RuntimeError, match="first question load failed"):
        _run_curses(FakeWindow(["\n"]), controller)

    assert controller.state.session_id
    saved = service.get_session(controller.state.session_id)
    assert saved.summary.state == "interrupted"


def test_progress_observer_failure_does_not_change_quiz_semantics(tmp_path) -> None:
    service = QuizService(EmptyReader(), QuizSessionStore(tmp_path / "quiz.db"))
    plan = _one_question_plan()

    def broken_reporter(_stage: str) -> None:
        raise RuntimeError("renderer unavailable")

    with service.progress_reporting(broken_reporter):
        started = service.start_planned_session(plan)
        assert started.session is not None
        assert service.current_question(started.session.summary.session_id) is not None


def test_bounded_controller_cleanup_keeps_service_compatibility_surface() -> None:
    controller_parameters = inspect.signature(QuizTuiController._start_session).parameters
    service_parameters = inspect.signature(QuizService.start_session).parameters
    assert tuple(controller_parameters) == ("self",)
    assert "allow_shortage" in service_parameters
