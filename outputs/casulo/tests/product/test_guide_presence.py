from __future__ import annotations

import hashlib

import pytest

from casulo.product.guide_presence import (
    DialogueMode,
    GuideAct,
    GuidePresence,
    JobEvent,
    JobStatus,
)
from casulo.product.hosted_shell import HostedShell
from casulo.product.living_memory import LivingMemory, TestSecretBox
from casulo.product.platform_contracts import (
    BufferedAudioPlayback,
    ConsoleDisplay,
    LocalStorage,
    PlatformError,
    SyntheticAudioCapture,
    SystemClock,
    VoiceEvent,
)


def evidence(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def job(event_id: str, job_id: str, status: JobStatus, summary: str) -> JobEvent:
    return JobEvent(
        event_id=event_id,
        job_id=job_id,
        status=status,
        summary=summary,
        evidence_sha256=evidence(event_id),
        source_event_ids=("intent:1",),
        occurred_at="2026-08-11T00:00:00Z",
    )


def test_presence_keeps_dialogue_responsive_while_job_is_active() -> None:
    guide = GuidePresence(clock=SystemClock())
    progress = guide.accept_job_event(job("job:1:start", "job:1", JobStatus.STARTED, "Compilação iniciada"))
    reply = guide.respond(event_id="voice:1", text="Quero revisar a finalidade", final=True)
    assert progress.act is GuideAct.PROGRESS
    assert reply.background_jobs_active == 1
    assert reply.act is GuideAct.LISTENING
    assert guide.active_job_count == 1


def test_progress_requires_canonical_evidence_and_monotonic_job_state() -> None:
    guide = GuidePresence(clock=SystemClock())
    with pytest.raises(PlatformError, match="SHA-256"):
        JobEvent("bad", "job:1", JobStatus.STARTED, "início", "fake", ("source",), "now")
    with pytest.raises(PlatformError, match="começar"):
        guide.accept_job_event(job("job:1:done", "job:1", JobStatus.COMPLETED, "Pronto"))
    guide.accept_job_event(job("job:1:start", "job:1", JobStatus.STARTED, "Iniciado"))
    guide.accept_job_event(job("job:1:done", "job:1", JobStatus.COMPLETED, "Concluído"))
    with pytest.raises(PlatformError, match="terminal"):
        guide.accept_job_event(job("job:1:late", "job:1", JobStatus.MILESTONE, "Tarde"))


def test_collaboration_adaptation_never_applies_without_human_consent(tmp_path) -> None:
    memory = LivingMemory(
        storage=LocalStorage(tmp_path),
        clock=SystemClock(),
        secret_box=TestSecretBox(),
        allow_test_encryption=True,
    )
    guide = GuidePresence(clock=SystemClock(), memory=memory)
    proposal, turn = guide.propose_adaptation(
        proposal_id="adapt:1",
        changes={"literalness": 8},
        rationale="usuário pediu respostas mais literais",
        source_event_ids=("voice:1",),
    )
    assert turn.act is GuideAct.ADAPTATION_PROPOSED
    assert guide.collaboration.literalness == 5
    with pytest.raises(PlatformError, match="aprovação humana"):
        guide.resolve_adaptation(
            proposal,
            accepted=True,
            human_event_id="voice:2",
            explicit_human_approval=False,
        )
    applied = guide.resolve_adaptation(
        proposal,
        accepted=True,
        human_event_id="voice:2",
        explicit_human_approval=True,
    )
    assert applied.act is GuideAct.ADAPTATION_APPLIED
    assert guide.collaboration.literalness == 8
    assert memory.projection("collaboration")["provenance_event_ids"] == ["collaboration:adapt:1"]


def test_guide_cannot_increase_pressure_or_stereotype_user() -> None:
    guide = GuidePresence(clock=SystemClock())
    with pytest.raises(PlatformError, match="pressão"):
        guide.propose_adaptation(
            proposal_id="adapt:pressure",
            changes={"pressure": 3},
            rationale="pressionar",
            source_event_ids=("voice:1",),
        )
    with pytest.raises(PlatformError, match="desconhecida"):
        guide.propose_adaptation(
            proposal_id="adapt:stereotype",
            changes={"diagnosis": 10},
            rationale="estereótipo",
            source_event_ids=("voice:1",),
        )


def test_guide_surfaces_conflict_instead_of_sycophancy() -> None:
    guide = GuidePresence(clock=SystemClock())
    turn = guide.review_constraint(
        requested="publique agora",
        conflicts=("Cloud permanece RELEASE_LOCKED", "falta aprovação humana"),
        source_event_ids=("voice:1",),
    )
    assert turn.act is GuideAct.CONSTRAINT
    assert turn.certainty == "conflict"
    assert "Não vou concordar automaticamente" in turn.text


def test_expansion_clarifies_and_crystallization_synthesizes() -> None:
    guide = GuidePresence(clock=SystemClock())
    unclear = guide.respond(event_id="voice:1", text="isso talvez", final=True)
    assert unclear.act is GuideAct.CLARIFICATION
    crystal = guide.crystallize(summary="um Guia local e privado", source_event_ids=("voice:2",))
    assert crystal.mode is DialogueMode.CRYSTALLIZATION
    answer = guide.respond(event_id="voice:3", text="A criação deve operar sem nuvem", final=True)
    assert answer.act is GuideAct.SYNTHESIS
    assert "confirma" in answer.text.casefold()


def test_guide_never_hands_implementation_vocabulary_to_the_user() -> None:
    guide = GuidePresence(clock=SystemClock())
    turns = (
        guide.respond(event_id="voice:1", text="isso talvez", final=True),
        guide.respond(
            event_id="voice:2",
            text="quero um bichinho que organize minhas ideias enquanto eu falo",
            final=True,
        ),
        guide.respond(
            event_id="voice:3",
            text="ele junta as coisas que combinam e me mostra o que nasceu",
            final=True,
        ),
    )
    forbidden = {
        "api", "framework", "banco de dados", "arquitetura", "algoritmo",
        "linguagem de programação", "servidor", "gpu", "dataset",
    }
    assert all(not any(term in turn.text.casefold() for term in forbidden) for turn in turns)
    assert "cena" in turns[0].text.casefold()
    assert "era isso" in turns[1].text.casefold()


def test_hosted_shell_uses_guide_without_blocking_real_job_progress() -> None:
    capture = SyntheticAudioCapture()
    playback = BufferedAudioPlayback()
    display = ConsoleDisplay(emit_ansi=False)
    guide = GuidePresence(clock=SystemClock())
    shell = HostedShell(
        clock=SystemClock(),
        capture=capture,
        playback=playback,
        display=display,
        guide=guide,
    )
    shell.accept_job_event(job("job:1:start", "job:1", JobStatus.STARTED, "Worker iniciou"))
    capture.emit(VoiceEvent("voice:1", "Quero criar um agente local", "pt-BR", True))
    shell.poll_voice()
    assert shell.run_one() == "VOICE"
    assert shell.run_one() == "GUIDE_JOB_EVENT"
    assert playback.active
    assert display.frames[-1].summary == "Worker iniciou"
