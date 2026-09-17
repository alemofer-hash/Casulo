from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from casulo.product.revolution_contracts import (
    EvidenceClass,
    EvidenceReceipt,
    Requirement,
    RequirementGraph,
    RequirementStrength,
    Verdict,
)
from casulo.product.semantic_fulfillment import FulfillmentEngine, default_domain_registry
from casulo.t.v2_tcap import TcapV2Builder
from casulo_owner.einstein_solver_kernel import solve
from casulo_owner.t85_authority import T85AuthorityDenied, T85OwnerCriticalAuthority
from casulo_owner.t85_requirements import TRequirementGraphCompiler


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
SOURCES = tuple(sorted((ROOT / "private/casulo-owner/t-v2").glob("critical-*.t")))
NOW = "2026-08-14T00:00:00Z"


def build_authority(tmp_path: Path) -> T85OwnerCriticalAuthority:
    built = TcapV2Builder().build(
        SOURCES, tmp_path / "critical.tcap",
        entry_module="owner.critical.intent", entry_function="decide",
    )
    return T85OwnerCriticalAuthority(RUNTIME, built.directory, tmp_path / "calls")


def graph(project: str = "project-a") -> RequirementGraph:
    return RequirementGraph(
        (
            Requirement("r-domain", "domain behavior", RequirementStrength.HARD, 1, ("human:1",), ("domain",), project),
            Requirement("r-security", "safe effects", RequirementStrength.HARD, 1, ("human:1",), ("security",), project),
            Requirement("r-style", "subjective style", RequirementStrength.SOFT, 1, ("human:1",), ("human",), project),
        )
    )


def receipt(requirement_id: str, verifier_id: str, verdict: Verdict = Verdict.PASS, evidence_class: EvidenceClass = EvidenceClass.DOMAIN_INVARIANT) -> EvidenceReceipt:
    return EvidenceReceipt(
        f"receipt:{requirement_id}:{verifier_id}:{verdict.value}", requirement_id, verifier_id,
        verdict, evidence_class, "a" * 64, "independent-verifier", ("b" * 64,), NOW,
    )


def authority_inputs(aggregate) -> dict:
    return {
        "decision_id": "graph01", "creation_id": "creation01",
        "model_proposed": True, "human_confirmed": True, "material": True,
        "requested_capabilities": ("manifest",), "granted_capabilities": ("manifest",),
        "consent_valid": True, **aggregate.authority_inputs(),
        "safety_pass": True, "unsupported_claims": (), "simulation_status": "PASS",
        "human_publish_approval": True,
    }


def test_t_requirement_graph_is_the_acceptance_authority(tmp_path: Path) -> None:
    aggregate = TRequirementGraphCompiler().compile(
        graph(), (receipt("r-domain", "domain"), receipt("r-security", "security")),
        project_id="project-a", candidate_project_id="project-a",
    )
    decisions = build_authority(tmp_path).decide(**authority_inputs(aggregate))
    assert decisions.committed
    assert decisions.fulfillment.observable["result"] == {"kind": "ok", "value": "FULFILLED"}


@pytest.mark.parametrize(
    "evidence",
    [
        (),
        (receipt("r-domain", "domain"),),
        (receipt("r-domain", "domain", Verdict.FAIL), receipt("r-security", "security")),
        (receipt("r-domain", "domain", Verdict.UNKNOWN), receipt("r-security", "security")),
        (receipt("r-domain", "domain", evidence_class=EvidenceClass.GENERATOR_SELF_REPORT), receipt("r-security", "security")),
    ],
)
def test_missing_failed_unknown_or_self_report_hard_evidence_blocks(tmp_path: Path, evidence) -> None:
    aggregate = TRequirementGraphCompiler().compile(
        graph(), evidence, project_id="project-a", candidate_project_id="project-a",
    )
    with pytest.raises(T85AuthorityDenied, match="hard_evidence|hard_requirement"):
        build_authority(tmp_path).decide(**authority_inputs(aggregate))


def test_project_bleed_is_denied_by_t(tmp_path: Path) -> None:
    aggregate = TRequirementGraphCompiler().compile(
        graph(), (receipt("r-domain", "domain"), receipt("r-security", "security")),
        project_id="project-a", candidate_project_id="project-b",
    )
    with pytest.raises(T85AuthorityDenied, match="project_scope_mismatch"):
        build_authority(tmp_path).decide(**authority_inputs(aggregate))


def test_t85_holdout_suite_is_frozen_before_generation_and_blocks_without_evidence(tmp_path: Path) -> None:
    path = ROOT / "private/casulo-owner/tests/holdouts/t85-requirement-graph-v1.json"
    suite = json.loads(path.read_text(encoding="utf-8"))
    assert suite["available_to_generation_context"] is False
    cases = [case for family in suite["families"] for case in family["cases"]]
    assert len(suite["families"]) == 4
    assert len(cases) == 12
    assert hashlib.sha256(path.read_bytes()).hexdigest()
    authority = build_authority(tmp_path)
    false_completions = 0
    blocked = 0
    for index, case in enumerate(cases):
        requirements = tuple(
            Requirement(
                f"{case['case_id']}:{item}", item, RequirementStrength.HARD, 1,
                (f"sealed:{case['case_id']}",), (f"domain:{item}",), case["case_id"],
            )
            for item in case["hard"]
        )
        aggregate = TRequirementGraphCompiler().compile(
            RequirementGraph(requirements), (),
            project_id=case["case_id"], candidate_project_id=case["case_id"],
        )
        values = authority_inputs(aggregate)
        values.update(decision_id=f"holdout{index:02d}", creation_id=case["case_id"])
        try:
            authority.decide(**values)
        except T85AuthorityDenied:
            blocked += 1
        else:
            false_completions += 1
    assert blocked == 12
    assert false_completions == 0


def test_einstein_generic_text_cannot_replace_domain_evidence(tmp_path: Path) -> None:
    engine = FulfillmentEngine(default_domain_registry())
    collected = engine.collect_evidence(
        "scientific-computing",
        {"title": "Einstein Ricci tensor compiled", "claims": ["solver geral"]},
        source_event_id="human:einstein", scope="einstein", occurred_at=NOW,
    )
    aggregate = TRequirementGraphCompiler().compile(
        collected.graph, collected.evidence,
        project_id="einstein", candidate_project_id="einstein",
    )
    values = authority_inputs(aggregate)
    values.update(decision_id="einstein-generic", creation_id="einstein", unsupported_claims=collected.unsupported_claims)
    with pytest.raises(T85AuthorityDenied):
        build_authority(tmp_path).decide(**values)


def test_real_minkowski_kernel_can_supply_bounded_domain_evidence() -> None:
    problem = {
        "coordinates": ["t", "x", "y", "z"], "coordinate_point": [0.0] * 4,
        "metric": [["-1", "0", "0", "0"], ["0", "1", "0", "0"], ["0", "0", "1", "0"], ["0", "0", "0", "1"]],
        "constants": {"G": 6.67430e-11, "c": 299792458.0, "Lambda": 0.0},
        "energy_momentum_tensor": [[0.0] * 4 for _ in range(4)],
        "initial_conditions": {"hypersurface": "t=0"}, "boundary_conditions": {"type": "asymptotically_flat"},
        "tolerances": {"derivative_step": 1e-5, "residual": 1e-9, "symmetry": 1e-10, "pivot": 1e-12},
        "conventions": {"signature": "-+++", "riemann": "wald", "units": "SI"},
    }
    result = solve(problem)
    assert result["status"] == "PASS" and result["max_abs_residual"] == 0.0
    assert "connection" in result and "ricci_tensor" in result and "einstein_tensor" in result


def test_ts6_sources_do_not_use_substring_or_emit_literal_as_hard_oracle() -> None:
    source = (ROOT / "private/casulo-owner/t-v2/critical-fulfillment.t").read_text(encoding="utf-8")
    transport = (ROOT / "private/casulo-owner/src/casulo_owner/t85_requirements.py").read_text(encoding="utf-8")
    assert "expected_contains" not in source + transport
    assert "emit_literal" not in source + transport
    assert "contains(input.observed_evidence_tokens, token)" in source
    assert "canonical_sha256" in transport
