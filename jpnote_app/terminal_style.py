"""ANSI color policy for jpnote's terminal presentation layer.

Colors are deliberately configured at the CLI boundary.  Core data, SQLite,
JSON, Markdown, and repository/services code never contain ANSI sequences.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TextIO

_RESET = "\x1b[0m"
_ENABLED = False
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

_CODES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
}


def configure(
    mode: str | None = None,
    *,
    output_format: str = "text",
    stream: TextIO | None = None,
) -> bool:
    """Configure color output and return whether ANSI styling is enabled.

    Precedence is explicit ``mode`` > ``JPNOTE_COLOR`` > ``auto``.  JSON is
    always plain.  In auto mode, ``NO_COLOR``, ``TERM=dumb``, and a non-TTY
    output stream disable ANSI sequences.
    """
    global _ENABLED

    selected = (mode or os.environ.get("JPNOTE_COLOR") or "auto").strip().lower()
    if selected not in {"auto", "always", "never"}:
        raise ValueError("JPNOTE_COLOR／--color 必須是 auto、always 或 never。")

    if output_format == "json" or selected == "never":
        _ENABLED = False
    elif selected == "always":
        _ENABLED = True
    else:
        target = stream or sys.stdout
        _ENABLED = (
            "NO_COLOR" not in os.environ
            and os.environ.get("TERM", "") != "dumb"
            and bool(getattr(target, "isatty", lambda: False)())
        )
    return _ENABLED


def enabled() -> bool:
    return _ENABLED


def style(text: str, *roles: str) -> str:
    if not _ENABLED or not text:
        return text
    codes = [_CODES[role] for role in roles if role in _CODES]
    if not codes:
        return text
    return f"\x1b[{';'.join(codes)}m{text}{_RESET}"


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def tone(text: str, name: str | None, *, bold: bool = False) -> str:
    roles: list[str] = []
    if bold:
        roles.append("bold")
    if name in _CODES:
        roles.append(str(name))
    return style(text, *roles)
