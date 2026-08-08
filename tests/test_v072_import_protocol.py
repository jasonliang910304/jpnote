from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from jpnote_app import cli
from jpnote_app.import_source import ImportSource
from jpnote_app.import_transport import (
    IMPORT_PROTOCOL_ID,
    IMPORT_PROTOCOL_VERSION,
    MAX_IMPORT_BYTES,
    read_import_stdin,
)


ROOT = Path(__file__).resolve().parents[1]


def payload(key: str = "vocab:猫") -> str:
    display = key.split(":", 1)[1]
    return json.dumps(
        {
            "source": "v0.7.2 protocol test",
            "items": [
                {
                    "key": key,
                    "type": "vocabulary",
                    "display": display,
                    "reading": "ねこ" if display == "猫" else "いぬ",
                    "meanings": ["測試"],
                }
            ],
        },
        ensure_ascii=False,
    )


def run_cli(tmp_path: Path, *args: str, input_bytes: bytes) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["JPNOTE_DATA_DIR"] = str(tmp_path / "data")
    return subprocess.run(
        [sys.executable, "-m", "jpnote_app", *args],
        input=input_bytes,
        capture_output=True,
        env=env,
        check=False,
    )


def decode_json(data: bytes) -> dict[str, object]:
    return json.loads(data.decode("utf-8"))


def test_import_parser_accepts_stdin_aliases_and_protocol() -> None:
    parser = cli.build_parser()

    dash = parser.parse_args(["import", "-", "--check", "--protocol", "1"])
    assert dash.file == "-"
    assert dash.stdin is False
    assert dash.protocol_version == "1"

    option = parser.parse_args(["import", "--stdin", "--protocol", "1"])
    assert option.file is None
    assert option.stdin is True


def test_import_stdin_rejects_cleanup_flags() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["import", "--stdin", "--keep-source"])

    with pytest.raises(ValueError, match="標準輸入沒有"):
        cli.command_import(args)


def test_read_import_stdin_is_utf8_strict_bom_aware_and_bounded() -> None:
    raw = io.BytesIO(b"\xef\xbb\xbf" + payload().encode("utf-8"))
    stream = io.TextIOWrapper(raw, encoding="ascii", errors="ignore")
    assert json.loads(read_import_stdin(stream))["items"][0]["display"] == "猫"

    invalid = io.TextIOWrapper(io.BytesIO(b"\xff\xfe"), encoding="ascii", errors="ignore")
    with pytest.raises(ValueError, match="有效 UTF-8"):
        read_import_stdin(invalid)

    oversized = io.TextIOWrapper(io.BytesIO(b"x" * 9), encoding="ascii")
    with pytest.raises(ValueError, match="大小上限"):
        read_import_stdin(oversized, max_bytes=8)


def test_import_source_accepts_bom_and_rejects_oversized_file(tmp_path: Path) -> None:
    source_path = tmp_path / "bom.json"
    source_path.write_bytes(b"\xef\xbb\xbf" + payload().encode("utf-8"))
    source = ImportSource.read(source_path)
    assert json.loads(source.text)["items"][0]["display"] == "猫"

    huge = tmp_path / "huge.json"
    with huge.open("wb") as handle:
        handle.truncate(MAX_IMPORT_BYTES + 1)
    with pytest.raises(ValueError, match="大小上限"):
        ImportSource.read(huge)


def test_protocol_check_envelope_is_stable(tmp_path: Path) -> None:
    proc = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--check",
        "--protocol",
        "1",
        input_bytes=payload().encode("utf-8"),
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert proc.stdout.isascii()
    result = decode_json(proc.stdout)
    assert result["protocol"] == IMPORT_PROTOCOL_ID
    assert result["protocol_version"] == IMPORT_PROTOCOL_VERSION
    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["mode"] == "check"
    assert result["preflight"]["database_modified"] is False
    assert result["preflight"]["summary"]["new_items"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", str(result["preflight_token"]))



def test_protocol_preflight_token_binds_check_to_apply(tmp_path: Path) -> None:
    raw = payload("vocab:犬").encode("utf-8")
    checked = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--check",
        "--yes",
        "--protocol",
        "1",
        input_bytes=raw,
    )
    assert checked.returncode == 0, checked.stderr.decode("utf-8", errors="replace")
    check_result = decode_json(checked.stdout)
    token = str(check_result["preflight_token"])
    assert re.fullmatch(r"[0-9a-f]{64}", token)

    applied = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--yes",
        "--protocol",
        "1",
        "--preflight-token",
        token,
        input_bytes=raw,
    )
    assert applied.returncode == 0, applied.stderr.decode("utf-8", errors="replace")
    apply_result = decode_json(applied.stdout)
    assert apply_result["ok"] is True
    assert apply_result["preflight_token"] == token
    assert apply_result["result"]["added_entries"] == 1


def test_protocol_rejects_stale_preflight_token(tmp_path: Path) -> None:
    checked = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--check",
        "--yes",
        "--protocol",
        "1",
        input_bytes=payload("vocab:猫").encode("utf-8"),
    )
    assert checked.returncode == 0
    token = str(decode_json(checked.stdout)["preflight_token"])

    stale = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--yes",
        "--protocol",
        "1",
        "--preflight-token",
        token,
        input_bytes=payload("vocab:犬").encode("utf-8"),
    )
    assert stale.returncode == 1
    result = decode_json(stale.stdout)
    assert result["ok"] is False
    assert "預檢" in result["error"]["message"]



def test_protocol_check_yes_matches_apply_safe_fix_plan(tmp_path: Path) -> None:
    raw = json.dumps(
        {
            "source": "v0.7.2 safe-fix token test",
            "items": [
                {
                    "key": "vocab:猫",
                    "type": "vocabulary",
                    "display": "猫",
                    "reading": "ねこ",
                    "aliases": ["ねこ"],
                    "meanings": ["貓"],
                }
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")

    checked = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--check",
        "--yes",
        "--protocol",
        "1",
        input_bytes=raw,
    )
    assert checked.returncode == 0, checked.stderr.decode("utf-8", errors="replace")
    check_result = decode_json(checked.stdout)
    assert check_result["preflight"]["safe_fixes"] == []
    token = str(check_result["preflight_token"])

    applied = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--yes",
        "--protocol",
        "1",
        "--preflight-token",
        token,
        input_bytes=raw,
    )
    assert applied.returncode == 0, applied.stderr.decode("utf-8", errors="replace")
    result = decode_json(applied.stdout)
    assert result["preflight_token"] == token
    assert result["result"]["added_entries"] == 1

def test_protocol_rejects_database_drift_after_check(tmp_path: Path) -> None:
    raw = payload("vocab:猫").encode("utf-8")
    checked = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--check",
        "--yes",
        "--protocol",
        "1",
        input_bytes=raw,
    )
    token = str(decode_json(checked.stdout)["preflight_token"])

    intervening = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--yes",
        "--protocol",
        "1",
        input_bytes=raw,
    )
    assert intervening.returncode == 0

    stale = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--yes",
        "--protocol",
        "1",
        "--preflight-token",
        token,
        input_bytes=raw,
    )
    assert stale.returncode == 1
    result = decode_json(stale.stdout)
    assert result["status"] == "error"
    assert "預檢" in result["error"]["message"]


def test_protocol_no_selection_keeps_success_status(tmp_path: Path) -> None:
    proc = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--yes",
        "--protocol",
        "1",
        "--skip-item",
        "vocab:猫",
        input_bytes=payload("vocab:猫").encode("utf-8"),
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    result = decode_json(proc.stdout)
    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["outcome"] == "no_selection"
    assert result["modified"] is False


def test_protocol_dry_run_is_wrapped_without_writing(tmp_path: Path) -> None:
    proc = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--dry-run",
        "--protocol",
        "1",
        input_bytes=payload().encode("utf-8"),
    )
    assert proc.returncode == 0
    result = decode_json(proc.stdout)
    assert result["status"] == "success"
    assert result["mode"] == "dry_run"
    assert result["plan"]["items"][0]["key"] == "vocab:猫"
    assert not (tmp_path / "data" / "jpnote.db").exists()

def test_protocol_import_envelope_and_noop_modified_flag(tmp_path: Path) -> None:
    raw = payload("vocab:犬").encode("utf-8")
    first = run_cli(
        tmp_path,
        "import",
        "-",
        "--yes",
        "--protocol",
        "1",
        input_bytes=raw,
    )
    assert first.returncode == 0, first.stderr.decode("utf-8", errors="replace")
    first_result = decode_json(first.stdout)
    assert first_result["ok"] is True
    assert first_result["mode"] == "import"
    assert first_result["modified"] is True
    assert first_result["result"]["added_entries"] == 1
    assert "source_cleanup" not in first_result

    second = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--yes",
        "--protocol",
        "1",
        input_bytes=raw,
    )
    assert second.returncode == 0
    second_result = decode_json(second.stdout)
    assert second_result["ok"] is True
    assert second_result["modified"] is False
    assert second_result["result"]["unchanged_entries"] == 1


def test_protocol_error_is_json_and_nonzero(tmp_path: Path) -> None:
    proc = run_cli(
        tmp_path,
        "import",
        "--stdin",
        "--check",
        "--protocol",
        "1",
        input_bytes=b"{ invalid",
    )
    assert proc.returncode == 1
    result = decode_json(proc.stdout)
    assert result["protocol"] == IMPORT_PROTOCOL_ID
    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["mode"] == "check"
    assert result["error"]["type"] in {"invalid_json", "invalid_input"}
    assert result["error"]["message"]


def test_legacy_json_output_remains_unwrapped(tmp_path: Path) -> None:
    source = tmp_path / "payload.json"
    source.write_text(payload(), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["JPNOTE_DATA_DIR"] = str(tmp_path / "data")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "jpnote_app",
            "import",
            str(source),
            "--check",
            "--format",
            "json",
        ],
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    result = decode_json(proc.stdout)
    assert "protocol" not in result
    assert result["database_modified"] is False
