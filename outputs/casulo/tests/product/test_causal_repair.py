from __future__ import annotations

import hashlib
import json
import time

import pytest

from casulo.product.causal_repair import (
    CausalRepairError,
    CausalRepairPlanner,
    RequirementSemanticBinding,
    bind_intent_requirements,
)
from casulo.product.engine_contracts import CancellationToken
from casulo.product.intent_reconstruction import (
    HypothesisImpactStatus,
    HypothesisRequirementImpact,
    IntentEvidenceKind,
    IntentHypothesis,
    IntentObservation,
    IntentStakes,
    IntentTaskKind,
    IntentTwin,
)
from casulo.product.neural_budget import NeuralOperation
from casulo.product.revolution_contracts import RequirementStrength
from casulo.product.t_forge import ForgeUnit
from casulo_owner import TProgramSynthesizer, VerifierRepairError, VerifierRepairLoop
from casulo_owner.local_model_runtime import ModelStreamEvent, ModelStreamKind, StochasticTrace


def _source(module: str, emitted: str) -> str:
    return f'''language T/1.1
module {module}

capability manifest

field Input
  trace value: Text

condense Act in Input
  effects [manifest]
  emit "{emitted}"
'''


def _confirmed_twin(*, second_path: tuple[str, ...] = ("behavior", "approval")) -> IntentTwin:
    observations = (
        IntentObservation(
            "obs:purpose",
            "Preservar decisões",
            IntentEvidenceKind.EXPLICIT,
            RequirementStrength.HARD,
            ("human:idea",),
            (("purpose", "summary"),),
            ("verifier:acceptance",),
            0.99,
        ),
        IntentObservation(
            "obs:approval",
            "Exigir confirmação",
            IntentEvidenceKind.EXPLICIT,
            RequirementStrength.HARD,
            ("human:idea",),
            (second_path,),
            ("verifier:simulation",),
            0.98,
        ),
    )
    hypothesis = IntentHypothesis(
        "hyp:one",
        "Agente consultivo com confirmação",
        "modo",
        "consultivo",
        "autônomo",
        ("Não executa sem confirmação",),
        0.95,
        tuple(item.observation_id for item in observations),
        tuple(
            HypothesisRequirementImpact(
                item.observation_id,
                HypothesisImpactStatus.PRESERVES,
                "preservado pela interpretação escolhida",
            )
            for item in observations
        ),
    )
    return IntentTwin(
        "twin:causal",
        "creation:causal",
        "Agente de decisões",
        IntentTaskKind.CREATION,
        IntentStakes.MATERIAL,
        observations,
        (hypothesis,),
        (),
        selected_hypothesis_id=hypothesis.hypothesis_id,
    ).confirm(human_event_id="human:confirm", explicit_human_approval=True)


def _units() -> tuple[ForgeUnit, ...]:
    return (
        ForgeUnit("decision", _source("generated.decision", "decisão"), (("purpose",),)),
        ForgeUnit("review", _source("generated.review", "revisão"), (("behavior",),), ("decision",)),
        ForgeUnit("output", _source("generated.output", "saída"), (("interface",),), ("review",)),
        ForgeUnit("identity", _source("generated.identity", "nome"), (("identity",),)),
    )


def test_confirmed_requirements_bind_to_units_by_semantic_path() -> None:
    bindings = bind_intent_requirements(_confirmed_twin(), _units())
    assert [item.requirement_id for item in bindings] == [
        "req:twin:causal:obs:purpose",
        "req:twin:causal:obs:approval",
    ]
    assert bindings[0].unit_ids == ("decision",)
    assert bindings[1].unit_ids == ("review",)
    assert bindings[1].source_event_ids == ("human:idea", "human:confirm")


def test_hard_requirement_without_t_unit_is_fail_closed() -> None:
    with pytest.raises(CausalRepairError, match="HARD"):
        bind_intent_requirements(
            _confirmed_twin(second_path=("unimplemented",)), _units()
        )


def test_planner_selects_semantic_seeds_and_only_downstream_closure() -> None:
    bindings = bind_intent_requirements(_confirmed_twin(), _units())
    plan = CausalRepairPlanner.plan(
        {
            "code": "TTEST_EXPECTED_TEXT_MISSING",
            "test_name": "approval",
            "unit_id": "review",
        },
        bindings=bindings,
        units=_units(),
        source_event_id="verifier:diagnostic:0:approval",
    )
    assert plan.requirement_ids == ("req:twin:causal:obs:approval",)
    assert plan.affected_paths == (("behavior", "approval"),)
    assert plan.seed_unit_ids == ("review",)
    assert plan.rebuild_unit_ids == ("review", "output")
    assert plan.reuse_unit_ids == ("decision", "identity")
    assert len(plan.plan_sha256) == 64


def test_diagnostic_without_confirmed_requirement_is_denied() -> None:
    bindings = bind_intent_requirements(_confirmed_twin(), _units())
    with pytest.raises(CausalRepairError, match="requisito confirmado"):
        CausalRepairPlanner.plan(
            {"code": "X", "test_name": "identity", "unit_id": "identity"},
            bindings=bindings,
            units=_units(),
            source_event_id="verifier:diagnostic:0:identity",
        )


def test_synthesis_retries_when_hard_requirement_has_no_t_unit() -> None:
    from casulo.product.domain import CreationSpec

    invalid = _project_payload()
    invalid["units"][1]["watch_paths"] = [["identity"]]  # type: ignore[index]
    runtime = _RuntimeDouble(invalid, _project_payload())
    project = TProgramSynthesizer(
        runtime, synthesis_candidate_budget=2  # type: ignore[arg-type]
    ).synthesize(
        CreationSpec("creation:causal", version=1),
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
        intent_twin=_confirmed_twin(),
    )
    assert len(project.candidate_rejections) == 1
    assert project.candidate_rejections[0]["error_class"] == "CausalRepairError"
    assert project.generation_trace.operation_id.endswith(":candidate-1")
    assert project.neural_route_decisions[0].operation is NeuralOperation.T_SYNTHESIS


class _RuntimeDouble:
    def __init__(self, *payloads: dict[str, object]) -> None:
        self.payloads = list(payloads)

    def stream_chat(self, request, cancellation):
        yield ModelStreamEvent(request.operation_id, 1, ModelStreamKind.STARTED)
        raw = json.dumps(self.payloads.pop(0), ensure_ascii=False)
        yield ModelStreamEvent(request.operation_id, 2, ModelStreamKind.TOKEN, raw)
        now = time.monotonic_ns()
        yield ModelStreamEvent(
            request.operation_id,
            3,
            ModelStreamKind.COMPLETED,
            trace=StochasticTrace(
                request.operation_id,
                "causal-test-double",
                "a" * 64,
                request.policy.policy_id,
                request.policy.seed,
                request.context_digest,
                hashlib.sha256(raw.encode()).hexdigest(),
                1,
                "stop",
                now - 1,
                now,
            ),
        )


def _project_payload() -> dict[str, object]:
    return {
        "units": [
            {
                "unit_id": "decision",
                "module": "generated.decision",
                "field_name": "DecisionInput",
                "operation_name": "RememberDecision",
                "emit_literal": "decisão",
                "watch_paths": [["purpose"]],
            },
            {
                "unit_id": "review",
                "module": "generated.review",
                "field_name": "ReviewInput",
                "operation_name": "ReviewDecision",
                "emit_literal": "revisão",
                "watch_paths": [["behavior"]],
            },
        ],
        "tests": [
            {
                "name": "preserva",
                "unit_id": "decision",
                "input": "x",
                "expected_contains": "decisão",
            },
            {
                "name": "approval",
                "unit_id": "review",
                "input": "x",
                "expected_contains": "confirmação",
            },
        ],
        "entry_unit": "review",
    }


def test_real_repair_seals_requirement_to_minimal_rebuild_receipt(tmp_path) -> None:
    from casulo.product.domain import CreationSpec

    runtime = _RuntimeDouble(
        _project_payload(),
        {
            "emit_literal": "revisão com confirmação",
            "rationale": "cumprir o diagnóstico preservando decisão",
        },
    )
    synthesizer = TProgramSynthesizer(runtime)  # type: ignore[arg-type]
    twin = _confirmed_twin()
    project = synthesizer.synthesize(
        CreationSpec("creation:causal", version=1),
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
        intent_twin=twin,
    )
    bindings = bind_intent_requirements(twin, project.units)
    outcome = VerifierRepairLoop(synthesizer, repair_budget=1).run(
        project,
        work_root=tmp_path / "causal-repair",
        cancellation=CancellationToken(),
        requirement_bindings=bindings,
        require_causal_repairs=True,
    )
    assert outcome.passed
    assert outcome.repair_count == 1
    assert len(outcome.causal_repairs) == 1
    receipt = outcome.causal_repairs[0]
    assert receipt.plan.requirement_ids == ("req:twin:causal:obs:approval",)
    assert receipt.changed_unit_ids == ("review",)
    assert receipt.rebuilt_unit_ids == ("review",)
    assert receipt.reused_unit_ids == ("decision",)
    assert receipt.all_tests_passed_after_rebuild
    assert len(receipt.receipt_sha256) == 64
    assert [item.operation for item in outcome.project.neural_route_decisions] == [
        NeuralOperation.T_SYNTHESIS,
        NeuralOperation.T_REPAIR,
    ]


def test_owner_strict_mode_rejects_repair_without_causal_bindings(tmp_path) -> None:
    from casulo.product.domain import CreationSpec

    runtime = _RuntimeDouble(_project_payload())
    synthesizer = TProgramSynthesizer(runtime)  # type: ignore[arg-type]
    project = synthesizer.synthesize(
        CreationSpec("creation:strict", version=1),
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
    )
    with pytest.raises(VerifierRepairError, match="binding causal"):
        VerifierRepairLoop(synthesizer, repair_budget=1).run(
            project,
            work_root=tmp_path / "strict-repair",
            cancellation=CancellationToken(),
            require_causal_repairs=True,
        )
