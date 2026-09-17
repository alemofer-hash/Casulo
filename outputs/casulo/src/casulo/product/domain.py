from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Iterable, Mapping


CREATION_SCHEMA = "casulo.creation/1.0"
INTENT_DELTA_SCHEMA = "casulo.intent-delta/1.0"
COLLABORATION_SCHEMA = "casulo.collaboration/1.0"
MEMORY_POLICY_SCHEMA = "casulo.memory-policy/1.0"
CAPABILITY_GRANT_SCHEMA = "casulo.capability-grant/1.0"
EVENT_SCHEMA = "casulo.creation-event/1.0"


class DomainError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class CreationState(StrEnum):
    SILENCE = "SILENCE"
    FIRST_INTENT = "FIRST_INTENT"
    LISTENING = "LISTENING"
    FIRST_FORM = "FIRST_FORM"
    CLARIFICATION = "CLARIFICATION"
    CONFIRMATION = "CONFIRMATION"
    PERSONALITY = "PERSONALITY"
    SIMULATION = "SIMULATION"
    INTERRUPTION = "INTERRUPTION"
    CORRECTION = "CORRECTION"
    AGREEMENT = "AGREEMENT"
    MATERIALIZATION = "MATERIALIZATION"


class DeltaConfirmation(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


_ALLOWED_TRANSITIONS: Mapping[CreationState, frozenset[CreationState]] = {
    CreationState.SILENCE: frozenset({CreationState.FIRST_INTENT}),
    CreationState.FIRST_INTENT: frozenset(
        {CreationState.LISTENING, CreationState.FIRST_FORM}
    ),
    CreationState.LISTENING: frozenset(
        {CreationState.FIRST_FORM, CreationState.CLARIFICATION}
    ),
    CreationState.FIRST_FORM: frozenset(
        {CreationState.CLARIFICATION, CreationState.CONFIRMATION}
    ),
    CreationState.CLARIFICATION: frozenset(
        {CreationState.LISTENING, CreationState.FIRST_FORM, CreationState.CONFIRMATION}
    ),
    CreationState.CONFIRMATION: frozenset(
        {CreationState.PERSONALITY, CreationState.SIMULATION, CreationState.INTERRUPTION}
    ),
    CreationState.PERSONALITY: frozenset(
        {CreationState.SIMULATION, CreationState.INTERRUPTION, CreationState.CORRECTION}
    ),
    CreationState.SIMULATION: frozenset(
        {CreationState.INTERRUPTION, CreationState.CORRECTION, CreationState.AGREEMENT}
    ),
    CreationState.INTERRUPTION: frozenset(
        {CreationState.LISTENING, CreationState.CORRECTION}
    ),
    CreationState.CORRECTION: frozenset(
        {CreationState.FIRST_FORM, CreationState.CONFIRMATION, CreationState.SIMULATION}
    ),
    CreationState.AGREEMENT: frozenset(
        {CreationState.CORRECTION, CreationState.MATERIALIZATION}
    ),
    CreationState.MATERIALIZATION: frozenset({CreationState.CORRECTION}),
}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            raise DomainError("P1001", "NaN e infinito não são valores canônicos")
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise DomainError("P1002", "chaves precisam ser texto não vazio")
            result[key] = _json_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_value(item) for item in value)
    if hasattr(value, "to_dict"):
        return _json_value(value.to_dict())
    raise DomainError("P1003", f"valor não serializável: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class CollaborationContract:
    literalness: int = 5
    humor: int = 5
    interruption_tolerance: int = 5
    correction_directness: int = 5
    pressure: int = 0
    initiative: int = 5
    exploration: int = 5
    containment: int = 5
    silence: int = 5
    consented: bool = False
    schema: str = COLLABORATION_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "literalness",
            "humor",
            "interruption_tolerance",
            "correction_directness",
            "pressure",
            "initiative",
            "exploration",
            "containment",
            "silence",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or not 0 <= value <= 10:
                raise DomainError("P1101", f"{name} deve estar entre 0 e 10")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "preferences": {
                "literalness": self.literalness,
                "humor": self.humor,
                "interruption_tolerance": self.interruption_tolerance,
                "correction_directness": self.correction_directness,
                "pressure": self.pressure,
                "initiative": self.initiative,
                "exploration": self.exploration,
                "containment": self.containment,
                "silence": self.silence,
            },
            "consented": self.consented,
        }


@dataclass(frozen=True, slots=True)
class MemoryPolicy:
    retention: str = "until_user_deletes"
    provenance_required: bool = True
    remote_context: str = "ephemeral_opt_in"
    training_with_user_content: bool = False
    schema: str = MEMORY_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.retention not in {"session", "until_user_deletes"}:
            raise DomainError("P1201", "política de retenção desconhecida")
        if self.remote_context not in {"denied", "ephemeral_opt_in"}:
            raise DomainError("P1202", "política de contexto remoto desconhecida")
        if self.training_with_user_content:
            raise DomainError(
                "P1203", "treino com conteúdo do usuário é negado por padrão"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "retention": self.retention,
            "provenance_required": self.provenance_required,
            "remote_context": self.remote_context,
            "training_with_user_content": self.training_with_user_content,
        }


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    capability: str
    granted_by: str
    source_event_id: str
    explicit_human_approval: bool
    schema: str = CAPABILITY_GRANT_SCHEMA

    def __post_init__(self) -> None:
        if not self.capability or "." not in self.capability:
            raise DomainError("P1301", "capability precisa de namespace")
        if self.granted_by != "human" or not self.explicit_human_approval:
            raise DomainError(
                "P1302", "somente aprovação humana explícita pode criar grant"
            )
        if not self.source_event_id:
            raise DomainError("P1303", "grant precisa de evento de origem")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "capability": self.capability,
            "granted_by": self.granted_by,
            "source_event_id": self.source_event_id,
            "explicit_human_approval": self.explicit_human_approval,
        }


@dataclass(frozen=True, slots=True)
class IntentOperation:
    action: str
    path: tuple[str, ...]
    value: Any = None

    def __post_init__(self) -> None:
        if self.action not in {"set", "remove"}:
            raise DomainError("P1401", "operação deve ser set ou remove")
        if not self.path or any(
            not part or part in {".", ".."} or "/" in part for part in self.path
        ):
            raise DomainError("P1402", "caminho de operação inválido")
        if self.path[0] in {"capabilities", "schema", "creation_id", "version"}:
            raise DomainError("P1403", f"delta não pode alterar {self.path[0]}")
        _json_value(self.value)

    def to_dict(self) -> dict[str, Any]:
        result = {"action": self.action, "path": list(self.path)}
        if self.action == "set":
            result["value"] = _json_value(self.value)
        return result


@dataclass(frozen=True, slots=True)
class IntentDelta:
    delta_id: str
    creation_id: str
    base_version: int
    operations: tuple[IntentOperation, ...]
    rationale: str
    source_event_ids: tuple[str, ...]
    confidence: float
    confirmation: DeltaConfirmation
    affected_paths: tuple[tuple[str, ...], ...]
    schema: str = INTENT_DELTA_SCHEMA

    def __post_init__(self) -> None:
        if not self.delta_id or not self.creation_id:
            raise DomainError("P1501", "delta e criação precisam de identidade")
        if self.base_version < 0:
            raise DomainError("P1502", "base_version inválida")
        if not self.operations:
            raise DomainError("P1503", "delta vazio")
        if not self.rationale or not self.source_event_ids:
            raise DomainError("P1504", "delta precisa de motivo e proveniência")
        if not 0.0 <= self.confidence <= 1.0:
            raise DomainError("P1505", "confidence deve estar entre 0 e 1")
        actual = tuple(operation.path for operation in self.operations)
        if tuple(self.affected_paths) != actual:
            raise DomainError("P1506", "affected_paths diverge das operações")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "delta_id": self.delta_id,
            "creation_id": self.creation_id,
            "base_version": self.base_version,
            "operations": [operation.to_dict() for operation in self.operations],
            "rationale": self.rationale,
            "source_event_ids": list(self.source_event_ids),
            "confidence": self.confidence,
            "confirmation_state": self.confirmation.value,
            "affected_paths": [list(path) for path in self.affected_paths],
        }


@dataclass(frozen=True, slots=True)
class CreationSpec:
    creation_id: str
    version: int = 0
    state: CreationState = CreationState.SILENCE
    content: Mapping[str, Any] = field(default_factory=dict)
    capabilities: frozenset[str] = field(default_factory=frozenset)
    rejected_delta_ids: tuple[str, ...] = ()
    schema: str = CREATION_SCHEMA

    def __post_init__(self) -> None:
        if not self.creation_id:
            raise DomainError("P1601", "criação precisa de identidade")
        if self.version < 0:
            raise DomainError("P1602", "versão inválida")
        normalized = _json_value(dict(self.content))
        object.__setattr__(self, "content", MappingProxyType(normalized))
        for capability in self.capabilities:
            if "." not in capability:
                raise DomainError("P1603", "capability sem namespace")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "creation_id": self.creation_id,
            "version": self.version,
            "state": self.state.value,
            "content": copy.deepcopy(dict(self.content)),
            "capabilities": sorted(self.capabilities),
            "rejected_delta_ids": list(self.rejected_delta_ids),
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class CreationEvent:
    event_id: str
    kind: str
    base_version: int
    resulting_version: int
    source_ids: tuple[str, ...]
    payload_sha256: str
    previous_event_sha256: str | None
    schema: str = EVENT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "kind": self.kind,
            "base_version": self.base_version,
            "resulting_version": self.resulting_version,
            "source_ids": list(self.source_ids),
            "payload_sha256": self.payload_sha256,
            "previous_event_sha256": self.previous_event_sha256,
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())


class CreationAggregate:
    def __init__(self, initial: CreationSpec) -> None:
        self._snapshots: list[CreationSpec] = [initial]
        self._events: list[CreationEvent] = []

    @property
    def current(self) -> CreationSpec:
        return self._snapshots[-1]

    @property
    def events(self) -> tuple[CreationEvent, ...]:
        return tuple(self._events)

    def rehydrate(self, version: int) -> CreationSpec:
        if version < 0 or version >= len(self._snapshots):
            raise DomainError("P1701", f"versão inexistente: {version}")
        return self._snapshots[version]

    def apply_delta(self, delta: IntentDelta) -> CreationSpec:
        current = self.current
        if delta.creation_id != current.creation_id:
            raise DomainError("P1702", "delta pertence a outra criação")
        if delta.base_version != current.version:
            raise DomainError("P1703", "conflito de base_version")
        if delta.confirmation is not DeltaConfirmation.CONFIRMED:
            if delta.confirmation is DeltaConfirmation.REJECTED:
                rejected = CreationSpec(
                    creation_id=current.creation_id,
                    version=current.version + 1,
                    state=current.state,
                    content=current.content,
                    capabilities=current.capabilities,
                    rejected_delta_ids=(*current.rejected_delta_ids, delta.delta_id),
                )
                return self._append(
                    rejected,
                    kind="DELTA_REJECTED",
                    event_id=f"event:{delta.delta_id}",
                    source_ids=delta.source_event_ids,
                    payload=delta.to_dict(),
                )
            raise DomainError("P1704", "somente delta confirmado altera estado")
        content = copy.deepcopy(dict(current.content))
        for operation in delta.operations:
            _apply_operation(content, operation)
        updated = CreationSpec(
            creation_id=current.creation_id,
            version=current.version + 1,
            state=current.state,
            content=content,
            capabilities=current.capabilities,
            rejected_delta_ids=current.rejected_delta_ids,
        )
        return self._append(
            updated,
            kind="INTENT_DELTA_APPLIED",
            event_id=f"event:{delta.delta_id}",
            source_ids=delta.source_event_ids,
            payload=delta.to_dict(),
        )

    def transition(self, target: CreationState, source_event_id: str) -> CreationSpec:
        current = self.current
        if target not in _ALLOWED_TRANSITIONS[current.state]:
            raise DomainError(
                "P1705", f"transição inválida: {current.state.value} -> {target.value}"
            )
        updated = CreationSpec(
            creation_id=current.creation_id,
            version=current.version + 1,
            state=target,
            content=current.content,
            capabilities=current.capabilities,
            rejected_delta_ids=current.rejected_delta_ids,
        )
        return self._append(
            updated,
            kind="STATE_TRANSITION",
            event_id=f"event:state:{updated.version}",
            source_ids=(source_event_id,),
            payload={"from": current.state.value, "to": target.value},
        )

    def grant(self, grant: CapabilityGrant) -> CreationSpec:
        current = self.current
        updated = CreationSpec(
            creation_id=current.creation_id,
            version=current.version + 1,
            state=current.state,
            content=current.content,
            capabilities=frozenset((*current.capabilities, grant.capability)),
            rejected_delta_ids=current.rejected_delta_ids,
        )
        return self._append(
            updated,
            kind="CAPABILITY_GRANTED",
            event_id=f"event:grant:{updated.version}",
            source_ids=(grant.source_event_id,),
            payload=grant.to_dict(),
        )

    def revoke(self, capability: str, source_event_id: str) -> CreationSpec:
        current = self.current
        updated = CreationSpec(
            creation_id=current.creation_id,
            version=current.version + 1,
            state=current.state,
            content=current.content,
            capabilities=frozenset(
                item for item in current.capabilities if item != capability
            ),
            rejected_delta_ids=current.rejected_delta_ids,
        )
        return self._append(
            updated,
            kind="CAPABILITY_REVOKED",
            event_id=f"event:revoke:{updated.version}",
            source_ids=(source_event_id,),
            payload={"capability": capability},
        )

    def _append(
        self,
        snapshot: CreationSpec,
        *,
        kind: str,
        event_id: str,
        source_ids: Iterable[str],
        payload: Any,
    ) -> CreationSpec:
        current = self.current
        if snapshot.version != current.version + 1:
            raise DomainError("P1706", "eventos precisam avançar uma versão")
        previous = self._events[-1].sha256 if self._events else None
        event = CreationEvent(
            event_id=event_id,
            kind=kind,
            base_version=current.version,
            resulting_version=snapshot.version,
            source_ids=tuple(source_ids),
            payload_sha256=canonical_sha256(payload),
            previous_event_sha256=previous,
        )
        self._events.append(event)
        self._snapshots.append(snapshot)
        return snapshot


def _apply_operation(document: dict[str, Any], operation: IntentOperation) -> None:
    cursor = document
    for part in operation.path[:-1]:
        child = cursor.get(part)
        if child is None:
            child = {}
            cursor[part] = child
        if not isinstance(child, dict):
            raise DomainError("P1801", "delta atravessa valor não estruturado")
        cursor = child
    leaf = operation.path[-1]
    if operation.action == "set":
        cursor[leaf] = _json_value(operation.value)
    elif leaf in cursor:
        del cursor[leaf]


def creation_spec_from_document(document: Mapping[str, Any]) -> CreationSpec:
    """Validate/migrate a serialized creation before exposing a typed value."""

    try:
        migrated = migrate_creation_document(document)
        return CreationSpec(
            creation_id=migrated["creation_id"],
            version=int(migrated["version"]),
            state=CreationState(migrated["state"]),
            content=migrated.get("content", {}),
            capabilities=frozenset(migrated.get("capabilities", [])),
            rejected_delta_ids=tuple(migrated.get("rejected_delta_ids", [])),
        )
    except DomainError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise DomainError("P1902", "documento de criacao incompleto ou mal tipado") from error


def migrate_creation_document(document: Mapping[str, Any]) -> dict[str, Any]:
    raw = copy.deepcopy(dict(document))
    schema = raw.get("schema")
    if schema == CREATION_SCHEMA:
        CreationSpec(
            creation_id=raw["creation_id"],
            version=int(raw["version"]),
            state=CreationState(raw["state"]),
            content=raw.get("content", {}),
            capabilities=frozenset(raw.get("capabilities", [])),
            rejected_delta_ids=tuple(raw.get("rejected_delta_ids", [])),
        )
        return raw
    if schema == "casulo.creation/0.1":
        migrated = {
            "schema": CREATION_SCHEMA,
            "creation_id": raw["id"],
            "version": int(raw.get("revision", 0)),
            "state": raw.get("phase", "SILENCE"),
            "content": {
                "name": raw.get("title", "Sem título"),
                **copy.deepcopy(raw.get("content", {})),
            },
            "capabilities": sorted(set(raw.get("capabilities", []))),
            "rejected_delta_ids": list(raw.get("rejected", [])),
        }
        return migrate_creation_document(migrated)
    raise DomainError("P1901", f"schema de criação não suportado: {schema!r}")
