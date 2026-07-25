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
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .session_models import (
    AnswerSnapshot,
    GeneratedQuestionSnapshot,
    QUESTION_RESULTS,
    QuestionChoiceSnapshot,
    QuestionEventSnapshot,
    QuizPruneResult,
    QuizQuestionTypeSummary,
    QuizSessionSnapshot,
    QuizSessionSummary,
    QuizValidationError,
    SESSION_STATES,
    TERMINAL_SESSION_STATES,
)

QUIZ_SCHEMA_VERSION = 2
QUIZ_HISTORY_EXPORT_VERSION = 2
DEFAULT_DETAIL_CAP_BYTES = 100 * 1024 * 1024

_DETAIL_SIZE_EXPRESSION = """
    LENGTH(CAST(q.question_event_id AS BLOB))
    + LENGTH(CAST(q.session_id AS BLOB))
    + LENGTH(CAST(q.position AS BLOB))
    + LENGTH(CAST(q.question_type AS BLOB))
    + LENGTH(CAST(q.generator_version AS BLOB))
    + LENGTH(CAST(q.source_kind AS BLOB))
    + LENGTH(CAST(q.source_key AS BLOB))
    + LENGTH(CAST(q.prompt AS BLOB))
    + LENGTH(CAST(q.choices_json AS BLOB))
    + LENGTH(CAST(q.correct_answer_json AS BLOB))
    + LENGTH(CAST(COALESCE(q.user_answer_json, '') AS BLOB))
    + LENGTH(CAST(COALESCE(q.result, '') AS BLOB))
    + LENGTH(CAST(COALESCE(q.answered_at, '') AS BLOB))
"""


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


def _question_type_summaries_to_json(
    summaries: Sequence[QuizQuestionTypeSummary],
) -> str:
    return _json_dump(
        [
            {
                "question_type": summary.question_type,
                "answered_count": summary.answered_count,
                "correct_count": summary.correct_count,
                "incorrect_count": summary.incorrect_count,
                "skipped_count": summary.skipped_count,
            }
            for summary in summaries
        ]
    )


def _question_type_summaries_from_json(
    raw: str | None,
) -> tuple[QuizQuestionTypeSummary, ...]:
    if raw is None:
        return ()
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise QuizValidationError("question type summary 必須是 array")
        result: list[QuizQuestionTypeSummary] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                raise QuizValidationError("question type summary item 必須是 object")
            question_type = item.get("question_type", "")
            values = (
                item.get("answered_count"),
                item.get("correct_count"),
                item.get("incorrect_count"),
                item.get("skipped_count"),
            )
            if not isinstance(question_type, str):
                raise QuizValidationError("question_type 必須是字串")
            if question_type in seen:
                raise QuizValidationError("question type summary 不可重複")
            seen.add(question_type)
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in values
            ):
                raise QuizValidationError("question type summary 計數必須是整數")
            result.append(
                QuizQuestionTypeSummary(
                    question_type=question_type,
                    answered_count=values[0],
                    correct_count=values[1],
                    incorrect_count=values[2],
                    skipped_count=values[3],
                )
            )
        return tuple(sorted(result, key=lambda summary: summary.question_type))
    except (json.JSONDecodeError, QuizValidationError) as exc:
        raise QuizStorageUnavailableError(
            f"Quiz question type summary 格式錯誤：{exc}"
        ) from exc


def _increment_question_type_summary(
    summaries: Sequence[QuizQuestionTypeSummary],
    *,
    question_type: str,
    result: str,
) -> tuple[QuizQuestionTypeSummary, ...]:
    counters = {
        summary.question_type: {
            "answered": summary.answered_count,
            "correct": summary.correct_count,
            "incorrect": summary.incorrect_count,
            "skipped": summary.skipped_count,
        }
        for summary in summaries
    }
    bucket = counters.setdefault(
        question_type,
        {"answered": 0, "correct": 0, "incorrect": 0, "skipped": 0},
    )
    bucket["answered"] += 1
    bucket[result] += 1
    return tuple(
        QuizQuestionTypeSummary(
            question_type=kind,
            answered_count=values["answered"],
            correct_count=values["correct"],
            incorrect_count=values["incorrect"],
            skipped_count=values["skipped"],
        )
        for kind, values in sorted(counters.items())
    )


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
                current = 1
            if current < 2:
                self._apply_schema_v2(conn)
                current = 2
            conn.execute(f"PRAGMA user_version={current}")
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

    def _apply_schema_v2(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            ALTER TABLE quiz_sessions
            ADD COLUMN question_type_summary_json TEXT NOT NULL DEFAULT '[]'
            """
        )
        sessions = conn.execute(
            """
            SELECT session_id FROM quiz_sessions
            WHERE details_pruned=0
            ORDER BY session_id
            """
        ).fetchall()
        for session in sessions:
            rows = conn.execute(
                """
                SELECT question_type, result, COUNT(*) AS count
                FROM quiz_question_events
                WHERE session_id=? AND result IS NOT NULL
                GROUP BY question_type, result
                ORDER BY question_type, result
                """,
                (session["session_id"],),
            ).fetchall()
            counters: dict[str, dict[str, int]] = {}
            for row in rows:
                question_type = str(row["question_type"])
                result = str(row["result"])
                if result not in QUESTION_RESULTS:
                    raise QuizValidationError(
                        f"migration 遇到不支援的 Quiz result：{result}"
                    )
                bucket = counters.setdefault(
                    question_type,
                    {"answered": 0, "correct": 0, "incorrect": 0, "skipped": 0},
                )
                count = int(row["count"])
                bucket["answered"] += count
                bucket[result] += count
            summaries = tuple(
                QuizQuestionTypeSummary(
                    question_type=question_type,
                    answered_count=values["answered"],
                    correct_count=values["correct"],
                    incorrect_count=values["incorrect"],
                    skipped_count=values["skipped"],
                )
                for question_type, values in sorted(counters.items())
            )
            conn.execute(
                """
                UPDATE quiz_sessions SET question_type_summary_json=?
                WHERE session_id=?
                """,
                (
                    _question_type_summaries_to_json(summaries),
                    session["session_id"],
                ),
            )

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
            question_rows = [
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
                )
                for position, (question, event_id) in enumerate(
                    zip(frozen_questions, event_ids, strict=True), start=1
                )
            ]
            conn.executemany(
                """
                INSERT INTO quiz_question_events (
                    question_event_id, session_id, position, question_type,
                    generator_version, source_kind, source_key, prompt,
                    choices_json, correct_answer_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                question_rows,
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
        self,
        *,
        limit: int = 20,
        include_abandoned: bool = True,
        states: Sequence[str] | None = None,
    ) -> tuple[QuizSessionSummary, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise QuizValidationError("limit 必須是正整數")

        clauses: list[str] = []
        parameters: list[Any] = []
        if states is not None:
            normalized_states = tuple(dict.fromkeys(str(state) for state in states))
            invalid_states = set(normalized_states) - SESSION_STATES
            if invalid_states:
                raise QuizValidationError(
                    f"不支援的 session state：{sorted(invalid_states)[0]}"
                )
            if not normalized_states:
                return ()
            placeholders = ", ".join("?" for _ in normalized_states)
            clauses.append(f"state IN ({placeholders})")
            parameters.extend(normalized_states)
        if not include_abandoned:
            clauses.append("state <> 'abandoned'")

        where = "" if not clauses else "WHERE " + " AND ".join(clauses)
        parameters.append(limit)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM quiz_sessions
                {where}
                ORDER BY updated_at DESC, session_id DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
            return tuple(self._summary_from_row(row) for row in rows)
        except sqlite3.Error as exc:
            raise QuizStorageUnavailableError(f"無法讀取 Quiz history：{exc}") from exc
        finally:
            conn.close()

    def detail_storage_bytes(self) -> int:
        """Return the stored byte size of immutable question-event details."""

        conn = self._connect()
        try:
            return self._detail_bytes(conn)
        except sqlite3.Error as exc:
            raise QuizStorageUnavailableError(
                f"無法計算 Quiz history detail 大小：{exc}"
            ) from exc
        finally:
            conn.close()

    def prune_details(
        self, *, cap_bytes: int = DEFAULT_DETAIL_CAP_BYTES
    ) -> QuizPruneResult:
        """Prune oldest terminal-session details while retaining summaries.

        Active, paused and interrupted sessions remain fully resumable and are
        never selected.  If their protected details alone exceed the cap, the
        result reports ``cap_satisfied=False`` rather than damaging a session.
        """

        if (
            isinstance(cap_bytes, bool)
            or not isinstance(cap_bytes, int)
            or cap_bytes < 0
        ):
            raise QuizValidationError("cap_bytes 必須是非負整數")

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            before = self._detail_bytes(conn)
            protected = self._detail_bytes(
                conn,
                where="s.state NOT IN ('completed','abandoned')",
            )
            current = before
            pruned: list[str] = []

            if current > cap_bytes:
                rows = conn.execute(
                    f"""
                    SELECT s.session_id,
                           COALESCE(SUM({_DETAIL_SIZE_EXPRESSION}), 0) AS detail_bytes
                    FROM quiz_sessions AS s
                    JOIN quiz_question_events AS q
                      ON q.session_id = s.session_id
                    WHERE s.state IN ('completed','abandoned')
                      AND s.details_pruned = 0
                    GROUP BY s.session_id
                    ORDER BY COALESCE(s.ended_at, s.updated_at) ASC,
                             s.started_at ASC,
                             s.session_id ASC
                    """
                ).fetchall()
                for row in rows:
                    if current <= cap_bytes:
                        break
                    session_id = str(row["session_id"])
                    detail_bytes = int(row["detail_bytes"])
                    conn.execute(
                        "DELETE FROM quiz_question_events WHERE session_id=?",
                        (session_id,),
                    )
                    conn.execute(
                        """
                        UPDATE quiz_sessions SET details_pruned=1
                        WHERE session_id=? AND state IN ('completed','abandoned')
                        """,
                        (session_id,),
                    )
                    current = max(0, current - detail_bytes)
                    pruned.append(session_id)

            after = self._detail_bytes(conn)
            conn.commit()
            return QuizPruneResult(
                cap_bytes=cap_bytes,
                detail_bytes_before=before,
                detail_bytes_after=after,
                protected_detail_bytes=protected,
                pruned_session_ids=tuple(pruned),
            )
        except sqlite3.Error as exc:
            conn.rollback()
            raise QuizStorageUnavailableError(
                f"無法清理 Quiz history details：{exc}"
            ) from exc
        finally:
            conn.close()

    def export_history(
        self,
        *,
        session_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_abandoned: bool = True,
    ) -> dict[str, Any]:
        """Return a stable JSON-ready history export.

        Pruned details are represented explicitly as ``status='pruned'`` and
        never reconstructed from mutable core data.
        """

        if session_id is not None and (
            start_date is not None or end_date is not None
        ):
            raise QuizValidationError("單一 session export 不可同時使用日期篩選")
        start = self._validate_export_date(start_date, name="start_date")
        end = self._validate_export_date(end_date, name="end_date")
        if start is not None and end is not None and start > end:
            raise QuizValidationError("start_date 不可晚於 end_date")

        clauses: list[str] = []
        params: list[object] = []
        if session_id is not None:
            if not session_id.strip():
                raise QuizValidationError("session_id 不可為空")
            clauses.append("session_id=?")
            params.append(session_id)
        else:
            if start is not None:
                clauses.append("substr(started_at, 1, 10) >= ?")
                params.append(start.isoformat())
            if end is not None:
                clauses.append("substr(started_at, 1, 10) <= ?")
                params.append(end.isoformat())
            if not include_abandoned:
                clauses.append("state <> 'abandoned'")
        where = "" if not clauses else "WHERE " + " AND ".join(clauses)

        conn = self._connect()
        try:
            session_rows = conn.execute(
                f"""
                SELECT * FROM quiz_sessions
                {where}
                ORDER BY started_at ASC, session_id ASC
                """,
                tuple(params),
            ).fetchall()
            if session_id is not None and not session_rows:
                raise QuizSessionNotFoundError(f"找不到 Quiz session：{session_id}")

            sessions: list[dict[str, Any]] = []
            for row in session_rows:
                summary = self._summary_from_row(row)
                question_rows = conn.execute(
                    """
                    SELECT * FROM quiz_question_events
                    WHERE session_id=? ORDER BY position
                    """,
                    (summary.session_id,),
                ).fetchall()
                questions = tuple(
                    self._question_from_row(item) for item in question_rows
                )
                sessions.append(self._session_to_export(summary, questions))

            return {
                "format": "jpnote-quiz-history",
                "version": QUIZ_HISTORY_EXPORT_VERSION,
                "exported_at": self._clock(),
                "filters": {
                    "session_id": session_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "include_abandoned": include_abandoned,
                },
                "sessions": sessions,
            }
        except QuizSessionNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise QuizStorageUnavailableError(f"無法匯出 Quiz history：{exc}") from exc
        finally:
            conn.close()

    def write_history_json(
        self,
        path: str | Path,
        *,
        session_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_abandoned: bool = True,
    ) -> Path:
        """Atomically write a private-permission JSON history export."""

        destination = Path(path).expanduser()
        payload = self.export_history(
            session_id=session_id,
            start_date=start_date,
            end_date=end_date,
            include_abandoned=include_abandoned,
        )
        temporary = destination.with_name(
            f".{destination.name}.pending-{uuid.uuid4().hex}"
        )
        try:
            if destination.parent.exists():
                if not destination.parent.is_dir():
                    raise OSError("export parent 不是目錄")
            else:
                _secure_directory(destination.parent)
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            _secure_file(temporary)
            os.replace(temporary, destination)
            _secure_file(destination)
            return destination
        except (OSError, TypeError, ValueError) as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise QuizStorageUnavailableError(
                f"無法寫入 Quiz history JSON：{exc}"
            ) from exc

    def delete_session(
        self, session_id: str, *, include_resumable: bool = False
    ) -> QuizSessionSummary:
        """Delete one history record, protecting resumable sessions by default."""

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM quiz_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None:
                raise QuizSessionNotFoundError(f"找不到 Quiz session：{session_id}")
            summary = self._summary_from_row(row)
            if (
                summary.state not in TERMINAL_SESSION_STATES
                and not include_resumable
            ):
                raise QuizSessionStateError(
                    f"session {summary.state} 仍可恢復；刪除時必須明確允許 resumable"
                )
            conn.execute(
                "DELETE FROM quiz_sessions WHERE session_id=?",
                (session_id,),
            )
            conn.commit()
            return summary
        except (QuizSessionNotFoundError, QuizSessionStateError):
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise QuizStorageUnavailableError(f"無法刪除 Quiz history：{exc}") from exc
        finally:
            conn.close()

    def delete_all_history(
        self, *, include_resumable: bool = False
    ) -> tuple[str, ...]:
        """Delete all terminal history, or everything when explicitly requested."""

        where = (
            ""
            if include_resumable
            else "WHERE state IN ('completed','abandoned')"
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"""
                SELECT session_id FROM quiz_sessions
                {where}
                ORDER BY started_at, session_id
                """
            ).fetchall()
            session_ids = tuple(str(row["session_id"]) for row in rows)
            if session_ids:
                placeholders = ",".join("?" for _ in session_ids)
                conn.execute(
                    f"DELETE FROM quiz_sessions WHERE session_id IN ({placeholders})",
                    session_ids,
                )
            conn.commit()
            return session_ids
        except sqlite3.Error as exc:
            conn.rollback()
            raise QuizStorageUnavailableError(f"無法刪除 Quiz history：{exc}") from exc
        finally:
            conn.close()

    @staticmethod
    def _validate_export_date(raw: str | None, *, name: str) -> date | None:
        if raw is None:
            return None
        try:
            return date.fromisoformat(raw)
        except (TypeError, ValueError) as exc:
            raise QuizValidationError(f"{name} 必須是 YYYY-MM-DD") from exc

    @staticmethod
    def _detail_bytes(
        conn: sqlite3.Connection, *, where: str | None = None
    ) -> int:
        join = (
            ""
            if where is None
            else "JOIN quiz_sessions AS s ON s.session_id=q.session_id"
        )
        clause = "" if where is None else f"WHERE {where}"
        row = conn.execute(
            f"""
            SELECT COALESCE(SUM({_DETAIL_SIZE_EXPRESSION}), 0) AS detail_bytes
            FROM quiz_question_events AS q
            {join}
            {clause}
            """
        ).fetchone()
        return int(row["detail_bytes"])

    @staticmethod
    def _summary_to_export(summary: QuizSessionSummary) -> dict[str, Any]:
        return {
            "session_id": summary.session_id,
            "mode": summary.mode,
            "requested_count": summary.requested_count,
            "question_count": summary.question_count,
            "state": summary.state,
            "answered_count": summary.answered_count,
            "correct_count": summary.correct_count,
            "incorrect_count": summary.incorrect_count,
            "skipped_count": summary.skipped_count,
            "effective_incorrect_count": summary.effective_incorrect_count,
            "accuracy": summary.accuracy,
            "question_type_summaries": [
                {
                    "question_type": item.question_type,
                    "answered_count": item.answered_count,
                    "correct_count": item.correct_count,
                    "incorrect_count": item.incorrect_count,
                    "skipped_count": item.skipped_count,
                    "effective_incorrect_count": item.effective_incorrect_count,
                    "accuracy": item.accuracy,
                }
                for item in summary.question_type_summaries
            ],
            "details_pruned": summary.details_pruned,
            "created_at": summary.created_at,
            "updated_at": summary.updated_at,
            "started_at": summary.started_at,
            "ended_at": summary.ended_at,
        }

    @staticmethod
    def _question_to_export(question: QuestionEventSnapshot) -> dict[str, Any]:
        return {
            "question_event_id": question.question_event_id,
            "session_id": question.session_id,
            "position": question.position,
            "question": {
                "question_type": question.question.question_type,
                "generator_version": question.question.generator_version,
                "source_kind": question.question.source_kind,
                "source_key": question.question.source_key,
                "prompt": question.question.prompt,
                "choices": [
                    {"choice_id": choice.choice_id, "text": choice.text}
                    for choice in question.question.choices
                ],
                "correct_answer": {
                    "answer_id": question.question.correct_answer.answer_id,
                    "text": question.question.correct_answer.text,
                },
            },
            "user_answer": (
                None
                if question.user_answer is None
                else {
                    "answer_id": question.user_answer.answer_id,
                    "text": question.user_answer.text,
                }
            ),
            "result": question.result,
            "answered_at": question.answered_at,
        }

    @classmethod
    def _session_to_export(
        cls,
        summary: QuizSessionSummary,
        questions: Sequence[QuestionEventSnapshot],
    ) -> dict[str, Any]:
        if summary.details_pruned and questions:
            raise QuizStorageUnavailableError(
                "Quiz history 標記為 pruned，但仍存在 question details"
            )
        if not summary.details_pruned and len(questions) != summary.question_count:
            raise QuizStorageUnavailableError(
                "Quiz history details 不完整，拒絕產生可能誤導的 export"
            )
        detail_status = "pruned" if summary.details_pruned else "available"
        return {
            "summary": cls._summary_to_export(summary),
            "details": {
                "status": detail_status,
                "questions": (
                    []
                    if summary.details_pruned
                    else [cls._question_to_export(question) for question in questions]
                ),
            },
        }

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
            question_type_summaries = _increment_question_type_summary(
                _question_type_summaries_from_json(
                    session_row["question_type_summary_json"]
                ),
                question_type=str(next_row["question_type"]),
                result=result,
            )
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
                    question_type_summary_json=?,
                    updated_at=?, ended_at=?
                WHERE session_id=?
                """,
                (
                    next_state,
                    correct_inc,
                    incorrect_inc,
                    skipped_inc,
                    _question_type_summaries_to_json(question_type_summaries),
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
        try:
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
                ended_at=(
                    None if row["ended_at"] is None else str(row["ended_at"])
                ),
                question_type_summaries=_question_type_summaries_from_json(
                    row["question_type_summary_json"]
                ),
            )
        except QuizStorageUnavailableError:
            raise
        except (QuizValidationError, TypeError, ValueError) as exc:
            raise QuizStorageUnavailableError(
                f"Quiz session summary 格式錯誤：{exc}"
            ) from exc

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
