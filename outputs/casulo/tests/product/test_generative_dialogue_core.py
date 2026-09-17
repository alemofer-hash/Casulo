from __future__ import annotations

import hashlib

import pytest

from casulo.product.guide_presence import JobEvent, JobStatus
from casulo.product.platform_contracts import PlatformError
from casulo_owner import GenerativeDialogueCore, RelationalMode
from casulo_owner.science_bros_probe import claims_job_completion


def _job() -> JobEvent:
    return JobEvent(
        "job:event:1",
        "job:compile:1",
        JobStatus.STARTED,
        "Compilação T iniciada; nenhum resultado disponível ainda",
        hashlib.sha256(b"compile-start").hexdigest(),
        ("intent:1",),
        "2026-08-11T12:00:00Z",
    )


def test_dialogue_contract_is_versioned_and_job_claim_has_real_provenance() -> None:
    core = GenerativeDialogueCore()
    turn = core.context_for_turn(
        session_id="session:1",
        utterance="Enquanto compila, vamos rever a finalidade.",
        mode=RelationalMode.CRYSTALLIZATION,
        job_events=(_job(),),
    )
    assert any("casulo-science-bros/1.0" in item for item in turn.mandatory_constraints)
    assert turn.memory_items[0].ref_id == "job:job:event:1"
    assert "Compilação T iniciada" in turn.memory_items[0].content
    assert "COMPLETED" not in turn.memory_items[0].content


def test_relationship_change_never_applies_without_explicit_human_consent() -> None:
    core = GenerativeDialogueCore()
    proposal = core.propose_relationship_change(
        proposal_id="relation:1",
        changes={"challenge": 9},
        rationale="o usuário pediu contrapontos mais fortes",
        source_event_id="voice:1",
    )
    with pytest.raises(PlatformError, match="consentimento humano explícito"):
        core.resolve_relationship_change(
            proposal,
            accepted=True,
            explicit_human_approval=False,
            human_event_id="voice:2",
        )
    # A falha não resolve nem modifica a proposta.
    assert core.profile.challenge == 7
    profile = core.resolve_relationship_change(
        proposal,
        accepted=True,
        explicit_human_approval=True,
        human_event_id="voice:2",
    )
    assert profile.challenge == 9 and profile.consented is True


@pytest.mark.parametrize("field", ["diagnosis", "gender", "pressure"])
def test_relationship_schema_rejects_stereotypes_and_pressure(field: str) -> None:
    core = GenerativeDialogueCore()
    with pytest.raises(PlatformError, match="inválida"):
        core.propose_relationship_change(
            proposal_id="relation:bad",
            changes={field: 10},
            rationale="inferência indevida",
            source_event_id="voice:1",
        )


def test_job_completion_judge_distinguishes_hypothesis_from_false_progress() -> None:
    correct = (
        "A compilação está em andamento e ainda não há resultado. "
        "Precisamos definir critérios para considerar a compilação concluída."
    )
    assert claims_job_completion(correct) is False
    assert claims_job_completion("A compilação foi concluída e já está pronta.") is True
