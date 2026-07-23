"""Search helper used by fzf's reload-on-change integration.

fzf is intentionally used only as the interactive selector.  Matching is done
here so hidden metadata (romaji variants, aliases, stable keys, mistake text)
uses the same normalization rules regardless of how fzf chooses to transform
visible columns with ``--with-nth``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .search_normalization import compact_text, fold_text


def _searchable_fields(line: str) -> str:
    parts = line.rstrip("\n").split("\t")
    if len(parts) >= 4:
        # token | preview_path | visible | metadata
        values = (parts[0], parts[2], parts[3])
    elif len(parts) >= 3:
        # token | visible | metadata
        values = (parts[0], parts[1], parts[2])
    else:
        values = tuple(parts)
    return " ".join(values)


def matches(line: str, query: str) -> bool:
    if not query:
        return True
    haystack = _searchable_fields(line)
    raw_query = fold_text(query)
    raw_haystack = fold_text(haystack)
    if raw_query and raw_query in raw_haystack:
        return True
    compact_query = compact_text(query)
    return bool(compact_query and compact_query in compact_text(haystack))


def filter_file(path: Path, query: str) -> int:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if matches(line, query):
                sys.stdout.write(line)
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
