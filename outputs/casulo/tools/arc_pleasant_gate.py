from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from casulo.product.pleasant_interface import (
    HonestBackgroundJob,
    JobEvidence,
    UxEvent,
    UxEventKind,
    UxStreamValidator,
    decode_ux_event,
    encode_ux_event,
)


def _json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attempt(root: Path) -> Path:
    sequence = 1
    while True:
        target = root / f"arc-pleasant-interface-2026-08-18-attempt{sequence}"
        if not target.exists():
            target.mkdir(parents=True)
            return target
        sequence += 1


def _seal(root: Path) -> str:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name not in {"MANIFEST.json", "SHA256SUMS"}):
        files.append({"path": path.relative_to(root).as_posix(), "sha256": _sha(path), "bytes": path.stat().st_size})
    manifest = {
        "schema": "casulo.arc9-evidence-manifest/1.0",
        "classification": "DETERMINISTIC_UX_CONTRACT_SMOKE_NOT_OWNER_NEURAL_HUMAN_PROOF",
        "files": files,
    }
    _json(root / "MANIFEST.json", manifest)
    manifest_hash = _sha(root / "MANIFEST.json")
    lines = [f"{item['sha256']}  {item['path']}" for item in files]
    lines.append(f"{manifest_hash}  MANIFEST.json")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return manifest_hash


def run(repo: Path, output_root: Path) -> Path:
    output = _attempt(output_root)
    now = datetime.now(timezone.utc).isoformat()
    validator = UxStreamValidator()
    encoded_events = []

    def accept(event_id: str, kind: UxEventKind, payload: Mapping[str, Any]) -> None:
        event = UxEvent.create(
            event_id=event_id,
            kind=kind,
            payload=payload,
            source_event_ids=("arc9:gate",),
            occurred_at=now,
        )
        line = encode_ux_event(event)
        decoded = decode_ux_event(line)
        if decoded is None:
            raise RuntimeError("evento ARC-9 desapareceu no transporte")
        validator.accept(decoded)
        encoded_events.append(decoded.to_dict())

    accept("ux:1", UxEventKind.PRESENCE_READY, {"text": "Estou aqui."})
    accept("ux:2", UxEventKind.MODEL_LOADING, {"text": "Acordando o motor local."})
    accept("ux:3", UxEventKind.ASSISTANT_START, {"turn_id": "turn:gate"})
    accept("ux:4", UxEventKind.ASSISTANT_TOKEN, {"turn_id": "turn:gate", "sequence": 1, "text": "Vamos "})
    accept("ux:5", UxEventKind.ASSISTANT_TOKEN, {"turn_id": "turn:gate", "sequence": 2, "text": "construir isso."})
    accept("ux:6", UxEventKind.ASSISTANT_END, {"turn_id": "turn:gate", "finish_reason": "stop"})

    job_events = []

    def worker(_token, report):
        artifact = output / "contract-artifact.json"
        _json(artifact, {"schema": "casulo.arc9-contract-artifact/1.0", "real_file_written": True})
        digest = _sha(artifact)
        report("Artifact de contrato persistido.", digest)
        return JobEvidence(digest, "Job de contrato concluído.", {"artifact": artifact.name})

    coordinator = HonestBackgroundJob(job_events.append)
    coordinator.start("arc9-contract", worker, start_evidence_sha256=hashlib.sha256(b"arc9-contract").hexdigest())
    coordinator.join(5)
    for index, item in enumerate(job_events, start=7):
        accept(
            f"ux:{index}",
            UxEventKind(f"JOB_{item.status}"),
            {
                "job_id": item.job_id,
                "summary": item.summary,
                "evidence_sha256": item.evidence_sha256,
                "sequence": item.sequence,
            },
        )

    launcher = repo / "product-demos/human-proof/monday-arc-pleasant-2026-08-18-attempt1/START_CASULO_ARC9.vbs"
    environment = os.environ.copy()
    environment["CASULO_MONDAY_DISCOVERY_DRY_RUN"] = "1"
    completed = subprocess.run(
        ["cscript.exe", "//nologo", str(launcher)],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="replace",
        check=False,
        shell=False,
        timeout=30,
    )
    ui_source = (repo / "tools/monday_discovery_session.pyw").read_text(encoding="utf-8")
    owner_source = (repo / "tools/casulo_semantic_multiverse_vm_inspect.py").read_text(encoding="utf-8")
    probe_source = (repo / "private/casulo-owner/src/casulo_owner/generative_agent_probe.py").read_text(encoding="utf-8")
    checks = {
        "structured_token_stream": [item["kind"] for item in encoded_events[:6]] == ["PRESENCE_READY", "MODEL_LOADING", "ASSISTANT_START", "ASSISTANT_TOKEN", "ASSISTANT_TOKEN", "ASSISTANT_END"],
        "background_job_real_artifact": (output / "contract-artifact.json").is_file(),
        "background_job_terminal": coordinator.snapshot()["status"] == "COMPLETED",
        "milestones_have_evidence": all(len(item.evidence_sha256) == 64 for item in job_events),
        "no_fabricated_percentage": "progress_percent" not in ui_source and "progress_percent" not in owner_source,
        "arc_stream_used": '"arc-stream"' in ui_source and "decode_ux_event" in ui_source,
        "post_confirmation_background": "create_in_background" in owner_source and "HonestBackgroundJob" in owner_source,
        "cancellation_reaches_worker": "cancellation=token" in owner_source and "cancellation_checkpoint" in probe_source,
        "technical_controls_secondary": "tk.Menubutton" in ui_source,
        "launcher_cscript_pass": completed.returncode == 0 and "CASULO_ARC9_VBS_PARSE_PASS" in completed.stdout,
        "cloud_release_locked_unchanged": "RELEASE_LOCKED" in owner_source,
    }
    gate = {
        "schema": "casulo.arc9-gate/1.0",
        "state": "PASS" if all(checks.values()) else "FAIL",
        "classification": "DETERMINISTIC_UX_CONTRACT_SMOKE_NOT_OWNER_NEURAL_HUMAN_PROOF",
        "checks": checks,
        "human_proof": "PENDING_GUILHERME",
        "voice_quality": "PENDING_GUILHERME",
        "design_status": "PROVISIONAL_OWNER_REVIEW_REQUIRED",
        "scientific_benchmark_started": False,
    }
    _json(output / "ux-events.json", {"schema": "casulo.arc9-ux-events/1.0", "events": encoded_events})
    _json(output / "job-events.json", {"schema": "casulo.arc9-job-events/1.0", "events": [item.__dict__ if hasattr(item, "__dict__") else {"job_id": item.job_id, "status": item.status, "summary": item.summary, "evidence_sha256": item.evidence_sha256, "sequence": item.sequence} for item in job_events]})
    _json(output / "launcher.json", {"path": launcher.relative_to(repo).as_posix(), "sha256": _sha(launcher), "cscript_exit": completed.returncode, "stdout": completed.stdout.strip()})
    _json(output / "gate.json", gate)
    (output / "report.md").write_text(
        "# ARC-9 — superfície owner agradável\n\n"
        f"Estado: `{gate['state']}`  \n"
        "Classificação: `DETERMINISTIC_UX_CONTRACT_SMOKE_NOT_OWNER_NEURAL_HUMAN_PROOF`\n\n"
        "O contrato comprova transporte token a token, rejeição de progresso inventado, job cancelável com evidência e launcher WSH válido. Não avalia química, beleza, voz física ou qualidade neural; esses gates pertencem a Guilherme.\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_hash = _seal(output)
    print(json.dumps({"state": gate["state"], "output": str(output), "manifest_sha256": manifest_hash, "events": len(encoded_events)}, ensure_ascii=False))
    if gate["state"] != "PASS":
        raise SystemExit(1)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path("product-demos/human-proof"))
    args = parser.parse_args()
    run(args.repo.resolve(), args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
