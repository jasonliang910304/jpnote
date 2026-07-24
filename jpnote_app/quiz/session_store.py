"""Independent SQLite store for optional Quiz sessions and live history.

The Quiz database is deliberately separate from the core jpnote database.  It
has its own schema version, migration transaction and failure boundary.  Merely
importing or starting core jpnote never imports this module or opens quiz.db.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from .session_models import (
    AnswerSnapshot,
    GeneratedQuestionSnapshot,
    QUESTION_RESULTS,
    QuestionChoiceSnapshot,
    QuestionEventSnapshot,
    QuizSessionSnapshot,
    QuizSessionSummary,
    QuizValidationError,
    SESSION_STATES,
    TERMINAL_SESSION_STATES,
)

QUIZ_SCHEMA_VERSION = 1


class QuizStorageError(RuntimeError):
    """Base class for Quiz-owned persistence failures."""


class QuizStorageUnavailableError(QuizStorageError):
    """Quiz storage cannot be opened or migrated safely."""


class QuizSessionNotFoundError(QuizStorageError):
    """Requested stable Quiz session or question event ID does not exist."""


class QuizSessionStateError(QuizStorageError):
    """Requested operation is invalid for the current session state."""


def default_quiz_db_path() -> Path:
    explicit = os.environ.get("JPNOTE_QUIZ_DB")
    if explicit:
        return Path(explicit).expanduser()

    data_dir = os.environ.get("JPNOTE_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser() / "quiz.db"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local/share"
    return base / "jpnote" / "quiz.db"


def _timestamp_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _default_id_factory(kind: str) -> str:
    return f"quiz-{kind}:{uuid.uuid4().hex}"


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _answer_to_json(answer: AnswerSnapshot) -> str:
    return _json_dump({"answer_id": answer.answer_id, "text": answer.text})


def _answer_from_json(raw: str | None) -> AnswerSnapshot | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise QuizValidationError("answer snapshot 必須是 object")
        answer_id = data.get("answer_id", "")
        text = data.get("text", "")
        if not isinstance(answer_id, str) or not isinstance(text, str):
            raise QuizValidationError("answer snapshot 欄位必須是字串")
        return AnswerSnapshot(answer_id=answer_id, text=text)
    except (json.JSONDecodeError, QuizValidationError) as exc:
        raise QuizStorageUnavailableError(f"Quiz answer snapshot 格式錯誤：{exc}") from exc


def _choices_to_json(choices: Sequence[QuestionChoiceSnapshot]) -> str:
    return _json_dump(
        [{"choice_id": choice.choice_id, "text": choice.text} for choice in choices]
    )


def _choices_from_json(raw: str) -> tuple[QuestionChoiceSnapshot, ...]:
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise QuizValidationError("choices snapshot 必須是 array")
        result: list[QuestionChoiceSnapshot] = []
        for item in data:
            if not isinstance(item, dict):
                raise QuizValidationError("choice snapshot 必須是 object")
            choice_id = item.get("choice_id", "")
            text = item.get("text", "")
            if not isinstance(choice_id, str) or not isinstance(text, str):
                raise QuizValidationError("choice snapshot 欄位必須是字串")
            result.append(QuestionChoiceSnapshot(choice_id=choice_id, text=text))
        return tuple(result)
    except (json.JSONDecodeError, QuizValidationError) as exc:
        raise QuizStorageUnavailableError(f"Quiz choices snapshot 格式錯誤：{exc}") from exc


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _secure_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


class QuizSessionStore:
    """Transactional store for Quiz sessions and immutable question history."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], str] = _timestamp_now,
        id_factory: Callable[[str], str] = _default_id_factory,
    ) -> None:
        self.path = Path(path) if path is not None else default_quiz_db_path()
        self._clock = clock
        self._id_factory = id_factory
        try:
            _secure_directory(self.path.parent)
            self._migrate()
            _secure_file(self.path)
        except QuizStorageUnavailableError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise QuizStorageUnavailableError(f"Quiz 儲存空間不可用：{exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _migrate(self) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current > QUIZ_SCHEMA_VERSION:
                raise QuizStorageUnavailableError(
                    "Quiz database schema 比目前程式新："
                    f"{current} > {QUIZ_SCHEMA_VERSION}"
                )
            if current < 1:
                self._apply_schema_v1(conn)
                conn.execute(f"PRAGMA user_version={QUIZ_SCHEMA_VERSION}")
            conn.commit()
        except Exception as exc:
            if conn is not None:
                conn.rollback()
            if isinstance(exc, QuizStorageUnavailableError):
                raise
            raise QuizStorageUnavailableError(f"Quiz schema migration 失敗：{exc}") from exc
        finally:
            if conn is not None:
                conn.close()

    def _apply_schema_v1(self, conn: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE quiz_sessions (
                session_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                requested_count INTEGER NOT NULL CHECK(requested_count >= 0),
                question_count INTEGER NOT NULL CHECK(question_count >= 0),
                state TEXT NOT NULL CHECK(
                    state IN ('active','paused','interrupted','completed','abandoned')
                ),
                answered_count INTEGER NOT NULL DEFAULT 0 CHECK(answered_count >= 0),
                correct_count INTEGER NOT NULL DEFAULT 0 CHECK(correct_count >= 0),
                incorrect_count INTEGER NOT NULL DEFAULT 0 CHECK(incorrect_count >= 0),
                skipped_count INTEGER NOT NULL DEFAULT 0 CHECK(skipped_count >= 0),
                details_pruned INTEGER NOT NULL DEFAULT 0 CHECK(details_pruned IN (0,1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT
            )
            """,
            """
            CREATE TABLE quiz_question_events (
                question_event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                position INTEGER NOT NULL CHECK(position >= 1),
                question_type TEXT NOT NULL,
                generator_version TEXT NOT NULL,
                source_kind TEXT NOT NULL CHECK(source_kind IN ('vocabulary','mistake')),
                source_key TEXT NOT NULL,
                prompt TEXT NOT NULL,
                choices_json TEXT NOT NULL,
                correct_answer_json TEXT NOT NULL,
                user_answer_json TEXT,
                result TEXT CHECK(result IN ('correct','incorrect','skipped')),
                answered_at TEXT,
                UNIQUE(session_id, position),
                FOREIGN KEY(session_id) REFERENCES quiz_sessions(session_id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX idx_quiz_sessions_updated
                ON quiz_sessions(updated_at DESC, session_id)
            """,
            """
            CREATE INDEX idx_quiz_question_session_position
                ON quiz_question_events(session_id, position)
            """,
            """
            CREATE INDEX idx_quiz_question_session_result
                ON quiz_question_events(session_id, result)
            """,
        )
        for statement in statements:
            conn.execute(statement)

    def create_session(
        self,
        *,
        mode: str,
        questions: Sequence[GeneratedQuestionSnapshot],
        requested_count: int | None = None,
        session_id: str | None = None,
    ) -> QuizSessionSnapshot:
        frozen_questions = tuple(questions)
        if not mode.strip():
            raise QuizValidationError("Quiz mode 不可為空")
        if not frozen_questions:
            raise QuizValidationError("Quiz session 至少需要一題")

        requested = len(frozen_questions) if requested_count is None else requested_count
        if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
            raise QuizValidationError("requested_count 必須是正整數")
        if requested < len(frozen_questions):
            raise QuizValidationError("requested_count 不可小於實際安全生成題數")

        identities = [question.identity_tuple() for question in frozen_questions]
        if len(identities) != len(set(identities)):
            raise QuizValidationError("同一 session 不可保存完全相同的 generated question")

        stable_session_id = session_id or self._id_factory("session")
        if not stable_session_id.strip():
            raise QuizValidationError("session_id 不可為空")
        event_ids = [self._id_factory("question") for _ in frozen_questions]
        if any(not event_id.strip() for event_id in event_ids):
            raise QuizValidationError("question_event_id 不可為空")
        if len(event_ids) != len(set(event_ids)):
            raise QuizValidationError("question_event_id 必須唯一")

        now = self._clock()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO quiz_sessions (
                    session_id, mode, requested_count, question_count, state,
                    created_at, updated_at, started_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    stable_session_id,
                    mode,
                    requested,
                    len(frozen_questions),
                    now,
                    now,
                    now,
                ),
            )
            for position, (question, event_id) in enumerate(
                zip(frozen_questions, event_ids, strict=True), start=1
            ):
                conn.execute(
                    """
                    INSERT INTO quiz_question_events (
                        question_event_id, session_id, position, question_type,
                        generator_version, source_kind, source_key, prompt,
                        choices_json, correct_answer_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        stable_session_id,
                        position,
                        question.question_type,
                        question.generator_version,
                        question.source_kind,
                        question.source_key,
                        question.prompt,
                        _choices_to_json(question.choices),
                        _answer_to_json(question.correct_answer),
                    ),
                )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise QuizValidationError(f"Quiz session identity 衝突：{exc}") from exc
        except sqlite3.Error as exc:
            conn.rollback()
            raise QuizStorageUnavailableError(f"無法建立 Quiz session：{exc}") from exc
        finally:
            conn.close()
        return self.get_session(stable_session_id)

    def get_session(self, session_id: str) -> QuizSessionSnapshot:
        conn = self._connect()
        try:
            session_row = conn.execute(
                "SELECT * FROM quiz_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if session_row is None:
                raise QuizSessionNotFoundError(f"找不到 Quiz session：{session_id}")
            question_rows = conn.execute(
                """
                SELECT * FROM quiz_question_events
                WHERE session_id=? ORDER BY position
                """,
                (session_id,),
            ).fetchall()
            return QuizSessionSnapshot(
                summary=self._summary_from_row(session_row),
                questions=tuple(self._question_from_row(row) for row in question_rows),
            )
        except sqlite3.Error as exc:
            raise QuizStorageUnavailableError(f"無法讀取 Quiz session：{exc}") from exc
        finally:
            conn.close()

    def list_recent_sessions(
        self, *, limit: int = 20, include_abandoned: bool = True
    ) -> tuple[QuizSessionSummary, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise QuizValidationError("limit 必須是正整數")
        where = "" if include_abandoned else "WHERE state <> 'abandoned'"
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM quiz_sessions
                {where}
                ORDER BY updated_at DESC, session_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return tuple(self._summary_from_row(row) for row in rows)
        except sqlite3.Error as exc:
            raise QuizStorageUnavailableError(f"無法讀取 Quiz history：{exc}") from exc
        finally:
            conn.close()

    def next_question(self, session_id: str) -> QuestionEventSnapshot | None:
        conn = self._connect()
        try:
            session_row = conn.execute(
                "SELECT state FROM quiz_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if session_row is None:
                raise QuizSessionNotFoundError(f"找不到 Quiz session：{session_id}")
            if session_row["state"] != "active":
                raise QuizSessionStateError(
                    f"session 必須是 active 才能取下一題，目前為 {session_row['state']}"
                )
            row = conn.execute(
                """
                SELECT * FROM quiz_question_events
                WHERE session_id=? AND result IS NULL
                ORDER BY position LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return None if row is None else self._question_from_row(row)
        except sqlite3.Error as exc:
            raise QuizStorageUnavailableError(f"無法讀取下一題：{exc}") from exc
        finally:
            conn.close()

    def submit_answer(
        self,
        session_id: str,
        question_event_id: str,
        *,
        user_answer: AnswerSnapshot,
        correct: bool,
    ) -> QuizSessionSnapshot:
        result = "correct" if correct else "incorrect"
        return self._record_result(
            session_id,
            question_event_id,
            result=result,
            user_answer=user_answer,
        )

    def skip_question(
        self, session_id: str, question_event_id: str
    ) -> QuizSessionSnapshot:
        return self._record_result(
            session_id,
            question_event_id,
            result="skipped",
            user_answer=None,
        )

    def _record_result(
        self,
        session_id: str,
        question_event_id: str,
        *,
        result: str,
        user_answer: AnswerSnapshot | None,
    ) -> QuizSessionSnapshot:
        if result not in QUESTION_RESULTS:
            raise QuizValidationError(f"不支援的 Quiz result：{result}")
        if result != "skipped" and user_answer is None:
            raise QuizValidationError("非 skip 作答必須保存 user_answer snapshot")
        if result == "skipped" and user_answer is not None:
            raise QuizValidationError("skip 不可保存虛構 user_answer")

        now = self._clock()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            session_row = conn.execute(
                "SELECT * FROM quiz_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if session_row is None:
                raise QuizSessionNotFoundError(f"找不到 Quiz session：{session_id}")
            if session_row["state"] != "active":
                raise QuizSessionStateError(
                    f"session 必須是 active 才能作答，目前為 {session_row['state']}"
                )

            next_row = conn.execute(
                """
                SELECT * FROM quiz_question_events
                WHERE session_id=? AND result IS NULL
                ORDER BY position LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if next_row is None:
                raise QuizSessionStateError("此 session 已沒有未作答題目")
            if next_row["question_event_id"] != question_event_id:
                raise QuizSessionStateError("只能提交目前下一題，避免跳題或重複作答")

            changed = conn.execute(
                """
                UPDATE quiz_question_events
                SET user_answer_json=?, result=?, answered_at=?
                WHERE question_event_id=? AND session_id=? AND result IS NULL
                """,
                (
                    None if user_answer is None else _answer_to_json(user_answer),
                    result,
                    now,
                    question_event_id,
                    session_id,
                ),
            ).rowcount
            if changed != 1:
                raise QuizSessionStateError("題目已作答或不存在")

            correct_inc = 1 if result == "correct" else 0
            incorrect_inc = 1 if result == "incorrect" else 0
            skipped_inc = 1 if result == "skipped" else 0
            answered_after = int(session_row["answered_count"]) + 1
            completes = answered_after == int(session_row["question_count"])
            next_state = "completed" if completes else "active"
            ended_at = now if completes else session_row["ended_at"]
            conn.execute(
                """
                UPDATE quiz_sessions
                SET state=?, answered_count=answered_count+1,
                    correct_count=correct_count+?,
                    incorrect_count=incorrect_count+?,
                    skipped_count=skipped_count+?,
                    updated_at=?, ended_at=?
                WHERE session_id=?
                """,
                (
                    next_state,
                    correct_inc,
                    incorrect_inc,
                    skipped_inc,
                    now,
                    ended_at,
                    session_id,
                ),
            )
            conn.commit()
        except (QuizSessionNotFoundError, QuizSessionStateError):
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise QuizStorageUnavailableError(f"無法保存 Quiz 作答：{exc}") from exc
        finally:
            conn.close()
        return self.get_session(session_id)

    def pause_session(self, session_id: str) -> QuizSessionSnapshot:
        return self._transition(session_id, allowed={"active"}, target="paused")

    def mark_interrupted(self, session_id: str) -> QuizSessionSnapshot:
        return self._transition(session_id, allowed={"active"}, target="interrupted")

    def resume_session(self, session_id: str) -> QuizSessionSnapshot:
        return self._transition(
            session_id, allowed={"paused", "interrupted"}, target="active"
        )

    def abandon_session(self, session_id: str) -> QuizSessionSnapshot:
        return self._transition(
            session_id,
            allowed={"active", "paused", "interrupted"},
            target="abandoned",
            terminal=True,
        )

    def _transition(
        self,
        session_id: str,
        *,
        allowed: set[str],
        target: str,
        terminal: bool = False,
    ) -> QuizSessionSnapshot:
        if target not in SESSION_STATES:
            raise QuizValidationError(f"不支援的 session state：{target}")
        now = self._clock()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state FROM quiz_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None:
                raise QuizSessionNotFoundError(f"找不到 Quiz session：{session_id}")
            current = str(row["state"])
            if current not in allowed:
                if current in TERMINAL_SESSION_STATES:
                    raise QuizSessionStateError(
                        f"terminal session {current} 不可轉為 {target}"
                    )
                raise QuizSessionStateError(f"session {current} 不可轉為 {target}")
            conn.execute(
                """
                UPDATE quiz_sessions SET state=?, updated_at=?, ended_at=?
                WHERE session_id=?
                """,
                (target, now, now if terminal else None, session_id),
            )
            conn.commit()
        except (QuizSessionNotFoundError, QuizSessionStateError):
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise QuizStorageUnavailableError(f"無法更新 Quiz session：{exc}") from exc
        finally:
            conn.close()
        return self.get_session(session_id)

    @staticmethod
    def _summary_from_row(row: sqlite3.Row) -> QuizSessionSummary:
        return QuizSessionSummary(
            session_id=str(row["session_id"]),
            mode=str(row["mode"]),
            requested_count=int(row["requested_count"]),
            question_count=int(row["question_count"]),
            state=str(row["state"]),
            answered_count=int(row["answered_count"]),
            correct_count=int(row["correct_count"]),
            incorrect_count=int(row["incorrect_count"]),
            skipped_count=int(row["skipped_count"]),
            details_pruned=bool(row["details_pruned"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            started_at=str(row["started_at"]),
            ended_at=None if row["ended_at"] is None else str(row["ended_at"]),
        )

    @staticmethod
    def _question_from_row(row: sqlite3.Row) -> QuestionEventSnapshot:
        try:
            correct_answer = _answer_from_json(str(row["correct_answer_json"]))
            if correct_answer is None:
                raise QuizValidationError("correct answer snapshot 不可為空")
            question = GeneratedQuestionSnapshot(
                question_type=str(row["question_type"]),
                generator_version=str(row["generator_version"]),
                source_kind=str(row["source_kind"]),
                source_key=str(row["source_key"]),
                prompt=str(row["prompt"]),
                choices=_choices_from_json(str(row["choices_json"])),
                correct_answer=correct_answer,
            )
            result = None if row["result"] is None else str(row["result"])
            if result is not None and result not in QUESTION_RESULTS:
                raise QuizValidationError(f"不支援的 result：{result}")
            return QuestionEventSnapshot(
                question_event_id=str(row["question_event_id"]),
                session_id=str(row["session_id"]),
                position=int(row["position"]),
                question=question,
                user_answer=_answer_from_json(row["user_answer_json"]),
                result=result,
                answered_at=(
                    None if row["answered_at"] is None else str(row["answered_at"])
                ),
            )
        except QuizValidationError as exc:
            raise QuizStorageUnavailableError(
                f"Quiz question snapshot 格式錯誤：{exc}"
            ) from exc
