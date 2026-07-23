"""Small helper used by one persistent fzf filter-panel process.

fzf calls this module through ``execute-silent``.  The helper only updates a
short-lived JSON state file and regenerates panel rows; it never touches the
jpnote database or user preferences.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .browsing import ALL_TYPES, DEFAULT_TYPES, LEVEL_VALUES, RESULT_VALUES, TYPE_LABELS

OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("types", "grammar", "類型", "文法"),
    ("types", "vocab", "類型", "單字"),
    ("types", "mistake", "類型", "錯題"),
    ("levels", "N5", "等級", "N5"),
    ("levels", "N4", "等級", "N4"),
    ("levels", "N3", "等級", "N3"),
    ("levels", "N2", "等級", "N2"),
    ("levels", "N1", "等級", "N1"),
    ("levels", "unclassified", "等級", "未分類"),
    ("results", "wrong", "錯題結果", "wrong"),
    ("results", "partial", "錯題結果", "partial"),
)

# Stable direct-key shortcuts inside the filter panel.  The less common
# "未分類" remains available through cursor+Space so the common set fits 1-0.
SHORTCUT_TOKENS: dict[str, str] = {
    "1": "types:grammar",
    "2": "types:vocab",
    "3": "types:mistake",
    "4": "levels:N5",
    "5": "levels:N4",
    "6": "levels:N3",
    "7": "levels:N2",
    "8": "levels:N1",
    "9": "results:wrong",
    "0": "results:partial",
}
TOKEN_SHORTCUTS = {token: key for key, token in SHORTCUT_TOKENS.items()}


def normalize_state(raw: Any) -> dict[str, set[str]]:
    data = raw if isinstance(raw, dict) else {}
    types = {value for value in data.get("types", []) if value in set(ALL_TYPES)}
    results = {value for value in data.get("results", []) if value in set(RESULT_VALUES)}
    if "mistake" not in types:
        results.clear()
    return {
        "types": types,
        "levels": {value for value in data.get("levels", []) if value in set(LEVEL_VALUES)},
        "results": results,
    }


def serializable(state: dict[str, set[str]]) -> dict[str, list[str]]:
    return {
        "types": [value for value in ALL_TYPES if value in state["types"]],
        "levels": [value for value in LEVEL_VALUES if value in state["levels"]],
        "results": [value for value in RESULT_VALUES if value in state["results"]],
    }


def read_state(path: Path) -> dict[str, set[str]]:
    return normalize_state(json.loads(path.read_text(encoding="utf-8")))


def write_state(path: Path, state: dict[str, set[str]]) -> None:
    path.write_text(json.dumps(serializable(state), ensure_ascii=False), encoding="utf-8")


def summary(state: dict[str, set[str]]) -> str:
    type_text = "、".join(
        TYPE_LABELS[value] for value in ALL_TYPES if value in state["types"]
    ) or "全部"
    levels = [value for value in LEVEL_VALUES if value in state["levels"]]
    level_text = "、".join("未分類" if value == "unclassified" else value for value in levels) or "全部"
    parts = [f"類型＝{type_text}", f"等級＝{level_text}"]
    if "mistake" in state["types"]:
        chosen = [value for value in RESULT_VALUES if value in state["results"]]
        result_text = "全部" if len(chosen) in {0, len(RESULT_VALUES)} else "、".join(chosen)
        parts.append(f"錯題＝{result_text}")
    return "｜".join(parts)


def render_panel(path: Path, state: dict[str, set[str]]) -> None:
    lines = [
        f"__summary__\t目前：{summary(state)}\t",
        "__help__\t1–0 快速切換｜Space 切換目前項目｜Enter 套用｜Ctrl-R 設定預設｜Esc 取消\t",
    ]
    for group, value, group_label, label in OPTIONS:
        if group == "results" and "mistake" not in state["types"]:
            continue
        checked = value in state[group]
        box = "[✓]" if checked else "[ ]"
        token = f"{group}:{value}"
        shortcut = TOKEN_SHORTCUTS.get(token)
        prefix = f"{shortcut}. " if shortcut else "   "
        lines.append(f"{token}\t{box} {prefix}{group_label}  {label}\t{group_label} {label}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def toggle(state: dict[str, set[str]], token: str) -> None:
    if ":" not in token:
        return
    group, value = token.split(":", 1)
    if group not in state:
        return
    allowed = {
        "types": {"grammar", "vocab", "mistake"},
        "levels": set(LEVEL_VALUES),
        "results": set(RESULT_VALUES),
    }[group]
    if value not in allowed:
        return
    if group == "results" and "mistake" not in state["types"]:
        return
    if value in state[group]:
        state[group].remove(value)
    else:
        state[group].add(value)
    if group == "types" and value == "mistake" and "mistake" not in state["types"]:
        state["results"].clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("toggle", "shortcut", "reset"))
    parser.add_argument("state")
    parser.add_argument("panel")
    parser.add_argument("defaults")
    parser.add_argument("token", nargs="?")
    args = parser.parse_args()

    state_path = Path(args.state)
    panel_path = Path(args.panel)
    defaults_path = Path(args.defaults)
    state = read_state(state_path)
    if args.action == "toggle":
        toggle(state, args.token or "")
    elif args.action == "shortcut":
        token = SHORTCUT_TOKENS.get(args.token or "")
        if token:
            toggle(state, token)
    else:
        state = read_state(defaults_path)
    write_state(state_path, state)
    render_panel(panel_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
