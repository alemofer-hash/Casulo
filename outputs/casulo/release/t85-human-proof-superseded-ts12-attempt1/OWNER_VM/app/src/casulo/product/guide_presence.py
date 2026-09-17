from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Mapping

from .domain import CollaborationContract
from .living_memory import LivingMemory
from .platform_contracts import Clock, PlatformError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COLLABORATION_FIELDS = frozenset(
    {
        "literalness",
        "humor",
        "interruption_tolerance",
        "correction_directness",
        "pressure",
        "initiative",
        "exploration",
        "containment",
        "silence",
    }
)


class DialogueMode(StrEnum):
    EXPANSION = "EXPANSION"
    CRYSTALLIZATION = "CRYSTALLIZATION"


class GuideAct(StrEnum):
    LISTENING = "LISTENING"
    CLARIFICATION = "CLARIFICATION"
    SYNTHESIS = "SYNTHESIS"
    PROGRESS = "PROGRESS"
    ADAPTATION_PROPOSED = "ADAPTATION_PROPOSED"
    ADAPTATION_APPLIED = "ADAPTATION_APPLIED"
    ADAPTATION_REJECTED = "ADAPTATION_REJECTED"
    CONSTRAINT = "CONSTRAINT"


class JobStatus(StrEnum):
    STARTED = "STARTED"
    MILESTONE = "MILESTONE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_TERMINAL_JOB_STATES = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)


@dataclass(frozen=True, slots=True)
class GuideTurn:
    turn_id: str
    act: GuideAct
    mode: DialogueMode
    text: str
    certainty: str
    source_event_ids: tuple[str, ...]
    background_jobs_active: int
    interruptible: bool = True

    def __post_init__(self) -> None:
        if not self.turn_id or not self.text.strip() or not self.source_event_ids:
            raise PlatformError("turno do Guia exige identidade, texto e proveniência")
        if self.certainty not in {"provisional", "proposed", "confirmed", "conflict"}:
            raise PlatformError("certeza do turno do Guia é inválida")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.guide-turn/1.0",
            "turn_id": self.turn_id,
            "act": self.act.value,
            "mode": self.mode.value,
            "text": self.text,
            "certainty": self.certainty,
            "source_event_ids": list(self.source_event_ids),
            "background_jobs_active": self.background_jobs_active,
            "interruptible": self.interruptible,
        }


@dataclass(frozen=True, slots=True)
class CollaborationProposal:
    proposal_id: str
    changes: Mapping[str, int]
    rationale: str
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.rationale.strip() or not self.source_event_ids:
            raise PlatformError("proposta de colaboração exige identidade e proveniência")
        normalized = dict(self.changes)
        if not normalized or set(normalized) - _COLLABORATION_FIELDS:
            raise PlatformError("proposta contém preferência de colaboração desconhecida")
        if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10 for value in normalized.values()):
            raise PlatformError("preferências propostas precisam estar entre 0 e 10")
        if normalized.get("pressure", 0) != 0:
            raise PlatformError("o Guia nunca pode aumentar pressão como adaptação")
        object.__setattr__(self, "changes", normalized)


@dataclass(frozen=True, slots=True)
class JobEvent:
    event_id: str
    job_id: str
    status: JobStatus
    summary: str
    evidence_sha256: str
    source_event_ids: tuple[str, ...]
    occurred_at: str

    def __post_init__(self) -> None:
        if not self.event_id or not self.job_id or not self.summary.strip():
            raise PlatformError("evento de job exige identidade e resumo")
        if not _SHA256.fullmatch(self.evidence_sha256):
            raise PlatformError("evento de job exige SHA-256 de evidência")
        if not self.source_event_ids or not self.occurred_at:
            raise PlatformError("evento de job exige proveniência e timestamp")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.job-event/1.0",
            "event_id": self.event_id,
            "job_id": self.job_id,
            "status": self.status.value,
            "summary": self.summary,
            "evidence_sha256": self.evidence_sha256,
            "source_event_ids": list(self.source_event_ids),
            "occurred_at": self.occurred_at,
        }


class GuidePresence:
    """Dialogue authority that stays responsive while workers evolve independently."""

    def __init__(
        self,
        *,
        clock: Clock,
        memory: LivingMemory | None = None,
        collaboration: CollaborationContract | None = None,
    ) -> None:
        self.clock = clock
        self.memory = memory
        self.collaboration = collaboration or CollaborationContract()
        self.mode = DialogueMode.EXPANSION
        self._turn_sequence = 0
        self._utterance_count = 0
        self._job_states: dict[str, JobStatus] = {}
        self._job_event_ids: set[str] = set()
        self._resolved_proposals: set[str] = set()

    @property
    def active_job_count(self) -> int:
        return sum(status not in _TERMINAL_JOB_STATES for status in self._job_states.values())

    def respond(self, *, event_id: str, text: str, final: bool = True) -> GuideTurn:
        cleaned = text.strip()
        if not event_id or not cleaned:
            raise PlatformError("fala ao Guia exige identidade e texto")
        if not final:
            return self._turn(
                GuideAct.LISTENING,
                f"Estou ouvindo: {cleaned}",
                "provisional",
                (event_id,),
            )
        self._utterance_count += 1
        if self._needs_clarification(cleaned):
            return self._turn(
                GuideAct.CLARIFICATION,
                "Quero preservar sua intenção sem completar lacunas por você. O que exatamente deve acontecer?",
                "proposed",
                (event_id,),
            )
        if self.mode is DialogueMode.EXPANSION:
            question = (
                "Entendi o começo. Qual finalidade essa criação precisa cumprir primeiro?"
                if self._utterance_count == 1
                else "Estou acompanhando. Qual restrição não pode ser violada enquanto damos forma a isso?"
            )
            return self._turn(GuideAct.LISTENING, question, "proposed", (event_id,))
        return self._turn(
            GuideAct.SYNTHESIS,
            f"Minha leitura provisória é: {cleaned}. Você confirma essa formulação?",
            "proposed",
            (event_id,),
        )

    def crystallize(self, *, summary: str, source_event_ids: tuple[str, ...]) -> GuideTurn:
        if not summary.strip() or not source_event_ids:
            raise PlatformError("cristalização exige síntese e proveniência")
        self.mode = DialogueMode.CRYSTALLIZATION
        return self._turn(
            GuideAct.SYNTHESIS,
            f"A forma que emergiu até aqui é: {summary.strip()}. O que precisa ser corrigido antes do acordo?",
            "proposed",
            source_event_ids,
        )

    def review_constraint(
        self,
        *,
        requested: str,
        conflicts: tuple[str, ...],
        source_event_ids: tuple[str, ...],
    ) -> GuideTurn:
        if not requested.strip() or not source_event_ids:
            raise PlatformError("revisão exige pedido e proveniência")
        if conflicts:
            return self._turn(
                GuideAct.CONSTRAINT,
                "Não vou concordar automaticamente: " + "; ".join(conflicts),
                "conflict",
                source_event_ids,
            )
        return self._turn(
            GuideAct.SYNTHESIS,
            f"O pedido é compatível com as restrições registradas: {requested.strip()}",
            "confirmed",
            source_event_ids,
        )

    def propose_adaptation(
        self,
        *,
        proposal_id: str,
        changes: Mapping[str, int],
        rationale: str,
        source_event_ids: tuple[str, ...],
    ) -> tuple[CollaborationProposal, GuideTurn]:
        proposal = CollaborationProposal(proposal_id, changes, rationale, source_event_ids)
        details = ", ".join(f"{name}={value}" for name, value in sorted(proposal.changes.items()))
        return proposal, self._turn(
            GuideAct.ADAPTATION_PROPOSED,
            f"Percebi uma preferência possível ({details}), mas só aplicarei com sua confirmação explícita.",
            "proposed",
            proposal.source_event_ids,
        )

    def resolve_adaptation(
        self,
        proposal: CollaborationProposal,
        *,
        accepted: bool,
        human_event_id: str,
        explicit_human_approval: bool,
    ) -> GuideTurn:
        if proposal.proposal_id in self._resolved_proposals:
            raise PlatformError("proposta de colaboração já foi resolvida")
        if not human_event_id:
            raise PlatformError("decisão de colaboração exige evento humano")
        if accepted and not explicit_human_approval:
            raise PlatformError("adaptação exige aprovação humana explícita")
        self._resolved_proposals.add(proposal.proposal_id)
        if not accepted:
            return self._turn(
                GuideAct.ADAPTATION_REJECTED,
                "Entendido. A adaptação foi rejeitada e não alterou seu perfil.",
                "confirmed",
                (human_event_id, *proposal.source_event_ids),
            )
        self.collaboration = replace(
            self.collaboration,
            **dict(proposal.changes),
            consented=True,
        )
        if self.memory is not None:
            self.memory.append(
                event_id=f"collaboration:{proposal.proposal_id}",
                kind="COLLABORATION",
                subject_id="guide:collaboration",
                text=proposal.rationale,
                payload=self.collaboration.to_dict(),
                source_ids=(human_event_id, *proposal.source_event_ids),
            )
        return self._turn(
            GuideAct.ADAPTATION_APPLIED,
            "Preferência aplicada com seu consentimento; você pode revogá-la depois.",
            "confirmed",
            (human_event_id, *proposal.source_event_ids),
        )

    def accept_job_event(self, event: JobEvent) -> GuideTurn:
        if event.event_id in self._job_event_ids:
            raise PlatformError("evento de job duplicado")
        previous = self._job_states.get(event.job_id)
        if previous is None and event.status is not JobStatus.STARTED:
            raise PlatformError("job precisa começar por evento STARTED")
        if previous in _TERMINAL_JOB_STATES:
            raise PlatformError("job terminal não aceita novos eventos")
        if previous is not None and event.status is JobStatus.STARTED:
            raise PlatformError("job já iniciado")
        self._job_event_ids.add(event.event_id)
        self._job_states[event.job_id] = event.status
        return self._turn(
            GuideAct.PROGRESS,
            event.summary,
            "confirmed",
            (event.event_id, *event.source_event_ids),
        )

    def _turn(
        self,
        act: GuideAct,
        text: str,
        certainty: str,
        source_event_ids: tuple[str, ...],
    ) -> GuideTurn:
        self._turn_sequence += 1
        return GuideTurn(
            turn_id=f"guide:{self._turn_sequence}",
            act=act,
            mode=self.mode,
            text=text,
            certainty=certainty,
            source_event_ids=source_event_ids,
            background_jobs_active=self.active_job_count,
        )

    @staticmethod
    def _needs_clarification(text: str) -> bool:
        words = re.findall(r"[\wÀ-ÿ]+", text.casefold())
        ambiguous = {"isso", "aquilo", "coisa", "talvez", "qualquer"}
        return len(words) < 3 or bool(ambiguous.intersection(words))
