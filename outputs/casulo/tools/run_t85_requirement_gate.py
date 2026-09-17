from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "private/casulo-owner/src"))

from casulo.product.revolution_contracts import (  # noqa: E402
    EvidenceClass,
    EvidenceReceipt,
    Requirement,
    RequirementGraph,
    RequirementStrength,
    Verdict,
    canonical_sha256,
)
from casulo.product.semantic_fulfillment import FulfillmentEngine, default_domain_registry  # noqa: E402
from casulo.t.v2_tcap import TcapV2Builder  # noqa: E402
from casulo_owner.einstein_solver_kernel import solve  # noqa: E402
from casulo_owner.t85_authority import T85AuthorityDenied, T85OwnerCriticalAuthority  # noqa: E402
from casulo_owner.t85_requirements import TRequirementGraphCompiler  # noqa: E402


NOW = "2026-08-14T00:00:00Z"


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def decision_inputs(aggregate, decision_id: str, creation_id: str, *, unsupported: tuple[str, ...] = ()) -> dict:
    return {
        "decision_id": decision_id,
        "creation_id": creation_id,
        "model_proposed": True,
        "human_confirmed": True,
        "material": True,
        "requested_capabilities": ("manifest",),
        "granted_capabilities": ("manifest",),
        "consent_valid": True,
        **aggregate.authority_inputs(),
        "safety_pass": True,
        "unsupported_claims": unsupported,
        "simulation_status": "PASS",
        "human_publish_approval": True,
    }


def minkowski() -> dict:
    return {
        "coordinates": ["t", "x", "y", "z"],
        "coordinate_point": [0.0, 0.0, 0.0, 0.0],
        "metric": [["-1", "0", "0", "0"], ["0", "1", "0", "0"], ["0", "0", "1", "0"], ["0", "0", "0", "1"]],
        "constants": {"G": 6.67430e-11, "c": 299792458.0, "Lambda": 0.0},
        "energy_momentum_tensor": [[0.0] * 4 for _ in range(4)],
        "initial_conditions": {"hypersurface": "t=0"},
        "boundary_conditions": {"type": "asymptotically_flat"},
        "tolerances": {"derivative_step": 1e-5, "residual": 1e-9, "symmetry": 1e-10, "pivot": 1e-12},
        "conventions": {"signature": "-+++", "riemann": "wald", "units": "SI"},
    }


def candidates() -> dict[str, dict]:
    einstein = solve(minkowski())
    if not (
        einstein["status"] == "PASS"
        and einstein["max_abs_residual"] == 0.0
        and all(key in einstein for key in ("connection", "ricci_tensor", "ricci_scalar", "einstein_tensor", "field_equation_residual"))
        and einstein["scope"] == "local 4D residual evaluation for a user-declared differentiable metric"
        and "does not integrate the global nonlinear Einstein initial-boundary-value problem" in einstein["limitations"]
    ):
        raise RuntimeError("Einstein bounded-domain verifier failed")
    return {
        "scientific-computing": {
            "science": {
                "inputs": ["metric", "coordinates", "constants", "stress_energy", "conditions", "tolerances"],
                "operators": ["levi_civita", "ricci_tensor", "ricci_scalar", "einstein_tensor"],
                "outputs": ["field_equation_residual"],
                "scope": "local-4d-evaluator",
                "refusals": ["global-pde-solver"],
            },
            "claims": ["avaliador tensorial local 4D"],
            "kernel_result_sha256": canonical_sha256(einstein),
        },
        "administrative-workflow": {
            "workflow": {"human_decision_required": True, "provenance": ["receipt:1"], "audit_log": "append-only"},
            "security": {"network_default": "deny"},
        },
        "stream-processing": {
            "stream": {"preserve_original": True, "memory_limit_bytes": 1048576, "time_semantics": "event-time", "explain_transform": True}
        },
        "interactive-creative-tool": {
            "creative": {"project_isolation": True, "barge_in": True, "export": "editable", "progress_source": "job-events-only"}
        },
        "local-software-service": {
            "service": {"bind": "127.0.0.1", "schema_validation": True, "standalone": True, "round_trip_fidelity": 1.0}
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or ROOT.resolve() not in output.parents:
        raise SystemExit("output must be new and inside the repository")
    output.mkdir(parents=True)

    sources = tuple(sorted((ROOT / "private/casulo-owner/t-v2").glob("critical-*.t")))
    built = TcapV2Builder().build(sources, output / "owner-requirements.tcap", entry_module="owner.critical.intent", entry_function="decide")
    runtime = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
    authority = T85OwnerCriticalAuthority(runtime, built.directory, output / "calls")
    compiler = TRequirementGraphCompiler()
    verifier = FulfillmentEngine(default_domain_registry())

    conformance: list[dict] = []
    for index, (pack_id, candidate) in enumerate(candidates().items()):
        collected = verifier.collect_evidence(
            pack_id, candidate, source_event_id=f"human:{pack_id}", scope=pack_id, occurred_at=NOW,
        )
        aggregate = compiler.compile(
            collected.graph, collected.evidence,
            project_id=pack_id, candidate_project_id=pack_id,
        )
        decisions = authority.decide(
            **decision_inputs(aggregate, f"domain{index:02d}", pack_id, unsupported=collected.unsupported_claims)
        )
        dump(output / "evidence-plans" / f"{pack_id}.json", aggregate.evidence_plan)
        conformance.append({
            "pack_id": pack_id,
            "status": "PASS" if decisions.committed else "FAIL",
            "candidate_sha256": collected.candidate_sha256,
            "evidence_count": len(collected.evidence),
            "evidence_plan_hash": aggregate.evidence_plan_hash,
            "fulfillment_receipt": decisions.fulfillment.receipt,
            "foreign_acceptance_consumed": False,
        })

    suite_path = ROOT / "private/casulo-owner/tests/holdouts/t85-requirement-graph-v1.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    holdouts: list[dict] = []
    cases = [(family["family_id"], case) for family in suite["families"] for case in family["cases"]]
    for index, (family_id, case) in enumerate(cases):
        graph = RequirementGraph(tuple(
            Requirement(
                f"{case['case_id']}:{item}", item, RequirementStrength.HARD, 1,
                (f"sealed:{case['case_id']}",), (f"domain:{item}",), case["case_id"],
            )
            for item in case["hard"]
        ))
        aggregate = compiler.compile(graph, (), project_id=case["case_id"], candidate_project_id=case["case_id"])
        status = "UNEXPECTED_PASS"
        diagnostic = ""
        try:
            authority.decide(**decision_inputs(aggregate, f"holdout{index:02d}", case["case_id"]))
        except T85AuthorityDenied as error:
            status = "BLOCKED"
            diagnostic = str(error)
        dump(output / "evidence-plans" / f"{case['case_id']}.json", aggregate.evidence_plan)
        holdouts.append({
            "family_id": family_id,
            "case_id": case["case_id"],
            "status": status,
            "reason": diagnostic,
            "hard_requirements": len(case["hard"]),
            "observed_evidence": 0,
            "evidence_plan_hash": aggregate.evidence_plan_hash,
        })

    original = {"service": {"bind": "0.0.0.0", "schema_validation": True}}
    before = verifier.collect_evidence(
        "local-software-service", original, source_event_id="human:repair", scope="repair", occurred_at=NOW,
    )
    repaired = deepcopy(original)
    repaired["service"].update({"bind": "127.0.0.1", "standalone": True, "round_trip_fidelity": 1.0})
    after = verifier.collect_evidence(
        "local-software-service", repaired, source_event_id="human:repair", scope="repair", occurred_at=NOW,
    )
    repaired_aggregate = compiler.compile(after.graph, after.evidence, project_id="repair", candidate_project_id="repair")
    repaired_decisions = authority.decide(**decision_inputs(repaired_aggregate, "repair01", "repair"))
    repair = {
        "classification": "ARCHITECTURE",
        "before_candidate_sha256": before.candidate_sha256,
        "before_diagnostics": [item.to_dict() for item in before.diagnostics],
        "after_candidate_sha256": after.candidate_sha256,
        "effects_expanded": False,
        "T_fulfillment": repaired_decisions.fulfillment.observable["result"],
        "receipt_hash": repaired_decisions.fulfillment.receipt["receipt_hash"],
    }

    generic = verifier.collect_evidence(
        "scientific-computing", {"title": "Einstein Ricci compiled", "claims": ["solver geral das PDEs de Einstein"]},
        source_event_id="human:einstein", scope="einstein-generic", occurred_at=NOW,
    )
    generic_aggregate = compiler.compile(generic.graph, generic.evidence, project_id="einstein-generic", candidate_project_id="einstein-generic")
    generic_status = "UNEXPECTED_PASS"
    try:
        authority.decide(**decision_inputs(generic_aggregate, "einstein-generic", "einstein-generic", unsupported=generic.unsupported_claims))
    except T85AuthorityDenied as error:
        generic_status = f"BLOCKED:{error}"
    einstein = {
        "generic_text_candidate": generic_status,
        "bounded_kernel": conformance[0],
        "authorized_claim": "avaliador tensorial local 4D parametrizavel; Minkowski no vacuo validado",
        "forbidden_claim": "solver geral das PDEs de Einstein",
    }

    pass_count = sum(item["status"] == "PASS" for item in conformance) + int(repaired_decisions.committed)
    false_hard_completion = sum(item["status"] == "UNEXPECTED_PASS" for item in holdouts) + int(generic_status == "UNEXPECTED_PASS")
    report = {
        "schema": "casulo.t85.requirement-gate/1.0",
        "gate": "TS6_T_REQUIREMENT_GRAPH_PASS",
        "tcap_hash": built.tcap_hash,
        "holdout_suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "families": len(suite["families"]),
        "holdouts": len(cases),
        "holdouts_blocked_honestly": sum(item["status"] == "BLOCKED" for item in holdouts),
        "bounded_passes": pass_count,
        "false_hard_completion": false_hard_completion,
        "FCR": 0.0 if pass_count and false_hard_completion == 0 else None,
        "substring_hard_oracle": False,
        "generator_self_report_authority": False,
        "foreign_acceptance_consumed": False,
        "all_hard_approved_or_blocked": all(item["status"] in {"BLOCKED", "PASS"} for item in holdouts),
        "conformance": conformance,
        "holdout_results": holdouts,
        "architecture_repair": repair,
        "einstein_regression": einstein,
        "locks": {"cloud": "RELEASE_LOCKED", "network": "OFF", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
    }
    dump(output / "requirement-gate.json", report)
    dump(output / "holdout-results.json", holdouts)
    dump(output / "architecture-repair.json", repair)
    dump(output / "einstein-regression.json", einstein)
    dump(output / "gate.json", {key: report[key] for key in ("gate", "families", "holdouts", "holdouts_blocked_honestly", "bounded_passes", "false_hard_completion", "FCR", "all_hard_approved_or_blocked")})
    print(json.dumps(json.loads((output / "gate.json").read_text(encoding="utf-8")), indent=2))
    return 0 if report["FCR"] == 0.0 and report["all_hard_approved_or_blocked"] and report["holdouts"] == 12 else 1


if __name__ == "__main__":
    raise SystemExit(main())
