from __future__ import annotations

from pathlib import Path

import pytest

from jpnote_app.import_source import ImportSource


def test_import_source_deletes_only_unchanged_regular_file(tmp_path: Path) -> None:
    source_path = tmp_path / "payload.json"
    source_path.write_text('{"schema":"jpnote"}\n', encoding="utf-8")

    source = ImportSource.read(source_path)

    assert source.text == '{"schema":"jpnote"}\n'
    source.delete_if_unchanged()
    assert not source_path.exists()


def test_import_source_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "payload.json"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="符號連結"):
        ImportSource.read(link)


def test_import_source_refuses_in_place_change_after_read(tmp_path: Path) -> None:
    source_path = tmp_path / "payload.json"
    source_path.write_text("{}", encoding="utf-8")
    source = ImportSource.read(source_path)

    source_path.write_text('{"changed":true}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="已被修改或替換"):
        source.delete_if_unchanged()
    assert source_path.exists()


def test_import_source_refuses_replaced_inode(tmp_path: Path) -> None:
    source_path = tmp_path / "payload.json"
    source_path.write_text("{}", encoding="utf-8")
    source = ImportSource.read(source_path)

    replacement = tmp_path / "replacement.json"
    replacement.write_text("{}", encoding="utf-8")
    replacement.replace(source_path)

    with pytest.raises(RuntimeError, match="已被修改或替換"):
        source.delete_if_unchanged()
    assert source_path.exists()
