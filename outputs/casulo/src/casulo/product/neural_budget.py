from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from .domain import DomainError, canonical_sha256


class NeuralBudgetError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


class NeuralOperation(StrEnum):
    DIALOGUE = "DIALOGUE"
    INTENT_RECONSTRUCTION = "INTENT_RECONSTRUCTION"
    INTENT_REFINEMENT = "INTENT_REFINEMENT"
    SEMANTIC_ROUTING = "SEMANTIC_ROUTING"
    T_SYNTHESIS = "T_SYNTHESIS"
    T_REPAIR = "T_REPAIR"


@dataclass(frozen=True, slots=True)
class NeuralBudget:
    budget_id: str
    operation: NeuralOperation
    sampling_family: str
    max_context_chars: int
    max_prompt_utf8_bytes: int
    max_generated_tokens: int
    runtime_context_tokens: int
    prompt_token_safety_margin: int
    max_conversation_messages: int
    max_memory_items: int
    structured_output: bool

    def __post_init__(self) -> None:
        if not self.budget_id or self.sampling_family not in {"dialogue", "planning", "code"}:
            raise NeuralBudgetError("NB101", "budget neural possui identidade ou família inválida")
        if not 2_048 <= self.max_context_chars <= 96_000:
            raise NeuralBudgetError("NB102", "budget de contexto neural inválido")
        if not 2_048 <= self.max_prompt_utf8_bytes <= 96_000:
            raise NeuralBudgetError("NB115", "budget UTF-8 neural inválido")
        if not 64 <= self.max_generated_tokens <= 2_048:
            raise NeuralBudgetError("NB103", "budget de saída neural inválido")
        if self.runtime_context_tokens < 2_048 or self.prompt_token_safety_margin < 0:
            raise NeuralBudgetError("NB116", "janela física do runtime inválida")
        # Tokenizadores com byte fallback não precisam de mais tokens que bytes
        # UTF-8. A margem cobre chat template e tokens de controle.
        if (
            self.max_prompt_utf8_bytes
            + self.max_generated_tokens
            + self.prompt_token_safety_margin
            > self.runtime_context_tokens
        ):
            raise NeuralBudgetError("NB117", "budget pode exceder a janela física do runtime")
        if not 0 <= self.max_conversation_messages <= 32:
            raise NeuralBudgetError("NB104", "budget de conversa neural inválido")
        if not 0 <= self.max_memory_items <= 128:
            raise NeuralBudgetError("NB105", "budget de memória neural inválido")

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "operation": self.operation.value,
            "sampling_family": self.sampling_family,
            "max_context_chars": self.max_context_chars,
            "max_prompt_utf8_bytes": self.max_prompt_utf8_bytes,
            "max_generated_tokens": self.max_generated_tokens,
            "runtime_context_tokens": self.runtime_context_tokens,
            "prompt_token_safety_margin": self.prompt_token_safety_margin,
            "max_conversation_messages": self.max_conversation_messages,
            "max_memory_items": self.max_memory_items,
            "structured_output": self.structured_output,
        }


NEURAL_BUDGETS: dict[NeuralOperation, NeuralBudget] = {
    NeuralOperation.DIALOGUE: NeuralBudget(
        "arc7-dialogue-v1", NeuralOperation.DIALOGUE, "dialogue",
        5_632, 5_632, 768, 8_192, 256, 8, 12, False,
    ),
    NeuralOperation.INTENT_RECONSTRUCTION: NeuralBudget(
        "arc7-intent-reconstruction-v1", NeuralOperation.INTENT_RECONSTRUCTION,
        "planning", 6_400, 6_400, 768, 8_192, 256, 0, 0, True,
    ),
    NeuralOperation.INTENT_REFINEMENT: NeuralBudget(
        "arc7-intent-refinement-v1", NeuralOperation.INTENT_REFINEMENT,
        "planning", 6_144, 6_144, 768, 8_192, 256, 0, 0, True,
    ),
    NeuralOperation.SEMANTIC_ROUTING: NeuralBudget(
        "arc7-semantic-routing-v1", NeuralOperation.SEMANTIC_ROUTING,
        "planning", 7_424, 7_424, 384, 8_192, 256, 0, 0, True,
    ),
    NeuralOperation.T_SYNTHESIS: NeuralBudget(
        "arc7-t-synthesis-v1", NeuralOperation.T_SYNTHESIS,
        "code", 6_400, 6_400, 1_536, 8_192, 256, 0, 0, True,
    ),
    NeuralOperation.T_REPAIR: NeuralBudget(
        "arc7-t-repair-v1", NeuralOperation.T_REPAIR,
        "code", 7_424, 7_424, 384, 8_192, 256, 0, 0, True,
    ),
}


@dataclass(frozen=True, slots=True)
class NeuralRouteRequest:
    operation: NeuralOperation
    source_event_ids: tuple[str, ...]
    human_confirmed: bool = False
    hard_requirement_count: int = 0
    material_gap_open: bool = False
    diagnostic_present: bool = False

    def __post_init__(self) -> None:
        if not self.source_event_ids or any(not item for item in self.source_event_ids):
            raise NeuralBudgetError("NB106", "rota neural exige proveniência")
        if isinstance(self.hard_requirement_count, bool) or self.hard_requirement_count < 0:
            raise NeuralBudgetError("NB107", "contagem HARD inválida")


@dataclass(frozen=True, slots=True)
class NeuralRouteDecision:
    operation: NeuralOperation
    budget: NeuralBudget
    reason: str
    source_event_ids: tuple[str, ...]
    gates: tuple[tuple[str, bool], ...]
    decision_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.neural-route-decision/1.0",
            "operation": self.operation.value,
            "budget": self.budget.to_dict(),
            "reason": self.reason,
            "source_event_ids": list(self.source_event_ids),
            "gates": dict(self.gates),
            "decision_sha256": self.decision_sha256,
        }


class NeuralBudgetRouter:
    """Selects compute by declared product operation, never by model output."""

    @staticmethod
    def decide(request: NeuralRouteRequest) -> NeuralRouteDecision:
        if request.operation is NeuralOperation.T_SYNTHESIS:
            if not request.human_confirmed:
                raise NeuralBudgetError("NB108", "síntese T exige intenção confirmada")
            if request.hard_requirement_count < 1:
                raise NeuralBudgetError("NB109", "síntese T exige ao menos um requisito HARD")
        if request.operation is NeuralOperation.T_REPAIR:
            if not request.human_confirmed or not request.diagnostic_present:
                raise NeuralBudgetError("NB110", "reparo T exige confirmação e diagnóstico real")
        if request.operation is NeuralOperation.INTENT_REFINEMENT and not request.material_gap_open:
            raise NeuralBudgetError("NB111", "refino neural exige lacuna material aberta")
        budget = NEURAL_BUDGETS[request.operation]
        gates = (
            ("human_confirmed", request.human_confirmed),
            ("hard_requirements_present", request.hard_requirement_count > 0),
            ("material_gap_open", request.material_gap_open),
            ("diagnostic_present", request.diagnostic_present),
        )
        reason = {
            NeuralOperation.DIALOGUE: "presença e conversa sem produção",
            NeuralOperation.INTENT_RECONSTRUCTION: "formar hipótese antes de produzir",
            NeuralOperation.INTENT_REFINEMENT: "resolver uma lacuna material já observada",
            NeuralOperation.SEMANTIC_ROUTING: "propor universos sem conceder autoridade",
            NeuralOperation.T_SYNTHESIS: "produzir T somente após confirmação e requisitos HARD",
            NeuralOperation.T_REPAIR: "corrigir unidade T a partir de diagnóstico real",
        }[request.operation]
        unsigned = {
            "schema": "casulo.neural-route-decision/1.0",
            "operation": request.operation.value,
            "budget": budget.to_dict(),
            "reason": reason,
            "source_event_ids": list(request.source_event_ids),
            "gates": dict(gates),
        }
        return NeuralRouteDecision(
            request.operation,
            budget,
            reason,
            request.source_event_ids,
            gates,
            canonical_sha256(unsigned),
        )


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    ref_id: str
    chars: int
    priority: int
    ordinal: int

    def __post_init__(self) -> None:
        if not self.ref_id or self.chars < 1 or not -100 <= self.priority <= 100:
            raise NeuralBudgetError("NB112", "candidato de contexto inválido")


@dataclass(frozen=True, slots=True)
class ContextSelection:
    included_refs: tuple[str, ...]
    dropped_refs: tuple[str, ...]
    used_chars: int
    budget_chars: int


class SufficientContextSelector:
    """Greedy stable selector; mandatory content is accounted before this call."""

    @staticmethod
    def select(
        candidates: Iterable[ContextCandidate],
        *,
        already_used_chars: int,
        budget_chars: int,
        item_limit: int,
    ) -> ContextSelection:
        if already_used_chars > budget_chars:
            raise NeuralBudgetError(
                "NB113", "conteúdo obrigatório excede budget; descarte silencioso negado"
            )
        values = tuple(candidates)
        ordered = sorted(values, key=lambda item: (-item.priority, item.ordinal))
        included: list[str] = []
        dropped: list[str] = []
        used = already_used_chars
        for item in ordered:
            if len(included) >= item_limit or used + item.chars > budget_chars:
                dropped.append(item.ref_id)
                continue
            included.append(item.ref_id)
            used += item.chars
        # Output is expressed in original order so the caller can preserve chronology.
        original = {item.ref_id: item.ordinal for item in values}
        return ContextSelection(
            tuple(sorted(included, key=original.__getitem__)),
            tuple(sorted(dropped, key=original.__getitem__)),
            used,
            budget_chars,
        )


@dataclass(frozen=True, slots=True)
class NeuralBudgetReceipt:
    route: NeuralRouteDecision
    actual_context_chars: int
    actual_context_utf8_bytes: int
    included_refs: tuple[str, ...]
    dropped_refs: tuple[str, ...]
    mandatory_constraint_count: int
    context_sha256: str
    receipt_sha256: str

    @classmethod
    def seal(
        cls,
        route: NeuralRouteDecision,
        *,
        actual_context_chars: int,
        actual_context_utf8_bytes: int,
        included_refs: tuple[str, ...],
        dropped_refs: tuple[str, ...],
        mandatory_constraint_count: int,
        context_sha256: str,
    ) -> "NeuralBudgetReceipt":
        if actual_context_chars > route.budget.max_context_chars:
            raise NeuralBudgetError("NB114", "contexto excedeu o budget selecionado")
        if actual_context_utf8_bytes > route.budget.max_prompt_utf8_bytes:
            raise NeuralBudgetError("NB118", "contexto UTF-8 excedeu o budget selecionado")
        unsigned = {
            "schema": "casulo.neural-budget-receipt/1.0",
            "route": route.to_dict(),
            "actual_context_chars": actual_context_chars,
            "actual_context_utf8_bytes": actual_context_utf8_bytes,
            "included_refs": list(included_refs),
            "dropped_refs": list(dropped_refs),
            "mandatory_constraint_count": mandatory_constraint_count,
            "context_sha256": context_sha256,
        }
        return cls(
            route,
            actual_context_chars,
            actual_context_utf8_bytes,
            included_refs,
            dropped_refs,
            mandatory_constraint_count,
            context_sha256,
            canonical_sha256(unsigned),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.neural-budget-receipt/1.0",
            "route": self.route.to_dict(),
            "actual_context_chars": self.actual_context_chars,
            "actual_context_utf8_bytes": self.actual_context_utf8_bytes,
            "included_refs": list(self.included_refs),
            "dropped_refs": list(self.dropped_refs),
            "mandatory_constraint_count": self.mandatory_constraint_count,
            "context_sha256": self.context_sha256,
            "receipt_sha256": self.receipt_sha256,
        }
