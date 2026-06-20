"""SQLite-backed anonymous session metadata for M5."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

import aiosqlite


DEFAULT_TITLE = "新的行程"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def title_from_message(message: str) -> str:
    """Create a compact title from the first user message."""
    compact = " ".join(message.strip().split())
    if not compact:
        return DEFAULT_TITLE
    return compact[:18]


class SessionStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def setup(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS session_meta (
                  thread_id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  deleted_at TEXT
                )
                """
            )
            await db.commit()

    async def create_session(self, title: str = DEFAULT_TITLE) -> dict:
        thread_id = uuid.uuid4().hex
        now = _now_iso()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO session_meta (thread_id, title, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (thread_id, title, now, now),
            )
            await db.commit()
        return {
            "thread_id": thread_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }

    async def list_sessions(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT thread_id, title, created_at, updated_at
                FROM session_meta
                WHERE deleted_at IS NULL
                ORDER BY updated_at DESC
                """
            )
        return [dict(row) for row in rows]

    async def get_session(self, thread_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT thread_id, title, created_at, updated_at
                FROM session_meta
                WHERE thread_id = ? AND deleted_at IS NULL
                """,
                (thread_id,),
            )
        return dict(rows[0]) if rows else None

    async def touch_session(self, thread_id: str, title: str | None = None) -> dict | None:
        now = _now_iso()
        async with aiosqlite.connect(self.db_path) as db:
            if title:
                await db.execute(
                    """
                    UPDATE session_meta
                    SET title = ?, updated_at = ?
                    WHERE thread_id = ? AND deleted_at IS NULL
                    """,
                    (title, now, thread_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE session_meta
                    SET updated_at = ?
                    WHERE thread_id = ? AND deleted_at IS NULL
                    """,
                    (now, thread_id),
                )
            await db.commit()
        return await self.get_session(thread_id)

    async def delete_session(self, thread_id: str) -> bool:
        now = _now_iso()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE session_meta
                SET deleted_at = ?
                WHERE thread_id = ? AND deleted_at IS NULL
                """,
                (now, thread_id),
            )
            await db.commit()
            return cursor.rowcount > 0
