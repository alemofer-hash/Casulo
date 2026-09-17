from __future__ import annotations

import os
from pathlib import Path

import pytest

from casulo.t.productive import ProductiveTExecutor
from casulo_owner.t85_agent_synthesis import T85AgentPlan, T85SynthesisError, execute_agent, lower_agent_plan
from casulo_owner.local_model_runtime import StochasticTrace


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")


def plan() -> T85AgentPlan:
    trace = StochasticTrace("op", "model", "a" * 64, "policy", None, "b" * 64, "c" * 64, 3, "stop", 1, 2)
    return T85AgentPlan(
        "data-01", "bounded CSV validator", "csv_guardian", "Validates local tabular data safely.",
        ("policy", "pipeline", "delivery"),
        (
            {"requirement_id": "original-preserved", "field_name": "bytes_preserved", "error_code": "original_missing", "success_value": "BYTES_PRESERVED"},
            {"requirement_id": "versioned-schema", "field_name": "schema_versioned", "error_code": "schema_missing", "success_value": "SCHEMA_OK"},
            {"requirement_id": "diagnostic-per-rejection", "field_name": "diagnostics_ready", "error_code": "diagnostics_missing", "success_value": "DIAGNOSTICS_OK"},
        ), trace, "d" * 64,
    )


def test_lowered_agent_is_multimodule_nontrivial_and_executes_all_functions(tmp_path: Path) -> None:
    from casulo_owner.t85_agent_synthesis import T85AgentSynthesizer

    build = object.__new__(T85AgentSynthesizer).build(plan(), tmp_path / "agent")
    run = execute_agent(build, RUNTIME, tmp_path / "calls")
    assert run.final_value == "AUDITED"
    assert len(run.calls) == 11
    assert len(run.receipt_chain) == len(set(run.receipt_chain))
    sources = "\n".join(source.read_text(encoding="utf-8") for source in build.sources)
    assert sources.count("module ") == 3
    assert sources.count("fn ") == 11
    assert sources.count("record ") == 3
    assert sources.count("enum ") == 3
    assert "spawn job" in sources and "request effect simulation" in sources
    assert "emit_literal" not in sources and "emit " not in sources


def test_constraint_mutation_blocks_before_simulation(tmp_path: Path) -> None:
    from casulo_owner.t85_agent_synthesis import T85AgentSynthesizer

    build = object.__new__(T85AgentSynthesizer).build(plan(), tmp_path / "agent")
    executor = ProductiveTExecutor(RUNTIME, build.tcap.directory, tmp_path / "calls")
    module = f"owner.agent.{plan().agent_id}.{plan().module_suffixes[0]}"
    payload = {
        "confirmed": True, "project_match": True, "evidence_statuses": ["PASS"] * 3,
        "bytes_preserved": False, "schema_versioned": True, "diagnostics_ready": True, "cancelled": False,
    }
    call = executor.execute(module, "decide", payload, call_id="negative", surface_id="agent_behavior", scope_id="agent:data-01")
    assert call.observable["result"] == {"kind": "error", "value": "original_missing"}
    assert call.observable["requested_effects"] == []


def test_missing_simulation_grant_blocks_effect(tmp_path: Path) -> None:
    from casulo_owner.t85_agent_synthesis import T85AgentSynthesizer

    build = object.__new__(T85AgentSynthesizer).build(plan(), tmp_path / "agent")
    executor = ProductiveTExecutor(RUNTIME, build.tcap.directory, tmp_path / "calls")
    module = f"owner.agent.{plan().agent_id}.{plan().module_suffixes[2]}"
    call = executor.execute(
        module, "simulate", {"previous": "WORKFLOW_READY", "simulated": True, "approved": False, "cancelled": False},
        call_id="denied", surface_id="agent_behavior", scope_id="agent:data-01",
    )
    assert call.observable["result"] == {"kind": "error", "value": "CAPABILITY_DENIED:simulation"}


def test_plan_validation_rejects_missing_hard_requirement() -> None:
    from casulo_owner.t85_agent_synthesis import T85AgentSynthesizer

    value = {
        "agent_id": "csv_guardian", "summary": "A sufficiently detailed architecture summary.",
        "module_suffixes": ["policy", "pipeline", "delivery"],
        "constraints": [{key: value for key, value in item.items() if key != "success_value"} for item in plan().constraints],
    }
    value["constraints"][2]["requirement_id"] = "invented"
    with pytest.raises(T85SynthesisError, match="exact HARD"):
        T85AgentSynthesizer._validate("data-01", "request", ("original-preserved", "versioned-schema", "diagnostic-per-rejection"), value, plan().trace, "d" * 64, ())


def test_success_event_is_derived_from_the_sealed_requirement() -> None:
    from casulo_owner.t85_agent_synthesis import T85AgentSynthesizer

    value = {
        "agent_id": "csv_guardian", "summary": "A sufficiently detailed architecture summary.",
        "module_suffixes": ["policy", "pipeline", "delivery"],
        "constraints": [{key: value for key, value in item.items() if key != "success_value"} for item in plan().constraints],
    }
    validated = T85AgentSynthesizer._validate(
        "data-01", "request",
        ("original-preserved", "versioned-schema", "diagnostic-per-rejection"),
        value, plan().trace, "d" * 64, (),
    )
    assert [item["success_value"] for item in validated.constraints] == [
        "ORIGINAL_PRESERVED_SATISFIED",
        "VERSIONED_SCHEMA_SATISFIED",
        "DIAGNOSTIC_PER_REJECTION_SATISFIED",
    ]


def test_long_diagnostic_and_success_event_have_independent_bounds() -> None:
    from casulo_owner.t85_agent_synthesis import T85AgentSynthesizer

    value = {
        "agent_id": "csv_guardian", "summary": "A sufficiently detailed architecture summary.",
        "module_suffixes": ["policy", "pipeline", "delivery"],
        "constraints": [
            {"requirement_id": "requirement-with-a-name-that-exceeds-the-event-budget", "field_name": "long_requirement", "error_code": "diagnostic_identifier_long_but_still_valid"},
            {"requirement_id": "versioned-schema", "field_name": "schema_versioned", "error_code": "schema_missing"},
            {"requirement_id": "diagnostic-per-rejection", "field_name": "diagnostics_ready", "error_code": "diagnostics_missing"},
        ],
    }
    validated = T85AgentSynthesizer._validate(
        "data-01", "request",
        ("requirement-with-a-name-that-exceeds-the-event-budget", "versioned-schema", "diagnostic-per-rejection"),
        value, plan().trace, "d" * 64, (),
    )
    assert len(validated.constraints[0]["success_value"]) <= 48
    assert validated.constraints[0]["error_code"] == "diagnostic_identifier_long_but_still_valid"
