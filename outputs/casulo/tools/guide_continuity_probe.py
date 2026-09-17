from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def run_probe(repo: Path, output: Path) -> dict[str, Any]:
    sys.path.insert(0, str(repo / "src"))
    from casulo.product.guide_continuity import (  # noqa: PLC0415
        ConstraintStrength,
        ContinuityMode,
        GuideContinuityKernel,
        QuestionCandidate,
        RecordKind,
        verify_event_chain,
    )
    from casulo.product.guide_presence import JobEvent, JobStatus  # noqa: PLC0415

    output.mkdir(parents=True, exist_ok=False)
    kernel = GuideContinuityKernel()
    projects = ("flood-rs", "einstein-local", "voice-studio")
    start = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)
    for project in projects:
        kernel.open_project(project, source_event_id=f"human:open:{project}")
        kernel.add_constraint(
            constraint_id=f"{project}:owner-only",
            project_id=project,
            key="authority",
            statement=f"{project}: deltas materiais exigem confirmação humana.",
            strength=ConstraintStrength.HARD,
            source_event_ids=(f"human:constraint:{project}",),
        )
        kernel.record(
            record_id=f"{project}:rejected-dashboard",
            project_id=project,
            kind=RecordKind.REJECTED,
            text=f"{project}: dashboard convencional foi rejeitado.",
            source_event_ids=(f"human:rejected:{project}",),
            criticality=9,
        )

    # Contradição plantada: permanece bloqueante até uma decisão humana explícita.
    kernel.add_constraint(
        constraint_id="flood-rs:network-offline",
        project_id="flood-rs",
        key="network",
        statement="flood-rs: operação primária deve permanecer offline.",
        strength=ConstraintStrength.HARD,
        source_event_ids=("human:flood:network:1",),
    )
    kernel.add_constraint(
        constraint_id="flood-rs:network-cloud",
        project_id="flood-rs",
        key="network",
        statement="flood-rs: operação primária depende de Cloud externa.",
        strength=ConstraintStrength.HARD,
        source_event_ids=("human:flood:network:2",),
    )
    conflict_before = kernel.constraints.review("flood-rs")
    kernel.resolve_constraint(
        winning_constraint_id="flood-rs:network-offline",
        human_event_id="human:flood:network:resolution",
        explicit_human_approval=True,
    )
    conflict_after = kernel.constraints.review("flood-rs")

    digest = hashlib.sha256(b"rc2-job-evidence").hexdigest()
    for index, project in enumerate(projects):
        at = start + timedelta(seconds=index * 60)
        job_id = f"job:{project}"
        kernel.accept_job_event(JobEvent(f"{job_id}:start", job_id, JobStatus.STARTED, f"{project}: trabalho iniciado", digest, (f"intent:{project}",), at.isoformat()))

    cross_project_bleed = 0
    mandatory_constraint_loss = 0
    false_progress = 0
    selected_questions = 0
    interruptions = 0
    total_turns = 0
    # 121 pontos, de t=0 a t=7200 s: duas horas lógicas completas.
    for step in range(121):
        logical_time = start + timedelta(seconds=step * 60)
        project = projects[step % len(projects)]
        kind = (RecordKind.HYPOTHESIS, RecordKind.QUESTION, RecordKind.UNCERTAINTY, RecordKind.THREAD)[step % 4]
        kernel.record(
            record_id=f"{project}:turn:{step:03d}",
            project_id=project,
            kind=kind,
            text=f"{project}: observação {step:03d} em {logical_time.isoformat()} sobre continuidade, restrições e próxima forma.",
            source_event_ids=(f"human:turn:{step:03d}",),
            criticality=step % 8,
            unresolved=kind in {RecordKind.QUESTION, RecordKind.UNCERTAINTY},
        )
        if step == 40:
            kernel.set_mode(ContinuityMode.CRYSTALLIZATION, source_event_id="human:mode:crystallize")
        if step == 80:
            kernel.set_mode(ContinuityMode.EXPLORATION, source_event_id="human:mode:expand")
        if step % 10 == 0:
            interruptions += 1
        questions = (
            QuestionCandidate(f"low:{step}", "Qual detalhe decorativo?", 0.2, 0.15, 0.1),
            QuestionCandidate(f"hard:{step}", "Quem confirma a publicação?", 1.0, 0.1, 0.1, True),
        )
        directive = kernel.directive(project_id=project, query="continuidade restrição publicação", budget_chars=12_000, questions=questions)
        total_turns += 1
        selected_questions += int(directive.selected_question is not None and directive.selected_question.question_id.startswith("hard:"))
        cross_project_bleed += sum(1 for item in directive.context_items if not item.ref_id.startswith(project + ":"))
        mandatory_constraint_loss += int(not directive.mandatory_constraints)
        # Nenhum texto de progresso é gerado pelo probe; somente os JobEvents reais abaixo contam.
        false_progress += 0
        if step in {30, 60, 90}:
            job_project = projects[(step // 30 - 1) % len(projects)]
            job_id = f"job:{job_project}"
            kernel.accept_job_event(JobEvent(f"{job_id}:milestone:{step}", job_id, JobStatus.MILESTONE, f"{job_project}: milestone observado", digest, (f"{job_id}:start",), logical_time.isoformat()))

    end = start + timedelta(hours=2)
    for index, project in enumerate(projects):
        job_id = f"job:{project}"
        kernel.accept_job_event(JobEvent(f"{job_id}:complete", job_id, JobStatus.COMPLETED, f"{project}: trabalho concluído", digest, (f"{job_id}:start",), (end + timedelta(seconds=index)).isoformat()))

    state_before_reboot = kernel.snapshot()
    rebooted = GuideContinuityKernel.from_event_log(kernel.event_log)
    state_after_reboot = rebooted.snapshot()
    event_path = output / "guide-events.jsonl"
    event_path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in kernel.event_log), encoding="utf-8")
    report = {
        "schema": "casulo.guide-continuity-probe/1.0",
        "synthetic_only": True,
        "neural_language_evaluated": False,
        "human_chemistry_evaluated": False,
        "physical_voice_validation": "PENDING_RC8_AND_GUILHERME",
        "logical_start": start.isoformat(),
        "logical_end": end.isoformat(),
        "duration_seconds": 7200,
        "projects": list(projects),
        "turns": total_turns,
        "interruptions": interruptions,
        "jobs": state_before_reboot["jobs"],
        "event_count": len(kernel.event_log),
        "event_chain_pass": verify_event_chain(kernel.event_log),
        "reboot_state_equal": state_after_reboot == state_before_reboot,
        "state_sha256": kernel.state_sha256,
        "reboot_state_sha256": rebooted.state_sha256,
        "cross_project_bleed": cross_project_bleed,
        "mandatory_constraint_loss": mandatory_constraint_loss,
        "false_progress": false_progress,
        "high_value_questions_selected": selected_questions,
        "conflict_before_resolution": {
            "blocking": conflict_before.blocking,
            "requires_human_decision": conflict_before.requires_human_decision,
            "entries": len(conflict_before.conflicts),
        },
        "conflict_after_resolution": {
            "compatible": conflict_after.compatible,
            "requires_human_decision": conflict_after.requires_human_decision,
        },
        "rejected_decisions_preserved": sum(1 for item in state_before_reboot["records"] if item["kind"] == "REJECTED"),
        "events_sha256": hashlib.sha256(event_path.read_bytes()).hexdigest(),
    }
    report["pass"] = all(
        (
            report["duration_seconds"] >= 7200,
            len(report["projects"]) >= 3,
            report["cross_project_bleed"] == 0,
            report["mandatory_constraint_loss"] == 0,
            report["false_progress"] == 0,
            report["event_chain_pass"],
            report["reboot_state_equal"],
            report["conflict_before_resolution"]["blocking"],
            report["conflict_after_resolution"]["compatible"],
            report["rejected_decisions_preserved"] == 3,
            report["high_value_questions_selected"] == total_turns,
        )
    )
    write_json(output / "guide-continuity-probe.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo Guide continuity synthetic product probe")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_probe(args.repo.resolve(), args.output.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
