from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MockMemoryEntry:
    user_id: str
    correlation_id: str
    summary: str
    session_id: str = "default"


class MockFamilyMemory:
    """Day 1 boundary: durable synthetic summaries, strictly scoped by user."""

    mock_only = True

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._connection:
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS mock_memory (
                    user_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    PRIMARY KEY (user_id, correlation_id)
                )"""
            )
            columns = {
                row[1]
                for row in self._connection.execute("PRAGMA table_info(mock_memory)")
            }
            if "session_id" not in columns:
                self._connection.execute(
                    """ALTER TABLE mock_memory ADD COLUMN session_id TEXT
                    NOT NULL DEFAULT 'default'"""
                )

    def remember(self, entry: MockMemoryEntry) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR REPLACE INTO mock_memory
                (user_id, correlation_id, summary, session_id) VALUES (?, ?, ?, ?)""",
                (
                    entry.user_id,
                    entry.correlation_id,
                    entry.summary,
                    entry.session_id,
                ),
            )

    def recent(
        self, user_id: str, *, session_id: str | None = None, limit: int = 10
    ) -> tuple[MockMemoryEntry, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit fora do intervalo")
        with self._lock:
            if session_id is None:
                rows = self._connection.execute(
                    """SELECT user_id, correlation_id, summary, session_id
                    FROM mock_memory WHERE user_id = ?
                    ORDER BY rowid DESC LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """SELECT user_id, correlation_id, summary, session_id
                    FROM mock_memory WHERE user_id = ? AND session_id = ?
                    ORDER BY rowid DESC LIMIT ?""",
                    (user_id, session_id, limit),
                ).fetchall()
        return tuple(MockMemoryEntry(*tuple(row)) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class FamilySessionMemory(MockFamilyMemory):
    """Day 4 metadata memory with mandatory user/session namespace keys."""

    mock_only = False
