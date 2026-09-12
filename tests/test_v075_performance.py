from __future__ import annotations

from datetime import date

import pytest

from jpnote_app import cli
from jpnote_app.quiz import generators
from jpnote_app.quiz.generators import PreparedVocabularyPool, QuestionGenerator
from jpnote_app.quiz.question_pool import QuestionPoolBuilder, _vocabulary_variants
from jpnote_app.romaji import spaced_hepburn
from jpnote_app.romaji_maintenance import romaji_is_equivalent
from jpnote_app.study_sources import EntryCapabilities, EntrySnapshot, SenseSnapshot


def _vocab(
    number: int,
    *,
    display: str | None = None,
    reading: str | None = None,
    meaning: str | None = None,
    aliases: tuple[str, ...] = (),
    review_group: str = "",
) -> EntrySnapshot:
    return EntrySnapshot(
        key=f"vocab:語{number}",
        entry_type="vocabulary",
        display=display or f"語{number}",
        reading=reading or f"よみ{number}",
        romaji="",
        level="N3",
        review_group=review_group,
        aliases=aliases,
        senses=(SenseSnapshot(meaning=meaning or f"意思{number}"),),
        sources=("v0.7.5 regression",),
        capabilities=EntryCapabilities(True, True, False, bool(aliases)),
    )


@pytest.mark.parametrize(
    ("reading", "expected"),
    (
        ("ていいん", "tē i n"),
        ("けいえいほうしん", "kē ē hō shi n"),
        ("そうおん", "sō o n"),
        ("おおきい", "ō kī"),
    ),
)
def test_spaced_hepburn_preserves_mora_after_one_long_vowel(reading, expected):
    assert spaced_hepburn(reading) == expected


def test_romaji_equivalence_is_canonical_directional_and_rejects_dropped_mora():
    assert romaji_is_equivalent("tei in", "tē i n")
    assert romaji_is_equivalent("kei ei hō shin", "kē ē hō shi n")
    assert not romaji_is_equivalent("tē n", "tē i n")
    assert not romaji_is_equivalent("sō n", "sō o n")


def test_recent_days_is_inclusive_local_calendar_window():
    assert cli._recent_since_date(1, today=date(2026, 9, 7)) == "2026-09-07"
    assert cli._recent_since_date(2, today=date(2026, 9, 7)) == "2026-09-06"
    assert cli._recent_since_date(7, today=date(2026, 9, 7)) == "2026-09-01"


def test_recent_days_parser_rejects_invalid_and_conflicting_ranges():
    parser = cli.build_parser()
    args = parser.parse_args(["recent", "--days", "2", "--all"])
    assert args.days == 2
    with pytest.raises(SystemExit):
        parser.parse_args(["recent", "--days", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["recent", "--days", "2", "--since", "2026-09-01"])
    with pytest.raises(SystemExit):
        parser.parse_args(["recent", "--days", "2", "--date", "2026-09-07"])


def test_prepared_vocabulary_pool_preserves_legacy_variant_rng_and_safety():
    pool = tuple(
        [
            _vocab(1, display="奇跡", reading="きせき", meaning="奇蹟"),
            _vocab(2, display="軌跡", reading="きせき", meaning="軌道、路徑"),
            _vocab(3, display="猫", reading="ねこ", meaning="貓"),
            _vocab(4, display="ネコ", reading="ねご", meaning="別義", aliases=("猫",)),
            _vocab(5, display="赤", reading="あか", meaning="紅色", review_group="顏色"),
            _vocab(6, display="青", reading="あお", meaning="藍色", review_group="顏色"),
            _vocab(7, display="家猫", reading="いえねこ", meaning="家裡飼養的貓"),
        ]
        + [_vocab(index) for index in range(8, 31)]
    )
    prepared_pool = PreparedVocabularyPool(pool)
    legacy = QuestionGenerator(seed="equivalence")
    optimized = QuestionGenerator(seed="equivalence")

    for source in pool:
        legacy_variants = _vocabulary_variants(legacy, source, pool)
        optimized_variants = _vocabulary_variants(
            optimized,
            source,
            pool,
            prepared=prepared_pool.for_source(source),
        )
        assert tuple(question.identity_tuple() for question in optimized_variants) == tuple(
            question.identity_tuple() for question in legacy_variants
        )


def test_question_pool_prepares_features_once_and_checks_unordered_pairs_once(monkeypatch):
    entries = tuple(_vocab(index) for index in range(1, 61))
    original_features = generators._vocabulary_features
    original_pair = generators._safe_vocabulary_feature_pair
    feature_calls = 0
    pair_calls = 0

    def counted_features(entry):
        nonlocal feature_calls
        feature_calls += 1
        return original_features(entry)

    def counted_pair(source, candidate):
        nonlocal pair_calls
        pair_calls += 1
        return original_pair(source, candidate)

    monkeypatch.setattr(generators, "_vocabulary_features", counted_features)
    monkeypatch.setattr(generators, "_safe_vocabulary_feature_pair", counted_pair)
    plan = QuestionPoolBuilder(seed="scaling").build(
        mode="vocabulary",
        requested_count=20,
        entries=entries,
    )
    assert plan.report.selected_count == 20
    assert feature_calls == len(entries)
    assert pair_calls <= len(entries) * (len(entries) - 1) // 2
