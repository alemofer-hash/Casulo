from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable

from casulo.t.resource import SemanticClass


MIN_PRIORITY = -20
MAX_PRIORITY = 20
MAX_BUDGET_TICKS = 1_000_000
MAX_DEADLINE_TICK = 1_000_000_000


@dataclass(frozen=True, slots=True)
class SemanticTask:
    task_id: str
    semantic_class: SemanticClass
    budget_ticks: int
    integrity_valid: bool = True
    permissions_valid: bool = True
    quality_valid: bool = True
    isolation_valid: bool = True
    priority: int = 0
    deadline_tick: int | None = None

    def __post_init__(self) -> None:
        if not self.task_id or not 1 <= self.budget_ticks <= MAX_BUDGET_TICKS:
            raise ValueError("task id and budget must be bounded")
        if not MIN_PRIORITY <= self.priority <= MAX_PRIORITY:
            raise ValueError("priority outside supported bounds")
        if self.deadline_tick is not None and not 1 <= self.deadline_tick <= MAX_DEADLINE_TICK:
            raise ValueError("deadline_tick outside supported bounds")


@dataclass(frozen=True, slots=True)
class AdmissionEvent:
    sequence: int
    task_id: str
    requested_class: SemanticClass
    admitted_class: SemanticClass
    reason: str


@dataclass(frozen=True, slots=True)
class ScheduleEvent:
    tick: int
    task_id: str
    semantic_class: SemanticClass
    decision: str
    remaining_ticks: int
    priority: int = 0
    deadline_tick: int | None = None
    deadline_missed: bool = False
    selection_checks: int = 0


@dataclass(slots=True)
class _QueuedTask:
    task: SemanticTask
    remaining: int
    sequence: int
    enqueued_tick: int


class _SchedulerBase:
    """Shared admission and accounting for deterministic reference policies."""

    policy_name = "base"

    def __init__(self) -> None:
        self.tick = 0
        self._sequence = 0
        self.trace: list[ScheduleEvent] = []
        self.admissions: list[AdmissionEvent] = []
        self.selection_checks = 0
        self.dispatches = 0
        self._quarantine: Deque[_QueuedTask] = deque()

    def _admit(self, task: SemanticTask) -> tuple[_QueuedTask, SemanticClass]:
        reason = self._gate_reason(task)
        destination = SemanticClass.QUARANTINE if reason else task.semantic_class
        if destination is SemanticClass.QUARANTINE and reason is None:
            reason = "requested_quarantine"
        sequence = self._sequence
        self._sequence += 1
        queued = _QueuedTask(task, task.budget_ticks, sequence, self.tick)
        self.admissions.append(
            AdmissionEvent(sequence, task.task_id, task.semantic_class, destination, reason or "all_hard_gates_passed")
        )
        if destination is SemanticClass.QUARANTINE:
            self._quarantine.append(queued)
        return queued, destination

    @staticmethod
    def _gate_reason(task: SemanticTask) -> str | None:
        failures = []
        if not task.integrity_valid:
            failures.append("integrity")
        if not task.permissions_valid:
            failures.append("permissions")
        if not task.quality_valid:
            failures.append("quality")
        if not task.isolation_valid:
            failures.append("isolation")
        return "hard_gate_failed:" + ",".join(failures) if failures else None

    def run(self, *, maximum_ticks: int) -> tuple[ScheduleEvent, ...]:
        if not 1 <= maximum_ticks <= MAX_BUDGET_TICKS:
            raise ValueError("maximum_ticks outside supported bounds")
        events: list[ScheduleEvent] = []
        for _ in range(maximum_ticks):
            event = self.step()
            if event is None:
                break
            events.append(event)
        return tuple(events)

    def quarantined(self) -> tuple[str, ...]:
        return tuple(item.task.task_id for item in self._quarantine)

    def completed(self, semantic_class: SemanticClass | None = None) -> tuple[ScheduleEvent, ...]:
        return tuple(
            event
            for event in self.trace
            if event.remaining_ticks == 0 and (semantic_class is None or event.semantic_class is semantic_class)
        )

    def overhead_proxy(self) -> dict[str, int | str]:
        """Operation counts only; deliberately not elapsed time or energy."""

        return {
            "unit": "deterministic_reference_operation_count",
            "admission_gate_checks": len(self.admissions) * 4,
            "selection_checks": self.selection_checks,
            "dispatches": self.dispatches,
            "total_proxy_operations": len(self.admissions) * 4 + self.selection_checks + self.dispatches,
        }

    def step(self) -> ScheduleEvent | None:  # pragma: no cover - protocol-like base
        raise NotImplementedError


class SemanticScheduler(_SchedulerBase):
    """Deterministic semantic policy; this is a host reference, not a speed claim.

    Hard gates precede all ranking. Audit work receives a reserved dispatch at
    each ``audit_interval`` boundary while pending. Otherwise class priority is
    lexicographic; inside a class, earlier deadline, higher priority and FIFO
    sequence break ties. Every dispatch consumes exactly one bounded budget tick.
    """

    policy_name = "semantic_v1"
    _ORDER = (
        SemanticClass.FLOW,
        SemanticClass.SYSTEM,
        SemanticClass.ATTRACTOR_RETRY,
        SemanticClass.ATTRACTOR_LOW_CONFIDENCE,
        SemanticClass.ATTRACTOR_AUDIT,
    )

    def __init__(self, *, audit_interval: int = 8) -> None:
        super().__init__()
        if not 2 <= audit_interval <= 1024:
            raise ValueError("audit_interval outside supported bounds")
        self.audit_interval = audit_interval
        self._queues: dict[SemanticClass, list[_QueuedTask]] = {item: [] for item in SemanticClass}

    def enqueue(self, task: SemanticTask) -> SemanticClass:
        queued, destination = self._admit(task)
        if destination is not SemanticClass.QUARANTINE:
            self._queues[destination].append(queued)
        return destination

    def step(self) -> ScheduleEvent | None:
        selected, reason, checks = self._select_queue()
        self.selection_checks += checks
        if selected is None:
            return None
        queue = self._queues[selected]
        index, rank_checks = self._rank_index(queue)
        self.selection_checks += rank_checks
        queued = queue.pop(index)
        queued.remaining -= 1
        self.tick += 1
        self.dispatches += 1
        missed = queued.task.deadline_tick is not None and self.tick > queued.task.deadline_tick
        event = ScheduleEvent(
            self.tick,
            queued.task.task_id,
            selected,
            reason,
            queued.remaining,
            queued.task.priority,
            queued.task.deadline_tick,
            missed,
            checks + rank_checks,
        )
        self.trace.append(event)
        if queued.remaining:
            queue.append(queued)
        return event

    def _select_queue(self) -> tuple[SemanticClass | None, str, int]:
        checks = 1
        audit = self._queues[SemanticClass.ATTRACTOR_AUDIT]
        if audit and (self.tick + 1) % self.audit_interval == 0:
            return SemanticClass.ATTRACTOR_AUDIT, "periodic_non_starvation", checks
        for item in self._ORDER:
            checks += 1
            if self._queues[item]:
                return item, "deterministic_semantic_priority", checks
        return None, "idle", checks

    @staticmethod
    def _rank_index(queue: list[_QueuedTask]) -> tuple[int, int]:
        def key(item: _QueuedTask) -> tuple[int, int, int]:
            deadline = item.task.deadline_tick if item.task.deadline_tick is not None else MAX_DEADLINE_TICK + 1
            return deadline, -item.task.priority, item.sequence

        best = min(range(len(queue)), key=lambda index: key(queue[index]))
        return best, len(queue)


class ConventionalScheduler(_SchedulerBase):
    """Deterministic flat FIFO round-robin comparator with identical hard gates."""

    policy_name = "conventional_fifo_round_robin_v1"

    def __init__(self) -> None:
        super().__init__()
        self._ready: Deque[_QueuedTask] = deque()

    def enqueue(self, task: SemanticTask) -> SemanticClass:
        queued, destination = self._admit(task)
        if destination is not SemanticClass.QUARANTINE:
            self._ready.append(queued)
        return destination

    def step(self) -> ScheduleEvent | None:
        self.selection_checks += 1
        if not self._ready:
            return None
        queued = self._ready.popleft()
        queued.remaining -= 1
        self.tick += 1
        self.dispatches += 1
        missed = queued.task.deadline_tick is not None and self.tick > queued.task.deadline_tick
        event = ScheduleEvent(
            self.tick,
            queued.task.task_id,
            queued.task.semantic_class,
            "deterministic_fifo_round_robin",
            queued.remaining,
            queued.task.priority,
            queued.task.deadline_tick,
            missed,
            1,
        )
        self.trace.append(event)
        if queued.remaining:
            self._ready.append(queued)
        return event


def enqueue_all(scheduler: _SchedulerBase, tasks: Iterable[SemanticTask]) -> None:
    for task in tasks:
        scheduler.enqueue(task)  # type: ignore[attr-defined]
