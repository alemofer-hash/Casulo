from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from .contracts import ChatRequest, FamilyResourceError, FamilyUnavailableError


class FamilyEngine(Protocol):
    mock_only: bool

    def generate(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]: ...


class SupervisorState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SupervisorTransition:
    sequence: int
    previous: SupervisorState
    current: SupervisorState
    reason_code: str
    timestamp_utc: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "previous": self.previous.value,
            "current": self.current.value,
            "reason_code": self.reason_code,
            "timestamp_utc": self.timestamp_utc,
        }


@dataclass(slots=True)
class DeterministicMockEngine:
    delay_seconds: float = 0.0
    mock_only: bool = True

    def generate(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]:
        chunks = ("[MOCK LOCAL] ", f"Resposta para: {request.message}")
        for chunk in chunks:
            if cancelled():
                return
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            if cancelled():
                return
            yield chunk


class FamilySupervisor:
    _ALLOWED = {
        SupervisorState.STOPPED: {SupervisorState.STARTING},
        SupervisorState.STARTING: {SupervisorState.READY, SupervisorState.FAILED},
        SupervisorState.READY: {
            SupervisorState.BUSY,
            SupervisorState.DRAINING,
            SupervisorState.FAILED,
        },
        SupervisorState.BUSY: {
            SupervisorState.DRAINING,
            SupervisorState.DEGRADED,
            SupervisorState.FAILED,
        },
        SupervisorState.DRAINING: {
            SupervisorState.READY,
            SupervisorState.STOPPED,
            SupervisorState.FAILED,
        },
        SupervisorState.DEGRADED: {
            SupervisorState.READY,
            SupervisorState.DRAINING,
            SupervisorState.FAILED,
        },
        SupervisorState.FAILED: {
            SupervisorState.STARTING,
            SupervisorState.DRAINING,
        },
    }

    def __init__(
        self,
        engine: FamilyEngine,
        *,
        minimum_available_ram_bytes: int = 1_024**3,
        minimum_disk_free_bytes: int = 30 * 1_024**3,
    ) -> None:
        self.engine = engine
        self.minimum_available_ram_bytes = minimum_available_ram_bytes
        self.minimum_disk_free_bytes = minimum_disk_free_bytes
        self._lock = threading.RLock()
        self._state = SupervisorState.STOPPED
        self._transitions: list[SupervisorTransition] = []
        self._active_generations = 0
        self._maximum_active_generations = 0
        self._last_error_code: str | None = None

    @property
    def state(self) -> SupervisorState:
        with self._lock:
            return self._state

    @property
    def ready(self) -> bool:
        return self.state in {SupervisorState.READY, SupervisorState.BUSY}

    @property
    def active_generations(self) -> int:
        with self._lock:
            return self._active_generations

    @property
    def transitions(self) -> tuple[SupervisorTransition, ...]:
        with self._lock:
            return tuple(self._transitions)

    def start(self) -> bool:
        with self._lock:
            if self._state in {SupervisorState.READY, SupervisorState.BUSY}:
                return True
            if self._state not in {SupervisorState.STOPPED, SupervisorState.FAILED}:
                return False
            self._transition(SupervisorState.STARTING, "START_REQUESTED")
        try:
            starter = getattr(self.engine, "start", None)
            if callable(starter):
                starter()
            checker = getattr(self.engine, "is_ready", None)
            if callable(checker) and not bool(checker()):
                raise FamilyUnavailableError("adapter não ficou pronto")
        except Exception:
            with self._lock:
                self._last_error_code = "ENGINE_START_FAILED"
                self._transition(SupervisorState.FAILED, self._last_error_code)
            return False
        with self._lock:
            self._last_error_code = None
            self._transition(SupervisorState.READY, "ENGINE_READY")
        return True

    def stop(self) -> None:
        with self._lock:
            if self._state == SupervisorState.STOPPED:
                return
            if self._state not in {
                SupervisorState.READY,
                SupervisorState.DEGRADED,
                SupervisorState.FAILED,
            }:
                raise FamilyUnavailableError("supervisor não pode parar neste estado")
            self._transition(SupervisorState.DRAINING, "STOP_REQUESTED")
        try:
            stopper = getattr(self.engine, "stop", None) or getattr(
                self.engine, "close", None
            )
            if callable(stopper):
                stopper()
        except Exception:
            with self._lock:
                self._last_error_code = "ENGINE_STOP_FAILED"
                self._transition(SupervisorState.FAILED, self._last_error_code)
            raise
        with self._lock:
            self._transition(SupervisorState.STOPPED, "ENGINE_STOPPED")

    def admission_sample(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
        if state not in {SupervisorState.READY, SupervisorState.BUSY}:
            raise FamilyUnavailableError(f"supervisor indisponível: {state.value}")
        diagnostics = self._engine_diagnostics()
        ram = diagnostics.get("available_ram_bytes")
        disk = diagnostics.get("disk_free_bytes")
        if not self.engine.mock_only and not isinstance(ram, int):
            raise FamilyResourceError("RAM disponível não pôde ser medida")
        if not self.engine.mock_only and not isinstance(disk, int):
            raise FamilyResourceError("disco livre não pôde ser medido")
        if isinstance(ram, int) and ram < self.minimum_available_ram_bytes:
            raise FamilyResourceError("piso de RAM de 1 GiB não preservado")
        if isinstance(disk, int) and disk < self.minimum_disk_free_bytes:
            raise FamilyResourceError("reserva de disco de 30 GiB não preservada")
        return diagnostics

    def respond(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]:
        with self._lock:
            if self._state != SupervisorState.READY:
                raise FamilyUnavailableError(
                    f"supervisor não aceita geração em {self._state.value}"
                )
            self._transition(SupervisorState.BUSY, "GENERATION_STARTED")
            self._active_generations += 1
            self._maximum_active_generations = max(
                self._maximum_active_generations, self._active_generations
            )
            if self._active_generations != 1:
                self._active_generations -= 1
                self._transition(SupervisorState.FAILED, "CONCURRENCY_INVARIANT")
                raise FamilyUnavailableError("mais de uma geração ativa")
        try:
            yield from self.engine.generate(request, cancelled)
        except Exception:
            if cancelled():
                with self._lock:
                    self._active_generations -= 1
                    self._transition(
                        SupervisorState.DRAINING, "GENERATION_CANCELLED"
                    )
                    self._transition(
                        SupervisorState.READY, "GENERATION_SLOT_RELEASED"
                    )
                return
            with self._lock:
                self._active_generations -= 1
                self._last_error_code = "ENGINE_STREAM_FAILED"
                self._transition(SupervisorState.DEGRADED, self._last_error_code)
            recovered = False
            recover = getattr(self.engine, "recover", None)
            try:
                recovered = bool(recover()) if callable(recover) else True
            except Exception:
                recovered = False
            with self._lock:
                if recovered:
                    self._transition(SupervisorState.READY, "ENGINE_RECOVERED")
                else:
                    self._transition(SupervisorState.FAILED, "ENGINE_RECOVERY_FAILED")
            raise
        finally:
            with self._lock:
                if (
                    self._state == SupervisorState.BUSY
                    and self._active_generations == 1
                ):
                    self._active_generations -= 1
                    self._transition(SupervisorState.DRAINING, "GENERATION_DRAINED")
                    self._transition(
                        SupervisorState.READY, "GENERATION_SLOT_RELEASED"
                    )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {
                "state": self._state.value,
                "ready": self._state in {SupervisorState.READY, SupervisorState.BUSY},
                "active_generations": self._active_generations,
                "maximum_active_generations": self._maximum_active_generations,
                "last_error_code": self._last_error_code,
                "mock_engine": bool(self.engine.mock_only),
                "transition_count": len(self._transitions),
            }
        result.update(self._engine_diagnostics())
        return result

    def _engine_diagnostics(self) -> dict[str, Any]:
        probe = getattr(self.engine, "diagnostics", None)
        if not callable(probe):
            return {}
        value = probe()
        return dict(value) if isinstance(value, Mapping) else {}

    def _transition(self, current: SupervisorState, reason_code: str) -> None:
        previous = self._state
        if current not in self._ALLOWED[previous]:
            raise FamilyUnavailableError(
                f"transição inválida: {previous.value}->{current.value}"
            )
        self._state = current
        self._transitions.append(
            SupervisorTransition(
                sequence=len(self._transitions) + 1,
                previous=previous,
                current=current,
                reason_code=reason_code,
                timestamp_utc=datetime.now(UTC).isoformat(),
            )
        )
