from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace

import pytest

from casulo.product.domain import CreationAggregate, CreationSpec, DeltaConfirmation
from casulo.product.engine_contracts import CancellationToken
from casulo.product.intent_engine import IntentEngine
from casulo.product.t_forge import ForgeUnit
from casulo.t.tcap import parse_tcap
from casulo_owner import (
    CandidateBudgetExhausted,
    GeneratedTProject,
    GenerativeForgeError,
    IntentPlanner,
    TProgramSynthesizer,
    compile_generated_project,
    validate_project_test_feasibility,
    verify_correction_scope,
    VerifierRepairLoop,
)
from casulo_owner.local_model_runtime import ModelStreamEvent, ModelStreamKind, StochasticTrace
from casulo_owner.generative_forge import T_SOURCE_PATTERN, lower_generated_unit_to_t
from casulo_owner.generative_agent_probe import OPEN_ENDED_REPAIR_BUDGET


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


def test_structured_t_source_pattern_rejects_unknown_top_level_lines() -> None:
    import re

    assert re.fullmatch(T_SOURCE_PATTERN, _source("generated.valid", "ok"))
    invalid = _source("generated.valid", "ok") + "notas.txt|notas.csv\n"
    assert re.fullmatch(T_SOURCE_PATTERN, invalid) is None
    assert lower_generated_unit_to_t("generated.valid", "Input", "Act", "ok") == _source("generated.valid", "ok")


class StructuredRuntimeDouble:
    def __init__(self, *payloads: dict[str, object]) -> None:
        self.payloads = list(payloads)
        self.requests = []

    def stream_chat(self, request, cancellation):
        self.requests.append(request)
        yield ModelStreamEvent(request.operation_id, 1, ModelStreamKind.STARTED)
        payload = self.payloads.pop(0)
        raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        yield ModelStreamEvent(request.operation_id, 2, ModelStreamKind.TOKEN, raw)
        now = time.monotonic_ns()
        trace = StochasticTrace(
            request.operation_id,
            "neural-test-double",
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


def _intent_payload() -> dict[str, object]:
    return {
        "rationale": "Criar agente de decisões com revisão humana.",
        "confidence": 0.82,
        "operations": [
            {"action": "set", "path": "purpose.summary", "value": "preservar decisões"},
            {"action": "set", "path": "behavior.autonomy", "value": "confirm-first"},
        ],
        "requested_capabilities": ["memory.read", "memory.read"],
    }


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
            {"name": "preserva", "unit_id": "decision", "input": "decisão A", "expected_contains": "decisão"},
            {"name": "confirma", "unit_id": "review", "input": "enviar", "expected_contains": "revisão"},
        ],
        "entry_unit": "review",
    }


def test_neural_plan_is_always_proposed_and_capability_request_is_not_grant() -> None:
    runtime = StructuredRuntimeDouble(_intent_payload())
    aggregate = CreationAggregate(CreationSpec("creation:gen"))
    plan = IntentPlanner(runtime).propose(  # type: ignore[arg-type]
        aggregate,
        source_event_id="voice:gen",
        utterance="crie um agente que preserve decisões",
        cancellation=CancellationToken(),
    )
    assert plan.delta.confirmation is DeltaConfirmation.PROPOSED
    assert plan.requested_capabilities == ("memory.read",)
    assert aggregate.current.capabilities == frozenset()
    with pytest.raises(Exception, match="aprovação humana"):
        IntentEngine().decide(
            plan.delta,
            human_event_id="model:auto",
            accepted=True,
            explicit_human_approval=False,
        )
    assert runtime.requests[0].json_schema is not None
    assert runtime.requests[0].messages[0].content.startswith("/no_think")


def test_planner_rejects_model_attempt_to_write_capabilities() -> None:
    payload = _intent_payload()
    payload["operations"] = [
        {"action": "set", "path": "capabilities.network_send", "value": True}
    ]
    runtime = StructuredRuntimeDouble(payload)
    with pytest.raises(GenerativeForgeError, match="fora do domínio"):
        IntentPlanner(runtime).propose(  # type: ignore[arg-type]
            CreationAggregate(CreationSpec("creation:gen")),
            source_event_id="voice:bad",
            utterance="libere rede",
            cancellation=CancellationToken(),
        )


def test_generated_t_traverses_forge_ir_graph_and_real_tcap() -> None:
    runtime = StructuredRuntimeDouble(_project_payload())
    creation = CreationSpec(
        "creation:gen",
        version=1,
        content={"purpose": {"summary": "preservar decisões"}},
    )
    project = TProgramSynthesizer(runtime).synthesize(  # type: ignore[arg-type]
        creation,
        source_event_ids=("voice:confirm",),
        cancellation=CancellationToken(),
    )
    compiled = compile_generated_project(project)
    assert compiled.forge_receipt.rebuilt_units == ("decision", "review")
    assert all(len(item.ir_sha256) == 64 and len(item.graph_sha256) == 64 for item in compiled.forge_receipt.artifacts)
    package = parse_tcap(compiled.tcap)
    assert package.manifest["capability_requirements"] == ["manifest"]
    assert "grants" not in package.manifest
    assert project.tests[0]["name"] == "preserva"


def test_semantically_invalid_t_project_is_rejected_before_repair_and_retried() -> None:
    invalid = _project_payload()
    invalid["units"][0]["field_name"] = "Read"
    invalid["units"][0]["operation_name"] = "Read"
    runtime = StructuredRuntimeDouble(invalid, _project_payload())
    creation = CreationSpec("creation:synthesis-retry", version=1)
    project = TProgramSynthesizer(
        runtime, synthesis_candidate_budget=2  # type: ignore[arg-type]
    ).synthesize(
        creation,
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
    )
    assert len(project.candidate_rejections) == 1
    rejection = project.candidate_rejections[0]
    assert rejection["phase"] == "synthesis"
    assert rejection["reason"] == "projeto_T_reprovado"
    assert rejection["error_class"] == "ForgeError"
    assert rejection["operation_id"].endswith(":candidate-0")
    assert project.generation_trace.operation_id.endswith(":candidate-1")
    assert compile_generated_project(project).forge_receipt.rebuilt_units == (
        "decision",
        "review",
    )


def test_unsatisfiable_generated_test_is_rejected_before_verifier() -> None:
    invalid = _project_payload()
    invalid["tests"][0]["expected_contains"] = "x" * 49
    runtime = StructuredRuntimeDouble(invalid, _project_payload())
    project = TProgramSynthesizer(
        runtime, synthesis_candidate_budget=2  # type: ignore[arg-type]
    ).synthesize(
        CreationSpec("creation:test-feasibility", version=1),
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
    )
    assert project.candidate_rejections[0]["reason"] == "projeto_T_reprovado"
    assert project.generation_trace.operation_id.endswith(":candidate-1")


def test_external_holdout_must_fit_same_emit_literal() -> None:
    runtime = StructuredRuntimeDouble(_project_payload())
    project = TProgramSynthesizer(runtime).synthesize(  # type: ignore[arg-type]
        CreationSpec("creation:external-feasibility", version=1),
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
    )
    with pytest.raises(GenerativeForgeError, match="insatisfatíveis"):
        validate_project_test_feasibility(
            project,
            external_tests=(
                {
                    "name": "holdout",
                    "unit_id": "decision",
                    "input": "x",
                    "expected_contains": "y" * 200,
                },
            ),
        )


def test_diff_cannot_hide_outside_declared_affected_paths() -> None:
    runtime = StructuredRuntimeDouble(_project_payload())
    creation = CreationSpec("creation:gen", version=1, content={"purpose": {"summary": "x"}})
    before = TProgramSynthesizer(runtime).synthesize(  # type: ignore[arg-type]
        creation,
        source_event_ids=("voice:confirm",),
        cancellation=CancellationToken(),
    )
    revised_units = tuple(
        replace(unit, source=_source("generated.review", "direto")) if unit.unit_id == "review" else unit
        for unit in before.units
    )
    after = replace(before, units=revised_units)
    assert verify_correction_scope(before, after, declared_affected_paths=(("behavior", "tone"),)) == ("review",)
    with pytest.raises(GenerativeForgeError, match="affected paths"):
        verify_correction_scope(before, after, declared_affected_paths=(("identity",),))


def test_revision_generation_changes_only_selected_unit() -> None:
    runtime = StructuredRuntimeDouble(
        _project_payload(),
        {"emit_literal": "revisão direta", "rationale": "tornar a resposta direta"},
    )
    creation = CreationSpec("creation:gen", version=1, content={"behavior": {"tone": "direto"}})
    synth = TProgramSynthesizer(runtime)  # type: ignore[arg-type]
    before = synth.synthesize(
        creation,
        source_event_ids=("voice:confirm",),
        cancellation=CancellationToken(),
    )
    after = synth.revise_unit(
        before,
        unit_id="review",
        correction="deixe a resposta direta",
        declared_affected_paths=(("behavior", "tone"),),
        source_event_id="voice:correction",
        cancellation=CancellationToken(),
    )
    before_map = {item.unit_id: item.source for item in before.units}
    after_map = {item.unit_id: item.source for item in after.units}
    assert before_map["decision"] == after_map["decision"]
    assert before_map["review"] != after_map["review"]


def test_invalid_revision_candidate_is_rejected_and_bounded_retry_is_sealed() -> None:
    runtime = StructuredRuntimeDouble(
        _project_payload(),
        {"emit_literal": 'inválido "com aspas"', "rationale": "primeiro candidato"},
        {"emit_literal": "revisão direta", "rationale": "segundo candidato válido"},
    )
    creation = CreationSpec("creation:gen-retry", version=1, content={"behavior": {"tone": "direto"}})
    synth = TProgramSynthesizer(runtime, revision_candidate_budget=2)  # type: ignore[arg-type]
    before = synth.synthesize(
        creation,
        source_event_ids=("voice:confirm",),
        cancellation=CancellationToken(),
    )
    after = synth.revise_unit(
        before,
        unit_id="review",
        correction="deixe a resposta direta",
        declared_affected_paths=(("behavior", "tone"),),
        source_event_id="voice:retry",
        cancellation=CancellationToken(),
    )
    assert len(after.candidate_rejections) == 1
    rejection = after.candidate_rejections[0]
    assert rejection["reason"] == "emit_literal_inválido"
    assert rejection["operation_id"].endswith(":candidate-0")
    assert rejection["trace"]["stream_events"] == 1
    assert "revisão direta" in next(item.source for item in after.units if item.unit_id == "review")


def test_malformed_structured_revision_is_hashed_rejected_and_retried() -> None:
    runtime = StructuredRuntimeDouble(
        _project_payload(),
        '{"emit_literal":"truncado',
        {"emit_literal": "revisão íntegra", "rationale": "segundo candidato válido"},
    )
    creation = CreationSpec("creation:json-retry", version=1, content={"behavior": {"tone": "íntegro"}})
    synth = TProgramSynthesizer(runtime, revision_candidate_budget=2)  # type: ignore[arg-type]
    before = synth.synthesize(
        creation,
        source_event_ids=("voice:confirm",),
        cancellation=CancellationToken(),
    )
    after = synth.revise_unit(
        before,
        unit_id="review",
        correction="produza uma revisão íntegra",
        declared_affected_paths=(("behavior", "tone"),),
        source_event_id="voice:json-retry",
        cancellation=CancellationToken(),
    )
    rejection = after.candidate_rejections[0]
    assert rejection["reason"] == "saída_estruturada_inválida"
    assert len(rejection["raw_sha256"]) == 64
    assert rejection["trace"]["finish_reason"] == "stop"


def test_exhausted_revision_candidates_preserve_all_rejection_receipts() -> None:
    runtime = StructuredRuntimeDouble(
        _project_payload(),
        {"emit_literal": 'inválido "um"', "rationale": "primeiro"},
        '{"emit_literal":"truncado',
    )
    synth = TProgramSynthesizer(runtime, revision_candidate_budget=2)  # type: ignore[arg-type]
    project = synth.synthesize(
        CreationSpec("creation:exhausted", version=1),
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
    )
    with pytest.raises(CandidateBudgetExhausted) as captured:
        synth.revise_unit(
            project,
            unit_id="review",
            correction="corrija",
            declared_affected_paths=(("behavior",),),
            source_event_id="voice:exhausted",
            cancellation=CancellationToken(),
        )
    assert captured.value.budget == 2
    assert [item["reason"] for item in captured.value.rejections] == [
        "emit_literal_inválido",
        "saída_estruturada_inválida",
    ]
    assert all(len(item["raw_sha256"]) == 64 for item in captured.value.rejections)


def test_real_diagnostic_drives_bounded_repair_and_reexecution(tmp_path) -> None:
    payload = _project_payload()
    payload["tests"].append(
        {
            "name": "nova-regra",
            "unit_id": "review",
            "input": "enviar",
            "expected_contains": "confirmação obrigatória",
        }
    )
    runtime = StructuredRuntimeDouble(
        payload,
        {
            "emit_literal": "revisão com confirmação obrigatória",
            "rationale": "atender o diagnóstico sem regredir o teste anterior",
        },
    )
    creation = CreationSpec("creation:repair", version=1, content={"behavior": {"approval": True}})
    synthesizer = TProgramSynthesizer(runtime)  # type: ignore[arg-type]
    project = synthesizer.synthesize(
        creation,
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
    )
    outcome = VerifierRepairLoop(synthesizer, repair_budget=1).run(
        project,
        work_root=tmp_path / "repair",
        cancellation=CancellationToken(),
    )
    assert outcome.status == "PASS"
    assert outcome.repair_count == 1
    assert outcome.attempts[0].diagnostics[0].code == "TTEST_EXPECTED_TEXT_MISSING"
    assert outcome.attempts[1].diagnostics == ()
    assert all(test.passed for test in outcome.attempts[1].tests)


def test_unresolved_repair_is_reported_when_budget_is_exhausted(tmp_path) -> None:
    payload = _project_payload()
    payload["tests"][1]["expected_contains"] = "frase que nunca aparece"
    runtime = StructuredRuntimeDouble(
        payload,
        {"emit_literal": "continua errado", "rationale": "tentativa limitada"},
    )
    creation = CreationSpec("creation:repair-fail", version=1)
    synthesizer = TProgramSynthesizer(runtime)  # type: ignore[arg-type]
    project = synthesizer.synthesize(
        creation,
        source_event_ids=("human:confirm",),
        cancellation=CancellationToken(),
    )
    outcome = VerifierRepairLoop(synthesizer, repair_budget=1).run(
        project,
        work_root=tmp_path / "repair-fail",
        cancellation=CancellationToken(),
    )
    assert outcome.status == "REPAIR_BUDGET_EXHAUSTED"
    assert outcome.repair_count == 1
    assert len(outcome.attempts) == 2
    assert outcome.attempts[-1].diagnostics


def test_open_ended_probe_repair_budget_is_explicit_and_bounded() -> None:
    assert OPEN_ENDED_REPAIR_BUDGET == 4
    assert 1 <= OPEN_ENDED_REPAIR_BUDGET <= 4
