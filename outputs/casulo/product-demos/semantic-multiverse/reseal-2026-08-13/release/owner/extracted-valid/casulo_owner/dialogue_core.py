from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum

from casulo.product.guide_presence import JobEvent
from casulo.product.platform_contracts import PlatformError

from .generative_engine import ContextItem, ContextTrust, OwnerTurnContext
from .local_model_runtime import ChatMessage


SCIENCE_BROS_CONTRACT = "casulo-science-bros/1.0"


class RelationalMode(StrEnum):
    EXPLORATION = "EXPLORATION"
    CRYSTALLIZATION = "CRYSTALLIZATION"


@dataclass(frozen=True, slots=True)
class RelationshipProfile:
    warmth: int = 6
    challenge: int = 7
    humor: int = 3
    initiative: int = 7
    brevity: int = 6
    consented: bool = False

    def __post_init__(self) -> None:
        values = (self.warmth, self.challenge, self.humor, self.initiative, self.brevity)
        if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10 for value in values):
            raise PlatformError("preferência relacional precisa estar entre 0 e 10")

    def prompt_fragment(self) -> str:
        return (
            f"calor={self.warmth}/10; desafio={self.challenge}/10; "
            f"humor={self.humor}/10; iniciativa={self.initiative}/10; "
            f"concisão={self.brevity}/10"
        )


@dataclass(frozen=True, slots=True)
class RelationshipProposal:
    proposal_id: str
    changes: tuple[tuple[str, int], ...]
    rationale: str
    source_event_id: str

    def __post_init__(self) -> None:
        allowed = {"warmth", "challenge", "humor", "initiative", "brevity"}
        if not self.proposal_id or not self.rationale.strip() or not self.source_event_id:
            raise PlatformError("proposta relacional incompleta")
        if not self.changes or any(key not in allowed or not 0 <= value <= 10 for key, value in self.changes):
            raise PlatformError("mudança relacional inválida")


class GenerativeDialogueCore:
    """Compõe o contrato relacional; todo texto de resposta vem do runtime neural."""

    CONTRACT_RULES = (
        "Não use abertura fixa nem elogio automático.",
        "Fale como colega, não como atendente nem texto corporativo.",
        "Quando discordar, dê a razão concreta em vez de concordar por reflexo.",
        "Apresente consequência não dita como hipótese, nunca como fato.",
        "Pergunte somente quando a ambiguidade mudar materialmente o agente.",
        "Não interrompa a ideia por detalhes irrelevantes e não fale para preencher silêncio.",
        "Nunca alegue progresso sem um JobEvent verificável no contexto.",
        "Não use diagnóstico, gênero ou qualquer estereótipo para adaptar colaboração.",
        "Nenhuma preferência material muda sem consentimento humano explícito.",
    )

    def __init__(self, profile: RelationshipProfile | None = None) -> None:
        self.profile = profile or RelationshipProfile()
        self._resolved: set[str] = set()

    def propose_relationship_change(
        self,
        *,
        proposal_id: str,
        changes: dict[str, int],
        rationale: str,
        source_event_id: str,
    ) -> RelationshipProposal:
        return RelationshipProposal(
            proposal_id,
            tuple(sorted(changes.items())),
            rationale,
            source_event_id,
        )

    def resolve_relationship_change(
        self,
        proposal: RelationshipProposal,
        *,
        accepted: bool,
        explicit_human_approval: bool,
        human_event_id: str,
    ) -> RelationshipProfile:
        if proposal.proposal_id in self._resolved:
            raise PlatformError("proposta relacional já resolvida")
        if not human_event_id:
            raise PlatformError("mudança relacional exige evento humano")
        if accepted and not explicit_human_approval:
            raise PlatformError("mudança relacional exige consentimento humano explícito")
        self._resolved.add(proposal.proposal_id)
        if not accepted:
            return self.profile
        self.profile = replace(self.profile, **dict(proposal.changes), consented=True)
        return self.profile

    def context_for_turn(
        self,
        *,
        session_id: str,
        utterance: str,
        conversation: tuple[ChatMessage, ...] = (),
        mode: RelationalMode = RelationalMode.EXPLORATION,
        hard_constraints: tuple[str, ...] = (),
        memory_items: tuple[ContextItem, ...] = (),
        job_events: tuple[JobEvent, ...] = (),
    ) -> OwnerTurnContext:
        job_items = tuple(self._job_context(event) for event in job_events)
        relational = (
            f"Contrato relacional {SCIENCE_BROS_CONTRACT}; modo={mode.value}; "
            f"preferências consentidas={self.profile.consented}; {self.profile.prompt_fragment()}.",
            *self.CONTRACT_RULES,
        )
        return OwnerTurnContext(
            session_id,
            utterance,
            conversation,
            (*relational, *hard_constraints),
            (*memory_items, *job_items),
        )

    @staticmethod
    def _job_context(event: JobEvent) -> ContextItem:
        # JobEvent já validou ID, hash, origem e timestamp. O modelo só recebe o
        # estado observado, sem autoridade para promover esse estado.
        return ContextItem(
            f"job:{event.event_id}",
            json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True),
            ContextTrust.LOCAL_DERIVED,
            "guide-presence-job-event",
            50,
        )
