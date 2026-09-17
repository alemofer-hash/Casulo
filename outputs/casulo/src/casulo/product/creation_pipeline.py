from __future__ import annotations

import json
from dataclasses import dataclass

from .domain import CreationAggregate, CreationSpec, DeltaConfirmation, IntentDelta
from .intent_engine import IntentEngine, IntentInterpretation, InterpretationStatus
from .platform_contracts import PlatformError
from .t_forge import ForgeReceipt, ForgeUnit, TForge


@dataclass(frozen=True, slots=True)
class PipelineDecision:
    delta: IntentDelta
    creation: CreationSpec
    forge_receipt: ForgeReceipt | None


class CreationPipeline:
    """Atomic dialogue -> intent -> candidate T build -> creation commit path."""

    def __init__(
        self,
        aggregate: CreationAggregate,
        *,
        intent_engine: IntentEngine | None = None,
        forge: TForge | None = None,
    ) -> None:
        self.aggregate = aggregate
        self.intent_engine = intent_engine or IntentEngine()
        self.forge = forge or TForge()
        self.pending: IntentDelta | None = None

    def bootstrap(self) -> ForgeReceipt:
        return self.forge.compile(creation_units(self.aggregate.current))

    def propose(self, *, source_event_id: str, utterance: str) -> IntentInterpretation:
        if self.pending is not None:
            raise PlatformError("há um IntentDelta pendente de decisão")
        interpretation = self.intent_engine.interpret(
            self.aggregate,
            source_event_id=source_event_id,
            utterance=utterance,
        )
        if interpretation.status is InterpretationStatus.EXACT:
            self.pending = interpretation.delta
        return interpretation

    def decide(
        self,
        *,
        human_event_id: str,
        accepted: bool,
        explicit_human_approval: bool,
    ) -> PipelineDecision:
        if self.pending is None:
            raise PlatformError("não existe IntentDelta pendente")
        decided = self.intent_engine.decide(
            self.pending,
            human_event_id=human_event_id,
            accepted=accepted,
            explicit_human_approval=explicit_human_approval,
        )
        if decided.confirmation is DeltaConfirmation.REJECTED:
            creation = self.aggregate.apply_delta(decided)
            self.pending = None
            return PipelineDecision(decided, creation, None)

        # Build from an isolated candidate first. A failed T build cannot mutate
        # the live aggregate, and TForge itself commits its cache transactionally.
        shadow = CreationAggregate(self.aggregate.current)
        candidate = shadow.apply_delta(decided)
        receipt = self.forge.compile(
            creation_units(candidate),
            affected_paths=decided.affected_paths,
        )
        creation = self.aggregate.apply_delta(decided)
        self.pending = None
        return PipelineDecision(decided, creation, receipt)


def creation_units(spec: CreationSpec) -> tuple[ForgeUnit, ...]:
    content = dict(spec.content)
    identity = _nested_text(content, "identity", "name", default="Casulo")
    tone = _nested_text(content, "behavior", "tone", default="acolhedor")
    channel = _nested_text(content, "interface", "channel", default="voice-first")
    return (
        ForgeUnit(
            "identity",
            _source("casulo.creation.identity", "Identity", identity),
            (("identity",),),
        ),
        ForgeUnit(
            "behavior",
            _source("casulo.creation.behavior", "Behavior", tone),
            (("behavior",),),
        ),
        ForgeUnit(
            "interface",
            _source("casulo.creation.interface", "Interface", channel),
            (("interface",),),
            ("identity", "behavior"),
        ),
    )


def _nested_text(content: dict, section: str, key: str, *, default: str) -> str:
    value = content.get(section, {})
    if not isinstance(value, dict):
        return default
    result = value.get(key, default)
    return result if isinstance(result, str) and result else default


def _source(module: str, operation: str, emitted: str) -> str:
    literal = json.dumps(emitted, ensure_ascii=False)
    return f"""language T/1.1
module {module}

capability manifest

field Input
  trace value: Text

condense {operation} in Input
  effects [manifest]
  emit {literal}
"""
