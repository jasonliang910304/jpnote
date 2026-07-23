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
DEFAULT_CONFIG: dict[str, Any] = {
    "browse": {
        "types": list(DEFAULT_TYPES),
        "levels": [],
        # Empty means no result narrowing, i.e. all mistake results.
        "results": [],
    }
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
    return {
        "browse": {
            "types": types,
            "levels": levels,
            "results": results,
        }
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
