from __future__ import annotations

from casulo.product.guide_continuity import (
    ConstraintStatus,
    ConstraintStrength,
    ContinuityError,
    ContinuityMode,
    DialogueDirector,
    GuideContinuityKernel,
    QuestionCandidate,
    RecordKind,
    verify_event_chain,
)
from casulo.product.guide_presence import JobEvent, JobStatus
from casulo_owner.dialogue_core import GenerativeDialogueCore, RelationalMode
from tools.guide_neural_continuity_probe import (
    recalls_offline_constraint,
    recalls_rejected_dashboard,
)


DIGEST = "a" * 64


def kernel_with_projects() -> GuideContinuityKernel:
    kernel = GuideContinuityKernel()
    for project in ("alpha", "beta", "gamma"):
        kernel.open_project(project, source_event_id=f"human:open:{project}")
    return kernel


def test_context_never_bleeds_between_projects() -> None:
    kernel = kernel_with_projects()
    kernel.record(
        record_id="alpha:secret",
        project_id="alpha",
        kind=RecordKind.DECISION,
        text="A identidade alpha usa âmbar e nunca azul.",
        source_event_ids=("human:1",),
        criticality=10,
    )
    kernel.record(
        record_id="beta:decision",
        project_id="beta",
        kind=RecordKind.DECISION,
        text="Beta usa apenas azul profundo.",
        source_event_ids=("human:2",),
        criticality=10,
    )
    selected = kernel.select_context(project_id="beta", query="qual cor?", budget_chars=1000)
    assert [item.record_id for item in selected] == ["beta:decision"]
    assert "alpha" not in " ".join(item.text for item in selected).casefold()


def test_contradiction_is_preserved_and_requires_human_resolution() -> None:
    kernel = kernel_with_projects()
    first = kernel.add_constraint(
        constraint_id="c:offline",
        project_id="alpha",
        key="network",
        statement="A criação precisa operar offline.",
        strength=ConstraintStrength.HARD,
        source_event_ids=("human:1",),
    )
    conflict = kernel.add_constraint(
        constraint_id="c:online",
        project_id="alpha",
        key="network",
        statement="A criação precisa depender de uma API externa.",
        strength=ConstraintStrength.HARD,
        source_event_ids=("human:2",),
    )
    review = kernel.constraints.review("alpha")
    assert first.status is ConstraintStatus.ACTIVE
    assert conflict.status is ConstraintStatus.CONFLICT
    assert review.blocking is True
    assert review.requires_human_decision is True
    try:
        kernel.resolve_constraint(
            winning_constraint_id=first.constraint_id,
            human_event_id="human:3",
            explicit_human_approval=False,
        )
    except ContinuityError:
        pass
    else:
        raise AssertionError("resolução sem confirmação deveria falhar")
    resolved = kernel.resolve_constraint(
        winning_constraint_id=first.constraint_id,
        human_event_id="human:4",
        explicit_human_approval=True,
    )
    assert resolved.status is ConstraintStatus.RESOLVED
    assert kernel.constraints.review("alpha").compatible is True
    assert len(kernel.constraints.entries) == 3


def test_rejected_decisions_are_mandatory_memory_not_deleted() -> None:
    kernel = kernel_with_projects()
    kernel.record(
        record_id="alpha:rejected-dashboard",
        project_id="alpha",
        kind=RecordKind.REJECTED,
        text="Dashboard convencional foi rejeitado pelo usuário.",
        source_event_ids=("human:reject:1",),
        criticality=9,
    )
    selected = kernel.select_context(project_id="alpha", query="nova interface", budget_chars=1000)
    assert selected[0].kind is RecordKind.REJECTED


def test_dialogue_director_asks_only_high_value_or_hard_question() -> None:
    kernel = kernel_with_projects()
    questions = (
        QuestionCandidate("low", "Qual cor secundária?", 0.3, 0.2, 0.2),
        QuestionCandidate("high", "Quem pode publicar?", 1.0, 0.1, 0.1, True),
    )
    directive = kernel.directive(
        project_id="alpha",
        query="vamos criar",
        budget_chars=1000,
        questions=questions,
        director=DialogueDirector(),
    )
    assert directive.selected_question is not None
    assert directive.selected_question.question_id == "high"


def test_job_progress_can_only_come_from_valid_events() -> None:
    kernel = kernel_with_projects()
    started = JobEvent("event:1", "job:1", JobStatus.STARTED, "compilação iniciada", DIGEST, ("intent:1",), "2026-08-14T00:00:00Z")
    completed = JobEvent("event:2", "job:1", JobStatus.COMPLETED, "compilação concluída", DIGEST, ("event:1",), "2026-08-14T00:00:02Z")
    kernel.accept_job_event(started)
    kernel.accept_job_event(completed)
    assert kernel.snapshot()["jobs"] == {"job:1": "COMPLETED"}
    try:
        kernel.accept_job_event(JobEvent("event:3", "job:1", JobStatus.MILESTONE, "falso tardio", DIGEST, ("event:2",), "2026-08-14T00:00:03Z"))
    except ContinuityError:
        pass
    else:
        raise AssertionError("evento após terminal deveria falhar")


def test_event_chain_detects_tamper() -> None:
    kernel = kernel_with_projects()
    kernel.set_mode(ContinuityMode.CRYSTALLIZATION, source_event_id="human:mode")
    events = [dict(item) for item in kernel.event_log]
    assert verify_event_chain(events) is True
    events[1]["payload"] = {"project_id": "intruder"}
    assert verify_event_chain(events) is False


def test_reboot_replays_canonical_state_from_hash_chained_events() -> None:
    kernel = kernel_with_projects()
    kernel.record(
        record_id="gamma:hypothesis",
        project_id="gamma",
        kind=RecordKind.HYPOTHESIS,
        text="O fluxo pode ser melhor sem dashboard.",
        source_event_ids=("human:1",),
        unresolved=True,
    )
    kernel.set_mode(ContinuityMode.CRYSTALLIZATION, source_event_id="human:2")
    before = kernel.state_sha256
    rebooted = GuideContinuityKernel.from_event_log(kernel.event_log)
    assert rebooted.state_sha256 == before
    assert rebooted.snapshot() == kernel.snapshot()


def test_continuity_directive_enters_neural_context_without_authority_transfer() -> None:
    kernel = kernel_with_projects()
    kernel.record(
        record_id="alpha:decision",
        project_id="alpha",
        kind=RecordKind.DECISION,
        text="Publicação sempre exige confirmação humana.",
        source_event_ids=("human:1",),
        criticality=10,
    )
    directive = kernel.directive(project_id="alpha", query="publique", budget_chars=1000)
    turn = GenerativeDialogueCore().context_for_turn(
        session_id="alpha",
        utterance="Quero continuar daqui.",
        mode=RelationalMode.EXPLORATION,
        continuity=directive,
    )
    assert turn.memory_items[0].content == "Publicação sempre exige confirmação humana."
    assert turn.memory_items[0].trust.value == "LOCAL_DERIVED"
    assert any("progresso" in rule.casefold() for rule in turn.mandatory_constraints)


def test_mandatory_context_is_never_silently_trimmed() -> None:
    kernel = kernel_with_projects()
    kernel.record(
        record_id="alpha:large",
        project_id="alpha",
        kind=RecordKind.DECISION,
        text="x" * 100,
        source_event_ids=("human:1",),
        criticality=10,
    )
    try:
        kernel.select_context(project_id="alpha", query="x", budget_chars=50)
    except ContinuityError as error:
        assert "recorte silencioso negado" in str(error)
    else:
        raise AssertionError("memória mandatória não pode desaparecer")


def test_neural_recall_oracle_accepts_the_concept_not_only_one_token() -> None:
    assert recalls_rejected_dashboard("Você rejeitou a interface convencional.") is True
    assert recalls_rejected_dashboard("O dashboard foi descartado.") is True
    assert recalls_rejected_dashboard("A interface convencional é ótima.") is False
    assert recalls_offline_constraint("O fluxo permanece offline, sem API externa.") is True
    assert recalls_offline_constraint("Não há conexão com servidores externos; opera em isolamento.") is True
    assert recalls_offline_constraint("Vamos chamar um servidor externo.") is False
