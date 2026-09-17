from __future__ import annotations

import pytest

from casulo.product.domain import CreationAggregate, CreationSpec, DeltaConfirmation, DomainError
from casulo.product.creation_pipeline import CreationPipeline
from casulo.product.intent_engine import IntentEngine, InterpretationStatus
from casulo.product.platform_contracts import PlatformError
from casulo.product.hosted_shell import HostedShell, ProductFeature
from casulo.product.platform_contracts import (
    BufferedAudioPlayback,
    ConsoleDisplay,
    SyntheticAudioCapture,
    SystemClock,
    VoiceEvent,
)
from casulo.product.t_forge import ForgeError, ForgeUnit, TForge


def source(module: str, operation: str, emitted: str) -> str:
    return f"""language T/1.1
module {module}

capability manifest

field Input
  trace value: Text

condense {operation} in Input
  effects [manifest]
  emit \"{emitted}\"
"""


def project(*, behavior: str = "acolhedor") -> tuple[ForgeUnit, ...]:
    return (
        ForgeUnit(
            "identity",
            source("demo.identity", "Identity", "Casulo"),
            (("identity",),),
        ),
        ForgeUnit(
            "behavior",
            source("demo.behavior", "Behavior", behavior),
            (("behavior",),),
        ),
        ForgeUnit(
            "interface",
            source("demo.interface", "Interface", "voice-first"),
            (("interface",),),
            ("identity", "behavior"),
        ),
    )


def artifact_map(receipt):
    return {artifact.unit_id: artifact for artifact in receipt.artifacts}


def test_final_speech_becomes_proposed_delta_and_requires_human_confirmation() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:1"))
    engine = IntentEngine()
    interpretation = engine.interpret(
        aggregate,
        source_event_id="voice:1",
        utterance="defina behavior.tone como acolhedor",
    )
    assert interpretation.status is InterpretationStatus.EXACT
    assert interpretation.delta is not None
    assert interpretation.delta.confirmation is DeltaConfirmation.PROPOSED
    assert interpretation.delta.affected_paths == (("behavior", "tone"),)
    with pytest.raises(DomainError, match="somente delta confirmado"):
        aggregate.apply_delta(interpretation.delta)
    confirmed = engine.decide(
        interpretation.delta,
        human_event_id="voice:confirm",
        accepted=True,
        explicit_human_approval=True,
    )
    updated = aggregate.apply_delta(confirmed)
    assert updated.content["behavior"]["tone"] == "acolhedor"
    assert confirmed.source_event_ids == ("voice:1", "voice:confirm")


def test_ambiguous_speech_never_creates_delta() -> None:
    interpretation = IntentEngine().interpret(
        CreationAggregate(CreationSpec("creation:1")),
        source_event_id="voice:1",
        utterance="deixa isso melhor",
    )
    assert interpretation.status is InterpretationStatus.CLARIFICATION_REQUIRED
    assert interpretation.delta is None
    assert interpretation.clarification


def test_model_or_adapter_cannot_confirm_without_human_event() -> None:
    engine = IntentEngine()
    proposed = engine.interpret(
        CreationAggregate(CreationSpec("creation:1")),
        source_event_id="voice:1",
        utterance="remova behavior.tone",
    ).delta
    assert proposed is not None
    with pytest.raises(PlatformError, match="aprovação humana"):
        engine.decide(
            proposed,
            human_event_id="engine:auto",
            accepted=True,
            explicit_human_approval=False,
        )


def test_incremental_forge_rebuilds_only_impact_and_downstream() -> None:
    forge = TForge()
    initial = forge.compile(project())
    before = artifact_map(initial)
    assert initial.rebuilt_units == ("behavior", "identity", "interface")
    corrected = forge.compile(
        project(behavior="direto"),
        affected_paths=(("behavior", "tone"),),
    )
    after = artifact_map(corrected)
    assert corrected.rebuilt_units == ("behavior", "interface")
    assert corrected.reused_units == ("identity",)
    assert after["identity"].artifact_sha256 == before["identity"].artifact_sha256
    assert after["behavior"].artifact_sha256 != before["behavior"].artifact_sha256
    assert after["interface"].artifact_sha256 != before["interface"].artifact_sha256
    assert after["interface"].graph_sha256 == before["interface"].graph_sha256


def test_source_change_cannot_hide_behind_wrong_affected_path() -> None:
    forge = TForge()
    forge.compile(project())
    receipt = forge.compile(
        project(behavior="conciso"),
        affected_paths=(("identity", "name"),),
    )
    assert set(receipt.rebuilt_units) == {"identity", "behavior", "interface"}


def test_failed_incremental_build_is_transactional() -> None:
    forge = TForge()
    initial = forge.compile(project())
    bad = list(project())
    bad[1] = ForgeUnit(
        "behavior",
        "language T/1.1\nmodule broken\ncondense nope\n",
        (("behavior",),),
    )
    with pytest.raises(ForgeError, match="reprovada"):
        forge.compile(bad, affected_paths=(("behavior",),))
    recovered = forge.compile(project())
    assert recovered.rebuilt_units == ()
    assert set(recovered.reused_units) == {"identity", "behavior", "interface"}
    assert artifact_map(recovered) == artifact_map(initial)


def test_forge_rejects_cycles_and_missing_dependencies() -> None:
    with pytest.raises(ForgeError, match="ausente"):
        TForge().compile((ForgeUnit("a", source("a", "A", "a"), (("a",),), ("b",)),))
    with pytest.raises(ForgeError, match="ciclo"):
        TForge().compile(
            (
                ForgeUnit("a", source("a", "A", "a"), (("a",),), ("b",)),
                ForgeUnit("b", source("b", "B", "b"), (("b",),), ("a",)),
            )
        )


def test_creation_pipeline_builds_candidate_before_committing_live_state() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:pipeline"))
    pipeline = CreationPipeline(aggregate)
    initial = artifact_map(pipeline.bootstrap())
    interpretation = pipeline.propose(
        source_event_id="voice:1",
        utterance="defina behavior.tone como direto",
    )
    assert interpretation.delta is pipeline.pending
    assert aggregate.current.version == 0
    decision = pipeline.decide(
        human_event_id="voice:2",
        accepted=True,
        explicit_human_approval=True,
    )
    assert decision.creation.content["behavior"]["tone"] == "direto"
    assert decision.forge_receipt is not None
    assert decision.forge_receipt.rebuilt_units == ("behavior", "interface")
    current = artifact_map(decision.forge_receipt)
    assert current["identity"].artifact_sha256 == initial["identity"].artifact_sha256


def test_rejected_pipeline_delta_records_rejection_without_compilation() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:pipeline"))
    pipeline = CreationPipeline(aggregate)
    pipeline.bootstrap()
    proposed = pipeline.propose(
        source_event_id="voice:1",
        utterance="defina identity.name como Outro",
    ).delta
    assert proposed is not None
    decision = pipeline.decide(
        human_event_id="voice:reject",
        accepted=False,
        explicit_human_approval=True,
    )
    assert decision.forge_receipt is None
    assert proposed.delta_id in decision.creation.rejected_delta_ids
    assert "identity" not in decision.creation.content


def test_hosted_voice_proposes_then_confirms_incremental_change() -> None:
    capture = SyntheticAudioCapture()
    playback = BufferedAudioPlayback()
    display = ConsoleDisplay(emit_ansi=False)
    shell = HostedShell(
        clock=SystemClock(),
        capture=capture,
        playback=playback,
        display=display,
        features=frozenset({ProductFeature.CREATOR}),
    )
    capture.emit(VoiceEvent("voice:1", "defina behavior.tone como direto", "pt-BR", True))
    shell.poll_voice()
    shell.run_one()
    assert shell.creation.current.content == {}
    assert "Diga ‘confirmo’" in display.frames[-1].summary
    capture.emit(VoiceEvent("voice:2", "confirmo", "pt-BR", True))
    shell.poll_voice()
    shell.run_one()
    assert shell.creation.current.content["behavior"]["tone"] == "direto"
    assert shell.creation.current.state.value == "FIRST_FORM"
    assert "behavior, interface" in display.frames[-1].summary
