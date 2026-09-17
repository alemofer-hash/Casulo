from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from casulo.t.sovereignty import (
    ForeignBoundaryManifest,
    SovereigntyAudit,
    SovereigntyError,
    TPolicyRuntime,
)


ROOT = Path(__file__).resolve().parents[2]


CASES = (
    ("intent_requirements", "requirements.t", "EvaluateRequirement", {"schema_valid": True, "evidence_present": True, "safety_pass": True}, "PASS"),
    ("agent_logic", "agent_logic.t", "AdvanceAgent", {"intent_confirmed": True, "constraints_satisfied": True, "cancelled": False}, "READY"),
    ("tools_composition", "tools.t", "AuthorizeTool", {"schema_valid": True, "capability_present": True, "simulation": True}, "SIMULATE"),
    ("memory", "memory.t", "AcceptMemory", {"schema_valid": True, "provenance_present": True, "project_scope_matches": True}, "ACCEPT"),
    ("jobs_concurrency", "jobs.t", "PublishJob", {"receipt_present": True, "cancelled": False, "generation_matches": True}, "PUBLISH"),
    ("effects_capabilities", "capabilities.t", "DecidePermit", {"schema_valid": True, "policy_pass": True, "grant_present": True, "human_approval": True}, "PERMIT"),
    ("interfaces", "interfaces.t", "RenderState", {"event_valid": True, "receipt_present": True}, "RENDER"),
    ("tests_simulation", "simulation.t", "AcceptSimulation", {"deterministic": True, "real_effects_absent": True, "requirements_covered": True}, "PASS"),
    ("materialization", "materialization.t", "PublishArtifact", {"schema_valid": True, "tests_pass": True, "safety_pass": True, "bytes_match_hash": True}, "PUBLISH"),
)


def boundary() -> ForeignBoundaryManifest:
    return ForeignBoundaryManifest(
        "python-reference-runtime",
        "Python",
        hashlib.sha256(b"pinned-reference-runtime").hexdigest(),
        "MIT/project",
        "casulo-artifact/0.8",
        ("ValidatedRecord",),
        ("DecisionReceipt",),
        "caller-owned immutable input",
        "single-threaded",
        ("manifest",),
        ("manifest",),
        5000,
        "typed diagnostic",
        "hosted-owner-restricted",
    )


def test_all_sovereignty_surfaces_compile_and_execute_through_t(tmp_path: Path) -> None:
    runtime = TPolicyRuntime(ROOT / "examples/t/revolution", tmp_path / "build")
    receipts = tuple(runtime.decide(*case[:-1]) for case in CASES)
    assert [item.result for item in receipts] == [case[-1] for case in CASES]
    audit = SovereigntyAudit(receipts, (boundary(),))
    assert audit.score == 1.0
    assert audit.critical_complete
    assert audit.accepted


@pytest.mark.parametrize(
    ("source_name", "operation", "payload", "expected"),
    (
        ("capabilities.t", "DecidePermit", {"schema_valid": True, "policy_pass": True, "grant_present": False, "human_approval": True}, "DENY"),
        ("materialization.t", "PublishArtifact", {"schema_valid": True, "tests_pass": True, "safety_pass": True, "bytes_match_hash": False}, "DENY"),
        ("jobs.t", "PublishJob", {"receipt_present": True, "cancelled": True, "generation_matches": True}, "DROP_STALE"),
    ),
)
def test_critical_t_decisions_fail_closed(tmp_path: Path, source_name: str, operation: str, payload: dict, expected: str) -> None:
    surface = {"capabilities.t": "effects_capabilities", "materialization.t": "materialization", "jobs.t": "jobs_concurrency"}[source_name]
    receipt = TPolicyRuntime(ROOT / "examples/t/revolution", tmp_path / "build").decide(surface, source_name, operation, payload)
    assert receipt.result == expected


def test_unmanifested_or_path_escaped_sources_are_rejected(tmp_path: Path) -> None:
    runtime = TPolicyRuntime(ROOT / "examples/t/revolution", tmp_path / "build")
    with pytest.raises(SovereigntyError):
        runtime.decide("effects_capabilities", "../product_capability.t", "Present", {"message": "x"})
    with pytest.raises(SovereigntyError):
        runtime.decide("opaque_python", "capabilities.t", "DecidePermit", {})


def test_foreign_boundary_must_be_complete() -> None:
    with pytest.raises(SovereigntyError):
        ForeignBoundaryManifest("bad", "C", "not-a-hash", "", "", (), (), "", "", (), (), 0, "", "")
