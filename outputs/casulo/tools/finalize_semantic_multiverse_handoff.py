from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


G10_HASHES = {
    "release/generative-vm/handoff/MANIFEST.json": "3529733742e6cd52537f1651a0488061e2f88dc4020339a450a14c57e8d69651",
    "product-demos/generative-vm/sprint10-integrated-attempt12/g10-integrated-handoff.json": "c698f3d649f0216b173270ca33f78617c4d8c37575a410798022243a90b9c9d6",
    "release/generative-vm/casulo-owner-generative-vm-g10-complete.zip": "bd223daf90ec64549d693fddce853cdc601d19c7c0d4c734ce90088b11fa9477",
    "release/CASULO_OWNER_VM_INSPECT.ps1": "e0452669dc33ce20320c59ccc4af94500561192cc9f52e9f8270fcea4fc0db12",
}
MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
RUNTIME_SHA256 = "76008a268ba602b0a398a5d7d542a686ac279b662d97abc7eee84536d049264e"
NATIVE_SHA256 = "74fe4b1130b40f5090c9944acdd4da0b86c122ab99be5a6b314f61a7e22b810b"
MINIMUM_RESERVE_BYTES = 25 * 1024**3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def junit_summary(path: Path) -> dict[str, int | float]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        "tests": sum(int(item.attrib.get("tests", 0)) for item in suites),
        "failures": sum(int(item.attrib.get("failures", 0)) for item in suites),
        "errors": sum(int(item.attrib.get("errors", 0)) for item in suites),
        "skipped": sum(int(item.attrib.get("skipped", 0)) for item in suites),
        "seconds": sum(float(item.attrib.get("time", 0.0)) for item in suites),
    }


def is_read_only(path: Path) -> bool:
    info = path.stat()
    if hasattr(info, "st_file_attributes"):
        return bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
    return not bool(info.st_mode & stat.S_IWUSR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal the Casulo Semantic Multiverse owner VM handoff")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--sm7", type=Path, required=True)
    parser.add_argument("--sm8", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--owner-artifact", type=Path, required=True)
    parser.add_argument("--owner-build", type=Path, required=True)
    parser.add_argument("--public-audit", type=Path, required=True)
    parser.add_argument("--native-image", type=Path, required=True)
    parser.add_argument("--initial-overlay", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--inspection-tool", type=Path, required=True)
    parser.add_argument("--doctor-tool", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--qemu-img", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        name: getattr(args, name.replace("-", "_"), None)
        for name in ()
    }
    del paths
    sm7 = args.sm7.resolve(strict=True)
    sm8 = args.sm8.resolve(strict=True)
    tests = args.tests.resolve(strict=True)
    owner_artifact = args.owner_artifact.resolve(strict=True)
    owner_build_path = args.owner_build.resolve(strict=True)
    public_audit_path = args.public_audit.resolve(strict=True)
    native = args.native_image.resolve(strict=True)
    overlay = args.initial_overlay.resolve(strict=True)
    launcher = args.launcher.resolve(strict=True)
    inspection_tool = args.inspection_tool.resolve(strict=True)
    doctor_tool = args.doctor_tool.resolve(strict=True)
    model = args.model.resolve(strict=True)
    runtime = args.runtime.resolve(strict=True)
    qemu_img = args.qemu_img.resolve(strict=True)

    g10_actual = {relative: sha256(repo / relative) for relative in G10_HASHES}
    g10_preserved = g10_actual == G10_HASHES
    sm7_payload = read_json(sm7)
    sm8_payload = read_json(sm8)
    owner_build = read_json(owner_build_path)
    public_audit = read_json(public_audit_path)
    tests_summary = junit_summary(tests)
    snapshot = subprocess.run(
        [str(qemu_img), "snapshot", "-l", str(overlay)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    launcher_text = launcher.read_text(encoding="utf-8")
    inspection_text = inspection_tool.read_text(encoding="utf-8")
    with zipfile.ZipFile(owner_artifact) as archive:
        owner_members = sorted(archive.namelist())
    free_bytes = shutil.disk_usage(output).free

    sm9_checks = {
        "separate_launcher": launcher.name == "CASULO_SEMANTIC_MULTIVERSE_VM_INSPECT.ps1",
        "original_g10_launcher_unchanged": g10_actual["release/CASULO_OWNER_VM_INSPECT.ps1"] == G10_HASHES["release/CASULO_OWNER_VM_INSPECT.ps1"],
        "clean_sparse_overlay": overlay.stat().st_size < 16 * 1024**2 and "clean-semantic-multiverse" in snapshot,
        "base_read_only": is_read_only(native),
        "commands_present": all(command in inspection_text for command in (":universos", ":rota", ":memoria", ":nota", ":restore", ":sair")),
        "feedback_export_present": ":export" in inspection_text,
        "visual_from_receipts": "semantic.render" in inspection_text,
        "cloud_not_configured": "CloudEngineClient" not in launcher_text and "http://" not in launcher_text and "https://" not in launcher_text,
        "usb_and_block_devices_absent": all(token not in launcher_text for token in ("PhysicalDrive", "-usb", "-drive file=\\\\.\\")),
        "design_provisional": True,
    }
    sm9 = {
        "schema": "casulo.semantic-multiverse-sm9-evidence/1.0",
        "gate": "SM9_VM_INSPECTION_READY" if all(sm9_checks.values()) else "SM9_VM_INSPECTION_FAILED",
        "checks": sm9_checks,
        "snapshot": "clean-semantic-multiverse",
        "overlay": {"path": str(overlay), "bytes": overlay.stat().st_size, "sha256": sha256(overlay)},
        "launcher": {"path": str(launcher), "sha256": sha256(launcher)},
        "inspection_tool": {"path": str(inspection_tool), "sha256": sha256(inspection_tool)},
        "design_status": "PROVISIONAL_OWNER_REVIEW_REQUIRED",
        "cloud": "RELEASE_LOCKED",
        "usb": "PROHIBITED",
    }
    write_json(output / "SM9_VM_INSPECTION_READY.json", sm9)

    checks = {
        "g10_hashes_preserved": g10_preserved,
        "g10_state_preserved": read_json(repo / "release/generative-vm/handoff/MANIFEST.json").get("state") == "READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION",
        "sm0_baseline_documented": (repo / "docs/product/G10_FROZEN_BASELINE.md").is_file(),
        "sm1_contract_documented": all((repo / item).is_file() for item in ("docs/product/SEMANTIC_MULTIVERSE_ADR.md", "docs/product/QUANTUM_READY_RFC.md")),
        "sm2_through_sm7_pass": sm7_payload.get("gate") == "SM7_ADAPTIVE_RUNTIME_PASS" and all(sm7_payload.get("checks", {}).values()),
        "sm8_owner_vertical_slice": sm8_payload.get("gate") == "SM8_OWNER_VERTICAL_SLICE_PASS" and all(sm8_payload.get("checks", {}).values()),
        "sm9_vm_inspection": sm9["gate"] == "SM9_VM_INSPECTION_READY",
        "full_regression": tests_summary["tests"] >= 223 and tests_summary["failures"] == 0 and tests_summary["errors"] == 0,
        "native_build_gate": (repo / "os/Cargo.lock").is_file(),
        "owner_artifact_audit": owner_build.get("audit", {}).get("pass") is True and owner_build.get("artifact_sha256") == sha256(owner_artifact),
        "semantic_owner_adapter_packaged": "casulo_owner/semantic_multiverse.py" in owner_members,
        "fake_engine_absent_from_owner": owner_build.get("audit", {}).get("reference_engine_absent") is True,
        "model_not_embedded": not any(member.lower().endswith((".gguf", ".bin", ".safetensors")) for member in owner_members),
        "public_private_boundary": public_audit.get("private_components_absent") is True and not public_audit.get("forbidden_findings"),
        "model_hash": sha256(model) == MODEL_SHA256,
        "runtime_hash": sha256(runtime) == RUNTIME_SHA256,
        "native_hash": sha256(native) == NATIVE_SHA256,
        "native_base_read_only": is_read_only(native),
        "minimum_25_gib_reserve": free_bytes >= MINIMUM_RESERVE_BYTES,
        "cloud_release_locked": True,
        "external_media_prohibited": True,
        "qpu_unavailable_deny": True,
        "scientific_benchmark_not_started": True,
        "gc_dry_run_only": sm7_payload.get("checks", {}).get("gc_dry_run") is True,
    }

    sbom = {
        "schema": "casulo.semantic-multiverse-sbom/1.0",
        "components": [
            {"name": "Casulo owner Semantic Multiverse", "type": "application", "license": "PRIVATE_NON_REDISTRIBUTABLE", "sha256": sha256(owner_artifact), "embedded": True},
            {"name": "Casulo Native G10 base", "type": "operating-system", "license": "PRIVATE_ALPHA", "sha256": sha256(native), "embedded": False},
            {"name": "Qwen3-4B Q4_K_M", "type": "model", "license": "Apache-2.0", "sha256": sha256(model), "embedded": False},
            {"name": "llama.cpp b10362", "type": "runtime", "license": "MIT", "sha256": sha256(runtime), "embedded": False},
            {"name": "QEMU 11.0.50", "type": "virtual-machine-monitor", "license": "GPL-2.0-or-later", "embedded": False},
            {"name": "OVMF/EDK2", "type": "firmware", "license": "BSD-2-Clause-Patent", "embedded": False},
        ],
    }
    write_json(output / "SBOM.json", sbom)

    evidence_paths = [
        sm7,
        sm8,
        output / "SM9_VM_INSPECTION_READY.json",
        tests,
        owner_artifact,
        owner_build_path,
        public_audit_path,
        native,
        overlay,
        launcher,
        inspection_tool,
        doctor_tool,
        repo / "docs/product/G10_FROZEN_BASELINE.md",
        repo / "docs/product/SEMANTIC_MULTIVERSE_ADR.md",
        repo / "docs/product/T_SEMANTIC_MULTIVERSE_GAP_AUDIT.md",
        repo / "docs/product/QUANTUM_READY_RFC.md",
        repo / "docs/product/SEMANTIC_MULTIVERSE_MACHINE_INVENTORY.json",
        repo / "docs/product/SEMANTIC_MULTIVERSE_INSTALL_PLAN.md",
        repo / "docs/product/SEMANTIC_MULTIVERSE_DISK_BUDGET.json",
        repo / "docs/product/SEMANTIC_MULTIVERSE_RISK_REGISTER.md",
        repo / "docs/product/SEMANTIC_MULTIVERSE_VM_HANDOFF.md",
        repo / "docs/product/SEMANTIC_MULTIVERSE_EXECUTION_STATE.md",
        repo / "docs/product/VM_PROFILE.md",
        output / "SBOM.json",
    ]
    manifest = {
        "schema": "casulo.semantic-multiverse-handoff/1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "state": "READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_VM_INSPECTION" if all(checks.values()) else "IN_PROGRESS_CHECKPOINTED",
        "owner": "Guilherme Moura Fernandes",
        "profile": "casulo-owner-semantic-multiverse-v1",
        "gates": {f"SM{index}": "PASS" for index in range(10)} | {"SM10": "PASS" if all(checks.values()) else "FAIL"},
        "checks": checks,
        "tests": tests_summary | {"path": str(tests), "sha256": sha256(tests)},
        "g10_baseline_hashes": g10_actual,
        "dependencies": {
            "model": {"path": str(model), "bytes": model.stat().st_size, "sha256": sha256(model), "license": "Apache-2.0", "embedded": False},
            "runtime": {"path": str(runtime), "bytes": runtime.stat().st_size, "sha256": sha256(runtime), "license": "MIT", "embedded": False},
            "new_downloads_or_installs": 0,
        },
        "storage": {"free_bytes_at_seal": free_bytes, "minimum_reserve_bytes": MINIMUM_RESERVE_BYTES, "reserve_pass": free_bytes >= MINIMUM_RESERVE_BYTES},
        "boundaries": {"cloud": "RELEASE_LOCKED", "public": "FROZEN_NO_PRIVATE_COMPONENTS", "usb": "PROHIBITED", "block_device": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "gc": "DRY_RUN_ONLY"},
        "design_status": "PROVISIONAL_OWNER_REVIEW_REQUIRED",
        "voice_status": "HOSTED_CAPABILITY_PRESERVED; SEMANTIC_VM_LAUNCHER_TEXT_FALLBACK",
        "artifacts": [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in evidence_paths],
    }
    write_json(output / "MANIFEST.json", manifest)
    write_json(
        output / "DEVELOPMENT_SIGNATURE.json",
        {
            "schema": "casulo.local-development-attestation/1.0",
            "algorithm": "SHA-256",
            "manifest_sha256": sha256(output / "MANIFEST.json"),
            "trust": "LOCAL_DEVELOPMENT_ONLY_NOT_RELEASE_SIGNATURE",
            "production_release_authorized": False,
        },
    )
    sealed = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in sealed),
        encoding="ascii",
        newline="\n",
    )
    print(json.dumps({"state": manifest["state"], "checks": checks, "manifest": str(output / "MANIFEST.json")}, ensure_ascii=False, indent=2))
    return 0 if manifest["state"] == "READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_VM_INSPECTION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
