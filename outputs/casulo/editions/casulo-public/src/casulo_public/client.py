from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from casulo.product.engine_contracts import (
    CancellationToken,
    CasuloEngine,
    EngineEvent,
    EngineRequest,
    validate_event_stream,
)


class PublicCloudUnavailable(RuntimeError):
    pass


@runtime_checkable
class CloudTransport(Protocol):
    def submit(
        self, request: EngineRequest, cancellation: CancellationToken
    ) -> Iterable[EngineEvent]: ...


class CloudEngineClient(CasuloEngine):
    """Única ligação de engine autorizada no cliente mundial."""

    def __init__(self, transport: CloudTransport | None = None) -> None:
        self._transport = transport

    def execute(
        self, request: EngineRequest, cancellation: CancellationToken
    ) -> tuple[EngineEvent, ...]:
        if self._transport is None:
            raise PublicCloudUnavailable(
                "Casulo Cloud indisponível; nenhuma geração local owner ou de terceiro foi usada."
            )
        return validate_event_stream(
            request, self._transport.submit(request, cancellation)
        )
