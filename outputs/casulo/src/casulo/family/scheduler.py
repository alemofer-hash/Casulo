from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    AuthContext,
    ChatRequest,
    EventKind,
    FamilyAuthorizationError,
    FamilyBackpressureError,
    JobEvent,
    JobStatus,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    correlation_id: str
    auth: AuthContext
    request: ChatRequest
    status: JobStatus


class FamilyJobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        self.recover_interrupted()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    status TEXT NOT NULL,
                    heavy INTEGER NOT NULL CHECK (heavy = 1),
                    request_json TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    terminal INTEGER NOT NULL CHECK (terminal IN (0, 1)),
                    timestamp_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (job_id, sequence)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_heavy_job
                    ON jobs(heavy) WHERE status = 'RUNNING';
                CREATE UNIQUE INDEX IF NOT EXISTS one_terminal_event
                    ON events(job_id) WHERE terminal = 1;
                """
            )
            columns = {
                row[1] for row in self._connection.execute("PRAGMA table_info(jobs)")
            }
            if "session_id" not in columns:
                self._connection.execute(
                    "ALTER TABLE jobs ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'"
                )

    def create_job(
        self,
        auth: AuthContext,
        request: ChatRequest,
        *,
        queue_capacity: int = 2,
        mock_only: bool = True,
    ) -> JobRecord:
        job_id = uuid.uuid4().hex
        correlation_id = uuid.uuid4().hex
        timestamp = utc_now()
        request_json = json.dumps(
            {"message": request.message}, ensure_ascii=False, separators=(",", ":")
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                queued = self._connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status = ?",
                    (JobStatus.QUEUED.value,),
                ).fetchone()[0]
                if queued >= queue_capacity:
                    raise FamilyBackpressureError("fila Family saturada")
                self._connection.execute(
                """INSERT INTO jobs
                (job_id, correlation_id, user_id, device_id, session_id, status, heavy,
                 request_json, created_utc, updated_utc)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    job_id,
                    correlation_id,
                    auth.user_id,
                    auth.device_id,
                    auth.session_id,
                    JobStatus.QUEUED.value,
                    request_json,
                    timestamp,
                    timestamp,
                ),
                )
                self._append_event_tx(
                    job_id,
                    EventKind.ACCEPTED,
                    {"mock_only": bool(mock_only), "queue_capacity": queue_capacity},
                    timestamp,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return JobRecord(job_id, correlation_id, auth, request, JobStatus.QUEUED)

    def claim_next(self) -> JobRecord | None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """SELECT * FROM jobs WHERE status = ?
                    ORDER BY created_utc, job_id LIMIT 1""",
                    (JobStatus.QUEUED.value,),
                ).fetchone()
                if row is None:
                    self._connection.commit()
                    return None
                timestamp = utc_now()
                self._connection.execute(
                    "UPDATE jobs SET status = ?, updated_utc = ? WHERE job_id = ?",
                    (JobStatus.RUNNING.value, timestamp, row["job_id"]),
                )
                self._append_event_tx(
                    row["job_id"], EventKind.STARTED, {"heavy_slot": 1}, timestamp
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return self._record_from_row(row, status=JobStatus.RUNNING)

    def append_delta(self, job_id: str, text: str) -> JobEvent | None:
        with self._lock, self._connection:
            row = self._job_row(job_id)
            if row["status"] != JobStatus.RUNNING.value:
                return None
            return self._append_event_tx(
                job_id, EventKind.DELTA, {"text": text}, utc_now()
            )

    def complete(
        self,
        job_id: str,
        *,
        mock_only: bool = True,
        metrics: Mapping[str, Any] | None = None,
    ) -> JobEvent | None:
        with self._lock, self._connection:
            row = self._job_row(job_id)
            if row["status"] != JobStatus.RUNNING.value:
                return None
            timestamp = utc_now()
            payload: dict[str, Any] = {"mock_only": bool(mock_only)}
            if metrics:
                payload.update(dict(metrics))
            event = self._append_event_tx(job_id, EventKind.COMPLETED, payload, timestamp)
            self._connection.execute(
                "UPDATE jobs SET status = ?, updated_utc = ? WHERE job_id = ?",
                (JobStatus.COMPLETED.value, timestamp, job_id),
            )
            return event

    def fail(self, job_id: str, reason_code: str) -> JobEvent | None:
        with self._lock, self._connection:
            row = self._job_row(job_id)
            if row["status"] in {
                JobStatus.COMPLETED.value,
                JobStatus.CANCELLED.value,
                JobStatus.FAILED.value,
            }:
                return None
            timestamp = utc_now()
            event = self._append_event_tx(
                job_id, EventKind.FAILED, {"reason_code": reason_code}, timestamp
            )
            self._connection.execute(
                "UPDATE jobs SET status = ?, updated_utc = ? WHERE job_id = ?",
                (JobStatus.FAILED.value, timestamp, job_id),
            )
            return event

    def cancel(
        self,
        job_id: str,
        auth: AuthContext,
        *,
        requested_by: str = "client",
    ) -> JobEvent | None:
        with self._lock, self._connection:
            row = self._authorized_row(job_id, auth)
            if row["status"] in {
                JobStatus.COMPLETED.value,
                JobStatus.CANCELLED.value,
                JobStatus.FAILED.value,
            }:
                return None
            timestamp = utc_now()
            event = self._append_event_tx(
                job_id,
                EventKind.CANCELLED,
                {"requested_by": requested_by},
                timestamp,
            )
            self._connection.execute(
                "UPDATE jobs SET status = ?, updated_utc = ? WHERE job_id = ?",
                (JobStatus.CANCELLED.value, timestamp, job_id),
            )
            return event

    def events(self, job_id: str, auth: AuthContext) -> tuple[JobEvent, ...]:
        with self._lock:
            job = self._authorized_row(job_id, auth)
            rows = self._connection.execute(
                "SELECT * FROM events WHERE job_id = ? ORDER BY sequence", (job_id,)
            ).fetchall()
        return tuple(
            JobEvent(
                job_id=job_id,
                correlation_id=job["correlation_id"],
                sequence=row["sequence"],
                kind=EventKind(row["kind"]),
                timestamp_utc=row["timestamp_utc"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        )

    def status(self, job_id: str) -> JobStatus:
        with self._lock:
            return JobStatus(self._job_row(job_id)["status"])

    def is_cancelled(self, job_id: str) -> bool:
        return self.status(job_id) == JobStatus.CANCELLED

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            ).fetchall()
        result = {status.value: 0 for status in JobStatus}
        result.update({row["status"]: row["count"] for row in rows})
        return result

    def queue_position(self, job_id: str) -> int | None:
        with self._lock:
            row = self._job_row(job_id)
            if row["status"] != JobStatus.QUEUED.value:
                return None
            ordered = self._connection.execute(
                """SELECT job_id FROM jobs WHERE status = ?
                ORDER BY created_utc, job_id""",
                (JobStatus.QUEUED.value,),
            ).fetchall()
        for position, item in enumerate(ordered, start=1):
            if item["job_id"] == job_id:
                return position
        return None

    def job_ids(self, status: JobStatus) -> tuple[str, ...]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT job_id FROM jobs WHERE status = ?
                ORDER BY created_utc, job_id""",
                (status.value,),
            ).fetchall()
        return tuple(row["job_id"] for row in rows)

    def recover_interrupted(self) -> int:
        recovered = 0
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT job_id FROM jobs WHERE status = ?",
                (JobStatus.RUNNING.value,),
            ).fetchall()
            for row in rows:
                timestamp = utc_now()
                self._append_event_tx(
                    row["job_id"],
                    EventKind.FAILED,
                    {"reason_code": "PROCESS_RESTART"},
                    timestamp,
                )
                self._connection.execute(
                    "UPDATE jobs SET status = ?, updated_utc = ? WHERE job_id = ?",
                    (JobStatus.FAILED.value, timestamp, row["job_id"]),
                )
                recovered += 1
        return recovered

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _record_from_row(
        self, row: sqlite3.Row, *, status: JobStatus | None = None
    ) -> JobRecord:
        document = json.loads(row["request_json"])
        return JobRecord(
            job_id=row["job_id"],
            correlation_id=row["correlation_id"],
            auth=AuthContext(row["user_id"], row["device_id"], row["session_id"]),
            request=ChatRequest.from_mapping(document),
            status=status or JobStatus(row["status"]),
        )

    def _job_row(self, job_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return row

    def _authorized_row(self, job_id: str, auth: AuthContext) -> sqlite3.Row:
        row = self._job_row(job_id)
        if (
            row["user_id"] != auth.user_id
            or row["device_id"] != auth.device_id
            or row["session_id"] != auth.session_id
        ):
            raise FamilyAuthorizationError("job não pertence ao contexto autenticado")
        return row

    def active_job_ids_for_device(self, user_id: str, device_id: str) -> tuple[str, ...]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT job_id FROM jobs
                WHERE user_id = ? AND device_id = ? AND status IN (?, ?)
                ORDER BY created_utc, job_id""",
                (
                    user_id,
                    device_id,
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                ),
            ).fetchall()
        return tuple(row["job_id"] for row in rows)

    def auth_for_job(self, job_id: str) -> AuthContext:
        with self._lock:
            row = self._job_row(job_id)
            return AuthContext(row["user_id"], row["device_id"], row["session_id"])

    def auth_contexts_for_device(self, device_id: str) -> tuple[AuthContext, ...]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT DISTINCT user_id, device_id, session_id FROM jobs
                WHERE device_id = ?""",
                (device_id,),
            ).fetchall()
        return tuple(
            AuthContext(row["user_id"], row["device_id"], row["session_id"])
            for row in rows
        )

    def _append_event_tx(
        self,
        job_id: str,
        kind: EventKind,
        payload: Mapping[str, Any],
        timestamp: str,
    ) -> JobEvent:
        job = self._job_row(job_id)
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE job_id = ?",
            (job_id,),
        ).fetchone()[0]
        terminal = int(kind in {EventKind.COMPLETED, EventKind.CANCELLED, EventKind.FAILED})
        self._connection.execute(
            """INSERT INTO events
            (job_id, sequence, kind, terminal, timestamp_utc, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                sequence,
                kind.value,
                terminal,
                timestamp,
                json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")),
            ),
        )
        return JobEvent(
            job_id,
            job["correlation_id"],
            sequence,
            kind,
            timestamp,
            dict(payload),
        )
