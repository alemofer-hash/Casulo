from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

from .guide_presence import JobEvent, JobStatus
from .platform_contracts import PlatformError


class ContinuityError(PlatformError):
    pass


class ContinuityMode(StrEnum):
    EXPLORATION = "EXPLORATION"
    CRYSTALLIZATION = "CRYSTALLIZATION"


class RecordKind(StrEnum):
    DECISION = "DECISION"
    REJECTED = "REJECTED"
    HYPOTHESIS = "HYPOTHESIS"
    QUESTION = "QUESTION"
    UNCERTAINTY = "UNCERTAINTY"
    THREAD = "THREAD"


class ConstraintStrength(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class ConstraintStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONFLICT = "CONFLICT"
    RESOLVED = "RESOLVED"


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[\wÀ-ÿ]+", text.casefold()))


@dataclass(frozen=True, slots=True)
class GuideRecord:
    record_id: str
    project_id: str
    kind: RecordKind
    text: str
    source_event_ids: tuple[str, ...]
    sequence: int
    criticality: int = 0
    unresolved: bool = False
    privacy_cost: int = 0

    def __post_init__(self) -> None:
        if not self.record_id or not self.project_id or not self.text.strip():
            raise ContinuityError("registro de continuidade incompleto")
        if not self.source_event_ids or self.sequence < 1:
            raise ContinuityError("registro exige provenance e sequência")
        if any(value < 0 or value > 10 for value in (self.criticality, self.privacy_cost)):
            raise ContinuityError("criticality/privacy fora do intervalo")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "project_id": self.project_id,
            "kind": self.kind.value,
            "text": self.text,
            "source_event_ids": list(self.source_event_ids),
            "sequence": self.sequence,
            "criticality": self.criticality,
            "unresolved": self.unresolved,
            "privacy_cost": self.privacy_cost,
        }


@dataclass(frozen=True, slots=True)
class ConstraintEntry:
    constraint_id: str
    project_id: str
    key: str
    statement: str
    strength: ConstraintStrength
    status: ConstraintStatus
    source_event_ids: tuple[str, ...]
    sequence: int
    conflicts_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.constraint_id or not self.project_id or not self.key or not self.statement.strip():
            raise ContinuityError("constraint incompleta")
        if not self.source_event_ids or self.sequence < 1:
            raise ContinuityError("constraint exige provenance e sequência")

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "project_id": self.project_id,
            "key": self.key,
            "statement": self.statement,
            "strength": self.strength.value,
            "status": self.status.value,
            "source_event_ids": list(self.source_event_ids),
            "sequence": self.sequence,
            "conflicts_with": list(self.conflicts_with),
        }


@dataclass(frozen=True, slots=True)
class ConstraintReview:
    compatible: bool
    blocking: bool
    active: tuple[ConstraintEntry, ...]
    conflicts: tuple[ConstraintEntry, ...]
    requires_human_decision: bool


class ConstraintLedger:
    """Append-only constraints: contradiction creates state; it never overwrites."""

    def __init__(self) -> None:
        self._entries: list[ConstraintEntry] = []

    @property
    def entries(self) -> tuple[ConstraintEntry, ...]:
        return tuple(self._entries)

    def add(
        self,
        *,
        constraint_id: str,
        project_id: str,
        key: str,
        statement: str,
        strength: ConstraintStrength,
        source_event_ids: tuple[str, ...],
        sequence: int,
    ) -> ConstraintEntry:
        if any(item.constraint_id == constraint_id for item in self._entries):
            raise ContinuityError("constraint_id duplicada")
        active_same_key = tuple(
            item
            for item in self._entries
            if item.project_id == project_id
            and item.key == key
            and item.status in {ConstraintStatus.ACTIVE, ConstraintStatus.CONFLICT}
        )
        normalized = " ".join(statement.casefold().split())
        conflicts = tuple(
            item.constraint_id
            for item in active_same_key
            if " ".join(item.statement.casefold().split()) != normalized
        )
        entry = ConstraintEntry(
            constraint_id,
            project_id,
            key,
            statement,
            strength,
            ConstraintStatus.CONFLICT if conflicts else ConstraintStatus.ACTIVE,
            source_event_ids,
            sequence,
            conflicts,
        )
        self._entries.append(entry)
        return entry

    def resolve(
        self,
        *,
        winning_constraint_id: str,
        human_event_id: str,
        explicit_human_approval: bool,
        sequence: int,
    ) -> ConstraintEntry:
        if not human_event_id or not explicit_human_approval:
            raise ContinuityError("conflito material exige decisão humana explícita")
        winner = next((item for item in self._entries if item.constraint_id == winning_constraint_id), None)
        if winner is None:
            raise ContinuityError("constraint vencedora desconhecida")
        related = {
            item.constraint_id
            for item in self._entries
            if item.project_id == winner.project_id and item.key == winner.key
        }
        resolved = ConstraintEntry(
            f"resolution:{winning_constraint_id}:{sequence}",
            winner.project_id,
            winner.key,
            winner.statement,
            winner.strength,
            ConstraintStatus.RESOLVED,
            (human_event_id, *winner.source_event_ids),
            sequence,
            tuple(sorted(related - {winning_constraint_id})),
        )
        self._entries.append(resolved)
        return resolved

    def review(self, project_id: str) -> ConstraintReview:
        scoped = tuple(item for item in self._entries if item.project_id == project_id)
        resolved_keys = {item.key for item in scoped if item.status is ConstraintStatus.RESOLVED}
        conflicts = tuple(
            item for item in scoped if item.status is ConstraintStatus.CONFLICT and item.key not in resolved_keys
        )
        active = tuple(
            item
            for item in scoped
            if item.status is ConstraintStatus.RESOLVED
            or (item.status is ConstraintStatus.ACTIVE and item.key not in resolved_keys)
        )
        blocking = any(item.strength is ConstraintStrength.HARD for item in conflicts)
        return ConstraintReview(not conflicts, blocking, active, conflicts, bool(conflicts))


@dataclass(frozen=True, slots=True)
class QuestionCandidate:
    question_id: str
    text: str
    current_entropy: float
    expected_entropy_after: float
    interruption_cost: float
    hard_constraint_unknown: bool = False

    @property
    def information_gain(self) -> float:
        return self.current_entropy - self.expected_entropy_after

    @property
    def utility(self) -> float:
        return self.information_gain - self.interruption_cost


@dataclass(frozen=True, slots=True)
class ContinuityContextItem:
    ref_id: str
    text: str
    source: str
    priority: int


@dataclass(frozen=True, slots=True)
class DialogueDirective:
    project_id: str
    mode: ContinuityMode
    mandatory_constraints: tuple[str, ...]
    context_items: tuple[ContinuityContextItem, ...]
    selected_question: QuestionCandidate | None
    conflicts: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    state_sha256: str


class DialogueDirector:
    """Selects objectives/context; a neural runtime realizes the actual wording."""

    def direct(
        self,
        *,
        project_id: str,
        mode: ContinuityMode,
        constraints: ConstraintReview,
        context: Sequence[GuideRecord],
        questions: Sequence[QuestionCandidate],
        state_sha256: str,
    ) -> DialogueDirective:
        eligible = [item for item in questions if item.hard_constraint_unknown or item.utility > 0]
        selected = max(
            eligible,
            key=lambda item: (item.hard_constraint_unknown, item.utility, item.question_id),
            default=None,
        )
        mandatory = tuple(item.statement for item in constraints.active if item.strength is ConstraintStrength.HARD)
        conflicts = tuple(item.statement for item in constraints.conflicts)
        items = tuple(
            ContinuityContextItem(
                item.record_id,
                item.text,
                f"guide-continuity:{item.project_id}",
                min(100, 20 + item.criticality * 6 + (15 if item.unresolved else 0)),
            )
            for item in context
        )
        source_ids = tuple(dict.fromkeys(source for item in context for source in item.source_event_ids))
        return DialogueDirective(project_id, mode, mandatory, items, selected, conflicts, source_ids or ("continuity:empty",), state_sha256)


class GuideContinuityKernel:
    """Deterministic canonical state beneath generative Guide language."""

    def __init__(self) -> None:
        self.mode = ContinuityMode.EXPLORATION
        self._sequence = 0
        self._projects: set[str] = set()
        self._records: list[GuideRecord] = []
        self.constraints = ConstraintLedger()
        self._jobs: dict[str, JobStatus] = {}
        self._job_events: list[JobEvent] = []
        self._event_log: list[dict[str, Any]] = []

    @classmethod
    def from_event_log(cls, events: Sequence[Mapping[str, Any]]) -> "GuideContinuityKernel":
        if not verify_event_chain(events):
            raise ContinuityError("event log de continuidade adulterado")
        kernel = cls()
        for raw_event in events:
            kind = str(raw_event["kind"])
            payload = dict(raw_event["payload"])
            if kind == "PROJECT_OPENED":
                kernel._projects.add(str(payload["project_id"]))
            elif kind == "MODE_CHANGED":
                kernel.mode = ContinuityMode(str(payload["mode"]))
            elif kind == "RECORD_ADDED":
                kernel._records.append(
                    GuideRecord(
                        str(payload["record_id"]),
                        str(payload["project_id"]),
                        RecordKind(str(payload["kind"])),
                        str(payload["text"]),
                        tuple(str(item) for item in payload["source_event_ids"]),
                        int(payload["sequence"]),
                        int(payload["criticality"]),
                        bool(payload["unresolved"]),
                        int(payload["privacy_cost"]),
                    )
                )
            elif kind in {"CONSTRAINT_ADDED", "CONSTRAINT_RESOLVED"}:
                kernel.constraints._entries.append(
                    ConstraintEntry(
                        str(payload["constraint_id"]),
                        str(payload["project_id"]),
                        str(payload["key"]),
                        str(payload["statement"]),
                        ConstraintStrength(str(payload["strength"])),
                        ConstraintStatus(str(payload["status"])),
                        tuple(str(item) for item in payload["source_event_ids"]),
                        int(payload["sequence"]),
                        tuple(str(item) for item in payload["conflicts_with"]),
                    )
                )
            elif kind == "JOB_EVENT":
                event = JobEvent(
                    str(payload["event_id"]),
                    str(payload["job_id"]),
                    JobStatus(str(payload["status"])),
                    str(payload["summary"]),
                    str(payload["evidence_sha256"]),
                    tuple(str(item) for item in payload["source_event_ids"]),
                    str(payload["occurred_at"]),
                )
                kernel._job_events.append(event)
                kernel._jobs[event.job_id] = event.status
            else:
                raise ContinuityError(f"evento de continuidade desconhecido: {kind}")
            kernel._sequence = int(raw_event["sequence"])
            kernel._event_log.append(dict(raw_event))
        return kernel

    @property
    def event_log(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._event_log)

    def open_project(self, project_id: str, *, source_event_id: str) -> None:
        if not project_id or not source_event_id:
            raise ContinuityError("projeto exige identidade e provenance")
        self._projects.add(project_id)
        self._append_event("PROJECT_OPENED", {"project_id": project_id, "source_event_id": source_event_id})

    def set_mode(self, mode: ContinuityMode, *, source_event_id: str) -> None:
        self.mode = mode
        self._append_event("MODE_CHANGED", {"mode": mode.value, "source_event_id": source_event_id})

    def record(
        self,
        *,
        record_id: str,
        project_id: str,
        kind: RecordKind,
        text: str,
        source_event_ids: tuple[str, ...],
        criticality: int = 0,
        unresolved: bool = False,
        privacy_cost: int = 0,
    ) -> GuideRecord:
        if project_id not in self._projects:
            raise ContinuityError("registro não pode escapar de projeto aberto")
        if any(item.record_id == record_id for item in self._records):
            raise ContinuityError("record_id duplicado")
        self._sequence += 1
        item = GuideRecord(record_id, project_id, kind, text, source_event_ids, self._sequence, criticality, unresolved, privacy_cost)
        self._records.append(item)
        self._append_event("RECORD_ADDED", item.to_dict(), increment=False)
        return item

    def add_constraint(
        self,
        *,
        constraint_id: str,
        project_id: str,
        key: str,
        statement: str,
        strength: ConstraintStrength,
        source_event_ids: tuple[str, ...],
    ) -> ConstraintEntry:
        if project_id not in self._projects:
            raise ContinuityError("constraint exige projeto aberto")
        self._sequence += 1
        entry = self.constraints.add(
            constraint_id=constraint_id,
            project_id=project_id,
            key=key,
            statement=statement,
            strength=strength,
            source_event_ids=source_event_ids,
            sequence=self._sequence,
        )
        self._append_event("CONSTRAINT_ADDED", entry.to_dict(), increment=False)
        return entry

    def resolve_constraint(
        self,
        *,
        winning_constraint_id: str,
        human_event_id: str,
        explicit_human_approval: bool,
    ) -> ConstraintEntry:
        self._sequence += 1
        entry = self.constraints.resolve(
            winning_constraint_id=winning_constraint_id,
            human_event_id=human_event_id,
            explicit_human_approval=explicit_human_approval,
            sequence=self._sequence,
        )
        self._append_event("CONSTRAINT_RESOLVED", entry.to_dict(), increment=False)
        return entry

    def accept_job_event(self, event: JobEvent) -> None:
        previous = self._jobs.get(event.job_id)
        terminal = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        if previous is None and event.status is not JobStatus.STARTED:
            raise ContinuityError("job precisa começar por STARTED")
        if previous in terminal or (previous is not None and event.status is JobStatus.STARTED):
            raise ContinuityError("transição de job inválida")
        if any(item.event_id == event.event_id for item in self._job_events):
            raise ContinuityError("evento de job duplicado")
        self._jobs[event.job_id] = event.status
        self._job_events.append(event)
        self._append_event("JOB_EVENT", event.to_dict())

    def select_context(self, *, project_id: str, query: str, budget_chars: int) -> tuple[GuideRecord, ...]:
        if project_id not in self._projects or budget_chars < 1:
            raise ContinuityError("seleção de contexto inválida")
        mandatory = [
            item
            for item in self._records
            if item.project_id == project_id and item.kind in {RecordKind.DECISION, RecordKind.REJECTED} and item.criticality >= 8
        ]
        mandatory_cost = sum(len(item.text) for item in mandatory)
        if mandatory_cost > budget_chars:
            raise ContinuityError("restrições/memórias mandatórias excedem budget; recorte silencioso negado")
        query_tokens = _tokens(query)

        def score(item: GuideRecord) -> tuple[float, int, str]:
            overlap = len(query_tokens & _tokens(item.text)) / max(1, len(query_tokens | _tokens(item.text)))
            recency = item.sequence / max(1, self._sequence)
            value = overlap * 6 + item.criticality + (3 if item.unresolved else 0) + recency - item.privacy_cost
            return value, item.sequence, item.record_id

        candidates = sorted(
            (item for item in self._records if item.project_id == project_id and item not in mandatory),
            key=score,
            reverse=True,
        )
        selected = list(mandatory)
        used = mandatory_cost
        for item in candidates:
            if used + len(item.text) > budget_chars:
                continue
            selected.append(item)
            used += len(item.text)
        return tuple(selected)

    def directive(
        self,
        *,
        project_id: str,
        query: str,
        budget_chars: int,
        questions: Sequence[QuestionCandidate] = (),
        director: DialogueDirector | None = None,
    ) -> DialogueDirective:
        context = self.select_context(project_id=project_id, query=query, budget_chars=budget_chars)
        review = self.constraints.review(project_id)
        return (director or DialogueDirector()).direct(
            project_id=project_id,
            mode=self.mode,
            constraints=review,
            context=context,
            questions=questions,
            state_sha256=self.state_sha256,
        )

    @property
    def state_sha256(self) -> str:
        return _sha(self.snapshot())

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "casulo.guide-continuity-state/1.0",
            "mode": self.mode.value,
            "projects": sorted(self._projects),
            "records": [item.to_dict() for item in self._records],
            "constraints": [item.to_dict() for item in self.constraints.entries],
            "jobs": {key: value.value for key, value in sorted(self._jobs.items())},
            "job_event_ids": [item.event_id for item in self._job_events],
            "event_count": len(self._event_log),
        }

    def _append_event(self, kind: str, payload: Mapping[str, Any], *, increment: bool = True) -> None:
        if increment:
            self._sequence += 1
        unsigned = {"sequence": self._sequence, "kind": kind, "payload": dict(payload)}
        previous = self._event_log[-1]["event_hash"] if self._event_log else "0" * 64
        event_hash = _sha({"previous_hash": previous, **unsigned})
        self._event_log.append({**unsigned, "previous_hash": previous, "event_hash": event_hash})


def verify_event_chain(events: Iterable[Mapping[str, Any]]) -> bool:
    previous = "0" * 64
    expected_sequence = 1
    for event in events:
        if event.get("sequence") != expected_sequence or event.get("previous_hash") != previous:
            return False
        unsigned = {"sequence": event["sequence"], "kind": event["kind"], "payload": event["payload"]}
        if event.get("event_hash") != _sha({"previous_hash": previous, **unsigned}):
            return False
        previous = str(event["event_hash"])
        expected_sequence += 1
    return True
