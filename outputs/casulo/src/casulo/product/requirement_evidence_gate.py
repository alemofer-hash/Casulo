from __future__ import annotations

from dataclasses import dataclass

from .revolution_contracts import (
    EvidenceClass,
    EvidenceReceipt,
    RequirementEvaluation,
    RequirementGraph,
    Verdict,
)


@dataclass(frozen=True, slots=True)
class RequirementEvidenceFacts:
    acceptance_pass: bool
    compile_pass: bool
    simulation_pass: bool
    clean_execution_pass: bool
    human_review_pass: bool


@dataclass(frozen=True, slots=True)
class RequirementEvidenceGateResult:
    evidence: tuple[EvidenceReceipt, ...]
    evaluation: RequirementEvaluation
    unsupported_verifier_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "casulo.requirement-evidence-gate/1.0",
            "accepted": self.evaluation.accepted,
            "coverage": self.evaluation.coverage,
            "spec_gap": self.evaluation.spec_gap,
            "verdicts": {key: value.value for key, value in self.evaluation.verdicts.items()},
            "hard_failures": list(self.evaluation.hard_failures),
            "unknown": list(self.evaluation.unknown),
            "unsupported_verifier_ids": list(self.unsupported_verifier_ids),
            "evidence": [item.to_dict() for item in self.evidence],
        }


class RequirementEvidenceGate:
    """Turns observed facts into receipts; unknown verifier kinds remain UNKNOWN."""

    @staticmethod
    def evaluate(
        graph: RequirementGraph,
        facts: RequirementEvidenceFacts,
        *,
        artifact_sha256: str,
        input_sha256: str,
        occurred_at: str,
    ) -> RequirementEvidenceGateResult:
        known: dict[str, tuple[bool, EvidenceClass, str]] = {
            "verifier:acceptance": (
                facts.acceptance_pass,
                EvidenceClass.PROPERTY,
                "teste de aceite confirmado executado em processo isolado",
            ),
            "verifier:compile": (
                facts.compile_pass,
                EvidenceClass.COMPILE,
                "T compilado e verificação estrutural concluída",
            ),
            "verifier:simulation": (
                facts.simulation_pass,
                EvidenceClass.SIMULATION,
                "simulação concluída sem efeito real",
            ),
            "verifier:clean-execution": (
                facts.clean_execution_pass,
                EvidenceClass.CLEAN_EXECUTION,
                "testes finais executaram em subprocessos isolados",
            ),
            "verifier:human-review": (
                facts.human_review_pass,
                EvidenceClass.HUMAN_REVIEW,
                "IntentTwin recebeu confirmação humana explícita",
            ),
        }
        evidence: list[EvidenceReceipt] = []
        unsupported: set[str] = set()
        for requirement in graph.requirements:
            for verifier_id in requirement.verifier_ids:
                observed = known.get(verifier_id)
                if observed is None:
                    unsupported.add(verifier_id)
                    continue
                passed, evidence_class, detail = observed
                evidence.append(
                    EvidenceReceipt(
                        receipt_id=f"evidence:{requirement.requirement_id}:{verifier_id.split(':')[-1]}",
                        requirement_id=requirement.requirement_id,
                        verifier_id=verifier_id,
                        verdict=Verdict.PASS if passed else Verdict.FAIL,
                        evidence_class=evidence_class,
                        artifact_sha256=artifact_sha256,
                        producer="casulo-requirement-evidence-gate/1.0",
                        input_hashes=(input_sha256, artifact_sha256),
                        occurred_at=occurred_at,
                        detail=detail,
                    )
                )
        evaluation = graph.evaluate(
            evidence,
            safety_pass=(
                facts.compile_pass
                and facts.simulation_pass
                and facts.clean_execution_pass
                and facts.human_review_pass
            ),
        )
        return RequirementEvidenceGateResult(
            tuple(evidence),
            evaluation,
            tuple(sorted(unsupported)),
        )
