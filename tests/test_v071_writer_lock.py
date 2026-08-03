from __future__ import annotations

import multiprocessing
import os
import sqlite3
import time
from pathlib import Path

import pytest

from jpnote_app.db import active_backups, connect, mutation_backup
from jpnote_app.writer_lock import WriterLockTimeout, writer_lock


def _hold_lock(data_dir: str, ready: str) -> None:
    os.environ["JPNOTE_DATA_DIR"] = data_dir
    with writer_lock("test-holder", timeout=2):
        Path(ready).write_text("ready", encoding="utf-8")
        time.sleep(0.5)


def _write_state(data_dir: str, label: str, value: str, ready: str | None, delay: float) -> None:
    os.environ["JPNOTE_DATA_DIR"] = data_dir
    with mutation_backup(label) as backup:
        if ready is not None:
            Path(ready).write_text("ready", encoding="utf-8")
        conn = connect()
        conn._jpnote_auto_close = False
        try:
            with conn:
                conn.execute(
                    "INSERT INTO metadata(key, value) VALUES('writer-test', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (value,),
                )
                time.sleep(delay)
            backup.mark_changed(True)
        finally:
            conn.close()


def _wait_for(path: Path, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.01)


def _snapshot_value(path: Path) -> str:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key='writer-test'").fetchone()
    return "" if row is None else str(row[0])


def test_writer_lock_is_reentrant_and_times_out_across_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(tmp_path / "data"))

    with writer_lock("outer", timeout=0.1):
        with writer_lock("inner", timeout=0.1):
            pass

    ready = tmp_path / "ready"
    process = multiprocessing.get_context("spawn").Process(
        target=_hold_lock,
        args=(os.environ["JPNOTE_DATA_DIR"], str(ready)),
    )
    process.start()
    try:
        _wait_for(ready)
        with pytest.raises(WriterLockTimeout, match="等待 jpnote 寫入鎖"):
            with writer_lock("contender", timeout=0.05, poll_interval=0.01):
                pass
    finally:
        process.join(timeout=3)
        if process.is_alive():
            process.kill()
            process.join()


def test_concurrent_mutations_publish_undo_snapshots_in_commit_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(data_dir))
    with connect() as conn:
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES('writer-test', 'initial') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )

    first_ready = tmp_path / "first-ready"
    ctx = multiprocessing.get_context("spawn")
    first = ctx.Process(
        target=_write_state,
        args=(str(data_dir), "first", "first", str(first_ready), 0.35),
    )
    second = ctx.Process(
        target=_write_state,
        args=(str(data_dir), "second", "second", None, 0.0),
    )

    first.start()
    _wait_for(first_ready)
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)
    assert first.exitcode == 0
    assert second.exitcode == 0

    backups = active_backups()
    assert len(backups) == 2
    assert "first" in backups[0].name
    assert "second" in backups[1].name
    assert _snapshot_value(backups[0]) == "initial"
    assert _snapshot_value(backups[1]) == "first"

    with connect() as conn:
        assert conn.execute(
            "SELECT value FROM metadata WHERE key='writer-test'"
        ).fetchone()[0] == "second"


def test_writer_lock_rejects_symlink_lock_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = tmp_path / "target"
    target.write_text("do-not-touch", encoding="utf-8")
    (data_dir / ".writer.lock").symlink_to(target)
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(data_dir))

    with pytest.raises(RuntimeError, match="不可是符號連結"):
        with writer_lock("symlink-test", timeout=0.1):
            pass
    assert target.read_text(encoding="utf-8") == "do-not-touch"


def test_writer_lock_rejects_hard_link_lock_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = tmp_path / "target"
    target.write_text("do-not-touch", encoding="utf-8")
    os.link(target, data_dir / ".writer.lock")
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(data_dir))

    with pytest.raises(RuntimeError, match="hard link"):
        with writer_lock("hardlink-test", timeout=0.1):
            pass
    assert target.read_text(encoding="utf-8") == "do-not-touch"
