"""Phase 1 Quiz runtime shell.

No generators, session storage, CLI adapter, or TUI live here yet.  This layer
only verifies the optional package can consume the stable core read contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..study_sources import QuestionSourceReader, StudySourceService


@dataclass(frozen=True, slots=True)
class QuizRuntimeStatus:
    ready: bool
    entry_sources: int = 0
    replayable_attempt_sources: int = 0
    error: str = ""


class QuizRuntime:
    def __init__(self, source_reader: QuestionSourceReader):
        if not isinstance(source_reader, QuestionSourceReader):
            raise TypeError("source_reader 必須實作 QuestionSourceReader")
        self._source_reader = source_reader

    @property
    def source_reader(self) -> QuestionSourceReader:
        return self._source_reader

    def probe(self) -> QuizRuntimeStatus:
        """Check source availability without allowing failures to escape."""

        try:
            catalog = self._source_reader.source_catalog()
        except Exception as exc:
            return QuizRuntimeStatus(ready=False, error=f"Quiz 題目來源不可用：{exc}")
        return QuizRuntimeStatus(
            ready=True,
            entry_sources=catalog.entry_count,
            replayable_attempt_sources=catalog.replayable_attempt_count,
        )


def create_runtime(source_reader: QuestionSourceReader | None = None) -> QuizRuntime:
    return QuizRuntime(source_reader or StudySourceService.from_default_core())
