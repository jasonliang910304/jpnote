from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from jpnote_app import cli
from jpnote_app.db import connect, connect_preflight, connect_readonly
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.import_source import ImportSource
from jpnote_app.services import apply_import, prepare_import


class _NonInteractiveStdin:
    def isatty(self) -> bool:
        return False


class _InteractiveStdin:
    def isatty(self) -> bool:
        return True


def _cleanup_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "delete_source": False,
        "keep_source": False,
        "format": "text",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_import_parser_source_cleanup_flags_are_safe_by_default() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["import", "payload.json"])
    assert args.delete_source is False
    assert args.keep_source is False

    args = parser.parse_args(["import", "payload.json", "--delete-source"])
    assert args.delete_source is True
    assert args.keep_source is False

    args = parser.parse_args(["import", "payload.json", "--keep-source"])
    assert args.keep_source is True
    assert args.delete_source is False

    with pytest.raises(SystemExit):
        parser.parse_args(
            ["import", "payload.json", "--delete-source", "--keep-source"]
        )


def test_noninteractive_import_keeps_source_without_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "payload.json"
    path.write_text("{}", encoding="utf-8")
    source = ImportSource.read(path)
    monkeypatch.setattr(cli.sys, "stdin", _NonInteractiveStdin())

    result = cli._cleanup_import_source(source, _cleanup_args())

    assert result["status"] == "kept"
    assert result["reason"] == "noninteractive_default"
    assert path.exists()


def test_explicit_delete_source_is_post_success_and_fail_soft(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "payload.json"
    path.write_text("{}", encoding="utf-8")
    source = ImportSource.read(path)
    path.write_text('{"changed":true}', encoding="utf-8")

    result = cli._cleanup_import_source(
        source,
        _cleanup_args(delete_source=True),
    )

    assert result["status"] == "delete_failed"
    assert path.exists()
    assert "匯入已成功，但來源檔未刪除" in capsys.readouterr().err


def test_command_import_reads_one_verified_source_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "payload.json"
    path.write_text('{"schema":"jpnote-v0.3"}', encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(text: str, args: argparse.Namespace, *, source: ImportSource | None = None) -> int:
        captured["text"] = text
        captured["source"] = source
        return 17

    monkeypatch.setattr(cli, "_run_import_text", fake_run)
    args = argparse.Namespace(file=str(path))

    assert cli.command_import(args) == 17
    assert captured["text"] == '{"schema":"jpnote-v0.3"}'
    assert isinstance(captured["source"], ImportSource)
    assert captured["source"].path == path


def test_locked_import_revalidation_rejects_stale_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(tmp_path / "data"))
    payload = {
        "source": "test",
        "items": [{
            "key": "vocab:猫",
            "type": "vocabulary",
            "display": "猫",
            "reading": "ねこ",
            "meanings": ["貓"],
        }],
    }
    with connect_preflight() as conn:
        selected = prepare_import(conn, payload)
        approved = build_preflight_report(conn, selected)

    # Simulate a second writer committing after the user saw/approved preflight.
    with connect() as conn:
        conn.execute(
            "INSERT INTO entries(key, type, display, reading, romaji, level, aliases_json, origin_type, origin_language, origin_word, origin_note, created_at, updated_at) "
            "VALUES(?, 'vocabulary', ?, ?, '', '', '[]', '', '', '', '', datetime('now'), datetime('now'))",
            ("vocab:猫", "猫", "ねこ"),
        )

    with connect() as conn:
        with pytest.raises(RuntimeError, match="確認後已變更"):
            cli._apply_import_if_preflight_current(conn, selected, approved)


def test_locked_import_revalidation_applies_unchanged_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(tmp_path / "data"))
    payload = {
        "source": "test",
        "items": [{
            "key": "vocab:犬",
            "type": "vocabulary",
            "display": "犬",
            "reading": "いぬ",
            "meanings": ["狗"],
        }],
    }
    with connect_preflight() as conn:
        selected = prepare_import(conn, payload)
        approved = build_preflight_report(conn, selected)

    with connect() as conn:
        result = cli._apply_import_if_preflight_current(conn, selected, approved)
    assert result.added_entries == 1


def test_cleanup_prompt_interrupt_keeps_successful_import_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "payload.json"
    path.write_text("{}", encoding="utf-8")
    source = ImportSource.read(path)
    monkeypatch.setattr(cli.sys, "stdin", type("Tty", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(cli, "_confirm_yes_no", lambda _prompt: (_ for _ in ()).throw(KeyboardInterrupt()))

    result = cli._cleanup_import_source(source, _cleanup_args())

    assert result["status"] == "kept"
    assert result["reason"] == "prompt_interrupted"
    assert path.exists()


def test_locked_import_revalidation_preserves_generated_attempt_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(tmp_path / "data"))
    payload = {
        "source": "test",
        "items": [{
            "key": "vocab:鳥",
            "type": "vocabulary",
            "display": "鳥",
            "reading": "とり",
            "meanings": ["鳥"],
        }],
        "attempts": [{
            "result": "wrong",
            "question_type": "multiple_choice",
            "question": "1",
            "prompt": "鳥の読み方",
            "user_answer": "ちょう",
            "correct_answer": "とり",
            "linked_entries": ["vocab:鳥"],
        }],
    }
    with connect_preflight() as conn:
        selected = prepare_import(conn, payload)
        approved = build_preflight_report(conn, selected)
    assert selected.attempts[0]["_event_key_generated"] is True

    with connect() as conn:
        result = cli._apply_import_if_preflight_current(conn, selected, approved)
    assert result.added_attempts == 1

@pytest.mark.parametrize("exc_type", (EOFError, KeyboardInterrupt))
def test_precommit_yes_no_interrupt_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    exc_type: type[BaseException],
) -> None:
    def interrupted_input() -> str:
        raise exc_type()

    monkeypatch.setattr("builtins.input", interrupted_input)
    assert cli._confirm_precommit_yes_no("是否正式匯入？[y/N] ") is None


def test_duplicate_prompt_keyboard_interrupt_cancels_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(tmp_path / "data"))
    with connect() as conn:
        apply_import(
            conn,
            prepare_import(
                conn,
                {
                    "items": [{
                        "key": "vocab:餌",
                        "type": "vocabulary",
                        "display": "餌",
                        "reading": "えさ",
                        "meanings": ["飼料"],
                    }]
                },
            ),
        )

    payload = json.dumps(
        {
            "items": [{
                "key": "vocab:えさ",
                "type": "vocabulary",
                "display": "えさ",
                "reading": "えさ",
                "aliases": ["餌"],
                "meanings": ["餵動物的食物"],
            }]
        },
        ensure_ascii=False,
    )
    args = cli.build_parser().parse_args(["import", "payload.json"])
    monkeypatch.setattr(cli.sys, "stdin", _InteractiveStdin())

    def interrupted_input() -> str:
        raise KeyboardInterrupt()

    def forbidden_mutation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("pre-commit Ctrl+C must not enter execute_safe_mutation")

    monkeypatch.setattr("builtins.input", interrupted_input)
    monkeypatch.setattr(cli, "execute_safe_mutation", forbidden_mutation)

    assert cli._run_import_text(payload, args) == 0
    output = capsys.readouterr().out
    assert "疑似重複" in output
    assert "已取消，未修改資料庫。" in output

    with connect_readonly() as conn:
        keys = {
            row[0]
            for row in conn.execute(
                "SELECT key FROM entries WHERE key IN ('vocab:餌', 'vocab:えさ')"
            )
        }
    assert keys == {"vocab:餌"}


def test_safe_fix_prompt_keyboard_interrupt_cancels_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(tmp_path / "data"))
    payload = json.dumps(
        {
            "items": [{
                "key": "vocab:猫",
                "type": "vocabulary",
                "display": "猫",
                "reading": "ねこ",
                "aliases": ["猫"],
                "meanings": ["貓"],
            }]
        },
        ensure_ascii=False,
    )
    args = cli.build_parser().parse_args(["import", "payload.json"])
    monkeypatch.setattr(cli.sys, "stdin", _InteractiveStdin())

    def interrupted_input() -> str:
        raise KeyboardInterrupt()

    def forbidden_mutation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("interrupted safe-fix prompt must not mutate")

    monkeypatch.setattr("builtins.input", interrupted_input)
    monkeypatch.setattr(cli, "execute_safe_mutation", forbidden_mutation)

    assert cli._run_import_text(payload, args) == 0
    output = capsys.readouterr().out
    assert "是否先套用安全修正" in output
    assert "已取消，未修改資料庫。" in output


def test_final_import_prompt_keyboard_interrupt_cancels_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(tmp_path / "data"))
    payload = json.dumps(
        {
            "items": [{
                "key": "vocab:犬",
                "type": "vocabulary",
                "display": "犬",
                "reading": "いぬ",
                "meanings": ["狗"],
            }]
        },
        ensure_ascii=False,
    )
    args = cli.build_parser().parse_args(["import", "payload.json"])
    monkeypatch.setattr(cli.sys, "stdin", _InteractiveStdin())

    def interrupted_input() -> str:
        raise KeyboardInterrupt()

    def forbidden_mutation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("final-confirmation Ctrl+C must not mutate")

    monkeypatch.setattr("builtins.input", interrupted_input)
    monkeypatch.setattr(cli, "execute_safe_mutation", forbidden_mutation)

    assert cli._run_import_text(payload, args) == 0
    output = capsys.readouterr().out
    assert "是否正式匯入？" in output
    assert "已取消，未修改資料庫。" in output
