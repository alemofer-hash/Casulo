from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterable, Iterator

from .audit import AuditLog
from .config import FamilyConfig
from .contracts import (
    AuthContext,
    ChatRequest,
    FamilyAuthorizationError,
    FamilyBackpressureError,
    FamilyResourceError,
    FamilyUnavailableError,
    JobEvent,
    JobStatus,
)
from .memory import MockFamilyMemory, MockMemoryEntry
from .scheduler import FamilyJobStore, JobRecord, utc_now
from .supervisor import FamilySupervisor, SupervisorState


class FamilyRuntime:
    def __init__(
        self,
        *,
        store: FamilyJobStore,
        audit: AuditLog,
        memory: MockFamilyMemory,
        supervisor: FamilySupervisor,
        authorized_contexts: Iterable[AuthContext],
        config: FamilyConfig | None = None,
        authorization_callback: Callable[[AuthContext], bool] | None = None,
    ) -> None:
        self.store = store
        self.audit = audit
        self.memory = memory
        self.supervisor = supervisor
        self.config = config or FamilyConfig(mock_only=supervisor.engine.mock_only)
        if self.config.mock_only != bool(supervisor.engine.mock_only):
            raise FamilyUnavailableError("modo do config diverge do adapter")
        self._authorized = frozenset(authorized_contexts)
        self._authorization_callback = authorization_callback
        if not self._authorized and self._authorization_callback is None:
            raise FamilyAuthorizationError("nenhum contexto sintético autorizado")
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._events_changed = threading.Condition()
        self._active_lock = threading.RLock()
        self._active_job: JobRecord | None = None
        self._stats_lock = threading.RLock()
        self._stats = {
            "accepted": 0,
            "enqueued": 0,
            "rejected": 0,
            "cancelled": 0,
            "completed": 0,
            "failed": 0,
        }
        self.supervisor.start()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="casulo-family-supervised-worker",
            daemon=True,
        )
        self._worker.start()

    def submit(self, auth: AuthContext, request: ChatRequest) -> JobRecord:
        self._authorize(auth)
        try:
            self.supervisor.admission_sample()
            job = self.store.create_job(
                auth,
                request,
                queue_capacity=self.config.queue_capacity,
                mock_only=self.supervisor.engine.mock_only,
            )
        except (FamilyBackpressureError, FamilyResourceError, FamilyUnavailableError):
            self._increment("rejected")
            raise
        self._increment("accepted")
        self._increment("enqueued")
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
                "mock_only": bool(self.supervisor.engine.mock_only),
                "queue_capacity": self.config.queue_capacity,
            },
        )
        self._notify()
        self._wake.set()
        return job

    def events(self, auth: AuthContext, job_id: str) -> tuple[JobEvent, ...]:
        self._authorize(auth)
        return self.store.events(job_id, auth)

    def stream_events(
        self,
        auth: AuthContext,
        job_id: str,
        *,
        timeout: float,
        after_sequence: int = 0,
    ) -> Iterator[JobEvent]:
        self._authorize(auth)
        deadline = time.monotonic() + timeout
        next_sequence = after_sequence + 1
        while True:
            events = self.store.events(job_id, auth)
            for event in events:
                if event.sequence < next_sequence:
                    continue
                next_sequence = event.sequence + 1
                yield event
                if event.terminal:
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.cancel(auth, job_id, requested_by="stream_timeout")
                continue
            with self._events_changed:
                self._events_changed.wait(timeout=min(0.1, remaining))

    def cancel(
        self,
        auth: AuthContext,
        job_id: str,
        *,
        requested_by: str = "client",
    ) -> JobEvent | None:
        self._authorize(auth)
        event = self.store.cancel(job_id, auth, requested_by=requested_by)
        if event is not None:
            self._increment("cancelled")
            self._audit_event(auth, event)
            self._notify()
        self._wake.set()
        return event

    def disconnect(self, auth: AuthContext, job_id: str) -> JobEvent | None:
        if self.config.disconnect_policy == "drain":
            return None
        return self.cancel(auth, job_id, requested_by="disconnect")

    def wait_terminal(
        self, auth: AuthContext, job_id: str, *, timeout: float
    ) -> tuple[JobEvent, ...]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = self.events(auth, job_id)
            if events and events[-1].terminal:
                return events
            with self._events_changed:
                self._events_changed.wait(timeout=0.01)
        return self.events(auth, job_id)

    def wait_status(
        self, job_id: str, status: JobStatus, *, timeout: float
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.store.status(job_id) == status:
                return True
            with self._events_changed:
                self._events_changed.wait(timeout=0.01)
        return self.store.status(job_id) == status

    def health(self) -> dict[str, object]:
        counts = self.store.counts()
        supervisor = self.supervisor.snapshot()
        return {
            "status": "ok" if supervisor["ready"] else "unavailable",
            "mode": "DAY1_MOCK_ONLY" if self.config.mock_only else "DAY3_LOCAL_MODEL",
            "mock_engine": bool(self.supervisor.engine.mock_only),
            "mock_memory": bool(self.memory.mock_only),
            "queued": counts[JobStatus.QUEUED.value],
            "running_heavy": counts[JobStatus.RUNNING.value],
            "queue_capacity": self.config.queue_capacity,
            "supervisor": supervisor,
            "counters": self.counters(),
            "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
            "temperature_telemetry_collected_by_runner": False,
            "temperature_claim": "NONE",
        }

    def counters(self) -> dict[str, int]:
        with self._stats_lock:
            return dict(self._stats)

    def close(self) -> None:
        self._stop.set()
        with self._active_lock:
            active = self._active_job
        if active is not None:
            event = self.store.cancel(
                active.job_id, active.auth, requested_by="runtime_shutdown"
            )
            if event is not None:
                self._increment("cancelled")
                self._audit_event(active.auth, event)
        self._wake.set()
        self._notify()
        self._worker.join(timeout=15.0)
        if self._worker.is_alive():
            raise RuntimeError("worker não encerrou")
        if self.supervisor.state != SupervisorState.STOPPED:
            self.supervisor.stop()
        self.store.close()
        self.memory.close()

    def _authorize(self, auth: AuthContext) -> None:
        allowed = auth in self._authorized
        if self._authorization_callback is not None:
            allowed = bool(self._authorization_callback(auth))
        if not allowed:
            raise FamilyAuthorizationError("contexto sintético não autorizado")

    def revoke_device(self, user_id: str, device_id: str) -> int:
        cancelled = 0
        for job_id in self.store.active_job_ids_for_device(user_id, device_id):
            try:
                auth = self.store.auth_for_job(job_id)
                event = self.store.cancel(
                    job_id, auth, requested_by="device_revoked"
                )
            except KeyError:
                continue
            if event is not None:
                cancelled += 1
                self._increment("cancelled")
                self._audit_event(auth, event)
        self._wake.set()
        self._notify()
        return cancelled

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next()
            if job is None:
                self._wake.wait(0.1)
                self._wake.clear()
                continue
            with self._active_lock:
                if self._active_job is not None:
                    event = self.store.fail(job.job_id, "CONCURRENCY_INVARIANT")
                    if event is not None:
                        self._increment("failed")
                        self._audit_event(job.auth, event)
                        self._notify()
                    continue
                self._active_job = job
            started_ns = time.monotonic_ns()
            first_delta_ns: int | None = None
            delta_count = 0
            try:
                started = self.store.events(job.job_id, job.auth)[-1]
                self._audit_event(job.auth, started)
                self._notify()
                stream = iter(self.supervisor.respond(
                    job.request,
                    lambda: self._stop.is_set()
                    or self.store.is_cancelled(job.job_id),
                ))
                try:
                    for chunk in stream:
                        if self.store.is_cancelled(job.job_id):
                            break
                        if not isinstance(chunk, str) or not chunk:
                            continue
                        if len(chunk) > self.config.max_stream_chunk_chars:
                            raise FamilyUnavailableError("fragmento excede limite")
                        delta_count += 1
                        if delta_count > self.config.max_stream_events:
                            raise FamilyUnavailableError("stream excede limite de eventos")
                        event = self.store.append_delta(job.job_id, chunk)
                        if event is not None:
                            first_delta_ns = first_delta_ns or time.monotonic_ns()
                            self._audit_event(job.auth, event)
                            self._notify()
                finally:
                    closer = getattr(stream, "close", None)
                    if callable(closer):
                        closer()
                if self.store.is_cancelled(job.job_id):
                    continue
                if delta_count == 0:
                    raise FamilyUnavailableError("adapter concluiu sem fragmentos")
                ended_ns = time.monotonic_ns()
                metrics = {
                    "stream_events": delta_count,
                    "time_to_first_fragment_ms": round(
                        ((first_delta_ns or ended_ns) - started_ns) / 1_000_000, 3
                    ),
                    "duration_ms": round((ended_ns - started_ns) / 1_000_000, 3),
                }
                event = self.store.complete(
                    job.job_id,
                    mock_only=self.supervisor.engine.mock_only,
                    metrics=metrics,
                )
                if event is not None:
                    self._increment("completed")
                    self.memory.remember(
                        MockMemoryEntry(
                            user_id=job.auth.user_id,
                            correlation_id=job.correlation_id,
                            summary=(
                                "[MOCK MEMORY] interaction completed"
                                if self.supervisor.engine.mock_only
                                else "[LOCAL MODEL] interaction completed"
                            ),
                            session_id=job.auth.session_id,
                        )
                    )
                    self._audit_event(job.auth, event)
                    self._notify()
            except Exception:
                event = self.store.fail(job.job_id, "ADAPTER_EXECUTION_FAILED")
                if event is not None:
                    self._increment("failed")
                    self._audit_event(job.auth, event)
                    self._notify()
            finally:
                with self._active_lock:
                    self._active_job = None
                self._notify()

    def _increment(self, field: str) -> None:
        with self._stats_lock:
            self._stats[field] += 1

    def _notify(self) -> None:
        with self._events_changed:
            self._events_changed.notify_all()

    def _audit_event(self, auth: AuthContext, event: JobEvent) -> None:
        self.audit.append(
            timestamp_utc=event.timestamp_utc,
            event_type=f"JOB_{event.kind.value}",
            correlation_id=event.correlation_id,
            user_id=auth.user_id,
            device_id=auth.device_id,
            session_id=auth.session_id,
            fields={
                "job_id": event.job_id,
                "sequence": event.sequence,
                "kind": event.kind.value,
            },
        )
