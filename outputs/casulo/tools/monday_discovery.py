from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from casulo.product.discovery_session import verify_chain


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_new(path: Path, payload: Any) -> Path:
    candidate = path
    index = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.stem}-attempt-{index}{path.suffix}")
        index += 1
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return candidate


def load_module(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise RuntimeError(f"modulo nao carregavel: {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def doctor(release: Path) -> dict[str, Any]:
    release = release.resolve(strict=True)
    control = load_module("monday_discovery_control", release / "OWNER_VM/app/tools/human_proof_control.pyw")
    release_verification = control.verify_release(release)
    registry = read(release / "OWNER_VM/CONTENT_REGISTRY.json")
    candidate_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/generative" / registry["model"]["candidate_id"]
    model = candidate_root / "model" / Path(registry["model"]["cache_relative"]).name
    runtime_entries = registry["neural_runtime"]["runtime_tree"]
    runtime_mismatches = []
    for item in runtime_entries:
        path = candidate_root / item["path"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != int(item["bytes"]) or sha256(path) != item["sha256"]:
            runtime_mismatches.append(item["path"])
    qemu = Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe")
    qemu_img = Path(r"C:\Program Files\qemu\qemu-img.exe")
    ovmf_code = Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd")
    ovmf_vars = Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd")
    version = "UNAVAILABLE"
    if qemu.is_file():
        completed = subprocess.run([str(qemu), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False, timeout=15)
        version = completed.stdout.splitlines()[0] if completed.stdout else "UNAVAILABLE"
    final_gate = read(ROOT / "product-demos/t85-sovereign-engine/ts15-reseal-attempt1/final-gate-attempt3.json")
    public_audit = read(ROOT / "product-demos/t85-sovereign-engine/ts15-reseal-attempt1/editions/public/PUBLIC_AUDIT.json")
    cloud = read(ROOT / "product-demos/t85-sovereign-engine/ts15-reseal-attempt1/editions/cloud-standby/MANIFEST.json")
    checks = {
        "release_verifier": release_verification["ready"] is True,
        "release_manifest_expected": release_verification["manifest_sha256"] == "87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee",
        "model_full_hash": model.is_file() and not model.is_symlink() and model.stat().st_size == int(registry["model"]["bytes"]) and sha256(model) == registry["model"]["sha256"],
        "llama_runtime_tree": len(runtime_mismatches) == 0 and len(runtime_entries) == 51,
        "qemu": qemu.is_file() and qemu_img.is_file(),
        "ovmf": ovmf_code.is_file() and ovmf_vars.is_file(),
        "base_vm_hash": sha256(release / "OWNER_VM/casulo-native-generative-interactive.img") == registry["base_vm"]["sha256"],
        "t_runtime_hash": sha256(release / "OWNER_VM" / registry["t_runtime"]["relative"]) == registry["t_runtime"]["sha256"],
        "final_gate": final_gate["gate"] == "TS15_RESEAL_HANDOFF_PASS" and all(final_gate["checks"].values()),
        "public_private_zero": public_audit["private_components_absent"] is True and not public_audit["forbidden_findings"],
        "cloud_locked": cloud["release_state"] == "RELEASE_LOCKED",
        "physical_voice_not_opened": True,
    }
    return {
        "schema": "casulo.monday-discovery-doctor/1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "read_only": True,
        "ready": all(checks.values()),
        "checks": checks,
        "release": release_verification,
        "model": {"path": str(model), "bytes": model.stat().st_size if model.is_file() else None, "sha256": registry["model"]["sha256"]},
        "runtime": {"expected_files": len(runtime_entries), "mismatches": runtime_mismatches},
        "vm": {"qemu_version": version, "base_hash": registry["base_vm"]["sha256"], "guest_network": "OFF", "block_devices": "PROHIBITED"},
        "boundaries": {"cloud": "RELEASE_LOCKED", "owner_network_api": "ABSENT", "physical_voice": "NOT_OPENED", "scientific_benchmark": "NOT_STARTED"},
    }


def analyse_session(session_root: Path) -> dict[str, Any]:
    session_root = session_root.resolve(strict=True)
    session = read(session_root / "session.json")
    automated_path = session_root / "automated-events.jsonl"
    human_path = session_root / "human-notes.jsonl"
    automated = [json.loads(line) for line in automated_path.read_text(encoding="utf-8").splitlines() if line] if automated_path.exists() else []
    human = [json.loads(line) for line in human_path.read_text(encoding="utf-8").splitlines() if line] if human_path.exists() else []
    auto_chain = verify_chain(automated_path, hash_field="event_hash", previous_field="previous_hash")
    human_chain = verify_chain(human_path, hash_field="note_hash", previous_field="previous_hash")
    summary = read(session_root / "session-summary.json") if (session_root / "session-summary.json").is_file() else None
    frictions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, severity: str, source: str, event_id: str, evidence: str) -> None:
        key = (kind, event_id)
        if key in seen:
            return
        seen.add(key)
        frictions.append(
            {
                "friction_id": f"M1-SESSION-{len(frictions) + 1:03d}",
                "kind": kind,
                "severity": severity,
                "source": source,
                "evidence": evidence,
                "source_event_id": event_id,
            }
        )

    for event in automated:
        kind = event["kind"]
        if kind == "TRACEBACK_EXPOSED":
            add("TRACEBACK_EXPOSED", "P1", "AUTOMATED_DIAGNOSTIC", event["event_id"], "hash de linha no evento automatizado")
        elif kind == "INFRASTRUCTURE_EXPOSED":
            add("INFRASTRUCTURE_EXPOSED", "P1", "AUTOMATED_DIAGNOSTIC", event["event_id"], "fingerprint de infraestrutura no evento automatizado")
        elif kind in {"COMPONENT_FAILURE", "RECOVERABLE_FAILURE"}:
            add(kind, "P1" if kind == "COMPONENT_FAILURE" else "P2", "AUTOMATED_DIAGNOSTIC", event["event_id"], "evento automatizado append-only")
        elif kind == "SILENCE_THRESHOLD" and int(event["payload"].get("threshold_ms", 0)) >= 30_000:
            add("RESPONSE_SILENCE_GE_30S", "P2", "AUTOMATED_DIAGNOSTIC", event["event_id"], "relógio monotônico do observer")
    for note in human:
        severity = note["severity"] if note["severity"] != "UNASSESSED" else "P2"
        add(note["category"], severity, "HUMAN_OPINION_GUILHERME", note["note_id"], "texto humano explicitamente submetido em human-notes.jsonl")
    has_verdict = any(note["category"] == "SESSION_VERDICT" for note in human)
    # A single process lifetime cannot prove reboot/recall. Only the campaign
    # analyser may promote the atlas after at least two session roots.
    state = "READY_FOR_GUILHERME_MONDAY_DISCOVERY_SESSION"
    return {
        "schema": "casulo.monday-discovery-session-analysis/1.0",
        "state": state,
        "session_id": session["session_id"],
        "chains": {"automated": auto_chain, "human": human_chain},
        "summary": summary,
        "human_session_verdict_present": has_verdict,
        "session_ready_for_campaign": summary is not None and auto_chain["valid"] and human_chain["valid"],
        "frictions": frictions,
        "privacy": {"raw_audio_persisted": False, "observer_transcripts_persisted": False, "secrets_included": False},
        "next_action": "incorporar notas no atlas" if has_verdict else "Guilherme deve concluir o roteiro e registrar uma nota SESSION_VERDICT",
    }


def analyse_campaign(campaign_root: Path) -> dict[str, Any]:
    campaign_root = campaign_root.resolve(strict=True)
    sessions = sorted(path for path in campaign_root.glob("session-*") if (path / "session.json").is_file())
    analyses = [analyse_session(path) for path in sessions]
    all_chains_valid = bool(analyses) and all(
        item["chains"]["automated"]["valid"] and item["chains"]["human"]["valid"] for item in analyses
    )
    has_verdict = any(item["human_session_verdict_present"] for item in analyses)
    reboot_exercised = len(analyses) >= 2
    state = (
        "MONDAY_FAILURE_ATLAS_COMPLETE"
        if all_chains_valid and has_verdict and reboot_exercised
        else "READY_FOR_GUILHERME_MONDAY_DISCOVERY_SESSION"
    )
    frictions: list[dict[str, Any]] = []
    for analysis in analyses:
        for friction in analysis["frictions"]:
            frictions.append({**friction, "session_id": analysis["session_id"]})
    return {
        "schema": "casulo.monday-discovery-campaign-analysis/1.0",
        "state": state,
        "campaign_root": str(campaign_root),
        "sessions": len(analyses),
        "all_chains_valid": all_chains_valid,
        "human_session_verdict_present": has_verdict,
        "reboot_exercised": reboot_exercised,
        "frictions": frictions,
        "session_analyses": analyses,
        "next_action": (
            "incorporar o resultado em docs/product/MONDAY_FAILURE_ATLAS_2026-08-17.*"
            if state == "MONDAY_FAILURE_ATLAS_COMPLETE"
            else "concluir duas sessões (antes/depois do reboot) e registrar SESSION_VERDICT"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo Monday Discovery M1")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--release", type=Path, default=ROOT / "release/t85-human-proof")
    doctor_parser.add_argument("--output", type=Path)
    analyse_parser = sub.add_parser("analyze")
    analyse_parser.add_argument("--session-root", type=Path, required=True)
    analyse_parser.add_argument("--output", type=Path)
    campaign_parser = sub.add_parser("analyze-campaign")
    campaign_parser.add_argument("--campaign-root", type=Path, required=True)
    campaign_parser.add_argument("--output", type=Path)
    verify_parser = sub.add_parser("verify-session")
    verify_parser.add_argument("--session-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "doctor":
        payload = doctor(args.release)
        output = write_new(args.output, payload) if args.output else None
    elif args.command == "analyze":
        payload = analyse_session(args.session_root)
        output = write_new(args.output or args.session_root / "analysis.json", payload)
    elif args.command == "analyze-campaign":
        payload = analyse_campaign(args.campaign_root)
        output = write_new(args.output or args.campaign_root / "campaign-analysis.json", payload)
    else:
        root = args.session_root.resolve(strict=True)
        payload = {
            "automated": verify_chain(root / "automated-events.jsonl", hash_field="event_hash", previous_field="previous_hash"),
            "human": verify_chain(root / "human-notes.jsonl", hash_field="note_hash", previous_field="previous_hash"),
        }
        payload["valid"] = payload["automated"]["valid"] and payload["human"]["valid"]
        output = None
    result = {**payload, **({"output": str(output)} if output else {})}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ready", result.get("valid", True)) is not False else 2


if __name__ == "__main__":
    raise SystemExit(main())
