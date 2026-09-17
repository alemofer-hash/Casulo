from __future__ import annotations

import hashlib
import json
import time

import pytest

from casulo.product.domain import DomainError
from casulo.product.engine_contracts import CancellationToken
from casulo.product.intent_reconstruction import (
    EpistemicGap,
    HypothesisImpactStatus,
    HypothesisRequirementImpact,
    IntentEvidenceKind,
    IntentHypothesis,
    IntentObservation,
    IntentStakes,
    IntentTaskKind,
    IntentTwin,
    IntentTwinRenderer,
)
from casulo.product.neural_budget import NeuralOperation
from casulo.product.revolution_contracts import RequirementStrength
from casulo.product.requirement_evidence_gate import RequirementEvidenceFacts, RequirementEvidenceGate
from casulo_owner.intent_reconstruction import IntentReconstructionEngine
from casulo_owner.local_model_runtime import ModelStreamEvent, ModelStreamKind, StochasticTrace


class StructuredRuntimeDouble:
    def __init__(self, *payloads: dict[str, object]) -> None:
        self.payloads = list(payloads)
        self.requests = []

    def stream_chat(self, request, cancellation):
        self.requests.append(request)
        yield ModelStreamEvent(request.operation_id, 1, ModelStreamKind.STARTED)
        raw = json.dumps(self.payloads.pop(0), ensure_ascii=False)
        yield ModelStreamEvent(request.operation_id, 2, ModelStreamKind.TOKEN, raw)
        now = time.monotonic_ns()
        trace = StochasticTrace(
            request.operation_id,
            "intent-twin-test-double",
            "a" * 64,
            request.policy.policy_id,
            request.policy.seed,
            request.context_digest,
            hashlib.sha256(raw.encode()).hexdigest(),
            1,
            "stop",
            now - 1,
            now,
        )
        yield ModelStreamEvent(request.operation_id, 3, ModelStreamKind.COMPLETED, trace=trace)


def _observation(
    observation_id: str = "obs:1",
    *,
    kind: IntentEvidenceKind = IntentEvidenceKind.EXPLICIT,
    strength: RequirementStrength = RequirementStrength.HARD,
) -> IntentObservation:
    return IntentObservation(
        observation_id,
        "A criação deve explicar a decisão antes de agir.",
        kind,
        strength,
        ("human:idea:1",),
        (("behavior", "explanation"),),
        ("verifier:simulation",),
        0.91,
    )


def _impact(observation_id: str, status: HypothesisImpactStatus = HypothesisImpactStatus.PRESERVES) -> tuple[HypothesisRequirementImpact, ...]:
    return (HypothesisRequirementImpact(observation_id, status, "impacto explícito para o teste"),)


def _twin(*, gap: bool = True) -> IntentTwin:
    observation = _observation()
    hypotheses = (
        IntentHypothesis("hyp:1", "Assistente consultivo", "nível de ação", "recomendar sem executar", "preparar ação simulada", ("Somente recomenda ações",), 0.6, (observation.observation_id,), _impact(observation.observation_id)),
        IntentHypothesis("hyp:2", "Agente executor", "nível de ação", "preparar ação simulada", "recomendar sem executar", ("Pode preparar uma ação simulada",), 0.4, (observation.observation_id,), _impact(observation.observation_id)),
    )
    gaps = (
        EpistemicGap("gap:1", "Ele recomenda ou executa?", "Muda capabilities e testes.", (("behavior", "autonomy"),), 0.95, ("human:idea:1",)),
    ) if gap else ()
    return IntentTwin(
        "twin:1",
        "creation:1",
        "Agente que explica decisões",
        IntentTaskKind.CREATION,
        IntentStakes.MATERIAL,
        (observation,),
        hypotheses,
        gaps,
        selected_hypothesis_id=None if gap else "hyp:1",
    )


def test_open_gap_and_missing_human_confirmation_block_production() -> None:
    twin = _twin()
    assert not twin.production_ready
    with pytest.raises(DomainError, match="incerteza material"):
        twin.confirm(human_event_id="human:confirm:1", explicit_human_approval=True)
    resolved = twin.resolve_gap(
        "gap:1", "Somente recomenda.", source_event_id="human:answer:1", selected_hypothesis_id="hyp:1"
    )
    assert resolved.production_ready
    assert not resolved.confirmed
    with pytest.raises(DomainError, match="confirmação humana"):
        resolved.confirm(human_event_id="model:confirm", explicit_human_approval=True)


def test_hypotheses_must_be_mutually_exclusive_on_one_decision_dimension() -> None:
    observation = _observation()
    first = IntentHypothesis(
        "hyp:a", "Comparar", "modo", "comparar", "executar", ("Compara",), 0.5,
        (observation.observation_id,), _impact(observation.observation_id),
    )
    second = IntentHypothesis(
        "hyp:b", "Apresentar", "modo", "apresentar", "comparar", ("Apresenta",), 0.5,
        (observation.observation_id,), _impact(observation.observation_id),
    )
    with pytest.raises(DomainError, match="exclusão mútua"):
        IntentTwin(
            "twin:bad-branches", "creation:bad-branches", "Resumo",
            IntentTaskKind.CREATION, IntentStakes.MATERIAL,
            (observation,), (first, second), (), selected_hypothesis_id="hyp:a",
        )


def test_confirmed_twin_builds_requirement_graph_with_provenance() -> None:
    twin = _twin(gap=False).confirm(
        human_event_id="human:confirm:1", explicit_human_approval=True
    )
    graph = twin.requirement_graph()
    requirement = graph.requirements[0]
    assert requirement.strength is RequirementStrength.HARD
    assert requirement.verifier_ids == ("verifier:simulation",)
    assert requirement.source_event_ids == ("human:idea:1", "human:confirm:1")
    assert "Interpretação escolhida: Assistente consultivo" in twin.production_brief()


def test_inferred_observation_becomes_requirement_only_after_explicit_twin_confirmation() -> None:
    inferred = _observation("obs:inferred", kind=IntentEvidenceKind.INFERRED)
    hypothesis = IntentHypothesis("hyp:1", "Uma interpretação", "modo", "escolha única", "nenhuma alternativa", ("Uma consequência",), 0.8, (inferred.observation_id,), _impact(inferred.observation_id))
    twin = IntentTwin(
        "twin:inferred", "creation:inferred", "Resumo", IntentTaskKind.CREATION,
        IntentStakes.MATERIAL, (inferred,), (hypothesis,), (), selected_hypothesis_id="hyp:1",
    )
    confirmed = twin.confirm(human_event_id="human:confirm:inferred", explicit_human_approval=True)
    assert confirmed.observations[0].evidence_kind is IntentEvidenceKind.CONFIRMED
    assert confirmed.requirement_graph().requirements[0].statement == inferred.statement


def test_renderer_refuses_raw_dict_and_escapes_untrusted_text(tmp_path) -> None:
    twin = _twin(gap=False)
    with pytest.raises(DomainError, match="IntentTwin validado"):
        IntentTwinRenderer.render(twin.to_dict(), tmp_path / "raw")  # type: ignore[arg-type]
    malicious = IntentTwin(
        twin.twin_id, twin.creation_id, "<script>alert(1)</script>", twin.task_kind,
        twin.stakes, twin.observations, twin.hypotheses, twin.gaps,
        selected_hypothesis_id=twin.selected_hypothesis_id,
    )
    index = IntentTwinRenderer.render(malicious, tmp_path / "visual")
    page = index.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def _initial_payload(*, gap: bool = True) -> dict[str, object]:
    return {
        "summary": "Agente que explica decisões antes de agir",
        "task_kind": "CREATION",
        "stakes": "MATERIAL",
        "observations": [
            {
                "statement": "Deve explicar a decisão",
                "evidence_kind": "EXPLICIT",
                "strength": "HARD",
                "affected_paths": ["behavior.explanation"],
                "verifier_kind": "simulation",
                "confidence": 0.98,
            },
            {
                "statement": "Talvez prepare ações",
                "evidence_kind": "INFERRED",
                "strength": "SOFT",
                "affected_paths": ["behavior.autonomy"],
                "verifier_kind": "human-review",
                "confidence": 0.55,
            },
        ],
        "hypotheses": [
            {
                "interpretation": "Consultivo",
                "decision_dimension": "nível de ação",
                "choice_value": "somente recomendar",
                "excludes_choice_value": "preparar ação simulada após confirmação",
                "consequences": ["Recomenda sem executar"],
                "confidence": 0.55,
                "supporting_observation_indices": [0],
                "requirement_impacts": [
                    {"observation_index": 0, "status": "PRESERVES", "rationale": "mantém explicação"},
                    {"observation_index": 1, "status": "PRESERVES", "rationale": "não contradiz autonomia"},
                ],
            },
            {
                "interpretation": "Executor controlado",
                "decision_dimension": "nível de ação",
                "choice_value": "preparar ação simulada após confirmação",
                "excludes_choice_value": "somente recomendar",
                "consequences": ["Prepara ação após confirmação"],
                "confidence": 0.45,
                "supporting_observation_indices": [0, 1],
                "requirement_impacts": [
                    {"observation_index": 0, "status": "PRESERVES", "rationale": "mantém explicação"},
                    {"observation_index": 1, "status": "PRESERVES", "rationale": "prepara sem executar"},
                ],
            },
        ],
        "material_gap": {
            "question": "Ele apenas recomenda ou prepara uma ação?",
            "why_material": "Muda a fronteira de efeitos.",
            "affected_paths": ["behavior.autonomy"],
            "information_gain": 0.96,
        } if gap else None,
        "selected_hypothesis_index": None if gap else 0,
    }


def test_neural_reconstruction_produces_two_hypotheses_and_one_material_question() -> None:
    runtime = StructuredRuntimeDouble(_initial_payload())
    reconstruction = IntentReconstructionEngine(runtime).propose(  # type: ignore[arg-type]
        creation_id="creation:new",
        source_event_id="human:idea:new",
        utterance="Quero um agente que explique decisões.",
        expected_behavior="Explica antes de agir.",
        cancellation=CancellationToken(),
    )
    assert len(reconstruction.twin.hypotheses) == 2
    assert len(reconstruction.twin.open_gaps) == 1
    assert reconstruction.twin.hypotheses[1].supporting_observation_ids == (
        reconstruction.twin.observations[0].observation_id,
        reconstruction.twin.observations[1].observation_id,
    )
    assert runtime.requests[0].json_schema is not None
    assert runtime.requests[0].policy.policy_id == "casulo-arc7-intent-reconstruction-v1"
    assert reconstruction.route_decisions[0].operation is NeuralOperation.INTENT_RECONSTRUCTION


def test_neural_refinement_resolves_gap_but_does_not_self_confirm() -> None:
    refinement = {
        "refined_summary": "Agente consultivo que explica e não executa",
        "selected_hypothesis_index": 0,
        "additional_observations": [
            {
                "statement": "Não deve executar ações reais",
                "evidence_kind": "EXPLICIT",
                "strength": "HARD",
                "affected_paths": ["constraints.no_real_effects"],
                "verifier_kind": "simulation",
                "confidence": 1.0,
            }
        ],
        "hypothesis_impacts": [
            {
                "hypothesis_index": 0,
                "requirement_impacts": [
                    {"observation_index": 0, "status": "PRESERVES", "rationale": "explica"},
                    {"observation_index": 1, "status": "PRESERVES", "rationale": "permanece consultivo"},
                    {"observation_index": 2, "status": "PRESERVES", "rationale": "não executa"},
                ],
            },
            {
                "hypothesis_index": 1,
                "requirement_impacts": [
                    {"observation_index": 0, "status": "PRESERVES", "rationale": "explica"},
                    {"observation_index": 1, "status": "CHANGES", "rationale": "prepararia ação"},
                    {"observation_index": 2, "status": "PRESERVES", "rationale": "continua sem efeito real"},
                ],
            },
        ],
    }
    runtime = StructuredRuntimeDouble(_initial_payload(), refinement)
    engine = IntentReconstructionEngine(runtime)  # type: ignore[arg-type]
    initial = engine.propose(
        creation_id="creation:new",
        source_event_id="human:idea:new",
        utterance="Quero um agente que explique decisões.",
        expected_behavior="Explica antes de agir.",
        cancellation=CancellationToken(),
    )
    refined = engine.refine(
        initial,
        answer="Apenas recomenda; nunca executa.",
        source_event_id="human:answer:new",
        cancellation=CancellationToken(),
    )
    assert refined.twin.production_ready
    assert not refined.twin.confirmed
    assert refined.twin.gaps[0].answer == "Apenas recomenda; nunca executa."
    assert refined.twin.observations[-1].source_event_ids == ("human:answer:new",)
    assert refined.route_decisions[-1].operation is NeuralOperation.INTENT_REFINEMENT
    assert runtime.requests[-1].policy.policy_id == "casulo-arc7-intent-refinement-v1"


def test_deterministic_create_context_overrides_model_classification_and_records_it() -> None:
    payload = _initial_payload(gap=False)
    payload["task_kind"] = "CONVERSATION"
    runtime = StructuredRuntimeDouble(payload)
    reconstruction = IntentReconstructionEngine(runtime).propose(  # type: ignore[arg-type]
        creation_id="creation:command-create",
        source_event_id="human:command:create",
        utterance="Crie um agente local.",
        expected_behavior="O agente gera um artefato.",
        cancellation=CancellationToken(),
        task_kind_hint=IntentTaskKind.CREATION,
    )
    assert reconstruction.model_task_kind is IntentTaskKind.CONVERSATION
    assert reconstruction.twin.task_kind is IntentTaskKind.CREATION
    assert reconstruction.deterministic_overrides == ("task_kind:CONVERSATION->CREATION",)


def test_clear_intent_uses_one_viable_hypothesis_instead_of_fake_alternative() -> None:
    payload = _initial_payload(gap=False)
    payload["hypotheses"] = [payload["hypotheses"][0]]  # type: ignore[index]
    payload["hypotheses"][0]["excludes_choice_value"] = "nenhuma alternativa material"  # type: ignore[index]
    runtime = StructuredRuntimeDouble(payload)
    reconstruction = IntentReconstructionEngine(runtime).propose(  # type: ignore[arg-type]
        creation_id="creation:clear", source_event_id="human:clear",
        utterance="Crie um agente consultivo sem efeitos reais.",
        expected_behavior="Somente recomenda.", cancellation=CancellationToken(),
        task_kind_hint=IntentTaskKind.CREATION,
    )
    assert len(reconstruction.twin.hypotheses) == 1
    assert reconstruction.twin.viable_hypothesis_ids == (
        reconstruction.twin.hypotheses[0].hypothesis_id,
    )
    assert reconstruction.twin.production_ready


def test_hypothesis_conflicting_with_hard_observation_cannot_be_selected() -> None:
    payload = _initial_payload(gap=False)
    payload["hypotheses"][0]["requirement_impacts"][0]["status"] = "CONFLICTS"  # type: ignore[index]
    runtime = StructuredRuntimeDouble(payload)
    with pytest.raises(Exception, match="incompatível com requisito HARD"):
        IntentReconstructionEngine(runtime, candidate_budget=1).propose(  # type: ignore[arg-type]
            creation_id="creation:conflict", source_event_id="human:conflict",
            utterance="Crie", expected_behavior="Preserve o requisito",
            cancellation=CancellationToken(), task_kind_hint=IntentTaskKind.CREATION,
        )


def test_reconstruction_repairs_contract_rejection_with_bounded_second_candidate() -> None:
    invalid = _initial_payload(gap=False)
    invalid["hypotheses"][0]["excludes_choice_value"] = "algo que não é a outra escolha"  # type: ignore[index]
    valid = _initial_payload(gap=False)
    runtime = StructuredRuntimeDouble(invalid, valid)
    reconstruction = IntentReconstructionEngine(runtime, candidate_budget=2).propose(  # type: ignore[arg-type]
        creation_id="creation:repair-intent",
        source_event_id="human:repair-intent",
        utterance="Crie um agente consultivo.",
        expected_behavior="Ele não executa ações.",
        cancellation=CancellationToken(),
        task_kind_hint=IntentTaskKind.CREATION,
    )
    assert len(runtime.requests) == 2
    assert len(reconstruction.candidate_rejections) == 1
    assert "IT152" in reconstruction.candidate_rejections[0]["diagnostic"]
    assert reconstruction.twin.production_ready


def test_model_cannot_preselect_hypothesis_while_material_gap_is_open() -> None:
    payload = _initial_payload()
    payload["selected_hypothesis_index"] = 0
    runtime = StructuredRuntimeDouble(payload)
    with pytest.raises(Exception, match="antes de resolver lacuna"):
        IntentReconstructionEngine(runtime, candidate_budget=1).propose(  # type: ignore[arg-type]
            creation_id="creation:new", source_event_id="human:idea:new",
            utterance="Crie", expected_behavior="Funciona",
            cancellation=CancellationToken(),
        )


def test_requirement_evidence_gate_blocks_unknown_hard_verifier() -> None:
    observation = IntentObservation(
        "obs:domain", "Curvatura precisa respeitar a identidade de Bianchi",
        IntentEvidenceKind.EXPLICIT, RequirementStrength.HARD,
        ("human:domain:1",), (("constraints", "bianchi"),),
        ("verifier:acceptance", "verifier:domain-invariant"), 1.0,
    )
    hypothesis = IntentHypothesis(
        "hyp:domain", "Avaliador tensorial", "escopo", "validar identidade local", "nenhuma alternativa", ("Verifica identidade",), 1.0,
        (observation.observation_id,), _impact(observation.observation_id),
    )
    twin = IntentTwin(
        "twin:domain", "creation:domain", "Avaliador", IntentTaskKind.CREATION,
        IntentStakes.HIGH, (observation,), (hypothesis,), (),
        selected_hypothesis_id=hypothesis.hypothesis_id,
    ).confirm(human_event_id="human:confirm:domain", explicit_human_approval=True)
    result = RequirementEvidenceGate.evaluate(
        twin.requirement_graph(),
        RequirementEvidenceFacts(True, True, True, True, True),
        artifact_sha256="a" * 64,
        input_sha256="b" * 64,
        occurred_at="2026-08-18T12:00:00+00:00",
    )
    assert not result.evaluation.accepted
    assert result.evaluation.verdicts[next(iter(result.evaluation.verdicts))].value == "UNKNOWN"
    assert result.unsupported_verifier_ids == ("verifier:domain-invariant",)


def test_requirement_evidence_gate_passes_only_when_all_hard_receipts_pass() -> None:
    observation = IntentObservation(
        "obs:accept", "A saída deve conter a decisão explicada",
        IntentEvidenceKind.EXPLICIT, RequirementStrength.HARD,
        ("human:accept:1",), (("output", "decision"),),
        ("verifier:acceptance", "verifier:simulation"), 1.0,
    )
    hypothesis = IntentHypothesis(
        "hyp:accept", "Agente explicativo", "ordem", "explicar antes de agir", "nenhuma alternativa", ("Explica a decisão",), 1.0,
        (observation.observation_id,), _impact(observation.observation_id),
    )
    twin = IntentTwin(
        "twin:accept", "creation:accept", "Agente", IntentTaskKind.CREATION,
        IntentStakes.MATERIAL, (observation,), (hypothesis,), (),
        selected_hypothesis_id=hypothesis.hypothesis_id,
    ).confirm(human_event_id="human:confirm:accept", explicit_human_approval=True)
    graph = twin.requirement_graph()
    failed = RequirementEvidenceGate.evaluate(
        graph, RequirementEvidenceFacts(False, True, True, True, True),
        artifact_sha256="a" * 64, input_sha256="b" * 64,
        occurred_at="2026-08-18T12:00:00+00:00",
    )
    passed = RequirementEvidenceGate.evaluate(
        graph, RequirementEvidenceFacts(True, True, True, True, True),
        artifact_sha256="a" * 64, input_sha256="b" * 64,
        occurred_at="2026-08-18T12:00:00+00:00",
    )
    unsafe = RequirementEvidenceGate.evaluate(
        graph, RequirementEvidenceFacts(True, True, True, False, True),
        artifact_sha256="a" * 64, input_sha256="b" * 64,
        occurred_at="2026-08-18T12:00:00+00:00",
    )
    assert failed.evaluation.accepted is False
    assert unsafe.evaluation.accepted is False
    assert passed.evaluation.accepted is True
