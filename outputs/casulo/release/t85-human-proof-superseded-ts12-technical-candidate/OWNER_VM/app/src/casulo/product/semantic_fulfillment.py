from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence

from .revolution_contracts import (
    EvidenceClass,
    EvidenceReceipt,
    Requirement,
    RequirementEvaluation,
    RequirementGraph,
    RequirementStrength,
    Verdict,
    canonical_sha256,
)


class FulfillmentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class RuleOperator(StrEnum):
    EXISTS = "EXISTS"
    EQUALS = "EQUALS"
    CONTAINS_ALL = "CONTAINS_ALL"
    ABSENT = "ABSENT"
    NONEMPTY_LIST = "NONEMPTY_LIST"
    NONNEGATIVE_NUMBER = "NONNEGATIVE_NUMBER"


@dataclass(frozen=True, slots=True)
class DomainRule:
    rule_id: str
    statement: str
    path: tuple[str, ...]
    operator: RuleOperator
    expected: Any = None
    strength: RequirementStrength = RequirementStrength.HARD
    weight: float = 1.0
    evidence_class: EvidenceClass = EvidenceClass.DOMAIN_INVARIANT

    def __post_init__(self) -> None:
        if not self.rule_id or not self.statement.strip() or not self.path:
            raise FulfillmentError("FUL100", "regra de domínio incompleta")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise FulfillmentError("FUL101", "peso de regra inválido")

    @property
    def verifier_id(self) -> str:
        return f"domain:{self.rule_id}"


@dataclass(frozen=True, slots=True)
class DomainPack:
    pack_id: str
    version: str
    rules: tuple[DomainRule, ...]
    forbidden_claim_fragments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.pack_id or not self.version or not self.rules:
            raise FulfillmentError("FUL102", "domain pack incompleto")
        if len({item.rule_id for item in self.rules}) != len(self.rules):
            raise FulfillmentError("FUL103", "rule_id duplicada")

    def requirement_graph(self, *, source_event_id: str, scope: str) -> RequirementGraph:
        if not source_event_id or not scope:
            raise FulfillmentError("FUL104", "grafo exige provenance e escopo")
        requirements = tuple(
            Requirement(
                requirement_id=f"{self.pack_id}:{rule.rule_id}",
                statement=rule.statement,
                strength=rule.strength,
                weight=rule.weight,
                source_event_ids=(source_event_id,),
                verifier_ids=(rule.verifier_id,),
                scope=scope,
            )
            for rule in self.rules
        )
        return RequirementGraph(requirements)


class DomainPackRegistry:
    def __init__(self) -> None:
        self._packs: dict[str, DomainPack] = {}

    def register(self, pack: DomainPack) -> None:
        if pack.pack_id in self._packs:
            raise FulfillmentError("FUL105", "domain pack duplicado")
        self._packs[pack.pack_id] = pack

    def get(self, pack_id: str) -> DomainPack:
        try:
            return self._packs[pack_id]
        except KeyError as error:
            raise FulfillmentError("FUL106", "domain pack desconhecido") from error

    @property
    def pack_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._packs))


@dataclass(frozen=True, slots=True)
class RuleDiagnostic:
    rule_id: str
    code: str
    message: str
    path: tuple[str, ...]
    observed: Any
    expected: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "code": self.code,
            "message": self.message,
            "path": list(self.path),
            "observed": self.observed,
            "expected": self.expected,
        }


@dataclass(frozen=True, slots=True)
class FulfillmentResult:
    pack_id: str
    candidate_sha256: str
    evaluation: RequirementEvaluation
    evidence: tuple[EvidenceReceipt, ...]
    diagnostics: tuple[RuleDiagnostic, ...]
    unsupported_claims: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.evaluation.accepted

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.fulfillment-result/1.0",
            "pack_id": self.pack_id,
            "candidate_sha256": self.candidate_sha256,
            "accepted": self.accepted,
            "coverage": self.evaluation.coverage,
            "spec_gap": self.evaluation.spec_gap,
            "verdicts": {key: value.value for key, value in self.evaluation.verdicts.items()},
            "hard_failures": list(self.evaluation.hard_failures),
            "unknown": list(self.evaluation.unknown),
            "unsupported_claims": list(self.unsupported_claims),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class CollectedFulfillmentEvidence:
    """Verifier facts only; deliberately has no accepted/fulfilled field."""

    pack_id: str
    candidate_sha256: str
    graph: RequirementGraph
    evidence: tuple[EvidenceReceipt, ...]
    diagnostics: tuple[RuleDiagnostic, ...]
    unsupported_claims: tuple[str, ...]


class FulfillmentEngine:
    """Runs domain rules independently; generator self-report is never evidence."""

    def __init__(self, registry: DomainPackRegistry) -> None:
        self.registry = registry

    def evaluate(
        self,
        pack_id: str,
        candidate: Mapping[str, Any],
        *,
        source_event_id: str,
        scope: str,
        occurred_at: str,
        safety_pass: bool,
    ) -> FulfillmentResult:
        collected = self.collect_evidence(
            pack_id,
            candidate,
            source_event_id=source_event_id,
            scope=scope,
            occurred_at=occurred_at,
        )
        evaluation = collected.graph.evaluate(
            collected.evidence,
            safety_pass=safety_pass,
            unsupported_claims=collected.unsupported_claims,
        )
        return FulfillmentResult(
            collected.pack_id,
            collected.candidate_sha256,
            evaluation,
            collected.evidence,
            collected.diagnostics,
            collected.unsupported_claims,
        )

    def collect_evidence(
        self,
        pack_id: str,
        candidate: Mapping[str, Any],
        *,
        source_event_id: str,
        scope: str,
        occurred_at: str,
    ) -> CollectedFulfillmentEvidence:
        """Run heterogeneous domain adapters without making an accept decision."""
        pack = self.registry.get(pack_id)
        graph = pack.requirement_graph(source_event_id=source_event_id, scope=scope)
        candidate_plain = copy.deepcopy(dict(candidate))
        digest = canonical_sha256(candidate_plain)
        evidence: list[EvidenceReceipt] = []
        diagnostics: list[RuleDiagnostic] = []
        for rule in pack.rules:
            observed, exists = _resolve(candidate_plain, rule.path)
            passed = _apply_rule(rule, observed, exists)
            verdict = Verdict.PASS if passed else Verdict.FAIL
            requirement_id = f"{pack.pack_id}:{rule.rule_id}"
            detail = (
                "domain invariant satisfied"
                if passed
                else f"expected {rule.operator.value} {rule.expected!r} at {'.'.join(rule.path)}"
            )
            evidence.append(
                EvidenceReceipt(
                    receipt_id=f"evidence:{digest[:16]}:{rule.rule_id}",
                    requirement_id=requirement_id,
                    verifier_id=rule.verifier_id,
                    verdict=verdict,
                    evidence_class=rule.evidence_class,
                    artifact_sha256=digest,
                    producer=f"casulo-domain-pack:{pack.pack_id}@{pack.version}",
                    input_hashes=(digest,),
                    occurred_at=occurred_at,
                    detail=detail,
                )
            )
            if not passed:
                diagnostics.append(
                    RuleDiagnostic(
                        rule.rule_id,
                        "FUL200",
                        detail,
                        rule.path,
                        observed if exists else None,
                        rule.expected,
                    )
                )
        claims = _claim_text(candidate_plain)
        unsupported = tuple(
            fragment
            for fragment in pack.forbidden_claim_fragments
            if fragment.casefold() in claims.casefold()
        )
        return CollectedFulfillmentEvidence(
            pack_id,
            digest,
            graph,
            tuple(evidence),
            tuple(diagnostics),
            unsupported,
        )


@dataclass(frozen=True, slots=True)
class RepairAttempt:
    attempt: int
    input_sha256: str
    output_sha256: str
    diagnostics_sha256: str
    result: FulfillmentResult


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    accepted: bool
    candidate: Mapping[str, Any]
    attempts: tuple[RepairAttempt, ...]
    exhausted: bool


class ArchitectureRepairLoop:
    def __init__(self, engine: FulfillmentEngine, *, max_repairs: int = 3) -> None:
        if not 0 <= max_repairs <= 5:
            raise FulfillmentError("FUL107", "repair budget inválido")
        self.engine = engine
        self.max_repairs = max_repairs

    def run(
        self,
        pack_id: str,
        candidate: Mapping[str, Any],
        *,
        source_event_id: str,
        scope: str,
        occurred_at: str,
        safety_pass: bool,
        repairer: Callable[[Mapping[str, Any], tuple[RuleDiagnostic, ...], int], Mapping[str, Any]],
    ) -> RepairOutcome:
        current: Mapping[str, Any] = copy.deepcopy(dict(candidate))
        attempts: list[RepairAttempt] = []
        seen: set[str] = set()
        for attempt in range(self.max_repairs + 1):
            input_hash = canonical_sha256(current)
            if input_hash in seen:
                raise FulfillmentError("FUL108", "repair loop repetiu candidato sem mudança")
            seen.add(input_hash)
            result = self.engine.evaluate(
                pack_id,
                current,
                source_event_id=source_event_id,
                scope=scope,
                occurred_at=occurred_at,
                safety_pass=safety_pass,
            )
            if result.accepted:
                attempts.append(RepairAttempt(attempt, input_hash, input_hash, canonical_sha256([]), result))
                return RepairOutcome(True, copy.deepcopy(dict(current)), tuple(attempts), False)
            if attempt == self.max_repairs:
                attempts.append(
                    RepairAttempt(
                        attempt,
                        input_hash,
                        input_hash,
                        canonical_sha256([item.to_dict() for item in result.diagnostics]),
                        result,
                    )
                )
                return RepairOutcome(False, copy.deepcopy(dict(current)), tuple(attempts), True)
            repaired = copy.deepcopy(dict(repairer(copy.deepcopy(dict(current)), result.diagnostics, attempt + 1)))
            output_hash = canonical_sha256(repaired)
            attempts.append(
                RepairAttempt(
                    attempt,
                    input_hash,
                    output_hash,
                    canonical_sha256([item.to_dict() for item in result.diagnostics]),
                    result,
                )
            )
            current = repaired
        raise AssertionError("unreachable")


def _resolve(candidate: Mapping[str, Any], path: Sequence[str]) -> tuple[Any, bool]:
    current: Any = candidate
    for item in path:
        if not isinstance(current, Mapping) or item not in current:
            return None, False
        current = current[item]
    return current, True


def _apply_rule(rule: DomainRule, observed: Any, exists: bool) -> bool:
    if rule.operator is RuleOperator.EXISTS:
        return exists and observed not in (None, "", [], {})
    if rule.operator is RuleOperator.ABSENT:
        return not exists or observed in (None, "", [], {})
    if rule.operator is RuleOperator.EQUALS:
        return exists and observed == rule.expected
    if rule.operator is RuleOperator.NONEMPTY_LIST:
        return exists and isinstance(observed, list) and bool(observed)
    if rule.operator is RuleOperator.NONNEGATIVE_NUMBER:
        return exists and isinstance(observed, (int, float)) and not isinstance(observed, bool) and math.isfinite(observed) and observed >= 0
    if rule.operator is RuleOperator.CONTAINS_ALL:
        if not exists:
            return False
        if isinstance(observed, str):
            return all(_contains_declared_identifier(observed, str(item)) for item in rule.expected)
        if isinstance(observed, Sequence) and not isinstance(observed, (str, bytes)):
            declarations = tuple(str(item) for item in observed)
            return all(
                any(_contains_declared_identifier(declaration, str(expected)) for declaration in declarations)
                for expected in rule.expected
            )
        return False
    raise FulfillmentError("FUL109", "operador desconhecido")


def _contains_declared_identifier(declaration: str, expected: str) -> bool:
    """Match a canonical identifier in a typed declaration, not a prose substring."""

    needle = expected.casefold().strip()
    text = declaration.casefold()
    if not needle:
        return False
    escaped = re.escape(needle)
    if re.fullmatch(r"[a-z][a-z0-9_]*", needle):
        pattern = rf"(?<![a-z0-9_]){escaped}(?:_[a-z0-9]+)*(?![a-z0-9_])"
    else:
        pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _claim_text(candidate: Mapping[str, Any]) -> str:
    claims = candidate.get("claims", ())
    if isinstance(claims, str):
        return claims
    if isinstance(claims, Sequence):
        return "\n".join(str(item) for item in claims)
    return str(claims)


def default_domain_registry() -> DomainPackRegistry:
    registry = DomainPackRegistry()
    packs = (
        DomainPack(
            "scientific-computing",
            "1.0",
            (
                DomainRule("inputs", "entradas científicas explícitas", ("science", "inputs"), RuleOperator.CONTAINS_ALL, ("metric", "coordinates", "constants", "stress_energy", "conditions", "tolerances"), weight=2),
                DomainRule("connection", "conexão construída", ("science", "operators"), RuleOperator.CONTAINS_ALL, ("levi_civita",)),
                DomainRule("ricci", "Ricci construído", ("science", "operators"), RuleOperator.CONTAINS_ALL, ("ricci_tensor", "ricci_scalar")),
                DomainRule("einstein", "tensor de Einstein construído", ("science", "operators"), RuleOperator.CONTAINS_ALL, ("einstein_tensor",)),
                DomainRule("residual", "resíduo explícito", ("science", "outputs"), RuleOperator.CONTAINS_ALL, ("field_equation_residual",), weight=2),
                DomainRule("scope", "escopo local declarado", ("science", "scope"), RuleOperator.EQUALS, "local-4d-evaluator", weight=2),
                DomainRule("global-denial", "solução global recusada", ("science", "refusals"), RuleOperator.CONTAINS_ALL, ("global-pde-solver",)),
            ),
            ("solver geral das PDEs de Einstein", "solução global de geometrias arbitrárias"),
        ),
        DomainPack(
            "administrative-workflow",
            "1.0",
            (
                DomainRule("human-decision", "decisão humana preservada", ("workflow", "human_decision_required"), RuleOperator.EQUALS, True, weight=2),
                DomainRule("provenance", "provenance registrada", ("workflow", "provenance"), RuleOperator.EXISTS),
                DomainRule("network", "rede negada por padrão", ("security", "network_default"), RuleOperator.EQUALS, "deny"),
                DomainRule("audit", "audit log append-only", ("workflow", "audit_log"), RuleOperator.EQUALS, "append-only"),
            ),
        ),
        DomainPack(
            "stream-processing",
            "1.0",
            (
                DomainRule("original", "dado original preservado", ("stream", "preserve_original"), RuleOperator.EQUALS, True, weight=2),
                DomainRule("memory", "memória limitada", ("stream", "memory_limit_bytes"), RuleOperator.NONNEGATIVE_NUMBER),
                DomainRule("event-time", "event time explícito", ("stream", "time_semantics"), RuleOperator.EQUALS, "event-time"),
                DomainRule("explain", "transformação explicável", ("stream", "explain_transform"), RuleOperator.EQUALS, True),
            ),
        ),
        DomainPack(
            "interactive-creative-tool",
            "1.0",
            (
                DomainRule("isolation", "memória separada por obra", ("creative", "project_isolation"), RuleOperator.EQUALS, True, weight=2),
                DomainRule("barge", "interrupção disponível", ("creative", "barge_in"), RuleOperator.EQUALS, True),
                DomainRule("export", "export editável", ("creative", "export"), RuleOperator.EQUALS, "editable"),
                DomainRule("progress", "progresso somente por evento", ("creative", "progress_source"), RuleOperator.EQUALS, "job-events-only"),
            ),
        ),
        DomainPack(
            "local-software-service",
            "1.0",
            (
                DomainRule("loopback", "API somente loopback", ("service", "bind"), RuleOperator.EQUALS, "127.0.0.1", weight=2),
                DomainRule("schema", "schema validado", ("service", "schema_validation"), RuleOperator.EQUALS, True),
                DomainRule("standalone", "execução independente do repo", ("service", "standalone"), RuleOperator.EQUALS, True),
                DomainRule("roundtrip", "round-trip fiel", ("service", "round_trip_fidelity"), RuleOperator.EQUALS, 1.0, weight=2),
            ),
        ),
    )
    for pack in packs:
        registry.register(pack)
    return registry
