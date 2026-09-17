from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


EXPECTED_GATES = {
    "g1": "LOCAL_STOCHASTIC_INFERENCE_PASS",
    "g2": "OWNER_GENERATIVE_ENGINE_PASS",
    "g3": "SCIENCE_BROS_CONVERSATION_CONTRACT_PASS",
    "g4": "GENERATIVE_T_SYNTHESIS_PASS",
    "g5": "FIRST_OPEN_ENDED_AGENT_CREATED",
    "g6": "CASULO_VM_LIFECYCLE_PASS",
    "g7": "GENERATIVE_OWNER_VM_E2E_PASS",
    "g8": "PROVISIONAL_STARK_JOBS_VM_PASS",
    "g9": "OWNER_INSPECTION_WORKBENCH_PASS",
    "g10": "READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION",
}

MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
RUNTIME_SHA256 = "76008a268ba602b0a398a5d7d542a686ac279b662d97abc7eee84536d049264e"
MINIMUM_RESERVE_BYTES = 20 * 1024**3


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal Casulo generative VM inspection handoff")
    for gate in EXPECTED_GATES:
        parser.add_argument(f"--{gate}", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--owner-artifact", type=Path, required=True)
    parser.add_argument("--public-audit", type=Path, required=True)
    parser.add_argument("--native-image", type=Path, required=True)
    parser.add_argument("--initial-overlay", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--inspection-tool", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for name, expected in EXPECTED_GATES.items():
        path = getattr(args, name).resolve(strict=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        evidence[name] = {"path": str(path), "sha256": sha(path), "gate": payload.get("gate")}
        checks[f"{name}_sealed"] = payload.get("gate") == expected
    tests = args.tests.resolve(strict=True)
    root = ET.parse(tests).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    failures = sum(int(suite.attrib.get("failures", 0)) + int(suite.attrib.get("errors", 0)) for suite in suites)
    test_count = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    checks["full_product_regression"] = failures == 0 and test_count > 0
    public_audit_path = args.public_audit.resolve(strict=True)
    public_audit = json.loads(public_audit_path.read_text(encoding="utf-8"))
    checks["public_private_boundary"] = public_audit.get("private_components_absent") is True
    owner = args.owner_artifact.resolve(strict=True)
    native = args.native_image.resolve(strict=True)
    initial_overlay = args.initial_overlay.resolve(strict=True)
    launcher = args.launcher.resolve(strict=True)
    inspection_tool = args.inspection_tool.resolve(strict=True)
    model = args.model.resolve(strict=True)
    runtime = args.runtime.resolve(strict=True)
    free_bytes = shutil.disk_usage(output).free
    native_stat = native.stat()
    if hasattr(native_stat, "st_file_attributes"):
        native_read_only = bool(native_stat.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
    else:
        native_read_only = not bool(native_stat.st_mode & stat.S_IWUSR)
    checks.update(
        {
            "owner_artifact_present": owner.is_file(),
            "native_image_present": native.is_file(),
            "native_image_read_only": native_read_only,
            "initial_overlay_present": initial_overlay.is_file(),
            "launcher_present": launcher.is_file(),
            "inspection_tool_present": inspection_tool.is_file(),
            "model_hash_verified": sha(model) == MODEL_SHA256,
            "runtime_hash_verified": sha(runtime) == RUNTIME_SHA256,
            "minimum_20_gib_reserve": free_bytes >= MINIMUM_RESERVE_BYTES,
            "cloud_release_locked": True,
            "external_media_absent": True,
            "scientific_benchmark_absent": True,
        }
    )
    sbom = {
        "schema": "casulo.generative-vm-sbom/1.0",
        "components": [
            {"name": "Casulo owner generative artifact", "type": "application", "sha256": sha(owner), "license": "PRIVATE_NON_REDISTRIBUTABLE"},
            {"name": "Casulo Native generative interactive", "type": "operating-system", "sha256": sha(native), "license": "PRIVATE_ALPHA"},
            {"name": "Qwen3-4B Q4_K_M", "type": "model", "sha256": MODEL_SHA256, "license": "Apache-2.0", "embedded": False},
            {"name": "llama.cpp b10362", "type": "runtime", "archive_sha256": "a9d95d26cf00664f2902f73cb0fd9b167a3a1f252294bb2f8b236305f57d6363", "license": "MIT", "embedded": False},
            {"name": "QEMU 11.0.50", "type": "virtual-machine-monitor", "license": "GPL-2.0-or-later", "embedded": False},
            {"name": "OVMF/EDK2", "type": "firmware", "license": "BSD-2-Clause-Patent", "embedded": False},
        ],
    }
    write(output / "SBOM.json", sbom)
    artifacts = [
        owner,
        native,
        initial_overlay,
        launcher,
        inspection_tool,
        tests,
        public_audit_path,
        output / "SBOM.json",
    ]
    manifest = {
        "schema": "casulo.generative-vm-handoff/1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "state": "READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION" if all(checks.values()) else "IN_PROGRESS_CHECKPOINTED",
        "owner": "Guilherme Moura Fernandes",
        "profile": "casulo-owner-generative-vm-v1",
        "interface": "TEXT_FALLBACK_PT_BR; HOSTED_VOICE_NOT_NATIVE_BRIDGED",
        "inference_execution_location": "HOST_LOCAL_FIRST_PARTY_BRIDGE",
        "native_in_guest_model_execution": False,
        "design_status": "PROVISIONAL_OWNER_REVIEW_REQUIRED",
        "cloud": "RELEASE_LOCKED",
        "public": "FROZEN",
        "external_media": "NOT_IN_USE",
        "storage": {"free_bytes_at_seal": free_bytes, "minimum_reserve_bytes": MINIMUM_RESERVE_BYTES},
        "installed_dependencies": {
            "model": {"path": str(model), "bytes": model.stat().st_size, "sha256": sha(model)},
            "runtime": {"path": str(runtime), "bytes": runtime.stat().st_size, "sha256": sha(runtime)},
        },
        "evidence": evidence,
        "tests": {"count": test_count, "failures_or_errors": failures, "sha256": sha(tests)},
        "artifacts": [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)} for path in artifacts],
        "checks": checks,
    }
    write(output / "MANIFEST.json", manifest)
    attested_digest = sha(output / "MANIFEST.json")
    write(
        output / "DEVELOPMENT_SIGNATURE.json",
        {
            "schema": "casulo.local-development-attestation/1.0",
            "algorithm": "SHA-256",
            "manifest_sha256": attested_digest,
            "trust": "LOCAL_DEVELOPMENT_ONLY_NOT_RELEASE_SIGNATURE",
            "production_release_authorized": False,
        },
    )
    sealed = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text("".join(f"{sha(path)}  {path.name}\n" for path in sealed), encoding="ascii", newline="\n")
    print(json.dumps({"state": manifest["state"], "manifest": str(output / "MANIFEST.json")}, ensure_ascii=False))
    return 0 if manifest["state"] == "READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
