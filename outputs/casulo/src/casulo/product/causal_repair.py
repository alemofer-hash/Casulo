from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .domain import DomainError, canonical_sha256
from .intent_reconstruction import IntentEvidenceKind, IntentTwin
from .revolution_contracts import RequirementStrength
from .t_forge import ForgeReceipt, ForgeUnit


class CausalRepairError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


def _paths_intersect(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    common = min(len(left), len(right))
    return left[:common] == right[:common]


@dataclass(frozen=True, slots=True)
class RequirementSemanticBinding:
    requirement_id: str
    strength: RequirementStrength
    semantic_paths: tuple[tuple[str, ...], ...]
    unit_ids: tuple[str, ...]
    verifier_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.semantic_paths:
            raise CausalRepairError("CR101", "binding exige requisito e caminho semântico")
        if any(not path or any(not part for part in path) for path in self.semantic_paths):
            raise CausalRepairError("CR102", "binding contém caminho semântico inválido")
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise CausalRepairError("CR103", "binding contém unidade duplicada")
        if not self.verifier_ids or not self.source_event_ids:
            raise CausalRepairError("CR104", "binding exige verifier e proveniência")
        if self.strength is RequirementStrength.HARD and not self.unit_ids:
            raise CausalRepairError("CR105", "requisito HARD não alcança nenhuma unidade T")

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "strength": self.strength.value,
            "semantic_paths": [list(path) for path in self.semantic_paths],
            "unit_ids": list(self.unit_ids),
            "verifier_ids": list(self.verifier_ids),
            "source_event_ids": list(self.source_event_ids),
        }


def bind_intent_requirements(
    twin: IntentTwin,
    units: Iterable[ForgeUnit],
) -> tuple[RequirementSemanticBinding, ...]:
    """Bind confirmed requirements to T units using explicit semantic paths."""

    if not twin.confirmed:
        raise CausalRepairError("CR106", "binding causal exige IntentTwin confirmado")
    forge_units = tuple(units)
    if not forge_units:
        raise CausalRepairError("CR107", "binding causal exige unidades T")
    eligible = tuple(
        observation
        for observation in twin.observations
        if observation.evidence_kind
        in {IntentEvidenceKind.EXPLICIT, IntentEvidenceKind.CONFIRMED}
    )
    bindings: list[RequirementSemanticBinding] = []
    for observation in eligible:
        unit_ids = tuple(
            unit.unit_id
            for unit in forge_units
            if any(
                _paths_intersect(watch_path, semantic_path)
                for watch_path in unit.watch_paths
                for semantic_path in observation.affected_paths
            )
        )
        bindings.append(
            RequirementSemanticBinding(
                requirement_id=f"req:{twin.twin_id}:{observation.observation_id}",
                strength=observation.strength,
                semantic_paths=observation.affected_paths,
                unit_ids=unit_ids,
                verifier_ids=observation.verifier_ids,
                source_event_ids=tuple(
                    dict.fromkeys(
                        (*observation.source_event_ids, *twin.confirmation_event_ids)
                    )
                ),
            )
        )
    if not bindings:
        raise CausalRepairError("CR108", "IntentTwin não produziu bindings elegíveis")
    return tuple(bindings)


@dataclass(frozen=True, slots=True)
class CausalRepairPlan:
    diagnostic_sha256: str
    diagnostic_code: str
    test_name: str
    target_unit_id: str
    requirement_ids: tuple[str, ...]
    affected_paths: tuple[tuple[str, ...], ...]
    seed_unit_ids: tuple[str, ...]
    rebuild_unit_ids: tuple[str, ...]
    reuse_unit_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    plan_sha256: str

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema": "casulo.causal-repair-plan/1.0",
            "diagnostic_sha256": self.diagnostic_sha256,
            "diagnostic_code": self.diagnostic_code,
            "test_name": self.test_name,
            "target_unit_id": self.target_unit_id,
            "requirement_ids": list(self.requirement_ids),
            "affected_paths": [list(path) for path in self.affected_paths],
            "seed_unit_ids": list(self.seed_unit_ids),
            "rebuild_unit_ids": list(self.rebuild_unit_ids),
            "reuse_unit_ids": list(self.reuse_unit_ids),
            "source_event_ids": list(self.source_event_ids),
        }
        return {**value, "plan_sha256": self.plan_sha256} if include_hash else value


class CausalRepairPlanner:
    @staticmethod
    def plan(
        diagnostic: Mapping[str, Any],
        *,
        bindings: Iterable[RequirementSemanticBinding],
        units: Iterable[ForgeUnit],
        source_event_id: str,
    ) -> CausalRepairPlan:
        forge_units = tuple(units)
        by_id = {unit.unit_id: unit for unit in forge_units}
        target = str(diagnostic.get("unit_id", ""))
        if target not in by_id:
            raise CausalRepairError("CR109", "diagnóstico aponta para unidade T desconhecida")
        if not source_event_id:
            raise CausalRepairError("CR110", "plano causal exige evento de origem")
        matching_bindings = tuple(
            binding for binding in bindings if target in binding.unit_ids
        )
        if not matching_bindings:
            raise CausalRepairError(
                "CR111", "diagnóstico não alcança requisito confirmado; reparo negado"
            )
        affected_paths = tuple(
            dict.fromkeys(
                path
                for binding in matching_bindings
                for path in binding.semantic_paths
                if any(
                    _paths_intersect(path, watch_path)
                    for watch_path in by_id[target].watch_paths
                )
            )
        )
        if not affected_paths:
            raise CausalRepairError("CR112", "diagnóstico não possui caminho causal comum")
        seed_ids = {
            unit.unit_id
            for unit in forge_units
            if any(
                _paths_intersect(watch_path, affected_path)
                for watch_path in unit.watch_paths
                for affected_path in affected_paths
            )
        }
        seed_ids.add(target)
        rebuild_ids = CausalRepairPlanner._downstream_closure(seed_ids, by_id)
        order = CausalRepairPlanner._topological_order(by_id)
        diagnostic_document = dict(diagnostic)
        diagnostic_sha256 = canonical_sha256(diagnostic_document)
        unsigned = {
            "schema": "casulo.causal-repair-plan/1.0",
            "diagnostic_sha256": diagnostic_sha256,
            "diagnostic_code": str(diagnostic.get("code", "")),
            "test_name": str(diagnostic.get("test_name", "")),
            "target_unit_id": target,
            "requirement_ids": [item.requirement_id for item in matching_bindings],
            "affected_paths": [list(path) for path in affected_paths],
            "seed_unit_ids": [unit_id for unit_id in order if unit_id in seed_ids],
            "rebuild_unit_ids": [unit_id for unit_id in order if unit_id in rebuild_ids],
            "reuse_unit_ids": [unit_id for unit_id in order if unit_id not in rebuild_ids],
            "source_event_ids": [source_event_id],
        }
        return CausalRepairPlan(
            diagnostic_sha256=diagnostic_sha256,
            diagnostic_code=unsigned["diagnostic_code"],
            test_name=unsigned["test_name"],
            target_unit_id=target,
            requirement_ids=tuple(unsigned["requirement_ids"]),
            affected_paths=affected_paths,
            seed_unit_ids=tuple(unsigned["seed_unit_ids"]),
            rebuild_unit_ids=tuple(unsigned["rebuild_unit_ids"]),
            reuse_unit_ids=tuple(unsigned["reuse_unit_ids"]),
            source_event_ids=(source_event_id,),
            plan_sha256=canonical_sha256(unsigned),
        )

    @staticmethod
    def _topological_order(by_id: Mapping[str, ForgeUnit]) -> tuple[str, ...]:
        pending = {unit_id: set(unit.dependencies) for unit_id, unit in by_id.items()}
        order: list[str] = []
        while pending:
            ready = sorted(key for key, dependencies in pending.items() if not dependencies)
            if not ready:
                raise CausalRepairError("CR113", "grafo T causal contém ciclo")
            for unit_id in ready:
                order.append(unit_id)
                pending.pop(unit_id)
            for dependencies in pending.values():
                dependencies.difference_update(ready)
        return tuple(order)

    @staticmethod
    def _downstream_closure(
        seeds: set[str], by_id: Mapping[str, ForgeUnit]
    ) -> set[str]:
        result = set(seeds)
        changed = True
        while changed:
            changed = False
            for unit_id, unit in by_id.items():
                if unit_id not in result and set(unit.dependencies) & result:
                    result.add(unit_id)
                    changed = True
        return result


@dataclass(frozen=True, slots=True)
class CausalRepairReceipt:
    plan: CausalRepairPlan
    before_tcap_sha256: str
    after_tcap_sha256: str
    changed_unit_ids: tuple[str, ...]
    rebuilt_unit_ids: tuple[str, ...]
    reused_unit_ids: tuple[str, ...]
    reused_artifact_sha256: tuple[tuple[str, str], ...]
    all_tests_passed_after_rebuild: bool
    receipt_sha256: str

    @classmethod
    def seal(
        cls,
        plan: CausalRepairPlan,
        *,
        before_receipt: ForgeReceipt,
        after_receipt: ForgeReceipt,
        before_tcap_sha256: str,
        after_tcap_sha256: str,
        changed_unit_ids: tuple[str, ...],
        all_tests_passed_after_rebuild: bool,
    ) -> "CausalRepairReceipt":
        if tuple(after_receipt.rebuilt_units) != plan.rebuild_unit_ids:
            raise CausalRepairError("CR114", "Forge reconstruiu subgrafo diferente do plano causal")
        if tuple(after_receipt.reused_units) != plan.reuse_unit_ids:
            raise CausalRepairError("CR115", "Forge reutilizou unidades diferentes do plano causal")
        if set(changed_unit_ids) - set(plan.seed_unit_ids):
            raise CausalRepairError("CR116", "source diff escapou das sementes causais")
        before_artifacts = {
            item.unit_id: item.artifact_sha256 for item in before_receipt.artifacts
        }
        after_artifacts = {
            item.unit_id: item.artifact_sha256 for item in after_receipt.artifacts
        }
        reused = tuple(
            (unit_id, after_artifacts[unit_id]) for unit_id in plan.reuse_unit_ids
        )
        if any(before_artifacts.get(unit_id) != digest for unit_id, digest in reused):
            raise CausalRepairError("CR117", "artefato fora do subgrafo não foi preservado")
        unsigned = {
            "schema": "casulo.causal-repair-receipt/1.0",
            "plan": plan.to_dict(),
            "before_tcap_sha256": before_tcap_sha256,
            "after_tcap_sha256": after_tcap_sha256,
            "changed_unit_ids": list(changed_unit_ids),
            "rebuilt_unit_ids": list(after_receipt.rebuilt_units),
            "reused_unit_ids": list(after_receipt.reused_units),
            "reused_artifact_sha256": dict(reused),
            "all_tests_passed_after_rebuild": all_tests_passed_after_rebuild,
        }
        return cls(
            plan,
            before_tcap_sha256,
            after_tcap_sha256,
            changed_unit_ids,
            tuple(after_receipt.rebuilt_units),
            tuple(after_receipt.reused_units),
            reused,
            all_tests_passed_after_rebuild,
            canonical_sha256(unsigned),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.causal-repair-receipt/1.0",
            "plan": self.plan.to_dict(),
            "before_tcap_sha256": self.before_tcap_sha256,
            "after_tcap_sha256": self.after_tcap_sha256,
            "changed_unit_ids": list(self.changed_unit_ids),
            "rebuilt_unit_ids": list(self.rebuilt_unit_ids),
            "reused_unit_ids": list(self.reused_unit_ids),
            "reused_artifact_sha256": dict(self.reused_artifact_sha256),
            "all_tests_passed_after_rebuild": self.all_tests_passed_after_rebuild,
            "receipt_sha256": self.receipt_sha256,
        }
