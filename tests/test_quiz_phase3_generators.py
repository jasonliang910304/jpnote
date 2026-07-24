from __future__ import annotations

import itertools
import unittest

from jpnote_app.quiz.generators import GENERATOR_VERSION, QuestionGenerator
from jpnote_app.study_sources import (
    AttemptCapabilities,
    AttemptReplaySource,
    ChoiceSnapshot,
    EntryCapabilities,
    EntrySnapshot,
    ReorderPartSnapshot,
    SenseSnapshot,
)


def vocab(
    key: str,
    display: str,
    reading: str,
    meaning: str,
    *,
    aliases: tuple[str, ...] = (),
    review_group: str = "",
) -> EntrySnapshot:
    return EntrySnapshot(
        key=key,
        entry_type="vocabulary",
        display=display,
        reading=reading,
        romaji="",
        level="N3",
        review_group=review_group,
        aliases=aliases,
        senses=(SenseSnapshot(meaning=meaning),),
        sources=("test",),
        capabilities=EntryCapabilities(
            has_meaning=bool(meaning),
            has_reading=bool(reading),
            has_example=False,
            has_aliases=bool(aliases),
        ),
    )


def attempt(
    *,
    question_type: str = "multiple_choice",
    prompt: str = "正しいものを選んでください。",
    correct_answer: str = "猫",
    options: tuple[ChoiceSnapshot, ...] = (
        ChoiceSnapshot(1, "猫"),
        ChoiceSnapshot(2, "犬"),
        ChoiceSnapshot(3, "鳥"),
        ChoiceSnapshot(4, "魚"),
    ),
    before: str = "私は",
    after: str = "が好きです。",
    parts: tuple[ReorderPartSnapshot, ...] = (),
    correct_order: tuple[int, ...] = (),
    warnings: tuple[str, ...] = (),
) -> AttemptReplaySource:
    structure_valid = not warnings
    return AttemptReplaySource(
        event_key="attempt:test",
        result="wrong",
        attempt_date="2026-07-24",
        source="test",
        section="section",
        question="1",
        question_type=question_type,
        prompt=prompt,
        user_answer="",
        correct_answer=correct_answer,
        reason="",
        before=before,
        after=after,
        parts=parts,
        user_order=(),
        correct_order=correct_order,
        options=options,
        linked_entry_keys=("vocab:猫",),
        linked_levels=("N3",),
        recorded_at="2026-07-24T00:00:00+08:00",
        data_warnings=warnings,
        capabilities=AttemptCapabilities(
            has_prompt=bool(prompt),
            has_correct_answer=bool(correct_answer),
            has_choices=structure_valid and len(options) >= 2,
            has_reorder_parts=(
                structure_valid
                and len(parts) == 4
                and {part.part_id for part in parts} == {1, 2, 3, 4}
                and set(correct_order) == {1, 2, 3, 4}
            ),
            has_sentence_context=bool(before or after),
            structure_valid=structure_valid,
        ),
    )


CAT = vocab("vocab:猫", "猫", "ねこ", "貓")
DOG = vocab("vocab:犬", "犬", "いぬ", "狗")
BIRD = vocab("vocab:鳥", "鳥", "とり", "鳥類")
FISH = vocab("vocab:魚", "魚", "さかな", "魚類")
HORSE = vocab("vocab:馬", "馬", "うま", "馬匹")


class QuizPhase3GeneratorTests(unittest.TestCase):
    def test_ja_to_zh_four_choice_has_unique_safe_choices(self):
        question = QuestionGenerator(seed=7).vocabulary_four_choice(
            CAT, (DOG, BIRD, FISH, HORSE), direction="ja_to_zh"
        )
        self.assertIsNotNone(question)
        assert question is not None
        self.assertEqual(question.question_type, "vocab_ja_to_zh_mcq")
        self.assertEqual(question.generator_version, GENERATOR_VERSION)
        self.assertEqual(len(question.choices), 4)
        self.assertEqual(len({choice.choice_id for choice in question.choices}), 4)
        self.assertEqual(len({choice.text for choice in question.choices}), 4)
        self.assertEqual(question.correct_answer.answer_id, CAT.key)
        self.assertEqual(question.correct_answer.text, "貓")
        self.assertIn("ねこ", question.prompt)
        self.assertNotIn("「猫」", question.prompt)

    def test_zh_to_ja_four_choice_uses_stable_entry_keys(self):
        question = QuestionGenerator(seed=2).vocabulary_four_choice(
            CAT, (DOG, BIRD, FISH), direction="zh_to_ja"
        )
        assert question is not None
        self.assertEqual(question.question_type, "vocab_zh_to_ja_mcq")
        self.assertEqual({choice.choice_id for choice in question.choices}, {
            CAT.key, DOG.key, BIRD.key, FISH.key
        })
        self.assertEqual(question.correct_answer.text, "猫")

    def test_homophone_and_alias_collision_are_rejected(self):
        homophone = vocab("vocab:別語", "別語", "ねこ", "完全不同")
        alias_collision = vocab("vocab:ねこ別名", "ネコ", "ねご", "別の意味", aliases=("猫",))
        question = QuestionGenerator(seed=1).vocabulary_four_choice(
            CAT,
            (homophone, alias_collision, DOG, BIRD, FISH, HORSE),
            direction="ja_to_zh",
        )
        assert question is not None
        ids = {choice.choice_id for choice in question.choices}
        self.assertNotIn(homophone.key, ids)
        self.assertNotIn(alias_collision.key, ids)

    def test_kana_prompt_falls_back_to_display_when_reading_is_ambiguous(self):
        homophone = vocab("vocab:別語", "別語", "ねこ", "不同")
        question = QuestionGenerator(seed=1).vocabulary_four_choice(
            CAT,
            (homophone, DOG, BIRD, FISH, HORSE),
            direction="ja_to_zh",
        )
        assert question is not None
        self.assertIn("「猫」", question.prompt)

    def test_same_or_contained_meaning_is_rejected(self):
        same = vocab("vocab:同義", "同義", "どうぎ", "貓")
        contained = vocab("vocab:包含", "包含", "ほうがん", "家裡飼養的貓")
        question = QuestionGenerator(seed=3).vocabulary_four_choice(
            CAT, (same, contained, DOG, BIRD, FISH, HORSE), direction="ja_to_zh"
        )
        assert question is not None
        ids = {choice.choice_id for choice in question.choices}
        self.assertNotIn(same.key, ids)
        self.assertNotIn(contained.key, ids)

    def test_same_nonempty_review_group_is_rejected(self):
        source = vocab("vocab:赤", "赤", "あか", "紅色", review_group="顏色")
        related = vocab("vocab:青", "青", "あお", "藍色", review_group="顏色")
        question = QuestionGenerator(seed=4).vocabulary_four_choice(
            source, (related, DOG, BIRD, FISH, HORSE), direction="ja_to_zh"
        )
        assert question is not None
        self.assertNotIn(related.key, {choice.choice_id for choice in question.choices})

    def test_four_choice_falls_back_to_true_false(self):
        question = QuestionGenerator(seed=5).vocabulary_with_fallback(
            CAT, (DOG,), direction="ja_to_zh"
        )
        assert question is not None
        self.assertEqual(question.question_type, "vocab_meaning_true_false")
        self.assertEqual(len(question.choices), 2)

    def test_true_false_fallback_prefers_safety_over_false_balance(self):
        question = QuestionGenerator(seed=6).vocabulary_meaning_true_false(
            CAT, (), prefer_false=True
        )
        assert question is not None
        self.assertEqual(question.correct_answer.answer_id, "true")
        self.assertIn("貓", question.prompt)

    def test_meaning_false_candidate_uses_safe_other_entry(self):
        question = QuestionGenerator(seed=0).vocabulary_meaning_true_false(
            CAT, (DOG,), prefer_false=True
        )
        assert question is not None
        self.assertEqual(question.correct_answer.answer_id, "false")
        self.assertIn("狗", question.prompt)
        self.assertIn("ねこ", question.prompt)

    def test_reading_false_candidate_uses_only_subtle_orthographic_traps(self):
        source = vocab("vocab:以上", "以上", "いじょう", "以上")
        question = QuestionGenerator(seed=0).vocabulary_reading_true_false(
            source, (DOG,), prefer_false=True
        )
        assert question is not None
        self.assertEqual(question.correct_answer.answer_id, "false")
        self.assertIn("いじょ", question.prompt)
        self.assertNotIn("いぬ", question.prompt)
        self.assertEqual(question.question_type, "vocab_reading_trap_long_vowel")

    def test_reading_false_without_subtle_trap_is_skipped(self):
        question = QuestionGenerator(seed=0).vocabulary_reading_true_false(
            CAT, (DOG,), prefer_false=True
        )
        self.assertIsNone(question)

    def test_reading_traps_cover_long_vowel_sokuon_and_nasal(self):
        cases = (
            (vocab("vocab:コーヒー", "コーヒー", "コーヒー", "咖啡"), "long_vowel", "コヒー"),
            (vocab("vocab:以上", "以上", "いじょう", "以上"), "long_vowel", "いじょ"),
            (vocab("vocab:切手", "切手", "きって", "郵票"), "sokuon", "きて"),
            (vocab("vocab:新聞", "新聞", "しんぶん", "報紙"), "moraic_nasal", "しぶん"),
        )
        for source, kind, expected in cases:
            question = QuestionGenerator(seed=0).vocabulary_reading_true_false(
                source, prefer_false=True, trap_kind=kind
            )
            assert question is not None
            self.assertEqual(question.correct_answer.answer_id, "false")
            self.assertIn(expected, question.prompt)
            self.assertEqual(question.question_type, f"vocab_reading_trap_{kind}")

    def test_unavailable_reading_trap_is_skipped(self):
        question = QuestionGenerator(seed=0).vocabulary_reading_true_false(
            CAT, prefer_false=True, trap_kind="long_vowel"
        )
        self.assertIsNone(question)

    def test_incomplete_vocabulary_is_skipped_fail_soft(self):
        incomplete = vocab("vocab:空", "空", "", "")
        generator = QuestionGenerator(seed=0)
        self.assertIsNone(generator.vocabulary_four_choice(incomplete, (DOG, BIRD, FISH), direction="ja_to_zh"))
        self.assertIsNone(generator.vocabulary_meaning_true_false(incomplete))
        self.assertIsNone(generator.vocabulary_reading_true_false(incomplete))

    def test_multiple_choice_replay_resolves_correct_text(self):
        question = QuestionGenerator(seed=0).mistake_multiple_choice(attempt())
        assert question is not None
        self.assertEqual(question.source_kind, "mistake")
        self.assertEqual(question.source_key, "attempt:test")
        self.assertEqual(question.correct_answer.answer_id, "1")
        self.assertEqual(question.correct_answer.text, "猫")

    def test_multiple_choice_replay_resolves_numeric_option_id(self):
        question = QuestionGenerator(seed=0).mistake_multiple_choice(
            attempt(correct_answer="2")
        )
        assert question is not None
        self.assertEqual(question.correct_answer.answer_id, "2")
        self.assertEqual(question.correct_answer.text, "犬")

    def test_ambiguous_or_missing_multiple_choice_answer_is_skipped(self):
        duplicated = (
            ChoiceSnapshot(1, "猫"),
            ChoiceSnapshot(2, "猫"),
        )
        self.assertIsNone(QuestionGenerator(seed=0).mistake_multiple_choice(
            attempt(options=duplicated, correct_answer="猫")
        ))
        self.assertIsNone(QuestionGenerator(seed=0).mistake_multiple_choice(
            attempt(correct_answer="不存在")
        ))

    def test_reorder_4_replay_preserves_parts_and_correct_order(self):
        parts = (
            ReorderPartSnapshot(1, "私は"),
            ReorderPartSnapshot(2, "毎日"),
            ReorderPartSnapshot(3, "日本語を"),
            ReorderPartSnapshot(4, "勉強します"),
        )
        question = QuestionGenerator(seed=0).mistake_reorder_4(attempt(
            question_type="reorder_4",
            options=(),
            correct_answer="",
            before="",
            after="",
            parts=parts,
            correct_order=(1, 2, 3, 4),
        ))
        assert question is not None
        self.assertEqual(question.correct_answer.answer_id, "1-2-3-4")
        self.assertEqual(question.correct_answer.text, "私は毎日日本語を勉強します")
        self.assertEqual(tuple(choice.choice_id for choice in question.choices), ("1", "2", "3", "4"))

    def test_candidate_true_false_reconstructs_original_context(self):
        question = QuestionGenerator(seed=1).mistake_candidate_true_false(
            attempt(), prefer_false=True
        )
        assert question is not None
        self.assertEqual(question.correct_answer.answer_id, "false")
        self.assertTrue(question.prompt.startswith("以下句子是否正確？\n私は"))
        self.assertTrue(question.prompt.endswith("が好きです。"))
        self.assertNotIn("私は猫が好きです。", question.prompt)

    def test_malformed_attempts_are_skipped_fail_soft(self):
        broken = attempt(warnings=("options_json 格式損壞",))
        generator = QuestionGenerator(seed=0)
        self.assertIsNone(generator.mistake_multiple_choice(broken))
        self.assertIsNone(generator.mistake_candidate_true_false(broken))

    def test_fixed_seed_reproduces_choice_order_and_false_candidate(self):
        pool = (DOG, BIRD, FISH, HORSE)
        first = QuestionGenerator(seed=42).vocabulary_four_choice(CAT, pool, direction="ja_to_zh")
        second = QuestionGenerator(seed=42).vocabulary_four_choice(CAT, pool, direction="ja_to_zh")
        assert first is not None and second is not None
        self.assertEqual(first.identity_tuple(), second.identity_tuple())
        first_tf = QuestionGenerator(seed=42).vocabulary_meaning_true_false(CAT, pool, prefer_false=True)
        second_tf = QuestionGenerator(seed=42).vocabulary_meaning_true_false(CAT, pool, prefer_false=True)
        assert first_tf is not None and second_tf is not None
        self.assertEqual(first_tf.identity_tuple(), second_tf.identity_tuple())

    def test_permutation_fuzz_never_emits_duplicate_choices_or_multiple_correct(self):
        pool = (DOG, BIRD, FISH, HORSE)
        for seed, permutation in enumerate(itertools.permutations(pool)):
            for direction in ("ja_to_zh", "zh_to_ja"):
                question = QuestionGenerator(seed=seed).vocabulary_four_choice(
                    CAT, permutation, direction=direction
                )
                assert question is not None
                ids = [choice.choice_id for choice in question.choices]
                texts = [choice.text for choice in question.choices]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(len(texts), len(set(texts)))
                correct_matches = [
                    choice
                    for choice in question.choices
                    if choice.choice_id == question.correct_answer.answer_id
                    and choice.text == question.correct_answer.text
                ]
                self.assertEqual(len(correct_matches), 1)


if __name__ == "__main__":
    unittest.main()
