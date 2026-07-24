"""Pure menu helpers for the optional Quiz TUI.

These helpers contain no curses or storage dependency.  They keep filter and
history navigation deterministic and easy to test without opening a terminal.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from .session_models import QuizSessionSummary

LEVEL_ORDER = ("N5", "N4", "N3", "N2", "N1", "unclassified")
LEVEL_LABELS = {
    "N5": "N5",
    "N4": "N4",
    "N3": "N3",
    "N2": "N2",
    "N1": "N1",
    "unclassified": "未分類",
}
RESUMABLE_STATES = frozenset({"active", "paused", "interrupted"})


def ordered_levels(values: Iterable[str]) -> tuple[str, ...]:
    """Return unique levels in the stable TUI order."""

    unique = {str(value).strip() for value in values if str(value).strip()}
    ordered = [level for level in LEVEL_ORDER if level in unique]
    ordered.extend(sorted(unique - set(LEVEL_ORDER)))
    return tuple(ordered)


def normalized_options(values: Iterable[str]) -> tuple[str, ...]:
    """Return unique, non-empty options in stable lexical order."""

    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def toggle_selected(selected: Sequence[str], value: str) -> tuple[str, ...]:
    """Toggle one value while preserving the surrounding option order later."""

    current = list(dict.fromkeys(selected))
    if value in current:
        current.remove(value)
    else:
        current.append(value)
    return tuple(current)


def session_line(summary: QuizSessionSummary) -> str:
    """Compact human-readable history row."""

    accuracy = f"{summary.accuracy * 100:.0f}%"
    state_labels = {
        "active": "進行中",
        "paused": "已暫停",
        "interrupted": "已中斷",
        "completed": "已完成",
        "abandoned": "已放棄",
    }
    state = state_labels.get(summary.state, summary.state)
    return (
        f"{summary.started_at[:16].replace('T', ' ')}｜{summary.mode}｜"
        f"{summary.answered_count}/{summary.question_count}｜{state}｜{accuracy}"
    )


def can_resume(summary: QuizSessionSummary) -> bool:
    return summary.state in RESUMABLE_STATES
