from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from casulo.t.resource import SemanticClass

from .scheduler import ConventionalScheduler, ScheduleEvent, SemanticScheduler, SemanticTask, enqueue_all


EVIDENCE_SCHEMA = "casulo-semantic-scheduler-functional-evidence/1"


@dataclass(frozen=True, slots=True)
class PreregisteredScenario:
    scenario_id: str
    hypothesis: str
    expected_relation: str
    causal_variable: str
    controls: tuple[str, ...]
    tasks: tuple[SemanticTask, ...]
    maximum_ticks: int


def preregistered_scenarios() -> tuple[PreregisteredScenario, ...]:
    """Fixed scenarios declared before either policy is evaluated."""

    return (
        PreregisteredScenario(
            scenario_id="controlled_interference_help",
            hypothesis="semantic classification reduces FLOW completion latency under non-FLOW interference",
            expected_relation="semantic_flow_p95_lt_conventional_flow_p95",
            causal_variable="scheduler_policy_only",
            controls=(
                "identical_task_multiset",
                "identical_enqueue_order",
                "identical_one_tick_dispatch_cost",
                "identical_hard_gates",
                "no_wall_clock_measurement",
            ),
            tasks=(
                SemanticTask("noise-system", SemanticClass.SYSTEM, 8),
                SemanticTask("noise-retry", SemanticClass.ATTRACTOR_RETRY, 8),
                SemanticTask("flow-a", SemanticClass.FLOW, 2, priority=4, deadline_tick=8),
                SemanticTask("flow-b", SemanticClass.FLOW, 2, priority=2, deadline_tick=10),
                SemanticTask("audit", SemanticClass.ATTRACTOR_AUDIT, 2),
                SemanticTask("low-confidence", SemanticClass.ATTRACTOR_LOW_CONFIDENCE, 2),
            ),
            maximum_ticks=24,
        ),
        PreregisteredScenario(
            scenario_id="controlled_no_help",
            hypothesis="semantic classification provides no completion advantage when every admitted task is FLOW-equivalent",
            expected_relation="semantic_flow_p95_eq_conventional_flow_p95",
            causal_variable="scheduler_policy_only",
            controls=(
                "identical_task_multiset",
                "all_tasks_same_semantic_class",
                "identical_priority_and_no_deadlines",
                "identical_enqueue_order",
                "identical_one_tick_dispatch_cost",
                "no_wall_clock_measurement",
            ),
            tasks=tuple(SemanticTask(f"flow-{index}", SemanticClass.FLOW, 1) for index in range(1, 7)),
            maximum_ticks=6,
        ),
    )


def build_functional_evidence() -> dict[str, Any]:
    scenario_results = [_run_scenario(spec) for spec in preregistered_scenarios()]
    safety = _safety_proof()
    starvation = _non_starvation_proof()
    reference_vector = {
        scenario["scenario_id"]: {
            policy: result["events"]
            for policy, result in scenario["policies"].items()
        }
        for scenario in scenario_results
    }
    reference_vector_sha256 = hashlib.sha256(
        json.dumps(reference_vector, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assertions = {
        "help_relation_holds": scenario_results[0]["relation_holds"],
        "no_help_relation_holds": scenario_results[1]["relation_holds"],
        "all_required_queues_exercised": scenario_results[0]["all_required_queues_exercised"],
        "hard_gates_hold": safety["hard_gates_hold"],
        "quarantine_never_executed": safety["quarantine_never_executed"],
        "audit_non_starvation_bound_holds": starvation["bound_holds"],
        "finite_workload_completes": starvation["finite_workload_completes"],
    }
    return {
        "schema": EVIDENCE_SCHEMA,
        "status": "PASS" if all(assertions.values()) else "FAIL",
        "claim_scope": "deterministic_functional_reference_only",
        "excluded_claims": [
            "no_wall_clock_speedup",
            "no_energy_advantage",
            "no_kernel_scheduler_equivalence",
            "no_S6_claim",
        ],
        "preregistration": {
            "frozen_before_execution": True,
            "scenarios": [_scenario_manifest(item) for item in preregistered_scenarios()],
        },
        "assertions": assertions,
        "scenario_results": scenario_results,
        "reference_vector_sha256": reference_vector_sha256,
        "safety_proof": safety,
        "non_starvation_proof": starvation,
        "kernel_port_markers": [
            "CASULO_G4_POLICY_ID=semantic_v1",
            "CASULO_G4_HARD_GATES=integrity,permissions,quality,isolation",
            "CASULO_G4_AUDIT_BOUND_TICKS=<configured_interval>",
            "CASULO_G4_QUARANTINE_DISPATCHES=0",
            f"CASULO_G4_REFERENCE_VECTOR_SHA256={reference_vector_sha256}",
        ],
    }


def write_functional_evidence(output_directory: Path) -> dict[str, Path]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    evidence = build_functional_evidence()
    json_path = output / "scheduler-functional-evidence.json"
    csv_path = output / "scheduler-events.csv"
    markdown_path = output / "scheduler-functional-report.md"
    json_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(evidence, csv_path)
    markdown_path.write_text(_markdown(evidence), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": markdown_path}


def _run_scenario(spec: PreregisteredScenario) -> dict[str, Any]:
    policies: tuple[tuple[str, Callable[[], Any]], ...] = (
        ("semantic_v1", lambda: SemanticScheduler(audit_interval=4)),
        ("conventional_fifo_round_robin_v1", ConventionalScheduler),
    )
    results: dict[str, Any] = {}
    for name, factory in policies:
        scheduler = factory()
        enqueue_all(scheduler, spec.tasks)
        events = scheduler.run(maximum_ticks=spec.maximum_ticks)
        completion = _completion_metrics(events, SemanticClass.FLOW)
        results[name] = {
            "events": [_event_dict(event) for event in events],
            "flow": completion,
            "deadline_misses": sum(event.deadline_missed for event in events if event.remaining_ticks == 0),
            "overhead_proxy": scheduler.overhead_proxy(),
            "quarantined": list(scheduler.quarantined()),
        }
    semantic_p95 = results["semantic_v1"]["flow"]["p95_style_completion_latency_ticks"]
    conventional_p95 = results["conventional_fifo_round_robin_v1"]["flow"]["p95_style_completion_latency_ticks"]
    relation = semantic_p95 < conventional_p95 if spec.expected_relation.endswith("_lt_conventional_flow_p95") else semantic_p95 == conventional_p95
    exercised = {
        event["semantic_class"]
        for event in results["semantic_v1"]["events"]
    }
    required = {item.value for item in SemanticClass if item is not SemanticClass.QUARANTINE}
    return {
        "scenario_id": spec.scenario_id,
        "hypothesis": spec.hypothesis,
        "expected_relation": spec.expected_relation,
        "relation_holds": relation,
        "all_required_queues_exercised": required <= exercised if spec.scenario_id == "controlled_interference_help" else True,
        "policies": results,
    }


def _safety_proof() -> dict[str, Any]:
    scheduler = SemanticScheduler(audit_interval=4)
    invalid = (
        SemanticTask("bad-integrity", SemanticClass.FLOW, 1, integrity_valid=False),
        SemanticTask("bad-permission", SemanticClass.SYSTEM, 1, permissions_valid=False),
        SemanticTask("bad-quality", SemanticClass.ATTRACTOR_RETRY, 1, quality_valid=False),
        SemanticTask("bad-isolation", SemanticClass.ATTRACTOR_LOW_CONFIDENCE, 1, isolation_valid=False),
        SemanticTask("requested-quarantine", SemanticClass.QUARANTINE, 1),
    )
    enqueue_all(scheduler, invalid)
    events = scheduler.run(maximum_ticks=32)
    quarantined = list(scheduler.quarantined())
    expected = [task.task_id for task in invalid]
    return {
        "invalid_task_ids": expected,
        "quarantined_task_ids": quarantined,
        "executed_task_ids": [event.task_id for event in events],
        "admissions": [
            {
                **asdict(event),
                "requested_class": event.requested_class.value,
                "admitted_class": event.admitted_class.value,
            }
            for event in scheduler.admissions
        ],
        "hard_gates_hold": quarantined == expected,
        "quarantine_never_executed": not events,
    }


def _non_starvation_proof() -> dict[str, Any]:
    interval = 4
    scheduler = SemanticScheduler(audit_interval=interval)
    scheduler.enqueue(SemanticTask("persistent-flow", SemanticClass.FLOW, 20))
    scheduler.enqueue(SemanticTask("audit", SemanticClass.ATTRACTOR_AUDIT, 4))
    events = scheduler.run(maximum_ticks=20)
    audit_ticks = [event.tick for event in events if event.semantic_class is SemanticClass.ATTRACTOR_AUDIT]
    gaps_from_origin = [audit_ticks[0], *[right - left for left, right in zip(audit_ticks, audit_ticks[1:])]]
    completion_scheduler = SemanticScheduler(audit_interval=interval)
    finite = (
        SemanticTask("flow", SemanticClass.FLOW, 2),
        SemanticTask("system", SemanticClass.SYSTEM, 2),
        SemanticTask("retry", SemanticClass.ATTRACTOR_RETRY, 2),
        SemanticTask("low", SemanticClass.ATTRACTOR_LOW_CONFIDENCE, 2),
        SemanticTask("audit", SemanticClass.ATTRACTOR_AUDIT, 2),
    )
    enqueue_all(completion_scheduler, finite)
    finite_events = completion_scheduler.run(maximum_ticks=sum(task.budget_ticks for task in finite))
    completed_ids = {event.task_id for event in finite_events if event.remaining_ticks == 0}
    return {
        "audit_interval_ticks": interval,
        "audit_dispatch_ticks": audit_ticks,
        "observed_service_gaps_ticks": gaps_from_origin,
        "maximum_observed_gap_ticks": max(gaps_from_origin),
        "bound_holds": max(gaps_from_origin) <= interval,
        "proof_domain": "pending audit queue under continuously runnable FLOW in a finite deterministic trace",
        "finite_workload_completed_ids": sorted(completed_ids),
        "finite_workload_completes": completed_ids == {task.task_id for task in finite},
    }


def _completion_metrics(events: Sequence[ScheduleEvent], semantic_class: SemanticClass) -> dict[str, Any]:
    completed = [event for event in events if event.semantic_class is semantic_class and event.remaining_ticks == 0]
    latencies = [event.tick for event in completed]
    return {
        "completed_task_ids": [event.task_id for event in completed],
        "completion_latency_ticks": latencies,
        "p95_style_definition": "nearest_rank_on_integer_completion_ticks_from_common_enqueue_origin_tick_0",
        "p95_style_completion_latency_ticks": _nearest_rank(latencies, 0.95),
    }


def _nearest_rank(values: Sequence[int], quantile: float) -> int:
    if not values:
        raise ValueError("at least one value is required")
    ordered = sorted(values)
    rank = max(1, (len(ordered) * int(quantile * 100) + 99) // 100)
    return ordered[min(rank - 1, len(ordered) - 1)]


def _event_dict(event: ScheduleEvent) -> dict[str, Any]:
    value = asdict(event)
    value["semantic_class"] = event.semantic_class.value
    return value


def _scenario_manifest(spec: PreregisteredScenario) -> dict[str, Any]:
    return {
        "scenario_id": spec.scenario_id,
        "hypothesis": spec.hypothesis,
        "expected_relation": spec.expected_relation,
        "causal_variable": spec.causal_variable,
        "controls": list(spec.controls),
        "maximum_ticks": spec.maximum_ticks,
        "tasks": [
            {
                **asdict(task),
                "semantic_class": task.semantic_class.value,
            }
            for task in spec.tasks
        ],
    }


def _write_csv(evidence: dict[str, Any], path: Path) -> None:
    fields = (
        "scenario_id", "policy", "tick", "task_id", "semantic_class", "decision",
        "remaining_ticks", "priority", "deadline_tick", "deadline_missed", "selection_checks",
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for scenario in evidence["scenario_results"]:
            for policy, result in scenario["policies"].items():
                for event in result["events"]:
                    writer.writerow({"scenario_id": scenario["scenario_id"], "policy": policy, **event})


def _markdown(evidence: dict[str, Any]) -> str:
    lines = [
        "# G4 semantic scheduler functional reference",
        "",
        f"Status: **{evidence['status']}**",
        "",
        "Scope: deterministic tick-level correctness only. No wall-clock, energy, kernel-equivalence or S6 claim is made.",
        "",
        "## Pre-registered causal scenarios",
        "",
        "| Scenario | Expected | Semantic FLOW p95 ticks | Conventional FLOW p95 ticks | Holds |",
        "|---|---|---:|---:|---|",
    ]
    for scenario in evidence["scenario_results"]:
        semantic = scenario["policies"]["semantic_v1"]["flow"]["p95_style_completion_latency_ticks"]
        conventional = scenario["policies"]["conventional_fifo_round_robin_v1"]["flow"]["p95_style_completion_latency_ticks"]
        lines.append(
            f"| {scenario['scenario_id']} | `{scenario['expected_relation']}` | {semantic} | {conventional} | {scenario['relation_holds']} |"
        )
    lines.extend((
        "",
        "## Safety and liveness",
        "",
        f"- Hard gates hold: {evidence['assertions']['hard_gates_hold']}",
        f"- Quarantine dispatches: 0 = {evidence['assertions']['quarantine_never_executed']}",
        f"- Audit service bound holds: {evidence['assertions']['audit_non_starvation_bound_holds']}",
        f"- Finite admitted workload completes: {evidence['assertions']['finite_workload_completes']}",
        "",
        "The overhead field is an operation-count proxy, not duration. It permits deterministic implementation comparison without disguising unavailable measurements as performance data.",
        "",
        "## Required kernel markers",
        "",
    ))
    lines.extend(f"- `{marker}`" for marker in evidence["kernel_port_markers"])
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic G4 scheduler correctness evidence")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = write_functional_evidence(args.output)
    print(json.dumps({key: str(value) for key, value in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
