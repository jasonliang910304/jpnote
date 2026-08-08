"""Bounded UTF-8 stdin transport and stable import protocol metadata."""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, BinaryIO, TextIO

IMPORT_PROTOCOL_ID = "jpnote.import.v1"
IMPORT_PROTOCOL_VERSION = 1
MAX_IMPORT_BYTES = 16 * 1024 * 1024


def read_import_stdin(
    stream: TextIO | None = None,
    *,
    max_bytes: int = MAX_IMPORT_BYTES,
) -> str:
    """Read one complete UTF-8 payload from stdin with a hard size limit.

    Real CLI stdin exposes ``.buffer`` and is read as bytes so locale-dependent
    text decoding cannot corrupt Windows/SSH input.  StringIO-like test streams
    remain supported and are measured after UTF-8 encoding.
    """
    if max_bytes <= 0:
        raise ValueError("import stdin 大小上限必須大於 0。")

    source = sys.stdin if stream is None else stream
    binary: BinaryIO | None = getattr(source, "buffer", None)

    if binary is not None:
        payload = binary.read(max_bytes + 1)
    else:
        text = source.read(max_bytes + 1)
        payload = text.encode("utf-8")

    if len(payload) > max_bytes:
        raise ValueError(
            f"匯入資料超過大小上限 {max_bytes} bytes；請拆分後再匯入。"
        )

    try:
        # utf-8-sig accepts ordinary UTF-8 and removes one optional BOM.
        return payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"標準輸入不是有效 UTF-8（byte {exc.start}）。"
        ) from exc


def import_protocol_envelope(
    *,
    jpnote_version: str,
    ok: bool,
    mode: str,
    **payload: Any,
) -> dict[str, Any]:
    """Return the versioned JSON envelope used by remote import clients."""
    return {
        "protocol": IMPORT_PROTOCOL_ID,
        "protocol_version": IMPORT_PROTOCOL_VERSION,
        "jpnote_version": jpnote_version,
        "ok": ok,
        "status": "success" if ok else "error",
        "mode": mode,
        **payload,
    }


def import_preflight_token(plan: Any, report: dict[str, Any]) -> str:
    """Hash the exact normalized plan and preflight shown to a remote user."""
    canonical = json.dumps(
        {"plan": plan.to_dict(), "preflight": report},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
