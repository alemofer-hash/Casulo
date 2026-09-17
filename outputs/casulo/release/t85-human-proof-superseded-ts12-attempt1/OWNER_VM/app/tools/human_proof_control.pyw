from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_root(release_root: Path) -> Path:
    root = release_root.resolve()
    if root.parent.name.casefold() != "release" or root.name.casefold() not in {"human-proof", "t85-human-proof"}:
        raise RuntimeError("o pacote precisa permanecer em release/human-proof ou release/t85-human-proof")
    bundled = root / "OWNER_VM" / "app"
    if bundled.is_dir():
        return bundled
    return root.parents[1]


def verify_release(release_root: Path) -> dict[str, Any]:
    release_root = release_root.resolve(strict=True)
    repo = repository_root(release_root)
    manifest_path = release_root / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[dict[str, str]] = []
    for entry in manifest.get("files", []):
        relative = Path(entry["path"])
        candidate = (release_root / relative).resolve(strict=False)
        try:
            candidate.relative_to(release_root)
        except ValueError:
            mismatches.append({"path": relative.as_posix(), "reason": "path_escape"})
            continue
        if not candidate.is_file():
            mismatches.append({"path": relative.as_posix(), "reason": "missing"})
        elif sha256(candidate) != entry["sha256"]:
            mismatches.append({"path": relative.as_posix(), "reason": "sha256"})

    signature_metadata = json.loads((release_root / "DEVELOPMENT_SIGNATURE.json").read_text(encoding="utf-8"))
    signature = subprocess.run(
        [
            "ssh-keygen", "-Y", "verify", "-f", str(release_root / "ALLOWED_SIGNERS"),
            "-I", str(signature_metadata["identity"]), "-n", str(signature_metadata["namespace"]),
            "-s", str(release_root / "MANIFEST.json.sig"),
        ],
        input=manifest_path.read_bytes(),
        capture_output=True,
        check=False,
        shell=False,
    )
    candidate_path = repo / ("registry/qwen3-4b-q4km-llamacpp-b10362.json" if (repo / "registry").is_dir() else "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/generative" / candidate["candidate_id"]
    model = cache / "model" / candidate["model"]["file"]
    runtime = cache / "runtime" / candidate["runtime"]["required_executable"]
    checks = {
        "manifest_files": not mismatches,
        "development_signature": signature.returncode == 0,
        "base_vm": (release_root / "OWNER_VM/casulo-native-generative-interactive.img").is_file(),
        "model_verified": model.is_file() and sha256(model) == candidate["model"]["sha256"],
        "runtime_available": runtime.is_file(),
        "cloud_locked": manifest.get("boundaries", {}).get("cloud") == "RELEASE_LOCKED",
        "guest_network_off": manifest.get("boundaries", {}).get("guest_network_default") == "OFF",
        "physical_devices_prohibited": manifest.get("boundaries", {}).get("usb_block_devices") == "PROHIBITED",
        "human_proof_pending": manifest.get("human_proof") == "PENDING_GUILHERME",
        "checkout_independent": not (release_root / "OWNER_VM/app").is_dir() or repo == (release_root / "OWNER_VM/app").resolve(),
    }
    return {
        "schema": "casulo.human-proof-verification/1.0",
        "ready": all(checks.values()),
        "read_only": True,
        "checks": checks,
        "mismatches": mismatches,
        "manifest_sha256": sha256(manifest_path),
        "signature_output": (signature.stdout + signature.stderr).decode("utf-8", "replace").strip(),
    }


def controller_for_release(release_root: Path):
    repo = repository_root(release_root)
    sys.path[:0] = [str(repo), str(repo / "src"), str(repo / "private/casulo-owner/src")]
    from tools.casulo_semantic_multiverse_vm_inspect import prepare_semantic_controller

    state_name = "t85-human-proof" if release_root.resolve().name.casefold() == "t85-human-proof" else "human-proof"
    state_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / f"Casulo/{state_name}/owner-vm"
    return prepare_semantic_controller(
        release_root / "OWNER_VM/casulo-native-generative-interactive.img",
        state_root,
    )


def restore_clean(release_root: Path) -> dict[str, Any]:
    controller = controller_for_release(release_root.resolve(strict=True))
    snapshot_name = "t85-human-proof-clean" if release_root.resolve().name.casefold() == "t85-human-proof" else "human-proof-clean"
    if not controller.snapshot_exists(snapshot_name):
        controller.snapshot(snapshot_name)
    result = controller.reset_to_snapshot(snapshot_name)
    result.update({"schema": "casulo.human-proof-restore/1.0", "feedback_preserved": True})
    return result


def collect_feedback(release_root: Path, note: str, output: Path | None = None) -> dict[str, Any]:
    normalized = " ".join(note.split())
    if not normalized or len(normalized) > 4000:
        raise RuntimeError("a nota precisa conter de 1 a 4000 caracteres")
    root = output or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/owner-human-proof-feedback")
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    note_id = hashlib.sha256(f"{timestamp}\0{normalized}".encode("utf-8")).hexdigest()[:16]
    record = {
        "schema": "casulo.human-proof-note/1.0",
        "note_id": note_id,
        "timestamp": timestamp,
        "channel": "selected-text",
        "text": normalized,
        "raw_audio_persisted": False,
        "full_transcript_persisted": False,
        "authority": "GUILHERME_REVIEW_PENDING",
        "release_manifest_sha256": sha256(release_root / "MANIFEST.json"),
    }
    destination = root / "notes.jsonl"
    with destination.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {"schema": "casulo.human-proof-feedback/1.0", "saved": True, "note_id": note_id, "path": str(destination)}


def show_result(title: str, result: dict[str, Any], *, error: bool = False) -> None:
    from tkinter import messagebox

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    (messagebox.showerror if error else messagebox.showinfo)(title, text[:3500])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("verify", "restore", "feedback"))
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--note")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "verify":
            result = verify_release(args.release)
        elif args.action == "restore":
            result = restore_clean(args.release)
        else:
            note = args.note
            if note is None:
                from tkinter.simpledialog import askstring
                note = askstring("Casulo · feedback", "O que você quer preservar desta sessão?")
            if note is None:
                return 0
            result = collect_feedback(args.release.resolve(strict=True), note, args.output)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            show_result("Casulo", result, error=not result.get("ready", result.get("saved", True)))
        return 0 if result.get("ready", result.get("saved", True)) else 2
    except Exception as error:
        result = {"schema": "casulo.human-proof-error/1.0", "recoverable": True, "error_type": type(error).__name__, "message": " ".join(str(error).split())[:600]}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            show_result("Casulo · ação recuperável", result, error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
