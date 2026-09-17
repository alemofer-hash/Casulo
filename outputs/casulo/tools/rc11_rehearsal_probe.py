from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from casulo.product.capabilities import Effect
from casulo.product.creation_pipeline import creation_units
from casulo.product.domain import CreationSpec, CreationState
from casulo.product.guide_continuity import ConstraintStrength, GuideContinuityKernel, RecordKind, verify_event_chain
from casulo.product.guide_presence import JobEvent, JobStatus
from casulo.product.materializer import ExecutableAgentBundle, MaterializedPackageImporter, Materializer
from casulo.product.simulation import SimulatedResponse, SimulationCapabilityDouble, SimulationPlan, SimulationRuntime, SimulationStep
from casulo.product.t_forge import TForge


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="RC11 integrated deterministic rehearsal around the real neural artifact")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--neural-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clean-root", type=Path, required=True)
    args = parser.parse_args()
    repo, evidence_path, output, clean = args.repo.resolve(), args.neural_evidence.resolve(strict=True), args.output.resolve(), args.clean_root.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output is not empty")
    if clean.exists() and any(clean.iterdir()):
        raise SystemExit("clean root is not empty")
    output.mkdir(parents=True, exist_ok=True)
    clean.mkdir(parents=True, exist_ok=True)
    neural = json.loads(evidence_path.read_text(encoding="utf-8"))
    neural_creation = json.loads((evidence_path.parent / "creation/g5-first-open-ended-agent.json").read_text(encoding="utf-8"))

    kernel = GuideContinuityKernel()
    projects = {
        "photo": "Nunca sobrescrever o scan original; toda operação precisa ser reversível.",
        "flood": "Trabalhar somente com telemetria validada e datum explícito.",
        "citations": "Toda citação precisa de origem verificável e nenhuma fonte inventada.",
    }
    for index, (project, constraint) in enumerate(projects.items(), start=1):
        kernel.open_project(project, source_event_id=f"human:open:{project}")
        kernel.add_constraint(constraint_id=f"{project}:hard", project_id=project, key="hard-boundary", statement=constraint, strength=ConstraintStrength.HARD, source_event_ids=(f"human:constraint:{project}",))
        kernel.record(record_id=f"{project}:decision", project_id=project, kind=RecordKind.DECISION, text=f"Decisão confirmada do projeto {project}: {constraint}", source_event_ids=(f"human:decision:{index}",), criticality=10)
    contexts = {project: [item.text for item in kernel.select_context(project_id=project, query="retome a restrição principal", budget_chars=2000)] for project in projects}
    no_bleed = all(all(other not in " ".join(context).casefold() for other in projects if other != project) for project, context in contexts.items())

    preserve = kernel.add_constraint(constraint_id="photo:preserve", project_id="photo", key="write-policy", statement="Preservar o original e escrever apenas derivados.", strength=ConstraintStrength.HARD, source_event_ids=("human:photo:preserve",))
    kernel.add_constraint(constraint_id="photo:overwrite", project_id="photo", key="write-policy", statement="Sobrescrever o original para economizar espaço.", strength=ConstraintStrength.HARD, source_event_ids=("human:photo:contradiction",))
    conflict_before = kernel.constraints.review("photo")
    resolved = kernel.resolve_constraint(winning_constraint_id=preserve.constraint_id, human_event_id="human:photo:resolve-preserve", explicit_human_approval=True)
    conflict_after = kernel.constraints.review("photo")

    digest = hashlib.sha256(b"rc11-job-start").hexdigest()
    started = JobEvent("rc11:job:started", "rc11:generation", JobStatus.STARTED, "Geração neural iniciada; nenhum artefato concluído.", digest, ("human:photo:start",), "2026-08-14T21:30:00Z")
    kernel.accept_job_event(started)
    during_job = kernel.directive(project_id="photo", query="continue conversando sem fingir conclusão", budget_chars=4000)
    cancelled = JobEvent("rc11:job:cancelled", "rc11:generation", JobStatus.CANCELLED, "Geração interrompida antes de publicação; novo requisito será usado em outro job.", hashlib.sha256(b"rc11-job-cancelled").hexdigest(), (started.event_id, "human:barge-in"), "2026-08-14T21:30:02Z")
    kernel.accept_job_event(cancelled)
    kernel.record(record_id="photo:new-requirement", project_id="photo", kind=RecordKind.DECISION, text="A versão corrigida também deve gerar máscara editável por etapa.", source_event_ids=("human:barge-in:new-requirement",), criticality=10)
    rebooted = GuideContinuityKernel.from_event_log(kernel.event_log)

    archive_v7 = Path(neural_creation["materialization"]["archive"]).resolve(strict=True)
    imported_v7 = MaterializedPackageImporter().import_archive(archive_v7)
    with zipfile.ZipFile(archive_v7) as archive:
        archive.extractall(clean)
    operation = imported_v7.agent_operation
    if operation is None:
        raise RuntimeError("neural package has no executable operation")
    env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT") if name in os.environ}
    execution = subprocess.run([sys.executable, "-X", "utf8", "-I", str(clean / "agent.py"), operation, "-"], input=json.dumps({"value": "restauro conservativo"}), capture_output=True, text=True, encoding="utf-8", cwd=clean, env=env, check=False, timeout=20)

    content_v8 = copy.deepcopy(dict(imported_v7.creation.content))
    content_v8.setdefault("interface", {})["editable_mask"] = {"description": "Máscara editável por etapa, adicionada após interrupção humana."}
    creation_v8 = CreationSpec(imported_v7.creation.creation_id, imported_v7.creation.version + 1, CreationState.AGREEMENT, content_v8, imported_v7.creation.capabilities, imported_v7.creation.rejected_delta_ids)
    forge_v8 = TForge().compile(creation_units(creation_v8), affected_paths=(("interface", "editable_mask"),))
    confirmation_v8 = CreationSpec(creation_v8.creation_id, creation_v8.version, CreationState.CONFIRMATION, creation_v8.content, creation_v8.capabilities)
    simulation = SimulationRuntime({Effect.MEMORY_READ: SimulationCapabilityDouble(Effect.MEMORY_READ, (SimulatedResponse(True, {"virtual": True, "mask": "editable"}),))}).run(
        confirmation_v8,
        SimulationPlan("simulation:rc11:v8", creation_v8.creation_id, (SimulationStep("virtual-mask", Effect.MEMORY_READ, "preview", {"source": "simulation://photo"}, (), (("interface", "editable_mask"),), ("human:barge-in:new-requirement",)),), ("human:barge-in:new-requirement",)),
    )
    materialized_v7 = Path(neural_creation["materialization"]["directory"]).resolve(strict=True)
    descriptor = json.loads((materialized_v7 / "agent-descriptor.json").read_text(encoding="utf-8"))
    bundle = ExecutableAgentBundle(
        descriptor["artifact_id"], descriptor["operation"], (materialized_v7 / "agent.py").read_bytes(),
        json.loads((materialized_v7 / "agent-artifact-manifest.json").read_text(encoding="utf-8")),
        (materialized_v7 / "agent.tcap").read_bytes(), json.loads((materialized_v7 / "agent-project.json").read_text(encoding="utf-8")),
        (evidence_path.parent / "creation/entry-build/source.t").read_bytes(),
    )
    receipt_v8 = Materializer(output / "roundtrip-v2").materialize(creation_v8, forge_receipt=forge_v8, simulation_receipt=simulation, executable_bundle=bundle)
    imported_v8 = MaterializedPackageImporter().import_archive(receipt_v8.archive)
    overlay = evidence_path.parent / "vm/state/owner-overlay.qcow2"
    base = repo / "release/casulo-native-generative-interactive.img"
    checks = {
        "real_neural_owner_creation": neural.get("gate") == "SM8_OWNER_VERTICAL_SLICE_PASS" and all(neural.get("checks", {}).values()),
        "three_projects_isolated": len(contexts) == 3 and no_bleed,
        "hard_contradiction_blocked": conflict_before.blocking and conflict_before.requires_human_decision,
        "human_resolution_preserved": resolved.statement.startswith("Preservar") and conflict_after.compatible,
        "presence_during_job": during_job.project_id == "photo" and kernel.snapshot()["jobs"]["rc11:generation"] == "CANCELLED",
        "interrupt_changes_requirement": any(item.get("record_id") == "photo:new-requirement" for item in kernel.snapshot()["records"]),
        "compile_but_not_fulfill_detected": neural_creation["checks"]["real_compiled_process_test_failed_first"] is True,
        "diagnostic_repair": neural_creation["repair"]["repair_count"] >= 1 and neural_creation["repair"]["status"] == "PASS",
        "simulation_no_real_effects": simulation.status == "PASS" and simulation.real_effects_executed is False,
        "external_clean_execution": execution.returncode == 0 and "preserva o original" in execution.stdout.casefold() and not (clean / ".git").exists(),
        "roundtrip_v2": imported_v8.creation.creation_id == imported_v7.creation.creation_id and imported_v8.creation.version == imported_v7.creation.version + 1,
        "roundtrip_constraints": imported_v8.creation.content["constraints"] == imported_v7.creation.content["constraints"],
        "local_edit_present": "editable_mask" in imported_v8.creation.content["interface"],
        "event_chain_and_rehydrate": verify_event_chain(kernel.event_log) and rebooted.state_sha256 == kernel.state_sha256,
        "hot_empty_after_reboot": neural["reboot"]["hot_after_reboot"] == [],
        "catalog_rehydrated": neural["reboot"]["sessions"] == 1,
        "overlay_quota": overlay.is_file() and overlay.stat().st_size < 12 * 1024**3,
        "base_hash_preserved": base.is_file() and sha(base) == "74fe4b1130b40f5090c9944acdd4da0b86c122ab99be5a6b314f61a7e22b810b",
        "cloud_usb_science_boundaries": neural["cloud"] == "RELEASE_LOCKED" and neural["checks"]["usb_prohibited"] and neural["checks"]["scientific_benchmark_absent"],
    }
    report = {
        "schema": "casulo.rc11-rehearsal/1.0", "state": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
        "neural_evidence": {"path": str(evidence_path), "sha256": sha(evidence_path), "route": neural["route"]},
        "projects": contexts, "continuity_state_sha256": kernel.state_sha256, "event_count": len(kernel.event_log),
        "repair": neural_creation["repair"], "external_execution": {"returncode": execution.returncode, "stdout_sha256": hashlib.sha256(execution.stdout.encode()).hexdigest()},
        "roundtrip": {"v7_archive_sha256": sha(archive_v7), "v8_archive": str(receipt_v8.archive), "v8_archive_sha256": receipt_v8.archive_sha256},
        "human_chemistry": "PENDING_GUILHERME", "human_voice": "PENDING_GUILHERME", "design": "PROVISIONAL_OWNER_REVIEW_REQUIRED",
    }
    write_json(output / "rc11-rehearsal.json", report)
    print(json.dumps({"state": report["state"], "checks": checks, "v8_archive_sha256": receipt_v8.archive_sha256}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
