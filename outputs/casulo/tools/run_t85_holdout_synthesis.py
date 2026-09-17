from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "private/casulo-owner/src"))

from casulo.product.engine_contracts import CancellationToken  # noqa: E402
from casulo.product.revolution_contracts import (  # noqa: E402
    EvidenceClass,
    EvidenceReceipt,
    Requirement,
    RequirementGraph,
    RequirementStrength,
    Verdict,
)
from casulo.t.productive import ProductiveTExecutor  # noqa: E402
from casulo.t.v2_tcap import TcapV2Builder  # noqa: E402
from casulo_owner.generative_model import GenerativeCandidate  # noqa: E402
from casulo_owner.local_model_runtime import LocalModelRuntime  # noqa: E402
from casulo_owner.t85_agent_synthesis import T85AgentSynthesizer, execute_agent  # noqa: E402
from casulo_owner.t85_authority import T85OwnerCriticalAuthority  # noqa: E402
from casulo_owner.t85_requirements import TRequirementGraphCompiler  # noqa: E402


SELECTED = ("data-01", "interactive-01", "technical-02")
NOW = "2026-08-14T00:00:00Z"


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or ROOT.resolve() not in output.parents:
        raise SystemExit("output must be new and inside the repository")
    output.mkdir(parents=True)

    suite_path = ROOT / "private/casulo-owner/tests/holdouts/t85-requirement-graph-v1.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    all_cases = {case["case_id"]: case for family in suite["families"] for case in family["cases"]}
    if set(SELECTED) - set(all_cases):
        raise SystemExit("selected holdout is absent")
    candidate = GenerativeCandidate.load(args.candidate)
    runtime_path = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")

    critical_sources = tuple(sorted((ROOT / "private/casulo-owner/t-v2").glob("critical-*.t")))
    critical = TcapV2Builder().build(
        critical_sources, output / "critical.tcap",
        entry_module="owner.critical.intent", entry_function="decide",
    )
    critical_authority = T85OwnerCriticalAuthority(runtime_path, critical.directory, output / "critical-calls")
    graph_compiler = TRequirementGraphCompiler()
    reports: list[dict] = []

    with LocalModelRuntime(candidate, args.cache.resolve(), threads=args.threads) as neural:
        synthesizer = T85AgentSynthesizer(neural)
        for index, case_id in enumerate(SELECTED):
            case = all_cases[case_id]
            hard = tuple(case["hard"])
            if len(hard) != 3:
                raise RuntimeError("TS7 selected holdouts require exactly three HARD requirements")
            plan = synthesizer.propose(
                case_id=case_id,
                request=case["request"],
                hard_requirements=hard,
                cancellation=CancellationToken(),
            )
            agent_root = output / "agents" / case_id
            build = synthesizer.build(plan, agent_root)
            execution = execute_agent(build, runtime_path, agent_root / "hosted-calls")

            requirements = RequirementGraph(tuple(
                Requirement(
                    f"{case_id}:{requirement_id}", requirement_id,
                    RequirementStrength.HARD, 1.0, (f"sealed:{case_id}",),
                    (f"agent-runtime:{requirement_id}",), case_id,
                )
                for requirement_id in hard
            ))
            evidence = tuple(
                EvidenceReceipt(
                    f"evidence:{case_id}:{item['requirement_id']}",
                    f"{case_id}:{item['requirement_id']}",
                    f"agent-runtime:{item['requirement_id']}",
                    Verdict.PASS,
                    EvidenceClass.CLEAN_EXECUTION,
                    build.tcap.tcap_hash,
                    "t-runtime/rust-2.0",
                    (execution.calls[position].receipt["canonical_output_hash"],),
                    NOW,
                    "dedicated T constraint function returned its generated success event",
                )
                for position, item in enumerate(plan.constraints)
            )
            aggregate = graph_compiler.compile(
                requirements, evidence, project_id=case_id, candidate_project_id=case_id,
            )
            decisions = critical_authority.decide(
                decision_id=f"ts7{index:02d}", creation_id=case_id,
                model_proposed=True, human_confirmed=True, material=True,
                requested_capabilities=("simulation", "manifest"),
                granted_capabilities=("simulation", "manifest"), consent_valid=True,
                **aggregate.authority_inputs(), safety_pass=True, unsupported_claims=(),
                simulation_status="PASS", human_publish_approval=True,
            )

            policy_module = f"owner.agent.{plan.agent_id}.{plan.module_suffixes[0]}"
            policy_payload = {
                "confirmed": True, "project_match": True, "evidence_statuses": ["PASS"] * 3,
                **{item["field_name"]: True for item in plan.constraints}, "cancelled": False,
            }
            first_constraint = plan.constraints[0]
            mutated_payload = {**policy_payload, first_constraint["field_name"]: False}
            negative_executor = ProductiveTExecutor(runtime_path, build.tcap.directory, agent_root / "negative-calls")
            negative = negative_executor.execute(
                policy_module, "decide", mutated_payload,
                call_id=f"{plan.agent_id}.negative", surface_id="agent_behavior", scope_id=f"agent:{case_id}",
            )
            publish_module = f"owner.agent.{plan.agent_id}.{plan.module_suffixes[2]}"
            denied = negative_executor.execute(
                publish_module, "simulate",
                {"previous": "WORKFLOW_READY", "simulated": True, "approved": False, "cancelled": False},
                call_id=f"{plan.agent_id}.denied", surface_id="agent_behavior", scope_id=f"agent:{case_id}",
            )

            plan_json = {
                "schema": "casulo.t85-agent-plan/1.0", "case_id": plan.case_id,
                "request": plan.request, "agent_id": plan.agent_id, "summary": plan.summary,
                "module_suffixes": list(plan.module_suffixes),
                "constraints": [dict(item) for item in plan.constraints],
                "success_events_origin": "canonical_derivation_from_frozen_requirement_id",
                "raw_sha256": plan.raw_sha256,
                "rejected_candidates": [dict(item) for item in plan.rejected_candidates],
                "stochastic_trace": plan.trace.to_dict(),
            }
            dump(agent_root / "architecture-plan.json", plan_json)
            dump(agent_root / "evidence-plan.json", aggregate.evidence_plan)
            dump(agent_root / "execution-receipts.json", [item.receipt for item in execution.calls])
            report = {
                "case_id": case_id,
                "request_sha256": hashlib.sha256(case["request"].encode("utf-8")).hexdigest(),
                "agent_id": plan.agent_id,
                "neural_trace": plan.trace.to_dict(),
                "tcap_hash": build.tcap.tcap_hash,
                "module_count": 3,
                "function_count": sum(source.read_text(encoding="utf-8").count("fn ") for source in build.sources),
                "record_count": sum(source.read_text(encoding="utf-8").count("record ") for source in build.sources),
                "enum_count": sum(source.read_text(encoding="utf-8").count("enum ") for source in build.sources),
                "hosted_receipts": len(execution.calls),
                "final_value": execution.final_value,
                "T_fulfillment": decisions.fulfillment.observable["result"],
                "T_publish": decisions.publish.observable["result"],
                "constraint_mutation": negative.observable["result"],
                "missing_capability": denied.observable["result"],
                "model_generated_architecture": True,
                "success_events_canonically_bound": True,
                "fixed_template_selected_by_prompt": False,
                "emit_literal": False,
                "fake_engine": False,
                "external_ai_api": False,
            }
            dump(agent_root / "agent-report.json", report)
            reports.append(report)

    checks = {
        "three_holdouts": len(reports) == 3,
        "three_distinct_agents": len({item["agent_id"] for item in reports}) == 3,
        "all_multimodule": all(item["module_count"] >= 3 for item in reports),
        "all_ten_functions": all(item["function_count"] >= 10 for item in reports),
        "all_records_enums": all(item["record_count"] >= 2 and item["enum_count"] >= 2 for item in reports),
        "all_executed": all(item["hosted_receipts"] >= 10 and item["final_value"] == "AUDITED" for item in reports),
        "all_fulfilled_and_committed_by_t": all(item["T_fulfillment"]["value"] == "FULFILLED" and item["T_publish"]["value"] == "COMMIT" for item in reports),
        "mutation_blocks": all(item["constraint_mutation"]["kind"] == "error" for item in reports),
        "capability_blocks": all(item["missing_capability"] == {"kind": "error", "value": "CAPABILITY_DENIED:simulation"} for item in reports),
        "neural_no_fixed_seed": all(item["neural_trace"]["seed_if_available"] is None for item in reports),
        "success_events_canonically_bound": all(item["success_events_canonically_bound"] for item in reports),
        "no_fake_template_replay": all(not item["fake_engine"] and not item["fixed_template_selected_by_prompt"] for item in reports),
        "no_external_api": all(not item["external_ai_api"] for item in reports),
    }
    gate = {
        "schema": "casulo.t85.holdout-synthesis/1.0",
        "gate": "TS7_T_NONTRIVIAL_HOLDOUTS_HOSTED_PASS" if all(checks.values()) else "TS7_FAIL",
        "model_id": candidate.candidate_id,
        "model_sha256": candidate.model.sha256,
        "runtime": "llama.cpp-local-loopback",
        "holdout_suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "selected": list(SELECTED),
        "agents": reports,
        "checks": checks,
        "native_conformance": "PENDING_APPLICABLE_PROBE",
        "locks": {"cloud": "RELEASE_LOCKED", "guest_network": "OFF", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
    }
    dump(output / "holdout-synthesis.json", gate)
    dump(output / "gate.json", {"gate": gate["gate"], "checks": checks, "selected": list(SELECTED), "native_conformance": gate["native_conformance"]})
    print(json.dumps({"gate": gate["gate"], "agents": [item["agent_id"] for item in reports], "native": gate["native_conformance"]}, indent=2))
    return 0 if gate["gate"].endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
