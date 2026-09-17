from __future__ import annotations

from copy import deepcopy

import pytest

from casulo.product.semantic_fulfillment import (
    ArchitectureRepairLoop,
    FulfillmentEngine,
    FulfillmentError,
    default_domain_registry,
)


NOW = "2026-08-14T20:00:00Z"


def evaluate(pack: str, candidate: dict[str, object]):
    return FulfillmentEngine(default_domain_registry()).evaluate(
        pack,
        candidate,
        source_event_id="human:holdout",
        scope="creation:holdout",
        occurred_at=NOW,
        safety_pass=True,
    )


def valid_scientific() -> dict[str, object]:
    return {
        "science": {
            "inputs": ["metric", "coordinates", "constants", "stress_energy", "conditions", "tolerances"],
            "operators": ["levi_civita", "ricci_tensor", "ricci_scalar", "einstein_tensor"],
            "outputs": ["field_equation_residual"],
            "scope": "local-4d-evaluator",
            "refusals": ["global-pde-solver"],
        },
        "claims": ["avaliador tensorial local 4D"],
    }


def test_generic_einstein_title_is_not_false_completion() -> None:
    result = evaluate(
        "scientific-computing",
        {"title": "Solver geral das equações de Einstein", "compiled": True},
    )
    assert result.accepted is False
    assert len(result.evaluation.hard_failures) == 7
    assert result.unsupported_claims == ()  # title is not itself an authorized claim field
    assert all(receipt.independent for receipt in result.evidence)


def test_compile_alone_does_not_satisfy_domain_invariants() -> None:
    result = evaluate("scientific-computing", {"compiled": True, "claims": []})
    assert result.accepted is False
    assert result.evaluation.coverage == 0
    input_diagnostic = next(item for item in result.diagnostics if item.rule_id == "inputs")
    assert input_diagnostic.expected == (
        "metric",
        "coordinates",
        "constants",
        "stress_energy",
        "conditions",
        "tolerances",
    )
    assert "metric" in input_diagnostic.message


def test_local_einstein_evaluator_passes_delimited_contract() -> None:
    result = evaluate("scientific-computing", valid_scientific())
    assert result.accepted is True
    assert result.evaluation.coverage == 1
    assert result.evaluation.spec_gap == 0
    assert not result.diagnostics


def test_typed_scientific_identifiers_satisfy_canonical_domain_names() -> None:
    candidate = valid_scientific()
    science = candidate["science"]
    assert isinstance(science, dict)
    science["inputs"] = [
        "metric_4d: tensor[4,4]",
        "coordinates: vector[4]",
        "constants: record",
        "stress_energy: tensor[4,4]",
        "conditions: record",
        "tolerances: record",
    ]
    science["operators"] = [
        "levi_civita: tensor[4,4,4]",
        "ricci_tensor: tensor[4,4]",
        "ricci_scalar: float64",
        "einstein_tensor: tensor[4,4]",
    ]
    science["outputs"] = ["field_equation_residual: tensor[4,4]"]
    science["refusals"] = ["global-pde-solver: denied"]
    assert evaluate("scientific-computing", candidate).accepted


def test_identifier_matching_does_not_accept_unrelated_substrings() -> None:
    candidate = valid_scientific()
    science = candidate["science"]
    assert isinstance(science, dict)
    science["inputs"] = [
        "parametric: number",
        "coordinates",
        "constants",
        "stress_energy",
        "conditions",
        "tolerances",
    ]
    result = evaluate("scientific-computing", candidate)
    assert not result.accepted
    assert "scientific-computing:inputs" in result.evaluation.hard_failures


def test_unsupported_global_claim_blocks_otherwise_valid_candidate() -> None:
    candidate = valid_scientific()
    candidate["claims"] = ["solver geral das PDEs de Einstein"]
    result = evaluate("scientific-computing", candidate)
    assert all(value.value == "PASS" for value in result.evaluation.verdicts.values())
    assert result.accepted is False
    assert result.unsupported_claims == ("solver geral das PDEs de Einstein",)


@pytest.mark.parametrize(
    ("pack", "candidate"),
    [
        (
            "administrative-workflow",
            {
                "workflow": {"human_decision_required": True, "provenance": ["receipt:1"], "audit_log": "append-only"},
                "security": {"network_default": "deny"},
            },
        ),
        (
            "stream-processing",
            {"stream": {"preserve_original": True, "memory_limit_bytes": 1048576, "time_semantics": "event-time", "explain_transform": True}},
        ),
        (
            "interactive-creative-tool",
            {"creative": {"project_isolation": True, "barge_in": True, "export": "editable", "progress_source": "job-events-only"}},
        ),
        (
            "local-software-service",
            {"service": {"bind": "127.0.0.1", "schema_validation": True, "standalone": True, "round_trip_fidelity": 1.0}},
        ),
    ],
)
def test_five_domain_family_contracts_have_real_pass_paths(pack: str, candidate: dict[str, object]) -> None:
    assert evaluate(pack, candidate).accepted is True


def test_architecture_repair_uses_diagnostics_and_does_not_mutate_input() -> None:
    original = {"service": {"bind": "0.0.0.0", "schema_validation": True}}

    def repairer(candidate, diagnostics, attempt):
        assert diagnostics
        repaired = deepcopy(candidate)
        repaired["service"].update(
            {"bind": "127.0.0.1", "standalone": True, "round_trip_fidelity": 1.0}
        )
        return repaired

    outcome = ArchitectureRepairLoop(FulfillmentEngine(default_domain_registry()), max_repairs=2).run(
        "local-software-service",
        original,
        source_event_id="human:1",
        scope="creation:1",
        occurred_at=NOW,
        safety_pass=True,
        repairer=repairer,
    )
    assert outcome.accepted is True
    assert outcome.exhausted is False
    assert len(outcome.attempts) == 2
    assert original == {"service": {"bind": "0.0.0.0", "schema_validation": True}}


def test_repair_loop_rejects_replayed_candidate() -> None:
    candidate = {"service": {}}
    loop = ArchitectureRepairLoop(FulfillmentEngine(default_domain_registry()), max_repairs=2)
    with pytest.raises(FulfillmentError, match="FUL108"):
        loop.run(
            "local-software-service",
            candidate,
            source_event_id="human:1",
            scope="creation:1",
            occurred_at=NOW,
            safety_pass=True,
            repairer=lambda current, diagnostics, attempt: current,
        )


def test_safety_failure_blocks_full_domain_pass() -> None:
    result = FulfillmentEngine(default_domain_registry()).evaluate(
        "scientific-computing",
        valid_scientific(),
        source_event_id="human:1",
        scope="creation:1",
        occurred_at=NOW,
        safety_pass=False,
    )
    assert result.evaluation.coverage == 1
    assert result.accepted is False
