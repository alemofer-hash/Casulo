from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterable

from .audit import AuditLog
from .contracts import (
    AuthContext,
    ChatRequest,
    FamilyAuthorizationError,
    JobEvent,
    JobStatus,
)
from .memory import MockFamilyMemory, MockMemoryEntry
from .scheduler import FamilyJobStore, JobRecord, utc_now
from .supervisor import FamilySupervisor


class FamilyRuntime:
    def __init__(
        self,
        *,
        store: FamilyJobStore,
        audit: AuditLog,
        memory: MockFamilyMemory,
        supervisor: FamilySupervisor,
        authorized_contexts: Iterable[AuthContext],
    ) -> None:
        self.store = store
        self.audit = audit
        self.memory = memory
        self.supervisor = supervisor
        self._authorized = frozenset(authorized_contexts)
        if not self._authorized:
            raise FamilyAuthorizationError("nenhum contexto sintético autorizado")
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop, name="casulo-family-mock-worker", daemon=True
        )
        self._worker.start()

    def submit(self, auth: AuthContext, request: ChatRequest) -> JobRecord:
        self._authorize(auth)
        job = self.store.create_job(auth, request)
        self.audit.append(
            timestamp_utc=utc_now(),
            event_type="JOB_ACCEPTED",
            correlation_id=job.correlation_id,
            user_id=auth.user_id,
            device_id=auth.device_id,
            fields={
                "job_id": job.job_id,
                "message_chars": len(request.message),
                "message_sha256": hashlib.sha256(
                    request.message.encode("utf-8")
                ).hexdigest(),
                "mock_only": True,
            },
        )
        self._wake.set()
        return job

    def events(self, auth: AuthContext, job_id: str) -> tuple[JobEvent, ...]:
        self._authorize(auth)
        return self.store.events(job_id, auth)

    def cancel(self, auth: AuthContext, job_id: str) -> JobEvent | None:
        self._authorize(auth)
        event = self.store.cancel(job_id, auth)
        if event is not None:
            self._audit_event(auth, event)
        self._wake.set()
        return event

    def wait_terminal(
        self, auth: AuthContext, job_id: str, *, timeout: float
    ) -> tuple[JobEvent, ...]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = self.events(auth, job_id)
            if events and events[-1].terminal:
                return events
            time.sleep(0.01)
        return self.events(auth, job_id)

    def health(self) -> dict[str, object]:
        counts = self.store.counts()
        return {
            "status": "ok",
            "mode": "DAY1_MOCK_ONLY",
            "mock_engine": True,
            "mock_memory": True,
            "queued": counts[JobStatus.QUEUED.value],
            "running_heavy": counts[JobStatus.RUNNING.value],
        }

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        self._worker.join(timeout=5.0)
        if self._worker.is_alive():
            raise RuntimeError("worker não encerrou")
        self.store.close()
        self.memory.close()

    def _authorize(self, auth: AuthContext) -> None:
        if auth not in self._authorized:
            raise FamilyAuthorizationError("contexto sintético não autorizado")

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next()
            if job is None:
                self._wake.wait(0.1)
                self._wake.clear()
                continue
            try:
                started = self.store.events(job.job_id, job.auth)[-1]
                self._audit_event(job.auth, started)
                for chunk in self.supervisor.respond(
                    job.request, lambda: self.store.is_cancelled(job.job_id)
                ):
                    event = self.store.append_delta(job.job_id, chunk)
                    if event is not None:
                        self._audit_event(job.auth, event)
                event = self.store.complete(job.job_id)
                if event is not None:
                    self.memory.remember(
                        MockMemoryEntry(
                            user_id=job.auth.user_id,
                            correlation_id=job.correlation_id,
                            summary="[MOCK MEMORY] interaction completed",
                        )
                    )
                    self._audit_event(job.auth, event)
            except Exception:
                event = self.store.fail(job.job_id, "MOCK_EXECUTION_FAILED")
                if event is not None:
                    self._audit_event(job.auth, event)

    def _audit_event(self, auth: AuthContext, event: JobEvent) -> None:
        self.audit.append(
            timestamp_utc=event.timestamp_utc,
            event_type=f"JOB_{event.kind.value}",
            correlation_id=event.correlation_id,
            user_id=auth.user_id,
            device_id=auth.device_id,
            fields={
                "job_id": event.job_id,
                "sequence": event.sequence,
                "kind": event.kind.value,
            },
        )
