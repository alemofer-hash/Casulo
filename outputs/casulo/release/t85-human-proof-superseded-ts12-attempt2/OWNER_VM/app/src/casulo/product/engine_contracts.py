from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Protocol, runtime_checkable


ENGINE_PROTOCOL = "casulo-engine/1.0"


class EngineError(RuntimeError):
    pass


class EngineEventKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    STARTED = "STARTED"
    TOKEN = "TOKEN"
    MILESTONE = "MILESTONE"
    READY_FOR_PREVIEW = "READY_FOR_PREVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class EngineRequest:
    request_id: str
    creation_id: str
    base_version: int
    intent_delta_sha256: str
    context_refs: tuple[str, ...] = ()
    protocol: str = ENGINE_PROTOCOL

    def __post_init__(self) -> None:
        if not self.request_id or not self.creation_id or self.base_version < 0:
            raise EngineError("request inválido")
        if len(self.intent_delta_sha256) != 64:
            raise EngineError("request precisa do SHA-256 do IntentDelta")


@dataclass(frozen=True, slots=True)
class EngineEvent:
    request_id: str
    sequence: int
    kind: EngineEventKind
    message: str
    payload_sha256: str | None = None
    protocol: str = ENGINE_PROTOCOL

    def __post_init__(self) -> None:
        if not self.request_id or self.sequence < 1 or not self.message:
            raise EngineError("evento de engine inválido")
        if self.payload_sha256 is not None and len(self.payload_sha256) != 64:
            raise EngineError("payload_sha256 inválido")


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@runtime_checkable
class CasuloEngine(Protocol):
    def execute(
        self, request: EngineRequest, cancellation: CancellationToken
    ) -> Iterable[EngineEvent]: ...


def payload_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_event_stream(request: EngineRequest, events: Iterable[EngineEvent]) -> tuple[EngineEvent, ...]:
    materialized = tuple(events)
    if not materialized:
        raise EngineError("engine não emitiu eventos")
    expected = 1
    terminal = 0
    for event in materialized:
        if event.request_id != request.request_id or event.sequence != expected:
            raise EngineError("stream fora de ordem ou de outro request")
        expected += 1
        if event.kind in {
            EngineEventKind.COMPLETED,
            EngineEventKind.CANCELLED,
            EngineEventKind.FAILED,
        }:
            terminal += 1
    if terminal != 1 or materialized[-1].kind not in {
        EngineEventKind.COMPLETED,
        EngineEventKind.CANCELLED,
        EngineEventKind.FAILED,
    }:
        raise EngineError("stream precisa de um único evento terminal ao final")
    return materialized
