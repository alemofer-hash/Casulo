from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class CapabilityDenied(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class Effect(StrEnum):
    PURE = "pure"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    AUDIO_CAPTURE = "audio.capture"
    AUDIO_PLAY = "audio.play"
    MODEL_INFER = "model.infer"
    NETWORK_CONNECT = "network.connect"
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    PROCESS_SPAWN = "process.spawn"
    SECRET_READ = "secret.read"
    HUMAN_APPROVAL = "human.approval"
    MANIFEST = "manifest"
    CATALOG_READ = "catalog.read"
    CATALOG_REBUILD = "catalog.rebuild"
    UNIVERSE_INSPECT = "universe.inspect"
    UNIVERSE_WARM = "universe.warm"
    UNIVERSE_ACTIVATE = "universe.activate"
    UNIVERSE_QUIESCE = "universe.quiesce"
    UNIVERSE_CRYSTALLIZE = "universe.crystallize"
    TRANSITION_EXECUTE = "transition.execute"
    INDEX_QUERY = "index.query"
    INDEX_UPDATE = "index.update"
    BLOB_READ = "blob.read"
    BLOB_STAGE = "blob.stage"
    BLOB_PUBLISH = "blob.publish"
    GC_PLAN = "gc.plan"
    QUANTUM_SIMULATE = "quantum.simulate"
    QUANTUM_QPU_SUBMIT = "quantum.qpu.submit"


SENSITIVE_EFFECTS = frozenset(
    {
        Effect.NETWORK_CONNECT,
        Effect.FILESYSTEM_WRITE,
        Effect.PROCESS_SPAWN,
        Effect.SECRET_READ,
    }
)


@dataclass(frozen=True, slots=True)
class EffectRequest:
    request_id: str
    creation_id: str
    effect: Effect
    action_sha256: str
    declared: bool

    def __post_init__(self) -> None:
        if not self.request_id or not self.creation_id:
            raise ValueError("effect request sem identidade")
        if len(self.action_sha256) != 64:
            raise ValueError("effect request sem action SHA-256")


@dataclass(frozen=True, slots=True)
class ApprovalToken:
    creation_id: str
    effect: Effect
    action_sha256: str
    source_event_id: str
    one_shot: bool = True


class CapabilityBroker:
    """Autoridade runtime fora de qualquer modelo generativo."""

    def __init__(self, grants: Mapping[str, frozenset[Effect]] | None = None) -> None:
        self._grants = dict(grants or {})
        self._consumed: set[tuple[str, str, str]] = set()

    def authorize(
        self,
        request: EffectRequest,
        approval: ApprovalToken | None = None,
    ) -> None:
        if request.effect is Effect.QUANTUM_QPU_SUBMIT:
            raise CapabilityDenied("CAP106", "QPU indisponível e deny-by-default neste perfil")
        if request.effect is Effect.PURE:
            if not request.declared:
                raise CapabilityDenied("CAP100", "effect pure não declarado")
            return
        if not request.declared:
            raise CapabilityDenied("CAP101", "effect não declarado pelo artefato")
        if request.effect not in self._grants.get(request.creation_id, frozenset()):
            raise CapabilityDenied("CAP102", "capability não concedida")
        if request.effect in SENSITIVE_EFFECTS:
            self._consume_approval(request, approval)

    def _consume_approval(
        self, request: EffectRequest, approval: ApprovalToken | None
    ) -> None:
        if approval is None:
            raise CapabilityDenied("CAP103", "aprovação humana ausente")
        if (
            approval.creation_id != request.creation_id
            or approval.effect is not request.effect
            or approval.action_sha256 != request.action_sha256
            or not approval.source_event_id
        ):
            raise CapabilityDenied("CAP104", "aprovação não corresponde à ação")
        identity = (
            approval.creation_id,
            approval.effect.value,
            approval.action_sha256,
        )
        if approval.one_shot and identity in self._consumed:
            raise CapabilityDenied("CAP105", "aprovação one-shot já consumida")
        if approval.one_shot:
            self._consumed.add(identity)
