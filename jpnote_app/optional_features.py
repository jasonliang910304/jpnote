"""Fault-isolated loaders for optional jpnote extensions."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any


@dataclass(frozen=True, slots=True)
class OptionalFeatureLoad:
    name: str
    available: bool
    value: Any = None
    error: str = ""


def load_quiz_runtime(source_reader: Any = None) -> OptionalFeatureLoad:
    """Load Quiz only when explicitly requested.

    Import and runtime construction failures are converted into an unavailable
    feature result.  Core startup and data operations never import Quiz through
    this module unless the caller explicitly invokes this function.
    """

    try:
        quiz_module = import_module("jpnote_app.quiz")
        runtime = quiz_module.create_runtime(source_reader=source_reader)
    except Exception as exc:
        return OptionalFeatureLoad(
            name="quiz",
            available=False,
            error=f"Quiz 無法啟用：{exc}",
        )
    return OptionalFeatureLoad(name="quiz", available=True, value=runtime)
