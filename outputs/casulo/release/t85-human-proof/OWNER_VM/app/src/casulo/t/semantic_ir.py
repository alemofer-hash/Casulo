from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .resource import ResourceContract, SemanticClass
from .tcap import TcapSegment, build_tcap, canonical_json, parse_tcap


SEMANTIC_IR_SCHEMA = "casulo.t-semantic-ir/1.0"
SEMANTIC_TCAP_ABI = "casulo-semantic-ir/1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")

SEMANTIC_EFFECTS = frozenset(
    {
        "catalog.read",
        "catalog.rebuild",
        "universe.inspect",
        "universe.warm",
        "universe.activate",
        "universe.quiesce",
        "universe.crystallize",
        "transition.execute",
        "index.query",
        "index.update",
        "blob.read",
        "blob.stage",
        "blob.publish",
        "gc.plan",
    }
)
DENIED_PRODUCT_EFFECTS = frozenset(
    {
        "network.connect",
        "cloud.casulo.connect",
        "block_device.write",
        "quantum.qpu.submit",
    }
)


class SemanticIRError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class DurationMs:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 0:
            raise SemanticIRError("TSM200", "DurationMs precisa ser inteiro não negativo")


@dataclass(frozen=True, slots=True)
class Bytes:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 0:
            raise SemanticIRError("TSM201", "Bytes precisa ser inteiro não negativo")


@dataclass(frozen=True, slots=True)
class RiskScore:
    value: float

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not 0 <= self.value <= 1:
            raise SemanticIRError("TSM202", "RiskScore precisa estar entre 0 e 1")


@dataclass(frozen=True, slots=True)
class FidelityBound:
    value: float

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not 0 <= self.value <= 1:
            raise SemanticIRError("TSM203", "FidelityBound precisa estar entre 0 e 1")


@dataclass(frozen=True, slots=True)
class BudgetConstraint:
    latency: DurationMs
    memory: Bytes
    transfer: Bytes
    semantic_risk: RiskScore
    fidelity: FidelityBound


@dataclass(frozen=True, slots=True)
class UniverseDecl:
    universe_id: str
    version: int
    content_hash: str
    semantic_address: tuple[str, ...]
    invariants: tuple[str, ...]
    capabilities: tuple[str, ...]
    neighbors: tuple[str, ...]
    resolution_levels: tuple[str, ...]
    activation_memory_bytes: int


@dataclass(frozen=True, slots=True)
class ProjectionDecl:
    projection_id: str
    required_fields: tuple[str, ...]
    fallback: str


@dataclass(frozen=True, slots=True)
class TransitionDecl:
    transition_id: str
    source: str
    destination: str
    input_contract: str
    output_contract: str
    projection: ProjectionDecl
    preserved_invariants: tuple[str, ...]
    required_effects: tuple[str, ...]
    budget: BudgetConstraint


@dataclass(frozen=True, slots=True)
class SemanticIRProgram:
    universes: tuple[UniverseDecl, ...]
    transitions: tuple[TransitionDecl, ...]
    effects: tuple[str, ...]
    impact_graph: tuple[tuple[str, tuple[str, ...]], ...]
    schema: str = SEMANTIC_IR_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["impact_graph"] = {key: list(value) for key, value in self.impact_graph}
        return payload

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict())).hexdigest()


class SemanticLowerer:
    """Lowering data-driven para Semantic IR; não adiciona sintaxe T implícita."""

    def lower(
        self,
        manifests: Iterable[Mapping[str, Any]],
        transitions: Iterable[Mapping[str, Any]],
    ) -> SemanticIRProgram:
        universes = tuple(self._universe(item) for item in manifests)
        by_id = {item.universe_id: item for item in universes}
        if not universes or len(by_id) != len(universes):
            raise SemanticIRError("TSM001", "universos vazios ou duplicados")
        lowered_transitions = tuple(self._transition(item, by_id) for item in transitions)
        transition_ids = {item.transition_id for item in lowered_transitions}
        if len(transition_ids) != len(lowered_transitions):
            raise SemanticIRError("TSM002", "transition_id duplicado")
        effects = tuple(sorted({effect for item in lowered_transitions for effect in item.required_effects}))
        impact: dict[str, set[str]] = {item.universe_id: set() for item in universes}
        for transition in lowered_transitions:
            impact[transition.source].add(transition.transition_id)
            impact[transition.destination].add(transition.transition_id)
        return SemanticIRProgram(
            universes,
            lowered_transitions,
            effects,
            tuple((key, tuple(sorted(value))) for key, value in sorted(impact.items())),
        )

    @staticmethod
    def _universe(value: Mapping[str, Any]) -> UniverseDecl:
        universe_id = str(value.get("universe_id", ""))
        content_hash = str(value.get("content_hash", ""))
        if not _ID.fullmatch(universe_id):
            raise SemanticIRError("TSM010", "universe_id inválido")
        if not _SHA256.fullmatch(content_hash):
            raise SemanticIRError("TSM011", f"content_hash inválido em {universe_id}")
        version = value.get("version")
        if type(version) is not int or version < 1:
            raise SemanticIRError("TSM012", f"version inválida em {universe_id}")
        activation = value.get("activation_profile")
        if not isinstance(activation, Mapping):
            raise SemanticIRError("TSM013", f"activation_profile ausente em {universe_id}")
        memory = activation.get("memory_bytes")
        if type(memory) is not int or not 4096 <= memory <= 1 << 34:
            raise SemanticIRError("TSM014", f"memory_bytes inválido em {universe_id}")
        return UniverseDecl(
            universe_id,
            version,
            content_hash,
            _texts(value.get("semantic_address"), "semantic_address"),
            _texts(value.get("invariants"), "invariants"),
            _texts(value.get("capabilities"), "capabilities", allow_empty=True),
            _texts(value.get("neighbors"), "neighbors", allow_empty=True),
            _texts(value.get("resolution_levels"), "resolution_levels"),
            memory,
        )

    @staticmethod
    def _transition(value: Mapping[str, Any], by_id: Mapping[str, UniverseDecl]) -> TransitionDecl:
        transition_id = str(value.get("transition_id", ""))
        source, destination = str(value.get("source", "")), str(value.get("destination", ""))
        if not _ID.fullmatch(transition_id) or source not in by_id or destination not in by_id or source == destination:
            raise SemanticIRError("TSM020", "identidade ou endpoints de transição inválidos")
        effects = _texts(value.get("required_effects"), "required_effects")
        if set(effects) - SEMANTIC_EFFECTS or set(effects) & DENIED_PRODUCT_EFFECTS:
            raise SemanticIRError("TSM021", "transição contém effect desconhecido ou negado")
        source_caps = set(by_id[source].capabilities)
        destination_caps = set(by_id[destination].capabilities)
        if destination_caps - source_caps:
            raise SemanticIRError("TSM022", "transição ampliaria capabilities")
        preserved = _texts(value.get("preserved_invariants"), "preserved_invariants")
        global_required = set(by_id[source].invariants) & set(by_id[destination].invariants)
        if not global_required <= set(preserved):
            raise SemanticIRError("TSM023", "transição não preserva invariantes comuns")
        projection_raw = value.get("projection")
        budget_raw = value.get("budget")
        if not isinstance(projection_raw, Mapping) or not isinstance(budget_raw, Mapping):
            raise SemanticIRError("TSM024", "projection ou budget ausente")
        projection = ProjectionDecl(
            str(projection_raw.get("projection_id", "")),
            _texts(projection_raw.get("required_fields"), "required_fields"),
            str(projection_raw.get("fallback", "")),
        )
        if not _ID.fullmatch(projection.projection_id) or not projection.fallback:
            raise SemanticIRError("TSM025", "projection inválida")
        budget = BudgetConstraint(
            DurationMs(_strict_int(budget_raw.get("latency_ms"), "latency_ms")),
            Bytes(_strict_int(budget_raw.get("memory_bytes"), "memory_bytes")),
            Bytes(_strict_int(budget_raw.get("transfer_bytes"), "transfer_bytes")),
            RiskScore(_strict_number(budget_raw.get("semantic_risk"), "semantic_risk")),
            FidelityBound(_strict_number(budget_raw.get("fidelity"), "fidelity")),
        )
        return TransitionDecl(
            transition_id,
            source,
            destination,
            str(value.get("input_contract", "")),
            str(value.get("output_contract", "")),
            projection,
            preserved,
            effects,
            budget,
        )


def build_semantic_tcap(program: SemanticIRProgram) -> bytes:
    payload = canonical_json(program.to_dict())
    resource = ResourceContract(
        memory_limit_bytes=max(4096, sum(item.activation_memory_bytes for item in program.universes)),
        arena_bytes=0,
        max_threads=1,
        semantic_class=SemanticClass.SYSTEM,
        deterministic=True,
        numerical_precision="integer",
        permissions=("memory", "telemetry"),
        quality_definition={"semantic_ir_sha256": program.sha256, "operational_equivalence": "scoped"},
        residual_routing={"invalid": "quarantine", "insufficient": "full-safe-projection"},
    )
    raw = build_tcap(
        segments=(
            TcapSegment("semantic.entry", b"SMIR\x01", "rx"),
            TcapSegment("semantic.ir.json", payload, "r"),
        ),
        target="casulo-semantic-runtime",
        abi=SEMANTIC_TCAP_ABI,
        entry_segment="semantic.entry",
        entry_offset=0,
        compiler={"name": "Casulo T Semantic Lowerer", "version": "1.0", "commit": "worktree"},
        resource_contract=resource,
        capability_requirements=program.effects,
    )
    parse_tcap(raw)
    return raw


def invalidation_closure(program: SemanticIRProgram, changed_universe: str) -> tuple[str, ...]:
    if changed_universe not in {item.universe_id for item in program.universes}:
        raise SemanticIRError("TSM030", "universo alterado não existe")
    impact = dict(program.impact_graph)
    return (changed_universe, *impact[changed_universe])


def _texts(value: Any, name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or (not value and not allow_empty):
        raise SemanticIRError("TSM090", f"{name} precisa ser lista textual")
    result = tuple(str(item).strip() for item in value)
    if any(not item for item in result) or len(set(result)) != len(result):
        raise SemanticIRError("TSM091", f"{name} possui item vazio ou duplicado")
    return result


def _strict_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise SemanticIRError("TSM092", f"{name} precisa ser inteiro não negativo")
    return value


def _strict_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SemanticIRError("TSM093", f"{name} precisa ser número")
    return float(value)
