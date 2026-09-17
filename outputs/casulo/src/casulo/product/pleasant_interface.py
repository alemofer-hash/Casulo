from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Callable, Mapping

from .domain import canonical_sha256
from .engine_contracts import CancellationToken


UX_EVENT_PREFIX = "CASULO_UX_EVENT "
UX_EVENT_SCHEMA = "casulo.owner-ux-event/1.0"
MAX_UX_EVENT_BYTES = 32 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _is_evidence_sha256(value: str) -> bool:
    return bool(_SHA256.fullmatch(value)) and value != "0" * 64


class UxEventKind(StrEnum):
    PRESENCE_READY = "PRESENCE_READY"
    MODEL_LOADING = "MODEL_LOADING"
    MODEL_READY = "MODEL_READY"
    INPUT_REQUEST = "INPUT_REQUEST"
    ASSISTANT_START = "ASSISTANT_START"
    ASSISTANT_TOKEN = "ASSISTANT_TOKEN"
    ASSISTANT_END = "ASSISTANT_END"
    JOB_STARTED = "JOB_STARTED"
    JOB_MILESTONE = "JOB_MILESTONE"
    JOB_COMPLETED = "JOB_COMPLETED"
    JOB_FAILED = "JOB_FAILED"
    JOB_CANCELLED = "JOB_CANCELLED"
    NOTICE = "NOTICE"
    RECOVERABLE_ERROR = "RECOVERABLE_ERROR"


_JOB_KINDS = frozenset(
    {
        UxEventKind.JOB_STARTED,
        UxEventKind.JOB_MILESTONE,
        UxEventKind.JOB_COMPLETED,
        UxEventKind.JOB_FAILED,
        UxEventKind.JOB_CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class UxEvent:
    event_id: str
    kind: UxEventKind
    payload: Mapping[str, Any]
    source_event_ids: tuple[str, ...]
    occurred_at: str
    event_hash: str
    schema: str = UX_EVENT_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        kind: UxEventKind,
        payload: Mapping[str, Any],
        source_event_ids: tuple[str, ...],
        occurred_at: str,
    ) -> "UxEvent":
        normalized = dict(payload)
        _validate_payload(kind, normalized)
        unsigned = {
            "schema": UX_EVENT_SCHEMA,
            "event_id": event_id,
            "kind": kind.value,
            "payload": normalized,
            "source_event_ids": list(source_event_ids),
            "occurred_at": occurred_at,
        }
        if not event_id or not source_event_ids or not occurred_at:
            raise ValueError("evento UX exige identidade, proveniência e horário")
        return cls(
            event_id=event_id,
            kind=kind,
            payload=normalized,
            source_event_ids=source_event_ids,
            occurred_at=occurred_at,
            event_hash=canonical_sha256(unsigned),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
            "source_event_ids": list(self.source_event_ids),
            "occurred_at": self.occurred_at,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UxEvent":
        kind = UxEventKind(str(value["kind"]))
        event = cls.create(
            event_id=str(value["event_id"]),
            kind=kind,
            payload=dict(value["payload"]),
            source_event_ids=tuple(str(item) for item in value["source_event_ids"]),
            occurred_at=str(value["occurred_at"]),
        )
        if value.get("schema") != UX_EVENT_SCHEMA or value.get("event_hash") != event.event_hash:
            raise ValueError("evento UX adulterado ou incompatível")
        return event


def encode_ux_event(event: UxEvent) -> str:
    encoded = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    line = UX_EVENT_PREFIX + encoded
    if len(line.encode("utf-8")) > MAX_UX_EVENT_BYTES:
        raise ValueError("evento UX excede limite")
    return line


def decode_ux_event(line: str) -> UxEvent | None:
    if not line.startswith(UX_EVENT_PREFIX):
        return None
    if len(line.encode("utf-8")) > MAX_UX_EVENT_BYTES:
        raise ValueError("evento UX excede limite")
    try:
        value = json.loads(line[len(UX_EVENT_PREFIX) :])
    except json.JSONDecodeError as error:
        raise ValueError("evento UX não é JSON válido") from error
    if not isinstance(value, dict):
        raise ValueError("evento UX precisa ser objeto")
    return UxEvent.from_dict(value)


class UxStreamValidator:
    """Rejects fabricated progress, late tokens and malformed terminal events."""

    def __init__(self) -> None:
        self._turns: dict[str, str] = {}
        self._token_sequence: dict[str, int] = {}
        self._jobs: dict[str, str] = {}
        self._event_ids: set[str] = set()

    def accept(self, event: UxEvent) -> None:
        if event.event_id in self._event_ids:
            raise ValueError("evento UX duplicado")
        self._event_ids.add(event.event_id)
        if event.kind in {UxEventKind.ASSISTANT_START, UxEventKind.ASSISTANT_TOKEN, UxEventKind.ASSISTANT_END}:
            turn_id = str(event.payload["turn_id"])
            state = self._turns.get(turn_id)
            if event.kind is UxEventKind.ASSISTANT_START:
                if state is not None:
                    raise ValueError("turno assistente duplicado")
                self._turns[turn_id] = "STREAMING"
                self._token_sequence[turn_id] = 0
            elif event.kind is UxEventKind.ASSISTANT_TOKEN:
                if state != "STREAMING":
                    raise ValueError("token fora de turno ativo")
                expected = self._token_sequence[turn_id] + 1
                if int(event.payload["sequence"]) != expected:
                    raise ValueError("token fora de ordem")
                self._token_sequence[turn_id] = expected
            else:
                if state != "STREAMING":
                    raise ValueError("fim de turno sem stream ativo")
                self._turns[turn_id] = "TERMINAL"
        if event.kind in _JOB_KINDS:
            job_id = str(event.payload["job_id"])
            previous = self._jobs.get(job_id)
            if event.kind is UxEventKind.JOB_STARTED:
                if previous is not None:
                    raise ValueError("job UX duplicado")
                self._jobs[job_id] = "ACTIVE"
            elif previous != "ACTIVE":
                raise ValueError("evento de job sem STARTED ativo")
            elif event.kind in {UxEventKind.JOB_COMPLETED, UxEventKind.JOB_FAILED, UxEventKind.JOB_CANCELLED}:
                self._jobs[job_id] = "TERMINAL"


@dataclass(frozen=True, slots=True)
class JobEvidence:
    evidence_sha256: str
    summary: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not _is_evidence_sha256(self.evidence_sha256) or not self.summary.strip():
            raise ValueError("resultado do job exige evidência e resumo")


@dataclass(frozen=True, slots=True)
class BackgroundJobEvent:
    job_id: str
    status: str
    summary: str
    evidence_sha256: str
    sequence: int


class HonestBackgroundJob:
    """One cancellable product job; late completion is never published."""

    def __init__(self, on_event: Callable[[BackgroundJobEvent], None]) -> None:
        self._on_event = on_event
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._token: CancellationToken | None = None
        self._job_id: str | None = None
        self._sequence = 0
        self._status = "IDLE"
        self._last_summary = "Nenhum trabalho em execução."

    @property
    def active(self) -> bool:
        with self._lock:
            return self._status in {"STARTED", "MILESTONE"}

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                "schema": "casulo.background-job-snapshot/1.0",
                "job_id": self._job_id,
                "status": self._status,
                "last_summary": self._last_summary,
                "sequence": self._sequence,
            }

    def start(
        self,
        job_id: str,
        worker: Callable[[CancellationToken, Callable[[str, str], None]], JobEvidence],
        *,
        start_evidence_sha256: str,
    ) -> None:
        if not job_id or not _is_evidence_sha256(start_evidence_sha256):
            raise ValueError("job exige identidade e evidência inicial")
        with self._lock:
            if self.active:
                raise RuntimeError("já existe job owner ativo")
            self._job_id = job_id
            self._token = CancellationToken()
            self._sequence = 0
            self._status = "STARTED"
            self._emit("STARTED", "Criação aceita; preparando o primeiro artefato verificável.", start_evidence_sha256)
            token = self._token

        def report(summary: str, evidence_sha256: str) -> None:
            with self._lock:
                if token.cancelled or self._status not in {"STARTED", "MILESTONE"}:
                    return
                self._status = "MILESTONE"
                self._emit("MILESTONE", summary, evidence_sha256)

        def run() -> None:
            try:
                result = worker(token, report)
                with self._lock:
                    if token.cancelled:
                        self._status = "CANCELLED"
                        self._emit("CANCELLED", "Criação cancelada; resultado tardio descartado.", result.evidence_sha256)
                    else:
                        self._status = "COMPLETED"
                        self._emit("COMPLETED", result.summary, result.evidence_sha256)
            except Exception as error:
                evidence = hashlib.sha256(type(error).__name__.encode("utf-8")).hexdigest()
                with self._lock:
                    status = "CANCELLED" if token.cancelled else "FAILED"
                    self._status = status
                    summary = "Criação cancelada sem publicar resultado." if token.cancelled else "A criação parou com falha recuperável; evidências parciais foram preservadas."
                    self._emit(status, summary, evidence)

        self._thread = threading.Thread(target=run, name=f"casulo-{job_id}", daemon=True)
        self._thread.start()

    def cancel(self) -> bool:
        with self._lock:
            if not self.active or self._token is None:
                return False
            self._token.cancel()
            return True

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _emit(self, status: str, summary: str, evidence_sha256: str) -> None:
        if not _is_evidence_sha256(evidence_sha256):
            raise ValueError("milestone sem SHA-256 de evidência")
        self._sequence += 1
        self._last_summary = summary
        self._on_event(BackgroundJobEvent(str(self._job_id), status, summary, evidence_sha256, self._sequence))


def _validate_payload(kind: UxEventKind, payload: Mapping[str, Any]) -> None:
    forbidden = {"progress_percent", "percentage", "eta", "fake_progress"}
    if forbidden.intersection(payload):
        raise ValueError("progresso UX não pode ser inventado")
    if kind in {UxEventKind.ASSISTANT_START, UxEventKind.ASSISTANT_TOKEN, UxEventKind.ASSISTANT_END}:
        if not str(payload.get("turn_id", "")):
            raise ValueError("evento assistente exige turn_id")
    if kind is UxEventKind.ASSISTANT_TOKEN:
        text = payload.get("text")
        if not isinstance(text, str) or not text or len(text) > 8192:
            raise ValueError("token UX inválido")
        if isinstance(payload.get("sequence"), bool) or int(payload.get("sequence", 0)) < 1:
            raise ValueError("sequência de token UX inválida")
    if kind in _JOB_KINDS:
        if not str(payload.get("job_id", "")) or not str(payload.get("summary", "")).strip():
            raise ValueError("evento de job exige identidade e resumo")
        if not _is_evidence_sha256(str(payload.get("evidence_sha256", ""))):
            raise ValueError("evento de job exige evidência real")
