from __future__ import annotations

from types import SimpleNamespace

from jpnote_app.quiz.tui import _run_curses
from jpnote_app.quiz.tui_controller import RenderedScreen


class FakeWindow:
    def __init__(self) -> None:
        self.frames: list[tuple[str, ...]] = []
        self._current: list[str] = []
        self._keys = iter(["\n"])

    def getmaxyx(self):
        return (20, 100)

    def erase(self):
        self._current = []

    def addnstr(self, _row, _column, line, _limit):
        self._current.append(line)

    def refresh(self):
        self.frames.append(tuple(self._current))

    def keypad(self, _enabled):
        pass

    def get_wch(self):
        return next(self._keys)


class SlowStartController:
    def __init__(self, window: FakeWindow) -> None:
        self.window = window
        self.state = SimpleNamespace(
            should_exit=False,
            screen="setup",
            setup_focus=2,
        )

    def render(self, _width: int, _height: int) -> RenderedScreen:
        return RenderedScreen(lines=("設定畫面",))

    def handle_key(self, key: str) -> None:
        assert key == "ENTER"
        assert any("正在準備題目" in line for frame in self.window.frames for line in frame)
        self.state.should_exit = True

    def interrupt_active_session(self) -> None:
        pass


def test_curses_refreshes_preparing_message_before_synchronous_start(monkeypatch) -> None:
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.start_color", lambda: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.use_default_colors", lambda: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.curs_set", lambda _value: None)
    monkeypatch.setattr("jpnote_app.quiz.tui.curses.mousemask", lambda _value: None)
    window = FakeWindow()
    controller = SlowStartController(window)
    assert _run_curses(window, controller) == 0
    assert any("正在準備題目" in line for frame in window.frames for line in frame)
