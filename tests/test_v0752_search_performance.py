from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from jpnote_app import fzf_search_helper as helper
from jpnote_app.search_normalization import entry_match_score
from jpnote_app.search_text import compact_folded_text, compact_text, fold_text


def _legacy_match(line: str, query: str) -> bool:
    if not query:
        return True
    haystack = helper._searchable_fields(line)
    raw_query = fold_text(query)
    raw_haystack = fold_text(haystack)
    if raw_query and raw_query in raw_haystack:
        return True
    compact_query = compact_text(query)
    return bool(compact_query and compact_query in compact_text(haystack))


def _filter_output(path: Path, query: str) -> str:
    output = io.StringIO()
    with patch("sys.stdout", output):
        assert helper.filter_file(path, query) == 0
    return output.getvalue()


def test_indexed_fzf_dataset_preserves_legacy_matching_and_raw_output(tmp_path: Path) -> None:
    raw_lines = [
        "entry:vocab:奇跡\t/tmp/p0\t[單字] 奇跡 きせき／N1\tki se ki kiseki",
        "entry:vocab:教室\t/tmp/p1\t[單字] 教室 きょうしつ／N4\tkyō shi tsu kyoshitsu kyoushitsu",
        "attempt:a\t/tmp/p2\t[錯題] wrong 2026-09-12 未分類\twrong event:a source",
        "entry:grammar:Nになる\t/tmp/p3\t[文法] Nになる N3\tninaru ni naru",
    ]
    indexed = [helper.append_search_index(line) for line in raw_lines]
    dataset = tmp_path / "records.tsv"
    dataset.write_text("\n".join(indexed) + "\n", encoding="utf-8")

    for line, indexed_line in zip(raw_lines, indexed, strict=True):
        parts = helper._indexed_parts(indexed_line)
        assert parts is not None
        assert parts[0] == line
        assert len(indexed_line.split("\t")) == len(line.split("\t")) + 2

    for query in ("", "奇跡", "ki se ki", "kiseki", "kyoushitsu", "N4", "錯題", "wrong", "未分類", "ninaru", "zzzz"):
        expected = "".join(
            line + "\n" for line in raw_lines if _legacy_match(line, query)
        )
        assert _filter_output(dataset, query) == expected


def test_unindexed_five_column_row_keeps_legacy_fallback() -> None:
    line = "token\tpreview\tvisible\tmetadata\textra"
    assert helper._indexed_parts(line) is None
    assert helper.matches(line, "metadata") is True
    assert helper.matches(line, "missing") is False


def test_indexed_reload_normalizes_query_once_not_once_per_row(tmp_path: Path) -> None:
    raw_lines = [
        f"entry:vocab:{index}\t[單字] item{index}\treading romaji meaning {index}"
        for index in range(500)
    ]
    dataset = tmp_path / "records.tsv"
    dataset.write_text(
        "\n".join(helper.append_search_index(line) for line in raw_lines) + "\n",
        encoding="utf-8",
    )

    real_fold = helper.fold_text
    real_compact_folded = helper.compact_folded_text
    fold_calls = 0
    compact_calls = 0

    def counted_fold(value: str) -> str:
        nonlocal fold_calls
        fold_calls += 1
        return real_fold(value)

    def counted_compact(value: str) -> str:
        nonlocal compact_calls
        compact_calls += 1
        return real_compact_folded(value)

    with (
        patch.object(helper, "fold_text", side_effect=counted_fold),
        patch.object(helper, "compact_folded_text", side_effect=counted_compact),
        patch("sys.stdout", io.StringIO()),
    ):
        helper.filter_file(dataset, "romaji")

    assert fold_calls == 1
    assert compact_calls == 1


def test_compacting_an_already_folded_value_is_exactly_equivalent() -> None:
    samples = (
        "Kyō shi tsu",
        "ＫＹＯＵ－ＳＨＩＴＳＵ",
        "  ma ta wa  ",
        "〜てくれる",
        "理由　N3",
        "école",
    )
    for sample in samples:
        assert compact_folded_text(fold_text(sample)) == compact_text(sample)


def test_entry_match_score_reuses_variant_sets_when_falling_through_to_metadata() -> None:
    entry = {
        "key": "vocab:教室",
        "type": "vocabulary",
        "display": "教室",
        "reading": "きょうしつ",
        "romaji": "kyō shi tsu",
        "level": "N4",
        "aliases": [],
        "sources": ["TRY! N4"],
        "senses": [{"meaning": "教室", "example_ja": "", "example_zh": ""}],
        "related_grammar": [],
        "pending_related_grammar": [],
    }

    import jpnote_app.search_normalization as normalization

    real_romaji = normalization.romaji_variants
    real_grammar = normalization.grammar_romaji_variants
    counts = {"romaji": 0, "grammar": 0}

    def counted_romaji(value: str) -> set[str]:
        counts["romaji"] += 1
        return real_romaji(value)

    def counted_grammar(value: dict[str, object]) -> set[str]:
        counts["grammar"] += 1
        return real_grammar(value)

    with (
        patch.object(normalization, "romaji_variants", side_effect=counted_romaji),
        patch.object(normalization, "grammar_romaji_variants", side_effect=counted_grammar),
    ):
        assert entry_match_score(entry, "definitely-no-match") is None

    # Before v0.7.5.2 both sets were rebuilt by entry_search_metadata() after
    # already being computed for relaxed-romaji scoring.
    assert counts == {"romaji": 1, "grammar": 1}
