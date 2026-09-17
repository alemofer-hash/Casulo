from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .domain import (
    CreationAggregate,
    DeltaConfirmation,
    IntentDelta,
    IntentOperation,
)
from .platform_contracts import PlatformError


_SET = re.compile(
    r"^\s*defina\s+([A-Za-zÀ-ÿ_][\wÀ-ÿ]*(?:\.[A-Za-zÀ-ÿ_][\wÀ-ÿ]*)*)\s+como\s+(.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_REMOVE = re.compile(
    r"^\s*remova\s+([A-Za-zÀ-ÿ_][\wÀ-ÿ]*(?:\.[A-Za-zÀ-ÿ_][\wÀ-ÿ]*)*)\s*[.!]?\s*$",
    re.IGNORECASE,
)


class InterpretationStatus(StrEnum):
    EXACT = "EXACT"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class IntentInterpretation:
    status: InterpretationStatus
    source_event_id: str
    delta: IntentDelta | None
    clarification: str | None

    def __post_init__(self) -> None:
        if not self.source_event_id:
            raise PlatformError("interpretação exige evento de origem")
        if self.status is InterpretationStatus.EXACT and self.delta is None:
            raise PlatformError("interpretação exata exige IntentDelta")
        if self.status is InterpretationStatus.CLARIFICATION_REQUIRED and not self.clarification:
            raise PlatformError("interpretação ambígua exige pergunta")


class IntentEngine:
    """Narrow deterministic ingress; never turns vague speech into intent."""

    def interpret(
        self,
        aggregate: CreationAggregate,
        *,
        source_event_id: str,
        utterance: str,
    ) -> IntentInterpretation:
        if not source_event_id or not utterance.strip():
            raise PlatformError("fala final exige identidade e conteúdo")
        match = _SET.fullmatch(utterance)
        if match is not None:
            path = tuple(match.group(1).split("."))
            operation = IntentOperation("set", path, self._value(match.group(2)))
        else:
            match = _REMOVE.fullmatch(utterance)
            if match is None:
                return IntentInterpretation(
                    InterpretationStatus.CLARIFICATION_REQUIRED,
                    source_event_id,
                    None,
                    "Posso registrar uma mudança exata. Diga ‘defina caminho como valor’ ou ‘remova caminho’.",
                )
            path = tuple(match.group(1).split("."))
            operation = IntentOperation("remove", path)
        digest = hashlib.sha256(
            f"{aggregate.current.creation_id}\0{aggregate.current.version}\0{source_event_id}\0{utterance}".encode("utf-8")
        ).hexdigest()
        delta = IntentDelta(
            delta_id=f"intent:{digest[:24]}",
            creation_id=aggregate.current.creation_id,
            base_version=aggregate.current.version,
            operations=(operation,),
            rationale="interpretação determinística de fala final com gramática explícita",
            source_event_ids=(source_event_id,),
            confidence=1.0,
            confirmation=DeltaConfirmation.PROPOSED,
            affected_paths=(operation.path,),
        )
        return IntentInterpretation(
            InterpretationStatus.EXACT,
            source_event_id,
            delta,
            None,
        )

    def decide(
        self,
        proposed: IntentDelta,
        *,
        human_event_id: str,
        accepted: bool,
        explicit_human_approval: bool,
    ) -> IntentDelta:
        if proposed.confirmation is not DeltaConfirmation.PROPOSED:
            raise PlatformError("somente delta proposto pode receber decisão")
        if not human_event_id:
            raise PlatformError("decisão exige evento humano")
        if accepted and not explicit_human_approval:
            raise PlatformError("confirmação exige aprovação humana explícita")
        return IntentDelta(
            delta_id=proposed.delta_id,
            creation_id=proposed.creation_id,
            base_version=proposed.base_version,
            operations=proposed.operations,
            rationale=proposed.rationale,
            source_event_ids=(*proposed.source_event_ids, human_event_id),
            confidence=proposed.confidence,
            confirmation=(
                DeltaConfirmation.CONFIRMED if accepted else DeltaConfirmation.REJECTED
            ),
            affected_paths=proposed.affected_paths,
        )

    @staticmethod
    def _value(raw: str) -> Any:
        cleaned = raw.strip().removesuffix(".").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return cleaned.strip('"')
