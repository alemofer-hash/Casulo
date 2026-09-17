from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from casulo_owner.generative_agent_probe import holdout_scanner_capability


EXPECTED = {
    "release/generative-vm/handoff/MANIFEST.json": "3529733742e6cd52537f1651a0488061e2f88dc4020339a450a14c57e8d69651",
    "product-demos/generative-vm/sprint10-integrated-attempt12/g10-integrated-handoff.json": "c698f3d649f0216b173270ca33f78617c4d8c37575a410798022243a90b9c9d6",
    "release/generative-vm/casulo-owner-generative-vm-g10-complete.zip": "bd223daf90ec64549d693fddce853cdc601d19c7c0d4c734ce90088b11fa9477",
    "release/CASULO_OWNER_VM_INSPECT.ps1": "e0452669dc33ce20320c59ccc4af94500561192cc9f52e9f8270fcea4fc0db12",
}
MINIMUM_RESERVE = 25 * 1024**3
CURRENT_HANDOFF = "release/semantic-multiverse/handoff-reinspection-2026-08-13"
CURRENT_STATE = "READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_handoff(repo: Path) -> dict[str, bool]:
    handoff_root = repo / CURRENT_HANDOFF
    manifest_path = handoff_root / "MANIFEST.json"
    signature_path = handoff_root / "DEVELOPMENT_SIGNATURE.json"
    detached_signature = handoff_root / "MANIFEST.json.sig"
    allowed_signers = handoff_root / "ALLOWED_SIGNERS"
    sums_path = handoff_root / "SHA256SUMS"
    if not all(path.is_file() for path in (manifest_path, signature_path, detached_signature, allowed_signers, sums_path)):
        return {
            "semantic_handoff_present": False,
            "semantic_handoff_ready": False,
            "semantic_handoff_checks": False,
            "semantic_handoff_signature": False,
            "semantic_handoff_sha256s": False,
            "semantic_dependencies_verified": False,
            "semantic_artifacts_verified": False,
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    signature = json.loads(signature_path.read_text(encoding="utf-8"))
    signature_verified = False
    try:
        verified = subprocess.run(
            [
                "ssh-keygen", "-Y", "verify", "-f", str(allowed_signers),
                "-I", "casulo-semantic-reinspection-dev", "-n", "casulo-release",
                "-s", str(detached_signature),
            ],
            input=manifest_path.read_bytes(),
            check=False,
            capture_output=True,
            shell=False,
        )
        signature_verified = verified.returncode == 0
    except OSError:
        signature_verified = False
    sums_valid = True
    for line in sums_path.read_text(encoding="ascii").splitlines():
        expected, name = line.split("  ", 1)
        target = handoff_root / name
        if not target.is_file() or sha(target) != expected:
            sums_valid = False
            break
    dependency_checks = []
    for item in manifest.get("dependencies", {}).values():
        if not isinstance(item, dict) or "path" not in item or "sha256" not in item:
            continue
        target = Path(item["path"])
        dependency_checks.append(target.is_file() and sha(target) == item["sha256"])
    artifact_checks = []
    for item in manifest.get("artifacts", []):
        if not isinstance(item, dict) or "path" not in item or "sha256" not in item:
            artifact_checks.append(False)
            continue
        target = Path(item["path"])
        artifact_checks.append(target.is_file() and sha(target) == item["sha256"])
    return {
        "semantic_handoff_present": True,
        "semantic_handoff_ready": manifest.get("state") == CURRENT_STATE,
        "semantic_handoff_checks": all(manifest.get("checks", {}).values()),
        "semantic_handoff_signature": (
            signature.get("label") == "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE"
            and signature.get("manifest_sha256") == sha(manifest_path)
            and signature_verified
        ),
        "semantic_handoff_sha256s": sums_valid,
        "semantic_dependencies_verified": bool(dependency_checks) and all(dependency_checks),
        "semantic_artifacts_verified": bool(artifact_checks) and all(artifact_checks),
    }


def doctor(repo: Path) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    hashes: dict[str, str | None] = {}
    for relative, expected in EXPECTED.items():
        path = repo / relative
        actual = sha(path) if path.is_file() else None
        hashes[relative] = actual
        checks[f"g10:{relative}"] = actual == expected
    handoff = json.loads((repo / "release/generative-vm/handoff/MANIFEST.json").read_text(encoding="utf-8"))
    free = shutil.disk_usage(repo).free
    scanner_capability = holdout_scanner_capability()
    holdout_scanner = str(scanner_capability["selected_backend"])
    checks.update(
        {
            "g10_state": handoff.get("state") == "READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION",
            "cloud_release_locked": handoff.get("cloud") == "RELEASE_LOCKED",
            "external_media_absent": handoff.get("external_media") == "NOT_IN_USE",
            "public_frozen": handoff.get("public") == "FROZEN",
            "minimum_25_gib_reserve": free >= MINIMUM_RESERVE,
            "semantic_launcher_present": (repo / "release/CASULO_SEMANTIC_MULTIVERSE_VM_INSPECT.ps1").is_file(),
            "semantic_runtime_present": (repo / "src/casulo/product/semantic_multiverse.py").is_file(),
            "semantic_ir_present": (repo / "src/casulo/t/semantic_ir.py").is_file(),
            "owner_adapter_present": (repo / "private/casulo-owner/src/casulo_owner/semantic_multiverse.py").is_file(),
            "holdout_scanner_available": holdout_scanner in {"rg", "bounded-python-literal-scan"},
        }
    )
    checks.update(_verify_handoff(repo))
    return {
        "schema": "casulo.semantic-multiverse-doctor/1.0",
        "ready": all(checks.values()), "read_only": True, "mutations_performed": False,
        "network_access_performed": False, "checks": checks, "baseline_hashes": hashes,
        "free_bytes": free, "minimum_reserve_bytes": MINIMUM_RESERVE,
        "holdout_scanner": holdout_scanner,
        "holdout_scanner_capability": scanner_capability,
        "cloud": "RELEASE_LOCKED", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY",
    }


def inspect_state(state_root: Path) -> dict[str, Any]:
    sessions = state_root / "owner-data" / "semantic-multiverse" / "sessions"
    values = []
    for path in sorted(sessions.glob("*.json")) if sessions.exists() else ():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values.append({"path": str(path), "sha256": sha(path), "operation_id": payload.get("operation_id"), "route": payload.get("universes_visited"), "hot_at_completion": payload.get("hot_at_completion")})
        except (OSError, UnicodeError, json.JSONDecodeError):
            values.append({"path": str(path), "status": "INVALID_NOT_USED"})
    return {"schema": "casulo.semantic-multiverse-inspection/1.0", "read_only": True, "session_count": len(values), "sessions": values}


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo Semantic Multiverse doctor/inspection")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_cmd = commands.add_parser("doctor")
    doctor_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    inspect_cmd = commands.add_parser("inspect")
    inspect_cmd.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args()
    result = doctor(args.repo.resolve()) if args.command == "doctor" else inspect_state(args.state_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if args.command != "doctor" or result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
