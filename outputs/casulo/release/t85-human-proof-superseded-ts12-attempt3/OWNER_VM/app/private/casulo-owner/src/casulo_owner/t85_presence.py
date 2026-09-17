from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from casulo.product.guide_presence import JobEvent, JobStatus
from casulo.product.platform_contracts import Clock
from casulo.product.voice_duplex import DuplexEvent
from casulo.t.productive import ProductiveTCall, ProductiveTError, ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder


@dataclass(frozen=True, slots=True)
class TurnDecision:
    value: str
    call: ProductiveTCall


class T85TurnCoordinator:
    def __init__(self, runtime: Path, tcap: Path, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.executor = ProductiveTExecutor(runtime, tcap, self.root)
        existing = [
            int(path.name.removeprefix("turn.").removesuffix(".json"))
            for path in self.root.glob("turn.*.json")
            if path.name.removeprefix("turn.").removesuffix(".json").isdigit()
        ]
        self.sequence = max(existing, default=0)
        receipts = sorted(self.root.glob("turn.*.receipt.json"))
        self.previous = json.loads(receipts[-1].read_text(encoding="utf-8"))["receipt"]["receipt_hash"] if receipts else "0" * 64

    @staticmethod
    def build(source: Path, output: Path) -> Path:
        if output.exists():
            return output
        return TcapV2Builder().build(
            (source,), output,
            entry_module="owner.guide.turn_coordinator", entry_function="coordinate",
            tests={"properties": ["barge_in_priority", "final_only_commit", "progress_requires_authenticated_event", "cancel_fail_closed"]},
        ).directory

    def decide(
        self,
        *,
        event_kind: str,
        speech_detected: bool,
        transcript_final: bool,
        transcript_nonempty: bool,
        tts_active: bool,
        job_event_authenticated: bool = False,
        cancelled: bool = False,
    ) -> TurnDecision:
        self.sequence += 1
        call_id = f"turn.{self.sequence:08d}"
        call = self.executor.execute(
            "owner.guide.turn_coordinator", "coordinate",
            {
                "event_kind": event_kind,
                "speech_detected": speech_detected,
                "transcript_final": transcript_final,
                "transcript_nonempty": transcript_nonempty,
                "tts_active": tts_active,
                "job_event_authenticated": job_event_authenticated,
                "cancelled": cancelled,
            },
            call_id=call_id, surface_id="dialogue_turning", scope_id="guide:presence",
            previous_receipt_hash=self.previous,
        )
        result = call.observable.get("result", {})
        if result.get("kind") != "ok":
            raise ProductiveTError(f"T TurnCoordinator denied event: {result.get('value')}")
        target = self.root / f"{call_id}.receipt.json"
        if target.exists():
            raise ProductiveTError("turn receipt duplicado")
        payload = {"observable": dict(call.observable), "receipt": dict(call.receipt)}
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, target)
        self.previous = str(call.receipt["receipt_hash"])
        return TurnDecision(str(result["value"]), call)

    def decide_duplex(self, event: DuplexEvent, *, tts_active: bool) -> TurnDecision:
        transcript = event.transcript
        return self.decide(
            event_kind=event.kind,
            speech_detected=event.kind in {"BARGE_IN", "TRANSCRIPT_PARTIAL", "TRANSCRIPT_FINAL"},
            transcript_final=bool(transcript and transcript.final),
            transcript_nonempty=bool(transcript and transcript.text.strip()),
            tts_active=tts_active,
        )


class PresenceWorkLanes:
    """Presence never waits for Work; progress exists only as signed facts."""

    def __init__(self, *, clock: Clock, coordinator: T85TurnCoordinator) -> None:
        self.clock = clock
        self.coordinator = coordinator
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="casulo-work")
        self._events: list[JobEvent] = []
        self._lock = threading.Lock()
        self._cancelled: set[str] = set()

    @property
    def events(self) -> tuple[JobEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def submit(self, job_id: str, work: Callable[[], bytes], *, source_event_id: str) -> Future[bytes]:
        start_digest = hashlib.sha256(f"{job_id}:STARTED".encode()).hexdigest()
        self._publish(JobEvent(f"{job_id}.started", job_id, JobStatus.STARTED, "trabalho iniciado", start_digest, (source_event_id,), self.clock.utc_timestamp()))

        def execute() -> bytes:
            try:
                result = work()
                with self._lock:
                    late = job_id in self._cancelled
                if late:
                    return result
                digest = hashlib.sha256(result).hexdigest()
                self._publish(JobEvent(f"{job_id}.completed", job_id, JobStatus.COMPLETED, "trabalho concluído", digest, (f"{job_id}.started",), self.clock.utc_timestamp()))
                return result
            except BaseException as error:
                digest = hashlib.sha256(type(error).__name__.encode()).hexdigest()
                self._publish(JobEvent(f"{job_id}.failed", job_id, JobStatus.FAILED, "trabalho falhou", digest, (f"{job_id}.started",), self.clock.utc_timestamp()))
                raise

        return self._pool.submit(execute)

    def cancel(self, job_id: str, *, source_event_id: str) -> bool:
        with self._lock:
            if job_id in self._cancelled or not any(item.job_id == job_id and item.status is JobStatus.STARTED for item in self._events):
                return False
            if any(item.job_id == job_id and item.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED} for item in self._events):
                return False
            self._cancelled.add(job_id)
        digest = hashlib.sha256(f"{job_id}:CANCELLED".encode()).hexdigest()
        self._publish(JobEvent(f"{job_id}.cancelled", job_id, JobStatus.CANCELLED, "trabalho cancelado", digest, (source_event_id,), self.clock.utc_timestamp()))
        return True

    def _publish(self, event: JobEvent) -> None:
        decision = self.coordinator.decide(
            event_kind="JOB_EVENT", speech_detected=False, transcript_final=False,
            transcript_nonempty=False, tts_active=False, job_event_authenticated=True,
        )
        if decision.value != "SHOW_PROGRESS":
            raise ProductiveTError("T recusou JobEvent autenticado")
        with self._lock:
            self._events.append(event)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)
