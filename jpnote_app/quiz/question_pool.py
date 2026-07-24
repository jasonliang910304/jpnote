"""Build deterministic, safety-first Quiz question pools.

The pool builder combines immutable vocabulary and mistake snapshots with the
capability-based generators.  It never reads core storage directly and never
creates low-confidence questions merely to satisfy a requested count.
"""
from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from jpnote_app.study_sources import AttemptReplaySource, EntrySnapshot

from .generators import QuestionGenerator
from .session_models import GeneratedQuestionSnapshot

QUIZ_MODES = frozenset({"mixed", "vocabulary", "mistake"})
_SOFT_BALANCE_MINIMUM = 5
_SOFT_BALANCE_LIMIT = 0.80


@dataclass(frozen=True, slots=True)
class QuestionPoolReport:
    """Explain how many safe questions were available and selected."""

    mode: str
    requested_count: int
    available_count: int
    selected_count: int
    vocabulary_source_count: int
    mistake_source_count: int
    vocabulary_available_count: int
    mistake_available_count: int
    skipped_vocabulary_source_count: int
    skipped_mistake_source_count: int

    @property
    def shortage_count(self) -> int:
        return max(0, self.requested_count - self.selected_count)

    @property
    def has_shortage(self) -> bool:
        return self.shortage_count > 0

    @property
    def can_start(self) -> bool:
        return self.selected_count > 0


@dataclass(frozen=True, slots=True)
class QuestionPoolPlan:
    """Immutable questions ready to pass to the independent session store."""

    questions: tuple[GeneratedQuestionSnapshot, ...]
    report: QuestionPoolReport


def _unique_entries(entries: Iterable[EntrySnapshot]) -> tuple[EntrySnapshot, ...]:
    by_key: dict[str, EntrySnapshot] = {}
    for entry in entries:
        if entry.entry_type == "vocabulary" and entry.key.strip():
            by_key.setdefault(entry.key, entry)
    return tuple(by_key[key] for key in sorted(by_key))


def _unique_attempts(
    attempts: Iterable[AttemptReplaySource],
) -> tuple[AttemptReplaySource, ...]:
    by_key: dict[str, AttemptReplaySource] = {}
    for attempt in attempts:
        if attempt.event_key.strip():
            by_key.setdefault(attempt.event_key, attempt)
    return tuple(by_key[key] for key in sorted(by_key))


def _append_unique(
    questions: list[GeneratedQuestionSnapshot],
    seen: set[tuple[object, ...]],
    question: GeneratedQuestionSnapshot | None,
) -> None:
    if question is None:
        return
    identity = question.identity_tuple()
    if identity in seen:
        return
    seen.add(identity)
    questions.append(question)


def _vocabulary_variants(
    generator: QuestionGenerator,
    source: EntrySnapshot,
    pool: Sequence[EntrySnapshot],
) -> tuple[GeneratedQuestionSnapshot, ...]:
    questions: list[GeneratedQuestionSnapshot] = []
    seen: set[tuple[object, ...]] = set()

    for direction in ("ja_to_zh", "zh_to_ja"):
        _append_unique(
            questions,
            seen,
            generator.vocabulary_four_choice(source, pool, direction=direction),
        )

    _append_unique(
        questions,
        seen,
        generator.vocabulary_meaning_true_false(
            source,
            pool,
            prefer_false=False,
        ),
    )
    _append_unique(
        questions,
        seen,
        generator.vocabulary_meaning_true_false(
            source,
            pool,
            prefer_false=True,
        ),
    )
    _append_unique(
        questions,
        seen,
        generator.vocabulary_reading_true_false(
            source,
            pool,
            prefer_false=False,
        ),
    )
    _append_unique(
        questions,
        seen,
        generator.vocabulary_reading_true_false(
            source,
            pool,
            prefer_false=True,
        ),
    )
    trap_markers = {
        "long_vowel": ("ー",),
        "sokuon": ("っ", "ッ"),
        "moraic_nasal": ("ん", "ン"),
    }
    for trap_kind, markers in trap_markers.items():
        if not any(marker in source.reading for marker in markers):
            continue
        _append_unique(
            questions,
            seen,
            generator.vocabulary_reading_true_false(
                source,
                pool,
                prefer_false=True,
                trap_kind=trap_kind,
            ),
        )
    return tuple(questions)


def _mistake_variants(
    generator: QuestionGenerator,
    source: AttemptReplaySource,
) -> tuple[GeneratedQuestionSnapshot, ...]:
    questions: list[GeneratedQuestionSnapshot] = []
    seen: set[tuple[object, ...]] = set()

    _append_unique(questions, seen, generator.mistake_multiple_choice(source))
    _append_unique(questions, seen, generator.mistake_reorder_4(source))
    _append_unique(
        questions,
        seen,
        generator.mistake_candidate_true_false(source, prefer_false=False),
    )
    _append_unique(
        questions,
        seen,
        generator.mistake_candidate_true_false(source, prefer_false=True),
    )
    return tuple(questions)


def _truth_value(question: GeneratedQuestionSnapshot) -> str | None:
    choice_ids = {choice.choice_id for choice in question.choices}
    if choice_ids != {"true", "false"}:
        return None
    answer_id = question.correct_answer.answer_id
    return answer_id if answer_id in {"true", "false"} else None


def _would_be_extreme(
    selected: Sequence[GeneratedQuestionSnapshot],
    candidate: GeneratedQuestionSnapshot,
) -> bool:
    candidate_value = _truth_value(candidate)
    if candidate_value is None:
        return False
    values = [
        value
        for question in selected
        if (value := _truth_value(question)) is not None
    ]
    values.append(candidate_value)
    if len(values) < _SOFT_BALANCE_MINIMUM:
        return False
    counts = Counter(values)
    return max(counts.values()) / len(values) > _SOFT_BALANCE_LIMIT


def _choose_variant(
    variants: list[GeneratedQuestionSnapshot],
    selected: Sequence[GeneratedQuestionSnapshot],
    random_source: random.Random,
) -> GeneratedQuestionSnapshot:
    random_source.shuffle(variants)
    for index, candidate in enumerate(variants):
        if not _would_be_extreme(selected, candidate):
            return variants.pop(index)
    return variants.pop(0)


class QuestionPoolBuilder:
    """Create one deterministic, safety-first pool for a future Quiz session."""

    def __init__(self, *, seed: int | str | bytes | None = None):
        self._random = random.Random(seed)

    def build(
        self,
        *,
        mode: str,
        requested_count: int,
        entries: Iterable[EntrySnapshot] = (),
        attempts: Iterable[AttemptReplaySource] = (),
    ) -> QuestionPoolPlan:
        if mode not in QUIZ_MODES:
            raise ValueError(f"不支援的 Quiz mode：{mode}")
        if (
            not isinstance(requested_count, int)
            or isinstance(requested_count, bool)
            or requested_count <= 0
        ):
            raise ValueError("requested_count 必須是大於 0 的整數")

        vocabulary_sources = _unique_entries(entries)
        mistake_sources = _unique_attempts(attempts)
        generator = QuestionGenerator(seed=self._random.getrandbits(64))

        groups: dict[
            tuple[str, str],
            list[GeneratedQuestionSnapshot],
        ] = {}
        skipped_vocabulary = 0
        skipped_mistakes = 0

        if mode in {"mixed", "vocabulary"}:
            for source in vocabulary_sources:
                variants = list(
                    _vocabulary_variants(generator, source, vocabulary_sources)
                )
                if variants:
                    groups[("vocabulary", source.key)] = variants
                else:
                    skipped_vocabulary += 1

        if mode in {"mixed", "mistake"}:
            for source in mistake_sources:
                variants = list(_mistake_variants(generator, source))
                if variants:
                    groups[("mistake", source.event_key)] = variants
                else:
                    skipped_mistakes += 1

        vocabulary_available = sum(
            len(variants)
            for (kind, _), variants in groups.items()
            if kind == "vocabulary"
        )
        mistake_available = sum(
            len(variants)
            for (kind, _), variants in groups.items()
            if kind == "mistake"
        )
        available_count = vocabulary_available + mistake_available

        selected: list[GeneratedQuestionSnapshot] = []
        group_keys = list(groups)

        # Mixed mode has no fixed quota.  When both source kinds are available
        # and the session has room, start with one source group of each kind so
        # neither kind disappears merely because of random ordering.
        ordered_groups: list[tuple[str, str]] = []
        if mode == "mixed" and requested_count >= 2:
            vocabulary_groups = [key for key in group_keys if key[0] == "vocabulary"]
            mistake_groups = [key for key in group_keys if key[0] == "mistake"]
            self._random.shuffle(vocabulary_groups)
            self._random.shuffle(mistake_groups)
            if vocabulary_groups and mistake_groups:
                first_pair = [vocabulary_groups.pop(), mistake_groups.pop()]
                self._random.shuffle(first_pair)
                ordered_groups.extend(first_pair)
                used = set(first_pair)
                group_keys = [key for key in group_keys if key not in used]

        self._random.shuffle(group_keys)
        ordered_groups.extend(group_keys)

        # First pass: at most one question per source.  This is the important
        # vocabulary de-duplication rule and is also a useful conservative
        # default for mistake sources.
        for key in ordered_groups:
            if len(selected) >= requested_count:
                break
            variants = groups[key]
            if variants:
                selected.append(_choose_variant(variants, selected, self._random))

        # Second pass: unique sources are exhausted, so alternate safe question
        # types from the same source may fill the remaining requested slots.
        remaining = [question for variants in groups.values() for question in variants]
        self._random.shuffle(remaining)
        while remaining and len(selected) < requested_count:
            selected.append(_choose_variant(remaining, selected, self._random))

        report = QuestionPoolReport(
            mode=mode,
            requested_count=requested_count,
            available_count=available_count,
            selected_count=len(selected),
            vocabulary_source_count=(
                len(vocabulary_sources) if mode in {"mixed", "vocabulary"} else 0
            ),
            mistake_source_count=(
                len(mistake_sources) if mode in {"mixed", "mistake"} else 0
            ),
            vocabulary_available_count=vocabulary_available,
            mistake_available_count=mistake_available,
            skipped_vocabulary_source_count=skipped_vocabulary,
            skipped_mistake_source_count=skipped_mistakes,
        )
        return QuestionPoolPlan(questions=tuple(selected), report=report)
