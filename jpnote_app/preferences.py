"""User-editable jpnote preferences.

The preferences file is intentionally separate from SQLite and import JSON.
It controls only local CLI behaviour, so changing defaults never mutates study
records or changes the public data schema.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .browsing import DEFAULT_TYPES, LEVEL_VALUES, RESULT_VALUES
from .fs_utils import atomic_write_text, ensure_directory, ensure_private_dir, ensure_private_file

CONFIG_ENV = "JPNOTE_CONFIG_FILE"
QUIZ_MODES = frozenset({"mixed", "vocabulary", "mistake"})
QUIZ_LEVEL_VALUES = ("N5", "N4", "N3", "N2", "N1", "unclassified")
DEFAULT_CONFIG: dict[str, Any] = {
    "browse": {
        "types": list(DEFAULT_TYPES),
        "levels": [],
        # Empty means no result narrowing, i.e. all mistake results.
        "results": [],
    },
    "quiz": {
        "mode": "mixed",
        "count": 10,
        "levels": [],
        "sources": [],
        "transparent_background": True,
        "history_detail_cap_mib": 100,
        "prune_after_session": True,
    },
}


def config_dir() -> Path:
    override = os.environ.get("XDG_CONFIG_HOME")
    root = Path(override).expanduser() if override else Path.home() / ".config"
    return root / "jpnote"


def config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    return config_dir() / "config.json"



def _uses_app_owned_config_parent() -> bool:
    return not bool(os.environ.get(CONFIG_ENV))

def _string_list(value: Any, *, field: str, allowed: set[str]) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"設定 {field} 必須是 JSON 陣列。")
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text not in allowed:
            choices = "、".join(sorted(allowed))
            raise ValueError(f"設定 {field} 含有不支援的值：{text}（可用：{choices}）")
        if text not in result:
            result.append(text)
    return result


def _free_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"設定 {field} 必須是 JSON 陣列。")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"設定 {field} 的每個值都必須是字串。")
        text = item.strip()
        if not text:
            raise ValueError(f"設定 {field} 不可包含空字串。")
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise ValueError(f"設定 {field} 不可包含控制字元。")
        if text not in result:
            result.append(text)
    return result


def _bounded_int(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"設定 {field} 必須是整數。")
    if not minimum <= value <= maximum:
        raise ValueError(f"設定 {field} 必須介於 {minimum} 到 {maximum}。")
    return value


def _boolean(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"設定 {field} 必須是 true 或 false。")
    return value


def validate_preferences(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("jpnote 設定檔最外層必須是 JSON object。")
    browse = raw.get("browse", {})
    if not isinstance(browse, dict):
        raise ValueError("設定 browse 必須是 JSON object。")

    types = _string_list(
        browse.get("types", list(DEFAULT_TYPES)),
        field="browse.types",
        allowed={"grammar", "vocab", "mistake"},
    )
    levels = _string_list(
        browse.get("levels", []),
        field="browse.levels",
        allowed=set(LEVEL_VALUES),
    )
    results = _string_list(
        browse.get("results", []),
        field="browse.results",
        allowed=set(RESULT_VALUES),
    )
    # wrong/partial are only active when mistake is explicitly selected.
    # Clear stale hidden filters instead of letting them silently affect later
    # browse sessions.  An empty type list means all types, not explicit mistake.
    if "mistake" not in types:
        results = []

    quiz = raw.get("quiz", {})
    if not isinstance(quiz, dict):
        raise ValueError("設定 quiz 必須是 JSON object。")
    mode = quiz.get("mode", DEFAULT_CONFIG["quiz"]["mode"])
    if not isinstance(mode, str) or mode not in QUIZ_MODES:
        choices = "、".join(sorted(QUIZ_MODES))
        raise ValueError(f"設定 quiz.mode 不支援：{mode}（可用：{choices}）")
    count = _bounded_int(
        quiz.get("count", DEFAULT_CONFIG["quiz"]["count"]),
        field="quiz.count",
        minimum=1,
        maximum=100,
    )
    quiz_levels = _string_list(
        quiz.get("levels", []),
        field="quiz.levels",
        allowed=set(QUIZ_LEVEL_VALUES),
    )
    sources = _free_string_list(quiz.get("sources", []), field="quiz.sources")
    transparent_background = _boolean(
        quiz.get(
            "transparent_background",
            DEFAULT_CONFIG["quiz"]["transparent_background"],
        ),
        field="quiz.transparent_background",
    )
    history_detail_cap_mib = _bounded_int(
        quiz.get(
            "history_detail_cap_mib",
            DEFAULT_CONFIG["quiz"]["history_detail_cap_mib"],
        ),
        field="quiz.history_detail_cap_mib",
        minimum=1,
        maximum=10240,
    )
    prune_after_session = _boolean(
        quiz.get(
            "prune_after_session",
            DEFAULT_CONFIG["quiz"]["prune_after_session"],
        ),
        field="quiz.prune_after_session",
    )
    return {
        "browse": {
            "types": types,
            "levels": levels,
            "results": results,
        },
        "quiz": {
            "mode": mode,
            "count": count,
            "levels": quiz_levels,
            "sources": sources,
            "transparent_background": transparent_background,
            "history_detail_cap_mib": history_detail_cap_mib,
            "prune_after_session": prune_after_session,
        },
    }


def load_preferences() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    if _uses_app_owned_config_parent():
        ensure_private_dir(path.parent)
    else:
        ensure_directory(path.parent)
    ensure_private_file(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"設定檔 {path} 第 {exc.lineno} 行、第 {exc.colno} 欄不是有效 JSON。"
        ) from exc
    return validate_preferences(raw)


def write_preferences(config: dict[str, Any]) -> Path:
    normalized = validate_preferences(config)
    path = config_path()
    private_parent = _uses_app_owned_config_parent()
    if private_parent:
        ensure_private_dir(path.parent)
    else:
        ensure_directory(path.parent)
    atomic_write_text(
        path,
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        private_parent=private_parent,
    )
    ensure_private_file(path)
    return path


def ensure_preferences() -> Path:
    path = config_path()
    if not path.exists():
        return write_preferences(deepcopy(DEFAULT_CONFIG))
    # Validate existing content so `jpnote init` catches mistakes early.
    load_preferences()
    return path


def browse_default_filters() -> dict[str, set[str]]:
    browse = load_preferences()["browse"]
    return {
        "types": set(browse["types"]),
        "levels": set(browse["levels"]),
        "results": set(browse["results"]),
    }


def quiz_defaults() -> dict[str, Any]:
    """Return validated local defaults for the optional Quiz UI."""

    return deepcopy(load_preferences()["quiz"])
