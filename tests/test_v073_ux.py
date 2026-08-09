from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys

from jpnote_app.browsing import browse_records
from jpnote_app.db import connect
from jpnote_app.import_preflight import build_preflight_report, render_preflight_text
from jpnote_app.quiz.tui_controller import MAX_QUESTION_COUNT, QuizTuiController
from jpnote_app.repository import search_entries
from jpnote_app.services import apply_import, prepare_import


ROOT = Path(__file__).resolve().parents[1]


class _CountOnlyService:
    def list_resumable_sessions(self, *, limit: int = 20):
        return ()


def _connect_at(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(tmp_path / "data"))
    return connect()


def test_preflight_exposes_update_details_for_local_and_protocol_clients(
    monkeypatch, tmp_path: Path
) -> None:
    with _connect_at(monkeypatch, tmp_path) as conn:
        apply_import(
            conn,
            prepare_import(
                conn,
                {
                    "source": "既有教材",
                    "items": [
                        {
                            "key": "vocab:募集",
                            "type": "vocabulary",
                            "display": "募集",
                            "reading": "ぼしゅう",
                            "level": "N4",
                            "meanings": ["募集"],
                        }
                    ],
                },
            ),
        )
        plan = prepare_import(
            conn,
            {
                "source": "TRY! N3",
                "items": [
                    {
                        "key": "vocab:募集",
                        "type": "vocabulary",
                        "display": "募集",
                        "reading": "ぼしゅう",
                        "level": "N3",
                        "aliases": ["募集する"],
                        "meanings": ["募集", "招募；徵集"],
                    }
                ],
            },
        )
        report = build_preflight_report(conn, plan)

    assert report["summary"]["update_items"] == 1
    assert len(report["updates"]) == 1
    update = report["updates"][0]
    assert update["key"] == "vocab:募集"
    assert update["type"] == "vocabulary"
    assert update["display"] == "募集"
    texts = [change["text"] for change in update["changes"]]
    assert "level：N4 → N3" in texts
    assert any(text.startswith("aliases：新增 募集する") for text in texts)
    assert any("meanings/examples：新增 招募；徵集" in text for text in texts)
    assert any(text.startswith("sources：新增 TRY! N3") for text in texts)

    rendered = render_preflight_text(report)
    assert "同 stable key，正式匯入時會更新／合併（1）" in rendered
    assert "[單字] 募集 <vocab:募集>" in rendered
    assert "· level：N4 → N3" in rendered
    assert "· aliases：新增 募集する" in rendered


def test_preflight_relation_only_change_is_described(monkeypatch, tmp_path: Path) -> None:
    with _connect_at(monkeypatch, tmp_path) as conn:
        apply_import(
            conn,
            prepare_import(
                conn,
                {
                    "items": [
                        {
                            "key": "grammar:Vている",
                            "type": "grammar",
                            "display": "Vている",
                            "meanings": ["正在～"],
                        },
                        {
                            "key": "grammar:Vてある",
                            "type": "grammar",
                            "display": "Vてある",
                            "meanings": ["處於被做好的狀態"],
                        },
                    ]
                },
            ),
        )
        plan = prepare_import(
            conn,
            {
                "items": [
                    {
                        "key": "grammar:Vている",
                        "type": "grammar",
                        "display": "Vている",
                        "meanings": ["正在～"],
                        "related_grammar": [
                            {
                                "key": "grammar:Vてある",
                                "relation": "對比",
                                "note": "動作進行 vs 結果狀態",
                            }
                        ],
                    }
                ]
            },
        )
        report = build_preflight_report(conn, plan)

    update = report["updates"][0]
    assert update["key"] == "grammar:Vている"
    assert any(
        change["field"] == "related_grammar"
        and "grammar:Vてある" in change["text"]
        for change in update["changes"]
    )


def test_grammar_search_derives_romaji_only_from_reliable_kana(
    monkeypatch, tmp_path: Path
) -> None:
    with _connect_at(monkeypatch, tmp_path) as conn:
        apply_import(
            conn,
            prepare_import(
                conn,
                {
                    "items": [
                        {
                            "key": "grammar:いる/います",
                            "type": "grammar",
                            "display": "いる／います",
                            "meanings": ["存在"],
                        },
                        {
                            "key": "grammar:Vている",
                            "type": "grammar",
                            "display": "Vている",
                            "meanings": ["正在～"],
                        },
                        {
                            "key": "grammar:場合",
                            "type": "grammar",
                            "display": "～場合",
                            "meanings": ["在～的情況下"],
                        },
                        {
                            "key": "grammar:場合かな",
                            "type": "grammar",
                            "display": "～場合",
                            "aliases": ["～ばあい"],
                            "meanings": ["在～的情況下（有假名 alias）"],
                        },
                        {
                            "key": "grammar:Aく/Nに+なる",
                            "type": "grammar",
                            "display": "Aく／Nに＋なる",
                            "meanings": ["變得～"],
                        },
                    ]
                },
            ),
        )

        assert search_entries(conn, "imasu")[0]["key"] == "grammar:いる/います"
        assert search_entries(conn, "teiru")[0]["key"] == "grammar:Vている"
        browse = browse_records(conn, types=("grammar",), query="imasu")
        assert [record["key"] for record in browse] == ["grammar:いる/います"]

        baai_keys = {entry["key"] for entry in search_entries(conn, "baai")}
        assert "grammar:場合かな" in baai_keys
        assert "grammar:場合" not in baai_keys
        assert search_entries(conn, "ninaru")[0]["key"] == "grammar:Aく/Nに+なる"


def test_quiz_count_can_be_typed_directly() -> None:
    controller = QuizTuiController(_CountOnlyService(), default_count=10)
    controller.state.setup_focus = 1

    controller.handle_key("5")
    controller.handle_key("0")
    assert controller.state.count_input == "50"
    assert controller.state.requested_count == 10
    assert "題數：50（輸入中）" in "\n".join(controller.render(80, 24).lines)

    controller.handle_key("ENTER")
    assert controller.state.requested_count == 50
    assert controller.state.count_input == ""
    assert controller.state.setup_focus == 2


def test_quiz_count_input_validates_bounds_and_backspace() -> None:
    controller = QuizTuiController(_CountOnlyService(), default_count=10)
    controller.state.setup_focus = 1

    controller.handle_key("0")
    controller.handle_key("ENTER")
    assert controller.state.setup_focus == 1
    assert controller.state.requested_count == 10
    assert controller.state.count_input_error

    controller.handle_key("BACKSPACE")
    controller.handle_key("1")
    controller.handle_key("0")
    controller.handle_key("0")
    assert controller.state.count_input == str(MAX_QUESTION_COUNT)
    controller.handle_key("9")
    assert controller.state.count_input == str(MAX_QUESTION_COUNT)
    assert "上限" in controller.state.count_input_error


def test_windows_client_renders_core_owned_update_details() -> None:
    module = (
        Path(__file__).resolve().parents[1]
        / "clients"
        / "windows"
        / "JpnoteFileImport"
        / "JpnoteFileImport.psm1"
    ).read_text(encoding="utf-8-sig")
    assert "$Response.preflight.updates" in module
    assert "$Change.text" in module
    assert "將更新／合併的既有項目" in module


def test_preflight_does_not_report_blank_optional_fields_as_replacements(
    monkeypatch, tmp_path: Path
) -> None:
    with _connect_at(monkeypatch, tmp_path) as conn:
        apply_import(
            conn,
            prepare_import(
                conn,
                {
                    "items": [
                        {
                            "key": "vocab:確認",
                            "type": "vocabulary",
                            "display": "確認",
                            "reading": "かくにん",
                            "level": "N4",
                            "meanings": ["確認"],
                        }
                    ]
                },
            ),
        )
        plan = prepare_import(
            conn,
            {
                "source": "追加來源",
                "items": [
                    {
                        "key": "vocab:確認",
                        "type": "vocabulary",
                        "display": "確認",
                        "reading": "",
                        "level": "",
                        "meanings": ["確認"],
                    }
                ],
            },
        )
        report = build_preflight_report(conn, plan)

    assert report["summary"]["update_items"] == 1
    texts = [change["text"] for change in report["updates"][0]["changes"]]
    assert texts == ["sources：新增 追加來源"]
    assert all("display" not in text for text in texts)
    assert all("reading" not in text for text in texts)
    assert all("level" not in text for text in texts)


def test_protocol_check_carries_core_update_details(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(data_dir))
    with connect() as conn:
        apply_import(
            conn,
            prepare_import(
                conn,
                {
                    "items": [
                        {
                            "key": "vocab:募集",
                            "type": "vocabulary",
                            "display": "募集",
                            "reading": "ぼしゅう",
                            "level": "N4",
                            "meanings": ["募集"],
                        }
                    ]
                },
            ),
        )

    payload = json.dumps(
        {
            "source": "Windows protocol detail test",
            "items": [
                {
                    "key": "vocab:募集",
                    "type": "vocabulary",
                    "display": "募集",
                    "reading": "ぼしゅう",
                    "level": "N3",
                    "meanings": ["募集"],
                }
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["JPNOTE_DATA_DIR"] = str(data_dir)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "jpnote_app",
            "import",
            "--stdin",
            "--check",
            "--protocol",
            "1",
        ],
        input=payload,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    envelope = json.loads(proc.stdout.decode("ascii"))
    updates = envelope["preflight"]["updates"]
    assert updates[0]["key"] == "vocab:募集"
    assert any(change["text"] == "level：N4 → N3" for change in updates[0]["changes"])


def test_quiz_count_escape_cancels_without_changing_committed_value() -> None:
    controller = QuizTuiController(_CountOnlyService(), default_count=10)
    controller.state.setup_focus = 1
    controller.handle_key("5")
    controller.handle_key("0")
    controller.handle_key("ESC")
    assert controller.state.count_input == ""
    assert controller.state.count_input_error == ""
    assert controller.state.requested_count == 10


def test_human_import_prints_update_details_before_apply(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JPNOTE_DATA_DIR", str(data_dir))
    with connect() as conn:
        apply_import(
            conn,
            prepare_import(
                conn,
                {
                    "items": [
                        {
                            "key": "vocab:募集",
                            "type": "vocabulary",
                            "display": "募集",
                            "reading": "ぼしゅう",
                            "level": "N4",
                            "meanings": ["募集"],
                        }
                    ]
                },
            ),
        )

    payload = json.dumps(
        {
            "source": "human import detail test",
            "items": [
                {
                    "key": "vocab:募集",
                    "type": "vocabulary",
                    "display": "募集",
                    "reading": "ぼしゅう",
                    "level": "N3",
                    "meanings": ["募集"],
                }
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["JPNOTE_DATA_DIR"] = str(data_dir)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "jpnote_app",
            "import",
            "--stdin",
            "--yes",
        ],
        input=payload,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    stdout = proc.stdout.decode("utf-8")
    assert "=== 正式匯入前完整預檢 ===" in stdout
    assert "[單字] 募集 <vocab:募集>" in stdout
    assert "· level：N4 → N3" in stdout
    assert stdout.index("· level：N4 → N3") < stdout.index("匯入完成：")
