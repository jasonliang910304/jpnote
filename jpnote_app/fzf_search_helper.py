"""Search helper used by fzf's reload-on-change integration.

fzf is intentionally used only as the interactive selector. Matching is done
here so hidden metadata (romaji variants, aliases, stable keys, mistake text)
uses the same normalization rules regardless of how fzf transforms visible
columns with ``--with-nth``.

The main process appends a folded and compact search index to every dataset row
once before fzf starts. Reloads therefore normalize only the query and perform
substring checks; legacy/unindexed rows retain the old normalization fallback.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .search_text import compact_folded_text, compact_text, fold_text


_INDEX_PREFIX = "__jpnote_search_index_v1__:"
_STRONG_PREFIX = "__jpnote_strong_index_v1__:"


def strong_search_index_field(values: object) -> str:
    """Encode normalized exact/whole terms once when the fzf dataset is built."""
    raw_terms: set[str] = set()
    compact_terms: set[str] = set()
    for value in values:
        folded = fold_text(str(value))
        if not folded:
            continue
        raw_terms.add(folded)
        compact = compact_folded_text(folded)
        if compact:
            compact_terms.add(compact)
    payload = [sorted(raw_terms), sorted(compact_terms)]
    return _STRONG_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def split_strong_search_index(line: str) -> tuple[str, str | None]:
    """Return the ordinary row and optional hidden strong-index field."""
    raw = line.rstrip("\n")
    parts = raw.split("\t")
    if parts and parts[-1].startswith(_STRONG_PREFIX):
        return "\t".join(parts[:-1]), parts[-1]
    return raw, None


def strip_strong_search_index(line: str) -> str:
    return split_strong_search_index(line)[0]


def _searchable_fields(line: str) -> str:
    raw, _strong = split_strong_search_index(line)
    parts = raw.split("\t")
    if len(parts) >= 4:
        # token | preview_path | visible | metadata
        values = (parts[0], parts[2], parts[3])
    elif len(parts) >= 3:
        # token | visible | metadata
        values = (parts[0], parts[1], parts[2])
    else:
        values = tuple(parts)
    return " ".join(values)


def search_index_fields(value: str) -> tuple[str, str]:
    """Return the exact two haystack forms used by the reload matcher."""
    folded = fold_text(value)
    return folded, compact_folded_text(folded)


def append_search_index(line: str) -> str:
    """Append hidden folded/compact columns to one raw fzf dataset row."""
    raw = line.rstrip("\n")
    folded, compact = search_index_fields(_searchable_fields(raw))
    return f"{raw}\t{_INDEX_PREFIX}{folded}\t{compact}"


def _indexed_parts(line: str) -> tuple[str, str, str] | None:
    parts = line.rstrip("\n").split("\t")
    # The explicit prefix avoids mistaking an arbitrary legacy/unindexed row
    # with five or six tab-separated fields for an indexed dataset row. Keep
    # the indexed fields only in the temp dataset; fzf itself receives the
    # original row shape.
    if len(parts) >= 3 and parts[-2].startswith(_INDEX_PREFIX):
        return (
            "\t".join(parts[:-2]),
            parts[-2][len(_INDEX_PREFIX):],
            parts[-1],
        )
    return None


def _matches_strong(line: str, raw_query: str, compact_query: str) -> bool:
    indexed = _indexed_parts(line)
    raw_line = indexed[0] if indexed is not None else line.rstrip("\n")
    _base, strong_field = split_strong_search_index(raw_line)
    if strong_field is None:
        return False
    try:
        raw_terms, compact_terms = json.loads(
            strong_field[len(_STRONG_PREFIX):]
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    return bool(
        (raw_query and raw_query in raw_terms)
        or (compact_query and compact_query in compact_terms)
    )


def _matches_normalized(line: str, raw_query: str, compact_query: str) -> bool:
    indexed = _indexed_parts(line)
    if indexed is None:
        haystack = _searchable_fields(line)
        raw_haystack = fold_text(haystack)
        compact_haystack = compact_text(haystack)
    else:
        _raw_line, raw_haystack, compact_haystack = indexed

    if raw_query and raw_query in raw_haystack:
        return True
    return bool(compact_query and compact_query in compact_haystack)


def matches(line: str, query: str) -> bool:
    """Compatibility matcher for tests/callers using one row at a time."""
    if not query:
        return True
    raw_query = fold_text(query)
    compact_query = compact_folded_text(raw_query)
    return _matches_normalized(line, raw_query, compact_query)


def filter_file(path: Path, query: str) -> int:
    raw_query = fold_text(query) if query else ""
    compact_query = compact_folded_text(raw_query) if raw_query else ""
    matched: list[tuple[str, bool]] = []
    has_strong_match = False
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            indexed = _indexed_parts(line)
            raw_line = indexed[0] if indexed is not None else line.rstrip("\n")
            visible_line = strip_strong_search_index(raw_line)
            if not query:
                matched.append((visible_line, False))
                continue
            strong = _matches_strong(line, raw_query, compact_query)
            if strong:
                has_strong_match = True
            if strong or _matches_normalized(line, raw_query, compact_query):
                matched.append((visible_line, strong))

    for raw_line, strong in matched:
        if not has_strong_match or strong:
            sys.stdout.write(raw_line + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 1:
        print("usage: python -m jpnote_app.fzf_search_helper DATASET [QUERY]", file=sys.stderr)
        return 2
    path = Path(args[0])
    query = args[1] if len(args) > 1 else ""
    return filter_file(path, query)


if __name__ == "__main__":
    raise SystemExit(main())
