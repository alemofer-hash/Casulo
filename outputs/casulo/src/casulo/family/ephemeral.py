"""Bounded, RAM-only conversation store for Cleo. No SQLite audio/text files."""
from pathlib import Path
import time

from .contracts import FamilyBackpressureError
from .scheduler import FamilyJobStore


class EphemeralFamilyJobStore(FamilyJobStore):
    def __init__(self, *, capacity: int = 16, retention_seconds: float = 120):
        if not 1 <= capacity <= 32 or not 1 <= retention_seconds <= 300:
            raise ValueError("ephemeral bounds invalid")
        self.capacity = capacity
        self.retention_seconds = retention_seconds
        self._deadlines = {}
        super().__init__(Path(":memory:"))

    def expire(self):
        with self._lock, self._connection:
            for job_id, deadline in list(self._deadlines.items()):
                if time.monotonic() >= deadline:
                    self.forget(job_id)

    def forget(self, job_id):
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT status FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or row[0] in {"QUEUED", "RUNNING"}:
                return
            self._connection.execute("DELETE FROM events WHERE job_id=?", (job_id,))
            self._connection.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
            self._volatile_requests.pop(job_id, None)
            self._deadlines.pop(job_id, None)

    def create_job(self, *args, **kwargs):
        with self._lock:
            self.expire()
            if sum(self.counts().values()) >= self.capacity:
                raise FamilyBackpressureError("ephemeral retention capacity")
            return super().create_job(*args, **kwargs)

    def _append_event_tx(self, job_id, kind, payload, timestamp):
        event = super()._append_event_tx(job_id, kind, payload, timestamp)
        if event.terminal:
            self._deadlines[job_id] = time.monotonic() + self.retention_seconds
        return event
