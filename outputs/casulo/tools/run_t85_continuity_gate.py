from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "private/casulo-owner/src")]

from casulo.product.guide_continuity import ConstraintStrength, QuestionCandidate, RecordKind, verify_event_chain  # noqa: E402
from casulo.product.living_memory import DpapiSecretBox, MemoryIntegrityError  # noqa: E402
from casulo.product.platform_contracts import SystemClock  # noqa: E402
from casulo_owner.t85_continuity import ContinuityServiceError, T85ContinuityService  # noqa: E402


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def open_service(profile: Path, tcap: Path) -> T85ContinuityService:
    runtime = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
    return T85ContinuityService(profile, clock=SystemClock(), secret_box=DpapiSecretBox(), t_runtime=runtime, tcap=tcap)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or ROOT.resolve() not in output.parents:
        raise SystemExit("output must be new and inside repository")
    output.mkdir(parents=True)
    tcap = T85ContinuityService.build_policy(ROOT / "private/casulo-owner/t-v2/guide-context-policy.t", output / "guide-context-policy.tcap")
    profile = output / "owner-profile"
    service = open_service(profile, tcap)
    projects = ("flood-rs", "einstein-local", "voice-studio")
    for project in projects:
        service.open_project(project, source_event_id=f"human:open:{project}")
        service.add_constraint(
            constraint_id=f"{project}:human-publish", project_id=project, key="publish",
            statement=f"{project}: publicação material exige confirmação humana.",
            strength=ConstraintStrength.HARD, source_event_ids=(f"human:constraint:{project}",),
        )
        for index in range(2):
            service.record(
                record_id=f"{project}:creation:{index}", project_id=project, kind=RecordKind.DECISION,
                text=f"{project}: criação {index} confirmada com provenance exclusiva.",
                source_event_ids=(f"artifact:{project}:{index}",), criticality=9,
            )

    service.add_constraint(
        constraint_id="flood-rs:offline", project_id="flood-rs", key="network",
        statement="flood-rs permanece offline", strength=ConstraintStrength.HARD,
        source_event_ids=("human:flood:offline",),
    )
    service.add_constraint(
        constraint_id="flood-rs:online", project_id="flood-rs", key="network",
        statement="flood-rs depende de rede externa", strength=ConstraintStrength.HARD,
        source_event_ids=("human:flood:online",),
    )
    conflict = service.select_context(
        project_id="flood-rs", query="rede", budget_chars=8192,
        questions=(QuestionCandidate("network-conflict", "offline ou rede externa?", 1.0, 0.0, 0.0, True),),
    )
    conflict_was_explicit = conflict.decision == "ASK_HUMAN" and bool(conflict.directive.conflicts)
    service.resolve_constraint(
        winning_constraint_id="flood-rs:offline", human_event_id="human:flood:resolve",
        explicit_human_approval=True,
    )

    second_writer_denied = False
    try:
        open_service(profile, tcap)
    except ContinuityServiceError:
        second_writer_denied = True

    bleed = 0
    hard_loss = 0
    decisions: dict[str, int] = {"SELECT": 0, "ASK_HUMAN": 0}
    reboot_checks: list[dict[str, object]] = []
    for turn in range(500):
        project = projects[turn % len(projects)]
        service.record(
            record_id=f"{project}:turn:{turn:04d}", project_id=project, kind=RecordKind.THREAD,
            text=f"{project}: turno sintético {turn:04d}; manter contexto, constraint e provenance do projeto.",
            source_event_ids=(f"synthetic-turn:{turn:04d}",), unresolved=turn % 17 == 0,
        )
        selected = service.select_context(project_id=project, query=f"{project} contexto constraint", budget_chars=24_000)
        decisions[selected.decision] = decisions.get(selected.decision, 0) + 1
        bleed += sum(1 for item in selected.directive.context_items if item.source != f"guide-continuity:{project}")
        expected_hard = {
            item.statement for item in service.kernel.constraints.review(project).active
            if item.strength is ConstraintStrength.HARD
        }
        hard_loss += int(set(selected.directive.mandatory_constraints) != expected_hard)
        if turn == 249:
            debris = profile / "living-memory/memory/events/.crash-partial.json.dpapi.tmp"
            debris.parent.mkdir(parents=True, exist_ok=True)
            debris.write_bytes(b"INTERRUPTED-DPAPI-WRITE")
        if turn in {99, 199, 299, 399}:
            before = service.kernel.state_sha256
            events_before = len(service.kernel.event_log)
            service.close()
            service = open_service(profile, tcap)
            reboot_checks.append({
                "turn": turn + 1,
                "state_equal": service.kernel.state_sha256 == before,
                "event_count_equal": len(service.kernel.event_log) == events_before,
                "chain_valid": verify_event_chain(service.kernel.event_log),
            })

    recalls = {project: service.recall("lembra daquilo?", project_id=project).status for project in projects}
    state_before_final = service.kernel.state_sha256
    events_before_final = len(service.kernel.event_log)
    compaction = service.compact("ts8-500-turns")
    export = service.memory.export()
    (output / "memory-export.json").write_bytes(export)
    delete_without_consent_denied = False
    try:
        service.memory.delete_all("não")
    except MemoryIntegrityError:
        delete_without_consent_denied = True
    service.close()
    service = open_service(profile, tcap)
    final_reboot_equal = service.kernel.state_sha256 == state_before_final and len(service.kernel.event_log) == events_before_final
    journal_files = sorted((profile / "living-memory/memory/events").glob("*.json.dpapi"))
    plaintext_probe = "turno sintético 0499".encode("utf-8")
    encrypted_at_rest = all(plaintext_probe not in path.read_bytes() for path in journal_files)
    receipt_files = sorted((profile / "t-context-receipts").glob("context.*.receipt.json"))
    receipts = [json.loads(path.read_text(encoding="utf-8"))["receipt"] for path in receipt_files]
    receipt_chain_valid = all(
        receipt["previous_receipt_hash"] == ("0" * 64 if index == 0 else receipts[index - 1]["receipt_hash"])
        for index, receipt in enumerate(receipts)
    )
    final_state = service.kernel.snapshot()
    service.close()

    checks = {
        "five_hundred_turns": decisions["SELECT"] == 500,
        "three_projects": final_state["projects"] == sorted(projects),
        "hard_constraints_preserved_100_percent": hard_loss == 0,
        "project_bleed_zero": bleed == 0,
        "ambiguity_explicit_per_project": set(recalls.values()) == {"AMBIGUOUS"},
        "conflict_explicit_before_human_resolution": conflict_was_explicit,
        "single_writer": second_writer_denied,
        "crash_reboot_recovery": all(all(value for key, value in item.items() if key != "turn") for item in reboot_checks) and final_reboot_equal,
        "journal_chain": verify_event_chain(service.kernel.event_log),
        "t_receipts_complete": len(receipts) == 501 and receipt_chain_valid,
        "dpapi_encrypted_at_rest": encrypted_at_rest,
        "compaction_non_destructive": compaction["canonical_events_deleted"] == 0 and compaction["events_preserved"] == len(journal_files),
        "delete_requires_consent": delete_without_consent_denied,
        "trainable_default_false": all(item.payload.get("trainable") is False for item in service.memory.events),
    }
    report = {
        "schema": "casulo.t85-continuity-gate/1.0",
        "gate": "TS8_GUIDE_LIVING_MEMORY_PASS" if all(checks.values()) else "TS8_FAIL",
        "synthetic_turns": 500,
        "projects": list(projects),
        "normal_context_decisions": decisions,
        "t_decision_receipts": len(receipts),
        "continuity_events": len(service.kernel.event_log),
        "living_memory_events": len(service.memory.events),
        "hard_constraint_loss": hard_loss,
        "project_bleed": bleed,
        "recall_status": recalls,
        "reboots": reboot_checks,
        "final_reboot_equal": final_reboot_equal,
        "compaction": compaction,
        "memory_export_sha256": sha(output / "memory-export.json"),
        "t_receipt_chain_head": receipts[-1]["receipt_hash"] if receipts else None,
        "checks": checks,
        "human_chemistry": "NOT_EXECUTED",
        "physical_voice": "NOT_EXECUTED",
        "locks": {"cloud": "RELEASE_LOCKED", "guest_network": "OFF", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
    }
    dump(output / "continuity-gate.json", report)
    dump(output / "gate.json", {"gate": report["gate"], "checks": checks})
    print(json.dumps({"gate": report["gate"], "turns": 500, "t_receipts": len(receipts), "bleed": bleed, "hard_loss": hard_loss}, indent=2))
    return 0 if report["gate"].endswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
