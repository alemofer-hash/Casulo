from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from casulo.product.engine_contracts import (
    CancellationToken,
    CasuloEngine,
    EngineEvent,
    EngineRequest,
    validate_event_stream,
)


@runtime_checkable
class OwnerMotor(Protocol):
    """Contrato privado do motor controlado por Guilherme Moura Fernandes."""

    def run_direct(
        self, request: EngineRequest, cancellation: CancellationToken
    ) -> Iterable[EngineEvent]: ...


class OwnerEngineAdapter(CasuloEngine):
    """Adapter direto: não contém cliente Cloud nem fallback de terceiros."""

    def __init__(self, motor: OwnerMotor) -> None:
        self._motor = motor

    def execute(
        self, request: EngineRequest, cancellation: CancellationToken
    ) -> tuple[EngineEvent, ...]:
        return validate_event_stream(
            request, self._motor.run_direct(request, cancellation)
        )
