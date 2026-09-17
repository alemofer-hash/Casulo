from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from casulo.product.revolution_contracts import (
    EvidenceClass,
    EvidenceReceipt,
    RequirementGraph,
    RequirementStrength,
    Verdict,
    canonical_sha256,
)


class TRequirementTransportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TRequirementAggregate:
    """Canonical T/2.0 input; it carries facts but does not decide acceptance."""

    graph_schema: str
    graph_version: int
    project_id: str
    candidate_project_id: str
    hard_requirement_ids: tuple[str, ...]
    expected_evidence_tokens: tuple[str, ...]
    observed_evidence_tokens: tuple[str, ...]
    evidence_plan_hash: str
    evidence_plan: Mapping[str, Any]

    def authority_inputs(self) -> dict[str, Any]:
        return {
            "graph_schema": self.graph_schema,
            "graph_version": self.graph_version,
            "project_id": self.project_id,
            "candidate_project_id": self.candidate_project_id,
            "hard_requirement_ids": self.hard_requirement_ids,
            "expected_evidence_tokens": self.expected_evidence_tokens,
            "observed_evidence_tokens": self.observed_evidence_tokens,
            "evidence_plan_hash": self.evidence_plan_hash,
        }


def evidence_token(
    *,
    project_id: str,
    requirement_id: str,
    verifier_id: str,
    verdict: Verdict,
    independent: bool,
) -> str:
    # Canonical JSON hash prevents substring, spelling, and delimiter tricks.
    return canonical_sha256(
        {
            "schema": "casulo.t-evidence-token/1.0",
            "project_id": project_id,
            "requirement_id": requirement_id,
            "verifier_id": verifier_id,
            "verdict": verdict.value,
            "independent": independent,
        }
    )


class TRequirementGraphCompiler:
    """Compiles graph/evidence into facts consumed by T; never returns a verdict."""

    SCHEMA = "casulo.requirement-graph/2.0"
    VERSION = 1

    def compile(
        self,
        graph: RequirementGraph,
        evidence: Iterable[EvidenceReceipt],
        *,
        project_id: str,
        candidate_project_id: str,
    ) -> TRequirementAggregate:
        if not project_id or not candidate_project_id:
            raise TRequirementTransportError("project identity is required")
        hard = tuple(
            requirement
            for requirement in graph.requirements
            if requirement.strength is RequirementStrength.HARD
        )
        if not hard:
            raise TRequirementTransportError("at least one HARD requirement is required")
        hard_ids = tuple(item.requirement_id for item in hard)
        if len(set(hard_ids)) != len(hard_ids):
            raise TRequirementTransportError("duplicate HARD requirement")
        expected = tuple(
            evidence_token(
                project_id=project_id,
                requirement_id=requirement.requirement_id,
                verifier_id=verifier_id,
                verdict=Verdict.PASS,
                independent=True,
            )
            for requirement in hard
            for verifier_id in requirement.verifier_ids
        )
        observed_items = tuple(evidence)
        observed = tuple(
            evidence_token(
                project_id=project_id,
                requirement_id=item.requirement_id,
                verifier_id=item.verifier_id,
                verdict=item.verdict,
                independent=item.evidence_class is not EvidenceClass.GENERATOR_SELF_REPORT,
            )
            for item in observed_items
        )
        plan = {
            "schema": "casulo.evidence-plan/1.0",
            "graph_schema": self.SCHEMA,
            "graph_version": self.VERSION,
            "project_id": project_id,
            "hard_requirements": [
                {
                    "requirement_id": item.requirement_id,
                    "verifier_ids": list(item.verifier_ids),
                    "source_event_ids": list(item.source_event_ids),
                    "scope": item.scope,
                }
                for item in hard
            ],
            "expected_evidence_tokens": list(expected),
        }
        return TRequirementAggregate(
            self.SCHEMA,
            self.VERSION,
            project_id,
            candidate_project_id,
            hard_ids,
            expected,
            observed,
            canonical_sha256(plan),
            plan,
        )
