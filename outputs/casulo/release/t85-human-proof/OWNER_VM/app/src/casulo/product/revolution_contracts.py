from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class RequirementStrength(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class EvidenceClass(StrEnum):
    TYPE_CHECK = "TYPE_CHECK"
    COMPILE = "COMPILE"
    PROPERTY = "PROPERTY"
    SIMULATION = "SIMULATION"
    CLEAN_EXECUTION = "CLEAN_EXECUTION"
    DOMAIN_INVARIANT = "DOMAIN_INVARIANT"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    GENERATOR_SELF_REPORT = "GENERATOR_SELF_REPORT"


class Taint(StrEnum):
    DATA = "DATA"
    INSTRUCTION = "INSTRUCTION"


class Severity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


INDEPENDENT_EVIDENCE = frozenset(EvidenceClass) - {
    EvidenceClass.GENERATOR_SELF_REPORT
}


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _require_sha256(value: str, field_name: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ContractError("RC100", f"{field_name} exige SHA-256 lowercase")


@dataclass(frozen=True, slots=True)
class Requirement:
    requirement_id: str
    statement: str
    strength: RequirementStrength
    weight: float
    source_event_ids: tuple[str, ...]
    verifier_ids: tuple[str, ...]
    scope: str

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.statement.strip() or not self.scope:
            raise ContractError("RC101", "requisito exige identidade, texto e escopo")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ContractError("RC102", "peso de requisito precisa ser finito e positivo")
        if not self.source_event_ids or not self.verifier_ids:
            raise ContractError("RC103", "requisito exige proveniência e verificadores")
        if len(set(self.verifier_ids)) != len(self.verifier_ids):
            raise ContractError("RC104", "verificadores duplicados")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.requirement/1.0",
            "requirement_id": self.requirement_id,
            "statement": self.statement,
            "strength": self.strength.value,
            "weight": self.weight,
            "source_event_ids": list(self.source_event_ids),
            "verifier_ids": list(self.verifier_ids),
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    receipt_id: str
    requirement_id: str
    verifier_id: str
    verdict: Verdict
    evidence_class: EvidenceClass
    artifact_sha256: str
    producer: str
    input_hashes: tuple[str, ...]
    occurred_at: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.receipt_id or not self.requirement_id or not self.verifier_id:
            raise ContractError("RC105", "evidência exige identidades")
        if not self.producer or not self.occurred_at:
            raise ContractError("RC106", "evidência exige produtor e timestamp")
        _require_sha256(self.artifact_sha256, "artifact_sha256")
        for digest in self.input_hashes:
            _require_sha256(digest, "input_hash")

    @property
    def independent(self) -> bool:
        return self.evidence_class in INDEPENDENT_EVIDENCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.evidence-receipt/1.0",
            "receipt_id": self.receipt_id,
            "requirement_id": self.requirement_id,
            "verifier_id": self.verifier_id,
            "verdict": self.verdict.value,
            "evidence_class": self.evidence_class.value,
            "artifact_sha256": self.artifact_sha256,
            "producer": self.producer,
            "input_hashes": list(self.input_hashes),
            "occurred_at": self.occurred_at,
            "detail": self.detail,
            "independent": self.independent,
        }


@dataclass(frozen=True, slots=True)
class RequirementEvaluation:
    verdicts: Mapping[str, Verdict]
    coverage: float
    spec_gap: float
    accepted: bool
    hard_failures: tuple[str, ...]
    unknown: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequirementGraph:
    requirements: tuple[Requirement, ...]
    dependencies: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        by_id = {requirement.requirement_id: requirement for requirement in self.requirements}
        if not by_id or len(by_id) != len(self.requirements):
            raise ContractError("RC107", "grafo exige requisitos únicos")
        normalized = {key: tuple(value) for key, value in self.dependencies.items()}
        if set(normalized) - set(by_id):
            raise ContractError("RC108", "dependência parte de requisito desconhecido")
        if any(dep not in by_id for deps in normalized.values() for dep in deps):
            raise ContractError("RC109", "dependência aponta para requisito desconhecido")
        self._assert_acyclic(normalized)
        object.__setattr__(self, "dependencies", normalized)

    @staticmethod
    def _assert_acyclic(dependencies: Mapping[str, tuple[str, ...]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ContractError("RC110", "RequirementGraph contém ciclo")
            if node in visited:
                return
            visiting.add(node)
            for dependency in dependencies.get(node, ()):
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in dependencies:
            visit(node)

    def evaluate(
        self,
        evidence: Iterable[EvidenceReceipt],
        *,
        safety_pass: bool,
        unsupported_claims: tuple[str, ...] = (),
    ) -> RequirementEvaluation:
        grouped: dict[str, list[EvidenceReceipt]] = {
            requirement.requirement_id: [] for requirement in self.requirements
        }
        for receipt in evidence:
            if receipt.requirement_id not in grouped:
                raise ContractError("RC111", "evidência referencia requisito desconhecido")
            grouped[receipt.requirement_id].append(receipt)
        verdicts: dict[str, Verdict] = {}
        hard_failures: list[str] = []
        unknown: list[str] = []
        total_weight = sum(requirement.weight for requirement in self.requirements)
        passed_weight = 0.0
        for requirement in self.requirements:
            receipts = grouped[requirement.requirement_id]
            by_verifier = {receipt.verifier_id: receipt for receipt in receipts if receipt.independent}
            required = set(requirement.verifier_ids)
            if any(receipt.verdict is Verdict.FAIL for receipt in receipts if receipt.independent):
                verdict = Verdict.FAIL
            elif required.issubset(by_verifier) and all(by_verifier[item].verdict is Verdict.PASS for item in required):
                verdict = Verdict.PASS
            else:
                verdict = Verdict.UNKNOWN
            verdicts[requirement.requirement_id] = verdict
            if verdict is Verdict.PASS:
                passed_weight += requirement.weight
            elif verdict is Verdict.UNKNOWN:
                unknown.append(requirement.requirement_id)
            if requirement.strength is RequirementStrength.HARD and verdict is not Verdict.PASS:
                hard_failures.append(requirement.requirement_id)
        coverage = passed_weight / total_weight
        accepted = not hard_failures and safety_pass and not unsupported_claims
        return RequirementEvaluation(
            verdicts,
            coverage,
            1.0 - coverage,
            accepted,
            tuple(hard_failures),
            tuple(unknown),
        )


@dataclass(frozen=True, slots=True)
class ActionPermit:
    grant: bool
    policy: bool
    scope: bool
    valid_consent: bool
    revoked: bool = False

    @property
    def allowed(self) -> bool:
        return self.grant and self.policy and self.scope and self.valid_consent and not self.revoked


@dataclass(frozen=True, slots=True)
class TrustedEnvelope:
    content_sha256: str
    taint: Taint
    source: str
    provenance_ids: tuple[str, ...]
    schema_validated: bool

    def __post_init__(self) -> None:
        _require_sha256(self.content_sha256, "content_sha256")
        if not self.source or not self.provenance_ids:
            raise ContractError("RC112", "envelope exige origem e provenance")

    @classmethod
    def imported(cls, content: bytes, *, source: str, provenance_ids: tuple[str, ...]) -> "TrustedEnvelope":
        return cls(hashlib.sha256(content).hexdigest(), Taint.DATA, source, provenance_ids, False)

    def as_instruction(self, *, policy_validated: bool, capability_authorized: bool) -> "TrustedEnvelope":
        if not self.schema_validated or not policy_validated or not capability_authorized:
            raise ContractError("RC113", "dado não pode virar instrução sem schema, policy e capability")
        return TrustedEnvelope(self.content_sha256, Taint.INSTRUCTION, self.source, self.provenance_ids, True)


@dataclass(frozen=True, slots=True)
class TSovereigntyConstitution:
    weights: Mapping[str, float]
    critical_surfaces: frozenset[str]
    minimum_score: float = 0.80

    def __post_init__(self) -> None:
        normalized = dict(self.weights)
        if not normalized or any(not math.isfinite(value) or value <= 0 for value in normalized.values()):
            raise ContractError("RC114", "pesos S_T precisam ser finitos e positivos")
        if not self.critical_surfaces or not self.critical_surfaces.issubset(normalized):
            raise ContractError("RC115", "superfícies críticas precisam ter peso")
        if not 0 < self.minimum_score <= 1:
            raise ContractError("RC116", "limiar S_T inválido")
        object.__setattr__(self, "weights", normalized)

    def evaluate(self, degrees: Mapping[str, float]) -> dict[str, Any]:
        if set(degrees) != set(self.weights):
            raise ContractError("RC117", "graus S_T não cobrem exatamente as superfícies")
        if any(value not in {0.0, 0.5, 1.0} for value in degrees.values()):
            raise ContractError("RC118", "grau S_T deve ser 0, 0.5 ou 1")
        total = sum(self.weights.values())
        score = sum(self.weights[name] * degrees[name] for name in self.weights) / total
        critical_pass = all(degrees[name] == 1.0 for name in self.critical_surfaces)
        return {
            "score": score,
            "minimum": self.minimum_score,
            "critical_pass": critical_pass,
            "pass": score >= self.minimum_score and critical_pass,
        }


RC_T_CONSTITUTION = TSovereigntyConstitution(
    weights={
        "capability_decision": 5,
        "material_intent_decision": 5,
        "publish_decision": 5,
        "agent_logic": 3,
        "tool_policy": 3,
        "memory_policy": 3,
        "job_policy": 2,
        "interface_contract": 2,
        "test_oracle": 2,
        "simulation_policy": 3,
        "materialization_policy": 3,
    },
    critical_surfaces=frozenset(
        {"capability_decision", "material_intent_decision", "publish_decision"}
    ),
)


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    severity: Severity
    supported_path: bool
    summary: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        if not self.finding_id or not self.summary:
            raise ContractError("RC119", "finding exige identidade e resumo")
        _require_sha256(self.evidence_sha256, "evidence_sha256")


def release_blockers(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    return tuple(
        finding
        for finding in findings
        if finding.severity is Severity.P0
        or (finding.severity is Severity.P1 and finding.supported_path)
    )


RC_THRESHOLDS: Mapping[str, Any] = {
    "guide": {
        "synthetic_duration_hours": 2,
        "projects": 3,
        "cross_project_bleed": 0,
        "false_progress": 0,
        "mandatory_constraint_loss": 0,
    },
    "fulfillment": {
        "all_hard_requirements": "PASS",
        "safety": "PASS",
        "unsupported_claims": 0,
    },
    "t_sovereignty": {"minimum": 0.80, "critical_degree": 1.0},
    "voice": {
        "quiet_intent_success_min": 0.95,
        "moderate_noise_intent_success_min": 0.85,
        "barge_in_p95_ms_max": 150,
        "false_barge_in_per_hour_max": 2,
        "asr_rtf_p95_max_exclusive": 1.0,
        "tts_first_audio_p95_ms_max": 1000,
    },
    "materialization": {"hard_field_round_trip_fidelity": 1.0},
    "security": {
        "unauthorized_effects": 0,
        "secrets_in_artifacts": 0,
        "private_components_in_public": 0,
        "invalid_updates_accepted": 0,
        "open_p0": 0,
        "open_p1_supported_path": 0,
    },
}


def constitution_sha256() -> str:
    return canonical_sha256(
        {
            "schema": "casulo.rc-constitution/1.0",
            "thresholds": RC_THRESHOLDS,
            "t_sovereignty": {
                "weights": RC_T_CONSTITUTION.weights,
                "critical_surfaces": sorted(RC_T_CONSTITUTION.critical_surfaces),
                "minimum_score": RC_T_CONSTITUTION.minimum_score,
            },
        }
    )
