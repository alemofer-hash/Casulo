from __future__ import annotations

import csv
import json

import pytest

from casulo.livelab.scheduler import ConventionalScheduler, SemanticScheduler, SemanticTask
from casulo.livelab.scheduler_evidence import build_functional_evidence, write_functional_evidence
from casulo.t.resource import SemanticClass


def test_invalid_work_is_quarantined_and_never_runs() -> None:
    scheduler = SemanticScheduler()
    destination = scheduler.enqueue(SemanticTask("bad", SemanticClass.FLOW, 4, integrity_valid=False))
    assert destination is SemanticClass.QUARANTINE
    assert scheduler.run(maximum_ticks=10) == ()
    assert scheduler.quarantined() == ("bad",)


def test_flow_has_priority_but_audit_does_not_starve() -> None:
    scheduler = SemanticScheduler(audit_interval=4)
    scheduler.enqueue(SemanticTask("flow", SemanticClass.FLOW, 10))
    scheduler.enqueue(SemanticTask("audit", SemanticClass.ATTRACTOR_AUDIT, 2))
    events = scheduler.run(maximum_ticks=8)
    assert [event.semantic_class for event in events] == [
        SemanticClass.FLOW, SemanticClass.FLOW, SemanticClass.FLOW,
        SemanticClass.ATTRACTOR_AUDIT, SemanticClass.FLOW, SemanticClass.FLOW,
        SemanticClass.FLOW, SemanticClass.ATTRACTOR_AUDIT,
    ]
    assert events[3].decision == "periodic_non_starvation"


def test_schedule_is_deterministic() -> None:
    def run_once() -> tuple[tuple[str, str], ...]:
        scheduler = SemanticScheduler()
        scheduler.enqueue(SemanticTask("flow", SemanticClass.FLOW, 2))
        scheduler.enqueue(SemanticTask("retry", SemanticClass.ATTRACTOR_RETRY, 1))
        return tuple((event.task_id, event.semantic_class.value) for event in scheduler.run(maximum_ticks=3))

    assert run_once() == run_once()


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"integrity_valid": False}, "integrity"),
        ({"permissions_valid": False}, "permissions"),
        ({"quality_valid": False}, "quality"),
        ({"isolation_valid": False}, "isolation"),
    ],
)
@pytest.mark.parametrize("scheduler_type", [SemanticScheduler, ConventionalScheduler])
def test_every_hard_gate_is_fail_closed(
    override: dict[str, bool], reason: str, scheduler_type: type[SemanticScheduler] | type[ConventionalScheduler]
) -> None:
    scheduler = scheduler_type()
    task = SemanticTask("invalid", SemanticClass.FLOW, 1, **override)
    assert scheduler.enqueue(task) is SemanticClass.QUARANTINE
    assert scheduler.step() is None
    assert reason in scheduler.admissions[0].reason


@pytest.mark.parametrize("priority", [-21, 21])
def test_priority_is_bounded(priority: int) -> None:
    with pytest.raises(ValueError, match="priority"):
        SemanticTask("task", SemanticClass.FLOW, 1, priority=priority)


@pytest.mark.parametrize("budget", [0, 1_000_001])
def test_budget_is_bounded(budget: int) -> None:
    with pytest.raises(ValueError, match="budget"):
        SemanticTask("task", SemanticClass.FLOW, budget)


@pytest.mark.parametrize("deadline", [0, 1_000_000_001])
def test_deadline_is_bounded(deadline: int) -> None:
    with pytest.raises(ValueError, match="deadline"):
        SemanticTask("task", SemanticClass.FLOW, 1, deadline_tick=deadline)


def test_deadline_then_priority_then_fifo_are_explicit_tie_breakers() -> None:
    scheduler = SemanticScheduler()
    scheduler.enqueue(SemanticTask("late-high", SemanticClass.FLOW, 1, priority=20, deadline_tick=20))
    scheduler.enqueue(SemanticTask("early-low", SemanticClass.FLOW, 1, priority=-20, deadline_tick=5))
    scheduler.enqueue(SemanticTask("early-high-first", SemanticClass.FLOW, 1, priority=5, deadline_tick=5))
    scheduler.enqueue(SemanticTask("early-high-second", SemanticClass.FLOW, 1, priority=5, deadline_tick=5))
    assert [event.task_id for event in scheduler.run(maximum_ticks=4)] == [
        "early-high-first",
        "early-high-second",
        "early-low",
        "late-high",
    ]


def test_budget_consumption_and_deadline_miss_are_auditable() -> None:
    scheduler = SemanticScheduler()
    scheduler.enqueue(SemanticTask("work", SemanticClass.FLOW, 3, deadline_tick=2))
    events = scheduler.run(maximum_ticks=3)
    assert [event.remaining_ticks for event in events] == [2, 1, 0]
    assert [event.deadline_missed for event in events] == [False, False, True]
    assert scheduler.completed() == (events[-1],)


@pytest.mark.parametrize("audit_interval", [2, 3, 4, 8, 16])
def test_audit_service_bound_property(audit_interval: int) -> None:
    scheduler = SemanticScheduler(audit_interval=audit_interval)
    scheduler.enqueue(SemanticTask("flow", SemanticClass.FLOW, audit_interval * 5))
    scheduler.enqueue(SemanticTask("audit", SemanticClass.ATTRACTOR_AUDIT, 5))
    events = scheduler.run(maximum_ticks=audit_interval * 5)
    ticks = [event.tick for event in events if event.semantic_class is SemanticClass.ATTRACTOR_AUDIT]
    gaps = [ticks[0], *[right - left for left, right in zip(ticks, ticks[1:])]]
    assert max(gaps) <= audit_interval


def test_conventional_comparator_is_flat_deterministic_round_robin() -> None:
    scheduler = ConventionalScheduler()
    scheduler.enqueue(SemanticTask("system", SemanticClass.SYSTEM, 2))
    scheduler.enqueue(SemanticTask("flow", SemanticClass.FLOW, 2))
    assert [event.task_id for event in scheduler.run(maximum_ticks=4)] == ["system", "flow", "system", "flow"]


def test_preregistered_help_and_no_help_cases_hold_without_performance_claim() -> None:
    evidence = build_functional_evidence()
    assert evidence["status"] == "PASS"
    assert evidence["assertions"] == {
        "help_relation_holds": True,
        "no_help_relation_holds": True,
        "all_required_queues_exercised": True,
        "hard_gates_hold": True,
        "quarantine_never_executed": True,
        "audit_non_starvation_bound_holds": True,
        "finite_workload_completes": True,
    }
    assert evidence["claim_scope"] == "deterministic_functional_reference_only"
    assert "no_S6_claim" in evidence["excluded_claims"]
    assert len(evidence["reference_vector_sha256"]) == 64
    int(evidence["reference_vector_sha256"], 16)


def test_evidence_writers_emit_machine_readable_json_csv_and_markdown(tmp_path) -> None:
    paths = write_functional_evidence(tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    with paths["csv"].open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and {row["policy"] for row in rows} == {
        "semantic_v1",
        "conventional_fifo_round_robin_v1",
    }
    report = paths["markdown"].read_text(encoding="utf-8")
    assert "No wall-clock, energy, kernel-equivalence or S6 claim" in report
