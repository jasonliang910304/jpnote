"""Stable, read-only study-source contracts for optional extensions.

This module is part of the jpnote core boundary.  Optional features such as
Quiz may depend on the immutable snapshots defined here, but must not reach
through this boundary into SQLite tables, repository row IDs, or CLI-private
handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence, runtime_checkable


class QuestionSourceUnavailableError(RuntimeError):
    """Raised when a public question source cannot be read safely."""


@dataclass(frozen=True, slots=True)
class SenseSnapshot:
    meaning: str
    example_ja: str = ""
    example_zh: str = ""


@dataclass(frozen=True, slots=True)
class ChoiceSnapshot:
    """A normalized replayable option without database-specific metadata."""

    option_id: int
    text: str


@dataclass(frozen=True, slots=True)
class ReorderPartSnapshot:
    part_id: int
    text: str


@dataclass(frozen=True, slots=True)
class EntryCapabilities:
    has_meaning: bool
    has_reading: bool
    has_example: bool
    has_aliases: bool


@dataclass(frozen=True, slots=True)
class AttemptCapabilities:
    has_prompt: bool
    has_correct_answer: bool
    has_choices: bool
    has_reorder_parts: bool
    has_sentence_context: bool
    structure_valid: bool


@dataclass(frozen=True, slots=True)
class EntrySnapshot:
    key: str
    entry_type: str
    display: str
    reading: str
    romaji: str
    level: str
    review_group: str
    aliases: tuple[str, ...]
    senses: tuple[SenseSnapshot, ...]
    sources: tuple[str, ...]
    accent: str = ""
    accent_type: str = ""
    accent_display: str = ""
    origin_language: str = ""
    origin_word: str = ""
    capabilities: EntryCapabilities = EntryCapabilities(False, False, False, False)


@dataclass(frozen=True, slots=True)
class AttemptReplaySource:
    event_key: str
    result: str
    attempt_date: str
    source: str
    section: str
    question: str
    question_type: str
    prompt: str
    user_answer: str
    correct_answer: str
    reason: str
    before: str
    after: str
    parts: tuple[ReorderPartSnapshot, ...]
    user_order: tuple[int, ...]
    correct_order: tuple[int, ...]
    options: tuple[ChoiceSnapshot, ...]
    linked_entry_keys: tuple[str, ...]
    linked_levels: tuple[str, ...]
    recorded_at: str
    data_warnings: tuple[str, ...]
    capabilities: AttemptCapabilities


@dataclass(frozen=True, slots=True)
class SourceCatalog:
    entry_count: int
    replayable_attempt_count: int
    levels: tuple[str, ...]
    sources: tuple[str, ...]


@runtime_checkable
class CoreReadPort(Protocol):
    """The existing public core methods used by the stable adapter."""

    def browse(
        self,
        types: list[str] | None = None,
        levels: list[str] | None = None,
        results: list[str] | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get(self, key: str) -> dict[str, Any] | None: ...

    def get_attempt(self, event_key: str) -> dict[str, Any] | None: ...


@runtime_checkable
class QuestionSourceReader(Protocol):
    """Stable public contract consumed by Quiz and future study extensions."""

    def list_entry_snapshots(
        self,
        *,
        entry_types: Sequence[str] | None = None,
        levels: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> tuple[EntrySnapshot, ...]: ...

    def get_entry_snapshot(self, key: str) -> EntrySnapshot | None: ...

    def list_attempt_replay_sources(
        self,
        *,
        results: Sequence[str] = ("wrong", "partial"),
        levels: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> tuple[AttemptReplaySource, ...]: ...

    def get_attempt_replay_source(self, event_key: str) -> AttemptReplaySource | None: ...

    def source_catalog(self) -> SourceCatalog: ...


def _text(value: Any) -> str:
    return value if isinstance(value, str) else "" if value is None else str(value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_text(item) for item in value if _text(item))


def _structured_text_snapshot(
    value: Any,
    *,
    snapshot_type: type[ChoiceSnapshot] | type[ReorderPartSnapshot],
) -> ChoiceSnapshot | ReorderPartSnapshot | None:
    if not isinstance(value, dict):
        return None
    raw_id = value.get("id")
    text = _text(value.get("text")).strip()
    if not isinstance(raw_id, int) or isinstance(raw_id, bool) or raw_id <= 0 or not text:
        return None
    if snapshot_type is ChoiceSnapshot:
        return ChoiceSnapshot(option_id=raw_id, text=text)
    return ReorderPartSnapshot(part_id=raw_id, text=text)


def _integer_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item for item in value
        if isinstance(item, int) and not isinstance(item, bool)
    )


def _entry_snapshot(data: dict[str, Any]) -> EntrySnapshot:
    senses: list[SenseSnapshot] = []
    raw_senses = data.get("senses", [])
    if isinstance(raw_senses, list):
        for raw in raw_senses:
            if not isinstance(raw, dict):
                continue
            senses.append(SenseSnapshot(
                meaning=_text(raw.get("meaning")),
                example_ja=_text(raw.get("example_ja")),
                example_zh=_text(raw.get("example_zh")),
            ))

    aliases = _string_tuple(data.get("aliases", []))
    reading = _text(data.get("reading"))
    return EntrySnapshot(
        key=_text(data.get("key")),
        entry_type=_text(data.get("type")),
        display=_text(data.get("display")),
        reading=reading,
        romaji=_text(data.get("romaji")),
        level=_text(data.get("level")),
        review_group=_text(data.get("review_group")),
        aliases=aliases,
        senses=tuple(senses),
        sources=_string_tuple(data.get("sources", [])),
        accent=_text(data.get("accent")),
        accent_type=_text(data.get("accent_type")),
        accent_display=_text(data.get("accent_display")),
        origin_language=_text(data.get("origin_language")),
        origin_word=_text(data.get("origin_word")),
        capabilities=EntryCapabilities(
            has_meaning=any(sense.meaning.strip() for sense in senses),
            has_reading=bool(reading.strip()),
            has_example=any(
                sense.example_ja.strip() or sense.example_zh.strip()
                for sense in senses
            ),
            has_aliases=bool(aliases),
        ),
    )


def _attempt_snapshot(
    data: dict[str, Any],
    *,
    linked_levels: Iterable[str] = (),
) -> AttemptReplaySource:
    raw_options = data.get("options", [])
    option_items = raw_options if isinstance(raw_options, list) else []
    options = tuple(
        choice
        for raw in option_items
        if (choice := _structured_text_snapshot(raw, snapshot_type=ChoiceSnapshot)) is not None
        and isinstance(choice, ChoiceSnapshot)
    )
    raw_parts = data.get("parts", [])
    part_items = raw_parts if isinstance(raw_parts, list) else []
    parts = tuple(
        part
        for raw in part_items
        if (part := _structured_text_snapshot(raw, snapshot_type=ReorderPartSnapshot)) is not None
        and isinstance(part, ReorderPartSnapshot)
    )
    user_order = _integer_tuple(data.get("user_order", []))
    correct_order = _integer_tuple(data.get("correct_order", []))
    warnings = _string_tuple(data.get("_data_warnings", []))
    prompt = _text(data.get("prompt"))
    correct_answer = _text(data.get("correct_answer"))
    before = _text(data.get("before"))
    after = _text(data.get("after"))
    structure_valid = not warnings
    choice_ids = [option.option_id for option in options]
    choice_text = [option.text for option in options]
    reorder_ids = {part.part_id for part in parts}

    return AttemptReplaySource(
        event_key=_text(data.get("event_key")),
        result=_text(data.get("result")),
        attempt_date=_text(data.get("date")),
        source=_text(data.get("source")),
        section=_text(data.get("section")),
        question=_text(data.get("question")),
        question_type=_text(data.get("question_type")),
        prompt=prompt,
        user_answer=_text(data.get("user_answer")),
        correct_answer=correct_answer,
        reason=_text(data.get("reason")),
        before=before,
        after=after,
        parts=parts,
        user_order=user_order,
        correct_order=correct_order,
        options=options,
        linked_entry_keys=_string_tuple(data.get("linked_entries", [])),
        linked_levels=tuple(dict.fromkeys(_text(level) for level in linked_levels if _text(level))),
        recorded_at=_text(data.get("created_at")),
        data_warnings=warnings,
        capabilities=AttemptCapabilities(
            has_prompt=bool(prompt.strip()),
            has_correct_answer=bool(correct_answer.strip()),
            has_choices=(
                structure_valid
                and len(options) >= 2
                and len(choice_ids) == len(set(choice_ids))
                and len(choice_text) == len(set(choice_text))
            ),
            has_reorder_parts=(
                structure_valid
                and len(parts) == 4
                and reorder_ids == {1, 2, 3, 4}
                and len(correct_order) == 4
                and set(correct_order) == {1, 2, 3, 4}
            ),
            has_sentence_context=bool(before.strip() or after.strip()),
            structure_valid=structure_valid,
        ),
    )



class StudySourceService:
    """Translate existing public core reads into stable immutable snapshots."""

    def __init__(self, core: CoreReadPort):
        if not isinstance(core, CoreReadPort):
            raise TypeError("core 必須實作 jpnote public read methods")
        self._core = core

    @classmethod
    def from_default_core(cls) -> "StudySourceService":
        # Lazy import is intentional: importing the contract module must not
        # initialize the DB and does not create a core -> Quiz dependency.
        from .api import JpnoteCore

        return cls(JpnoteCore())

    def _browse(self, **kwargs: Any) -> list[dict[str, Any]]:
        try:
            result = self._core.browse(**kwargs)
        except Exception as exc:  # fail-soft public boundary
            raise QuestionSourceUnavailableError(
                f"無法讀取 jpnote 題目來源：{exc}"
            ) from exc
        if not isinstance(result, list):
            raise QuestionSourceUnavailableError("jpnote 題目來源回傳格式錯誤")
        return result

    def list_entry_snapshots(
        self,
        *,
        entry_types: Sequence[str] | None = None,
        levels: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> tuple[EntrySnapshot, ...]:
        requested = ("grammar", "vocabulary") if entry_types is None else tuple(entry_types)
        browse_types: list[str] = []
        for value in requested:
            normalized = _text(value).strip().casefold()
            if normalized == "grammar":
                browse_types.append("grammar")
            elif normalized in {"vocab", "vocabulary"}:
                browse_types.append("vocab")
            else:
                raise ValueError(f"不支援的 entry type：{value}")

        records = self._browse(
            types=list(dict.fromkeys(browse_types)),
            levels=list(levels) if levels else None,
        )
        source_filter = {_text(value) for value in sources or () if _text(value)}
        snapshots: list[EntrySnapshot] = []
        for record in records:
            if not isinstance(record, dict) or record.get("kind") not in {"grammar", "vocab"}:
                continue
            data = record.get("data")
            if not isinstance(data, dict):
                continue
            snapshot = _entry_snapshot(data)
            if not snapshot.key:
                continue
            if source_filter and not source_filter.intersection(snapshot.sources):
                continue
            snapshots.append(snapshot)
        return tuple(snapshots)

    def get_entry_snapshot(self, key: str) -> EntrySnapshot | None:
        try:
            data = self._core.get(key)
        except Exception as exc:
            raise QuestionSourceUnavailableError(
                f"無法讀取 jpnote entry {key}：{exc}"
            ) from exc
        if data is None:
            return None
        if not isinstance(data, dict):
            raise QuestionSourceUnavailableError("jpnote entry 回傳格式錯誤")
        snapshot = _entry_snapshot(data)
        return snapshot if snapshot.key else None

    def list_attempt_replay_sources(
        self,
        *,
        results: Sequence[str] = ("wrong", "partial"),
        levels: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> tuple[AttemptReplaySource, ...]:
        records = self._browse(
            types=["mistake"],
            levels=list(levels) if levels else None,
            results=list(results),
        )
        source_filter = {_text(value) for value in sources or () if _text(value)}
        snapshots: list[AttemptReplaySource] = []
        for record in records:
            if not isinstance(record, dict) or record.get("kind") != "mistake":
                continue
            data = record.get("data")
            if not isinstance(data, dict):
                continue
            snapshot = _attempt_snapshot(data, linked_levels=record.get("levels", ()))
            if not snapshot.event_key:
                continue
            if source_filter and snapshot.source not in source_filter:
                continue
            snapshots.append(snapshot)
        return tuple(snapshots)

    def get_attempt_replay_source(self, event_key: str) -> AttemptReplaySource | None:
        try:
            data = self._core.get_attempt(event_key)
        except Exception as exc:
            raise QuestionSourceUnavailableError(
                f"無法讀取 jpnote attempt {event_key}：{exc}"
            ) from exc
        if data is None:
            return None
        if not isinstance(data, dict):
            raise QuestionSourceUnavailableError("jpnote attempt 回傳格式錯誤")
        snapshot = _attempt_snapshot(data)
        return snapshot if snapshot.event_key else None

    def source_catalog(self) -> SourceCatalog:
        entries = self.list_entry_snapshots()
        attempts = self.list_attempt_replay_sources()
        levels = sorted({entry.level for entry in entries if entry.level})
        sources = sorted(
            {source for entry in entries for source in entry.sources if source}
            | {attempt.source for attempt in attempts if attempt.source}
        )
        return SourceCatalog(
            entry_count=len(entries),
            replayable_attempt_count=len(attempts),
            levels=tuple(levels),
            sources=tuple(sources),
        )
