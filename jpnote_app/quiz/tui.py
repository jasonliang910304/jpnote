"""Python-native curses adapter for the optional jpnote Quiz TUI.

Business logic remains in :mod:`jpnote_app.quiz.service`; semantic UI state and
rendering remain in :mod:`jpnote_app.quiz.tui_controller`.  Importing core
jpnote never imports this module.  The adapter uses only the Python standard
library and therefore adds no mandatory dependency to the core installation.
"""
from __future__ import annotations

import curses
import locale
import sys
from collections.abc import Sequence
from typing import Any

from jpnote_app.study_sources import StudySourceService

from .service import QuizService
from .session_store import QuizSessionStore
from .tui_controller import QuizTuiController, RenderedScreen


def _service() -> QuizService:
    return QuizService(StudySourceService.from_default_core(), QuizSessionStore())


def _normalize_key(value: object) -> str:
    key_map = {
        curses.KEY_UP: "UP",
        curses.KEY_DOWN: "DOWN",
        curses.KEY_LEFT: "LEFT",
        curses.KEY_RIGHT: "RIGHT",
        curses.KEY_ENTER: "ENTER",
        curses.KEY_BACKSPACE: "BACKSPACE",
        curses.KEY_DC: "DELETE",
        10: "ENTER",
        13: "ENTER",
        27: "ESC",
        127: "BACKSPACE",
    }
    if value in key_map:
        return key_map[value]
    if isinstance(value, str):
        if value in {"\n", "\r"}:
            return "ENTER"
        if value == "\x1b":
            return "ESC"
        if value in {"\b", "\x7f"}:
            return "BACKSPACE"
        if value == " ":
            return "SPACE"
        return value
    return ""


def _draw(stdscr: curses.window, screen: RenderedScreen) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    for row, line in enumerate(screen.lines[:height]):
        try:
            stdscr.addnstr(row, 0, line, max(0, width - 1))
        except curses.error:
            pass
    stdscr.refresh()


def _mouse_target(screen: RenderedScreen) -> str | None:
    try:
        _, _, y, _, button_state = curses.getmouse()
    except curses.error:
        return None
    click_mask = (
        getattr(curses, "BUTTON1_CLICKED", 0)
        | getattr(curses, "BUTTON1_PRESSED", 0)
        | getattr(curses, "BUTTON1_RELEASED", 0)
    )
    if not button_state & click_mask:
        return None
    return screen.target_for_row(y)


def _configure_default_background(*, transparent_background: bool) -> None:
    """Keep cells on the terminal's default background when supported.

    Terminal emulators such as kitty only apply their configured opacity to
    cells using the terminal default background.  This is a best-effort ncurses
    capability and therefore must never make Quiz startup fail.
    """

    if not transparent_background:
        return
    try:
        curses.start_color()
        curses.use_default_colors()
    except (AttributeError, curses.error):
        pass


def _starts_slow_session_action(controller: QuizTuiController, key: str) -> bool:
    state = controller.state
    if state.screen == "setup":
        return key in {"ENTER", "SPACE"} and state.setup_focus >= 2
    if state.screen == "shortage":
        return key in {"ENTER", "SPACE", "y"}
    return False


def _preparing_screen() -> RenderedScreen:
    return RenderedScreen(
        lines=(
            "正在準備題目……",
            "",
            "正在讀取題庫、生成安全選項並建立測驗紀錄。",
        )
    )


def _run_curses(
    stdscr: curses.window,
    controller: QuizTuiController,
    transparent_background: bool = True,
) -> int:
    _configure_default_background(
        transparent_background=transparent_background,
    )
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
    except curses.error:
        pass

    try:
        while not controller.state.should_exit:
            height, width = stdscr.getmaxyx()
            screen = controller.render(width, height)
            _draw(stdscr, screen)
            value = stdscr.get_wch()
            if value == curses.KEY_MOUSE:
                target = _mouse_target(screen)
                if target is not None:
                    controller.handle_click(target)
                continue
            key = _normalize_key(value)
            if key:
                if _starts_slow_session_action(controller, key):
                    _draw(stdscr, _preparing_screen())
                controller.handle_key(key)
    except BaseException:
        controller.interrupt_active_session()
        raise
    return 0


def _prune_history_if_configured(
    service: Any,
    *,
    enabled: bool,
    cap_bytes: int,
) -> None:
    if not enabled:
        return
    store = getattr(service, "session_store", None)
    prune = getattr(store, "prune_details", None)
    if not callable(prune):
        return
    try:
        prune(cap_bytes=cap_bytes)
    except Exception:
        # Retention is best-effort at the UI boundary. A pruning failure must
        # never turn a completed or paused Quiz into a core CLI failure.
        pass


def run(
    *,
    service: QuizService | None = None,
    default_mode: str = "mixed",
    default_count: int = 10,
    default_levels: Sequence[str] = (),
    default_sources: Sequence[str] = (),
    transparent_background: bool = True,
    history_detail_cap_bytes: int = 100 * 1024 * 1024,
    prune_after_session: bool = True,
) -> int:
    locale.setlocale(locale.LC_ALL, "")
    quiz_service = service or _service()
    controller = QuizTuiController(
        quiz_service,
        default_mode=default_mode,
        default_count=default_count,
        default_levels=default_levels,
        default_sources=default_sources,
    )
    try:
        return curses.wrapper(
            _run_curses,
            controller,
            transparent_background,
        )
    finally:
        _prune_history_if_configured(
            quiz_service,
            enabled=prune_after_session,
            cap_bytes=history_detail_cap_bytes,
        )


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        print("jpnote Quiz TUI 目前不接受命令列參數", file=sys.stderr)
        return 2
    try:
        return run()
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        print(f"無法啟動 Quiz TUI：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Quiz TUI 發生錯誤：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
