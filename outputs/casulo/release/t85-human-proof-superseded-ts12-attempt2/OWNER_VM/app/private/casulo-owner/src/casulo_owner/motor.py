from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from casulo.product.creation_pipeline import CreationPipeline
from casulo.product.domain import CreationAggregate, IntentDelta, canonical_sha256
from casulo.product.engine_contracts import (
    CancellationToken,
    EngineEvent,
    EngineEventKind,
    EngineRequest,
    payload_sha256,
)


@dataclass(frozen=True, slots=True)
class AuthorizedIntent:
    delta: IntentDelta
    human_event_id: str
    explicit_human_approval: bool

    def __post_init__(self) -> None:
        if not self.human_event_id or not self.explicit_human_approval:
            raise ValueError("motor owner exige aprovacao humana explicita")


class LocalOwnerMotor:
    """First-party private motor: intent -> T Forge -> committed creation."""

    def __init__(
        self,
        aggregate: CreationAggregate,
        intents: Mapping[str, AuthorizedIntent],
    ) -> None:
        self.aggregate = aggregate
        self.pipeline = CreationPipeline(aggregate)
        self.initial_forge_receipt = self.pipeline.bootstrap()
        self.last_decision = None
        self._intents = dict(intents)

    def register_intent(self, authorization: AuthorizedIntent) -> str:
        digest = canonical_sha256(authorization.delta.to_dict())
        if digest in self._intents:
            raise ValueError("IntentDelta owner ja registrado")
        self._intents[digest] = authorization
        return digest

    def has_intent(self, digest: str) -> bool:
        return digest in self._intents

    def run_direct(
        self,
        request: EngineRequest,
        cancellation: CancellationToken,
    ) -> Iterable[EngineEvent]:
        sequence = 1
        if cancellation.cancelled:
            yield EngineEvent(request.request_id, sequence, EngineEventKind.CANCELLED, "Cancelado antes do motor owner")
            return
        yield EngineEvent(request.request_id, sequence, EngineEventKind.STARTED, "Motor owner direto iniciou")
        sequence += 1
        authorization = self._intents.get(request.intent_delta_sha256)
        if authorization is None:
            yield EngineEvent(request.request_id, sequence, EngineEventKind.FAILED, "IntentDelta autorizado nao encontrado")
            return
        delta = authorization.delta
        if canonical_sha256(delta.to_dict()) != request.intent_delta_sha256:
            yield EngineEvent(request.request_id, sequence, EngineEventKind.FAILED, "Integridade do IntentDelta reprovada")
            return
        if delta.creation_id != request.creation_id or delta.base_version != request.base_version:
            yield EngineEvent(request.request_id, sequence, EngineEventKind.FAILED, "Contrato de versao do IntentDelta reprovado")
            return
        if cancellation.cancelled:
            yield EngineEvent(request.request_id, sequence, EngineEventKind.CANCELLED, "Cancelado antes da compilacao")
            return
        self.pipeline.pending = delta
        try:
            decision = self.pipeline.decide(
                human_event_id=authorization.human_event_id,
                accepted=True,
                explicit_human_approval=authorization.explicit_human_approval,
            )
            self.last_decision = decision
        except Exception as error:
            self.pipeline.pending = None
            yield EngineEvent(
                request.request_id,
                sequence,
                EngineEventKind.FAILED,
                f"Motor owner falhou: {type(error).__name__}",
            )
            return
        assert decision.forge_receipt is not None
        yield EngineEvent(
            request.request_id,
            sequence,
            EngineEventKind.MILESTONE,
            "T Forge recompilou o subgrafo afetado",
            payload_sha256(decision.forge_receipt.to_dict()),
        )
        sequence += 1
        result = {
            "creation_id": decision.creation.creation_id,
            "version": decision.creation.version,
            "creation_sha256": decision.creation.sha256,
            "forge": decision.forge_receipt.to_dict(),
            "engine_boundary": "owner-direct-first-party",
        }
        yield EngineEvent(
            request.request_id,
            sequence,
            EngineEventKind.COMPLETED,
            "Criacao owner atualizada",
            payload_sha256(result),
        )
