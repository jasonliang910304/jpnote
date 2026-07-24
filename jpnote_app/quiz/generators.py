"""Capability-based, fail-soft Quiz question generators.

The generators consume immutable public study-source snapshots and emit exact
``GeneratedQuestionSnapshot`` values suitable for the independent Quiz session
store.  They never query core storage, SQLite tables, or CLI-private handlers.
"""
from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Iterable, Sequence

from jpnote_app.study_sources import AttemptReplaySource, EntrySnapshot

from .session_models import (
    AnswerSnapshot,
    GeneratedQuestionSnapshot,
    QuestionChoiceSnapshot,
)

GENERATOR_VERSION = "quiz-v1-generator-1"
_TRUE_CHOICE = QuestionChoiceSnapshot(choice_id="true", text="正確")
_FALSE_CHOICE = QuestionChoiceSnapshot(choice_id="false", text="錯誤")
_TRUTH_CHOICES = (_TRUE_CHOICE, _FALSE_CHOICE)
_TRAILING_PUNCTUATION = "。．.，,、；;：:！？!?（）()［］[]【】「」『』\"'"
_KANJI_RANGE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# Keep hiragana long-vowel traps deliberately conservative.  Broadly treating
# every o/u-row kana followed by う as a long vowel breaks phrases such as
# ``をうける`` across a particle/word boundary.  These patterns cover the
# unambiguous small-kana and direct おう／えい cases; katakana uses ``ー``.
_LONG_U_PRECEDERS = frozenset("おオょョゅュ")
_LONG_I_PRECEDERS = frozenset("えエ")


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return " ".join(normalized.split()).casefold()


def _semantic_text(value: str) -> str:
    return _normalize_text(value).strip(_TRAILING_PUNCTUATION + " ")


def _unique_preserving_order(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        marker = _normalize_text(text)
        if not text or not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(text)
    return tuple(result)


def _meaning_parts(entry: EntrySnapshot) -> tuple[str, ...]:
    return _unique_preserving_order(sense.meaning for sense in entry.senses)


def _meaning_summary(entry: EntrySnapshot) -> str:
    return "；".join(_meaning_parts(entry))


def _preferred_vocabulary_prompt(
    source: EntrySnapshot,
    pool: Sequence[EntrySnapshot],
) -> str:
    """Prefer kana for Chinese readers when the reading is unambiguous.

    A kana-only prompt avoids giving away Sino-Japanese vocabulary through the
    written kanji.  Homophones fall back to the display form because a reading
    alone would make the question ambiguous.
    """

    display = source.display.strip()
    reading = source.reading.strip()
    if not display or not reading or not _KANJI_RANGE.search(display):
        return display
    reading_marker = _normalize_text(reading)
    if not reading_marker:
        return display
    for candidate in pool:
        if candidate.key == source.key:
            continue
        if _normalize_text(candidate.reading) == reading_marker:
            return display
    return reading


def _entry_names(entry: EntrySnapshot) -> frozenset[str]:
    return frozenset(
        marker
        for marker in (
            _normalize_text(entry.display),
            *(_normalize_text(alias) for alias in entry.aliases),
        )
        if marker
    )


def _meaning_markers(entry: EntrySnapshot) -> frozenset[str]:
    return frozenset(
        marker for marker in (_semantic_text(value) for value in _meaning_parts(entry)) if marker
    )


def _meaning_sets_overlap(left: EntrySnapshot, right: EntrySnapshot) -> bool:
    left_markers = _meaning_markers(left)
    right_markers = _meaning_markers(right)
    if left_markers & right_markers:
        return True
    for left_value in left_markers:
        for right_value in right_markers:
            if left_value in right_value or right_value in left_value:
                return True
    return False


def _safe_vocabulary_pair(source: EntrySnapshot, candidate: EntrySnapshot) -> bool:
    """Conservative boundary for vocabulary distractors/false candidates."""

    if source.key == candidate.key:
        return False
    if source.entry_type != "vocabulary" or candidate.entry_type != "vocabulary":
        return False
    if not source.display.strip() or not candidate.display.strip():
        return False
    if _entry_names(source) & _entry_names(candidate):
        return False
    source_reading = _normalize_text(source.reading)
    candidate_reading = _normalize_text(candidate.reading)
    if source_reading and source_reading == candidate_reading:
        return False
    if _meaning_sets_overlap(source, candidate):
        return False
    if (
        source.review_group.strip()
        and candidate.review_group.strip()
        and _normalize_text(source.review_group) == _normalize_text(candidate.review_group)
    ):
        return False
    return True


def _stable_vocabulary_candidates(
    source: EntrySnapshot,
    pool: Iterable[EntrySnapshot],
) -> tuple[EntrySnapshot, ...]:
    candidates: list[EntrySnapshot] = []
    seen_keys: set[str] = set()
    for candidate in pool:
        if candidate.key in seen_keys or not _safe_vocabulary_pair(source, candidate):
            continue
        seen_keys.add(candidate.key)
        candidates.append(candidate)
    return tuple(candidates)


def _truth_answer(is_true: bool) -> AnswerSnapshot:
    return AnswerSnapshot(
        answer_id="true" if is_true else "false",
        text="正確" if is_true else "錯誤",
    )


def _choice_from_entry(entry: EntrySnapshot, text: str) -> QuestionChoiceSnapshot:
    return QuestionChoiceSnapshot(choice_id=entry.key, text=text)


def _question(
    *,
    question_type: str,
    source_kind: str,
    source_key: str,
    prompt: str,
    choices: Sequence[QuestionChoiceSnapshot],
    correct_answer: AnswerSnapshot,
) -> GeneratedQuestionSnapshot | None:
    if not prompt.strip() or not choices:
        return None
    choice_ids = [choice.choice_id for choice in choices]
    choice_texts = [_normalize_text(choice.text) for choice in choices]
    if len(choice_ids) != len(set(choice_ids)):
        return None
    if len(choice_texts) != len(set(choice_texts)):
        return None
    if correct_answer.answer_id not in choice_ids:
        return None
    matches = [
        choice
        for choice in choices
        if choice.choice_id == correct_answer.answer_id
        and _normalize_text(choice.text) == _normalize_text(correct_answer.text)
    ]
    if len(matches) != 1:
        return None
    return GeneratedQuestionSnapshot(
        question_type=question_type,
        generator_version=GENERATOR_VERSION,
        source_kind=source_kind,
        source_key=source_key,
        prompt=prompt,
        choices=tuple(choices),
        correct_answer=correct_answer,
    )


class QuestionGenerator:
    """Deterministic-capable generator facade.

    ``seed`` is an internal reproducibility hook.  Production callers may omit
    it; tests and debug adapters can supply a fixed value.
    """

    def __init__(self, *, seed: int | str | bytes | None = None):
        self._random = random.Random(seed)

    def _shuffled(self, values: Sequence[QuestionChoiceSnapshot]) -> tuple[QuestionChoiceSnapshot, ...]:
        result = list(values)
        self._random.shuffle(result)
        return tuple(result)

    def vocabulary_four_choice(
        self,
        source: EntrySnapshot,
        pool: Iterable[EntrySnapshot],
        *,
        direction: str,
    ) -> GeneratedQuestionSnapshot | None:
        if direction not in {"ja_to_zh", "zh_to_ja"}:
            raise ValueError(f"不支援的 vocabulary direction：{direction}")
        if source.entry_type != "vocabulary" or not source.display.strip():
            return None
        source_meaning = _meaning_summary(source)
        if not source_meaning:
            return None
        pool_items = tuple(pool)
        candidates = list(_stable_vocabulary_candidates(source, pool_items))
        self._random.shuffle(candidates)

        distractors: list[QuestionChoiceSnapshot] = []
        seen_texts: set[str] = set()
        correct_text = source_meaning if direction == "ja_to_zh" else source.display
        seen_texts.add(_normalize_text(correct_text))
        for candidate in candidates:
            candidate_text = (
                _meaning_summary(candidate)
                if direction == "ja_to_zh"
                else candidate.display.strip()
            )
            marker = _normalize_text(candidate_text)
            if not candidate_text or not marker or marker in seen_texts:
                continue
            seen_texts.add(marker)
            distractors.append(_choice_from_entry(candidate, candidate_text))
            if len(distractors) == 3:
                break
        if len(distractors) != 3:
            return None

        correct_choice = _choice_from_entry(source, correct_text)
        if direction == "ja_to_zh":
            prompt_term = _preferred_vocabulary_prompt(source, pool_items)
            prompt = f"「{prompt_term}」的中文意思是？"
            question_type = "vocab_ja_to_zh_mcq"
        else:
            prompt = f"哪一個日文詞彙最符合「{source_meaning}」？"
            question_type = "vocab_zh_to_ja_mcq"

        choices = self._shuffled((correct_choice, *distractors))
        return _question(
            question_type=question_type,
            source_kind="vocabulary",
            source_key=source.key,
            prompt=prompt,
            choices=choices,
            correct_answer=AnswerSnapshot(
                answer_id=source.key,
                text=correct_text,
            ),
        )

    def vocabulary_meaning_true_false(
        self,
        source: EntrySnapshot,
        pool: Iterable[EntrySnapshot] = (),
        *,
        prefer_false: bool | None = None,
    ) -> GeneratedQuestionSnapshot | None:
        if source.entry_type != "vocabulary" or not source.display.strip():
            return None
        pool_items = tuple(pool)
        source_meaning = _meaning_summary(source)
        if not source_meaning:
            return None
        make_false = self._random.choice((False, True)) if prefer_false is None else prefer_false
        shown_meaning = source_meaning
        is_true = True
        if make_false:
            candidates = [
                candidate
                for candidate in _stable_vocabulary_candidates(source, pool_items)
                if _meaning_summary(candidate)
            ]
            if candidates:
                shown_meaning = self._random.choice(candidates)
                shown_meaning = _meaning_summary(shown_meaning)
                is_true = False
        return _question(
            question_type="vocab_meaning_true_false",
            source_kind="vocabulary",
            source_key=source.key,
            prompt=(
                f"「{_preferred_vocabulary_prompt(source, pool_items)}」"
                f"的意思是「{shown_meaning}」。"
            ),
            choices=_TRUTH_CHOICES,
            correct_answer=_truth_answer(is_true),
        )

    def vocabulary_reading_true_false(
        self,
        source: EntrySnapshot,
        pool: Iterable[EntrySnapshot] = (),
        *,
        prefer_false: bool | None = None,
        trap_kind: str | None = None,
    ) -> GeneratedQuestionSnapshot | None:
        if (
            source.entry_type != "vocabulary"
            or not source.display.strip()
            or not source.reading.strip()
        ):
            return None
        make_false = self._random.choice((False, True)) if prefer_false is None else prefer_false
        shown_reading = source.reading.strip()
        is_true = True
        effective_type = "vocab_reading_true_false"
        if make_false:
            effective_trap_kind = trap_kind
            if effective_trap_kind is None:
                available = [
                    kind
                    for kind in ("long_vowel", "sokuon", "moraic_nasal")
                    if _reading_trap(source.reading, kind) is not None
                ]
                if not available:
                    return None
                effective_trap_kind = self._random.choice(available)
            trap = _reading_trap(source.reading, effective_trap_kind)
            if trap is None:
                return None
            shown_reading = trap
            is_true = False
            effective_type = f"vocab_reading_trap_{effective_trap_kind}"
        return _question(
            question_type=effective_type,
            source_kind="vocabulary",
            source_key=source.key,
            prompt=f"「{source.display}」的讀音是「{shown_reading}」。",
            choices=_TRUTH_CHOICES,
            correct_answer=_truth_answer(is_true),
        )

    def vocabulary_with_fallback(
        self,
        source: EntrySnapshot,
        pool: Iterable[EntrySnapshot],
        *,
        direction: str,
    ) -> GeneratedQuestionSnapshot | None:
        four_choice = self.vocabulary_four_choice(source, pool, direction=direction)
        if four_choice is not None:
            return four_choice
        return self.vocabulary_meaning_true_false(
            source,
            pool,
            prefer_false=True,
        )

    def mistake_multiple_choice(
        self,
        source: AttemptReplaySource,
    ) -> GeneratedQuestionSnapshot | None:
        if (
            source.question_type != "multiple_choice"
            or not source.capabilities.structure_valid
            or not source.capabilities.has_prompt
            or not source.capabilities.has_choices
            or not source.capabilities.has_correct_answer
        ):
            return None
        correct = _resolve_correct_choice(source)
        if correct is None:
            return None
        choices = tuple(
            QuestionChoiceSnapshot(choice_id=str(option.option_id), text=option.text)
            for option in source.options
        )
        return _question(
            question_type="mistake_multiple_choice",
            source_kind="mistake",
            source_key=source.event_key,
            prompt=source.prompt,
            choices=choices,
            correct_answer=AnswerSnapshot(
                answer_id=str(correct.option_id),
                text=correct.text,
            ),
        )

    def mistake_reorder_4(
        self,
        source: AttemptReplaySource,
    ) -> GeneratedQuestionSnapshot | None:
        if (
            source.question_type != "reorder_4"
            or not source.capabilities.structure_valid
            or not source.capabilities.has_prompt
            or not source.capabilities.has_reorder_parts
        ):
            return None
        parts_by_id = {part.part_id: part for part in source.parts}
        try:
            ordered_parts = tuple(parts_by_id[part_id] for part_id in source.correct_order)
        except KeyError:
            return None
        choices = tuple(
            QuestionChoiceSnapshot(choice_id=str(part.part_id), text=part.text)
            for part in source.parts
        )
        answer_id = "-".join(str(part.part_id) for part in ordered_parts)
        answer_text = "".join(part.text for part in ordered_parts)
        # Reorder answers are an ordered sequence, not one of the individual
        # choices, so construct the immutable snapshot directly after local
        # structural checks rather than using the single-choice helper.
        if len(choices) != 4 or len({choice.choice_id for choice in choices}) != 4:
            return None
        return GeneratedQuestionSnapshot(
            question_type="mistake_reorder_4",
            generator_version=GENERATOR_VERSION,
            source_kind="mistake",
            source_key=source.event_key,
            prompt=source.prompt,
            choices=choices,
            correct_answer=AnswerSnapshot(answer_id=answer_id, text=answer_text),
        )

    def mistake_candidate_true_false(
        self,
        source: AttemptReplaySource,
        *,
        prefer_false: bool | None = None,
    ) -> GeneratedQuestionSnapshot | None:
        if (
            source.question_type != "multiple_choice"
            or not source.capabilities.structure_valid
            or not source.capabilities.has_choices
            or not source.capabilities.has_correct_answer
            or not source.capabilities.has_sentence_context
        ):
            return None
        correct = _resolve_correct_choice(source)
        if correct is None:
            return None
        make_false = self._random.choice((False, True)) if prefer_false is None else prefer_false
        candidate = correct
        is_true = True
        if make_false:
            incorrect = [
                option
                for option in source.options
                if option.option_id != correct.option_id
                and _normalize_text(option.text) != _normalize_text(correct.text)
            ]
            if incorrect:
                candidate = self._random.choice(incorrect)
                is_true = False
        sentence = f"{source.before}{candidate.text}{source.after}".strip()
        if not sentence:
            return None
        return _question(
            question_type="mistake_candidate_true_false",
            source_kind="mistake",
            source_key=source.event_key,
            prompt=f"以下句子是否正確？\n{sentence}",
            choices=_TRUTH_CHOICES,
            correct_answer=_truth_answer(is_true),
        )


def _reading_trap(reading: str, trap_kind: str | None) -> str | None:
    if trap_kind == "long_vowel":
        if "ー" in reading:
            candidate = reading.replace("ー", "", 1).strip()
            return candidate if candidate else None
        for index, char in enumerate(reading):
            if index == 0:
                continue
            previous = reading[index - 1]
            if (
                char in {"う", "ウ"}
                and previous in _LONG_U_PRECEDERS
            ) or (
                char in {"い", "イ"}
                and previous in _LONG_I_PRECEDERS
            ):
                candidate = (reading[:index] + reading[index + 1 :]).strip()
                if candidate and _normalize_text(candidate) != _normalize_text(reading):
                    return candidate
        return None
    elif trap_kind == "sokuon":
        markers = ("っ", "ッ")
    elif trap_kind == "moraic_nasal":
        markers = ("ん", "ン")
    elif trap_kind is None:
        return None
    else:
        raise ValueError(f"不支援的 reading trap：{trap_kind}")
    for marker in markers:
        if marker in reading:
            candidate = reading.replace(marker, "", 1).strip()
            if candidate and _normalize_text(candidate) != _normalize_text(reading):
                return candidate
    return None


def _resolve_correct_choice(source: AttemptReplaySource):
    target = _normalize_text(source.correct_answer)
    if not target:
        return None
    text_matches = [
        option for option in source.options if _normalize_text(option.text) == target
    ]
    if len(text_matches) == 1:
        return text_matches[0]
    if len(text_matches) > 1:
        return None
    numeric_match = re.fullmatch(r"[+]?([1-9][0-9]*)", target)
    if numeric_match is None:
        return None
    option_id = int(numeric_match.group(1))
    id_matches = [option for option in source.options if option.option_id == option_id]
    return id_matches[0] if len(id_matches) == 1 else None
