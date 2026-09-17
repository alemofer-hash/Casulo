from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RC_GATES = (
    "rc00-baseline-attempt2", "rc01-contracts", "rc02-guide", "rc03-fulfillment",
    "rc04-t-sovereignty", "rc05-training", "rc06-semantic-multiverse", "rc07-vm",
    "rc08-voice", "rc09-materialization-attempt3", "rc10-security", "rc11-integrated",
    "rc12-release", "rc13-handoff-vbscript-reseal",
)
TS_GATES = (
    "ts00-baseline-freeze-attempt1", "ts01-honest-baseline-attempt1",
    "ts02-v2-semantics-attempt1", "ts03-tcap-v2-attempt5", "ts04-stdlib-vertical-attempt1",
    "ts05-critical-authority-attempt1", "ts06-requirement-graph-attempt1",
    "ts07-nontrivial-holdouts-attempt7", "ts08-guide-memory-attempt1",
    "ts09-presence-voice-attempt1", "ts10-physical-multiverse-attempt5",
    "ts11-sovereign-materialization-attempt3", "ts12-appliance-attempt5",
    "ts13-supply-chain-attempt3", "ts14-integrated-rehearsal-attempt3",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def junit(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        "tests": sum(int(item.attrib.get("tests", 0)) for item in suites),
        "failures": sum(int(item.attrib.get("failures", 0)) for item in suites),
        "errors": sum(int(item.attrib.get("errors", 0)) for item in suites),
        "skipped": sum(int(item.attrib.get("skipped", 0)) for item in suites),
    }


def verify_seal(root: Path) -> dict[str, object]:
    manifest_path = root / "MANIFEST.json"
    if not manifest_path.is_file():
        return {"valid": False, "cause": "manifest_absent"}
    manifest = read(manifest_path)
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        return {"valid": False, "cause": "unsupported_manifest_shape"}
    mismatches = [name for name, expected in files.items() if not (root / name).is_file() or sha256(root / name) != expected]
    return {"valid": not mismatches, "gate": manifest.get("gate"), "manifest_sha256": sha256(manifest_path), "files": len(files), "mismatches": mismatches}


def verify_legacy_gate(root: Path, expected_previous_sha256: str) -> dict[str, object]:
    """Verify the append-only gate-chain format used before TS5 introduced seals."""
    gate_path = root / "gate.json"
    if not gate_path.is_file():
        return {"valid": False, "cause": "gate_absent"}
    gate = read(gate_path)
    previous = gate.get("previous_gate_sha256")
    if previous is None and isinstance(gate.get("previous_gate"), dict):
        previous = gate["previous_gate"].get("sha256")
    gate_sha256 = sha256(gate_path)
    return {
        "valid": gate.get("status") == "PASS" and previous == expected_previous_sha256,
        "kind": "legacy_hash_chained_gate",
        "gate": gate.get("gate"),
        "gate_sha256": gate_sha256,
        "previous_gate_sha256": previous,
        "expected_previous_gate_sha256": expected_previous_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize TS15 without human-proof promotion")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", default="final-gate.json")
    args = parser.parse_args()
    evidence = args.evidence.resolve(strict=True)
    output = evidence / args.output
    if output.exists():
        raise SystemExit("final gate exists; overwrite denied")

    release = ROOT / "release/t85-human-proof"
    release_manifest = read(release / "MANIFEST.json")
    content_registry = read(release / "OWNER_VM/CONTENT_REGISTRY.json")
    appliance = read(evidence / "appliance-final/t85-appliance-probe.json")
    security = read(evidence / "security-attack-final/security-attack-probe.json")
    sovereignty = read(evidence / "sovereignty-final.json")
    product = junit(evidence / "product-tests-final.xml")
    compiler = junit(evidence / "compiler-tests.xml")
    cargo = read(evidence / "cargo.json")
    t_runtime_cargo = read(evidence / "t-runtime-cargo-test.json")
    compileall = read(evidence / "compileall-finalizer.json")
    ts6 = read(ROOT / "product-demos/t85-sovereign-engine/ts06-requirement-graph-attempt1/gate.json")
    ts7 = read(ROOT / "product-demos/t85-sovereign-engine/ts07-nontrivial-holdouts-attempt7/gate.json")
    ts10 = read(ROOT / "product-demos/t85-sovereign-engine/ts10-physical-multiverse-attempt5/physical-multiverse-gate.json")
    ts14 = read(ROOT / "product-demos/t85-sovereign-engine/ts14-integrated-rehearsal-attempt3/gate.json")
    public_audit = read(evidence / "editions/public/PUBLIC_AUDIT.json")
    public_manifest = read(evidence / "editions/public/MANIFEST.json")
    owner_manifest = read(evidence / "editions/owner/MANIFEST.json")
    cloud_manifest = read(evidence / "editions/cloud-standby/MANIFEST.json")
    edition_signature_receipts = {
        profile: (evidence / "editions" / profile / "SIGNATURE_VERIFICATION.txt").read_text(encoding="utf-8").strip()
        for profile in ("owner", "public", "cloud-standby")
    }

    rc = {name: read(ROOT / "product-demos/revolution-closure" / name / "gate.json") for name in RC_GATES}
    ts: dict[str, dict[str, object]] = {}
    previous_gate_sha256 = sha256(ROOT / "product-demos/revolution-closure/rc13-handoff-vbscript-reseal/gate.json")
    for index, name in enumerate(TS_GATES):
        root = ROOT / "product-demos/t85-sovereign-engine" / name
        if index < 5:
            receipt = verify_legacy_gate(root, previous_gate_sha256)
            previous_gate_sha256 = str(receipt.get("gate_sha256", ""))
        else:
            receipt = verify_seal(root)
        ts[name] = receipt
    critical = [item for item in sovereignty["surfaces"] if item["critical"]]
    old_release = ROOT / "release/t85-human-proof-superseded-ts12-technical-candidate"
    release_hash = sha256(release / "MANIFEST.json")
    release_sums_hash = sha256(release / "SHA256SUMS")
    runtime_hash = sha256(ROOT / "t-runtime/target/release/casulo-t-runtime.exe")
    packaged_runtime_hash = sha256(release / "OWNER_VM/app/t-runtime/target/release/casulo-t-runtime.exe")
    free = shutil.disk_usage(ROOT).free

    checks = {
        "rc0_rc13_regression": all(item.get("status") == "PASS" for item in rc.values()),
        "ts0_ts14_evidence": all(item["valid"] for item in ts.values()),
        "product_regression": product["tests"] >= 449 and product["failures"] == product["errors"] == 0,
        "compiler_system_regression": compiler["tests"] >= 74 and compiler["failures"] == compiler["errors"] == 0,
        "skips_not_counted": product["skipped"] == 1 and compiler["skipped"] == 1,
        "cargo_native": cargo["exit_code"] == 0,
        "t_runtime_cargo": t_runtime_cargo["exit_code"] == 0 and runtime_hash == packaged_runtime_hash,
        "compileall": compileall["exit_code"] == 0,
        "release_manifest": release_hash == "87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee",
        "release_signature": appliance["verification"]["checks"]["development_signature"] is True,
        "release_checkout_independent": release_manifest["checkout_dependency"] is False and release_manifest["pythonpath_dependency"] is False,
        "appliance_external": appliance["gate"] == "TS12_APPLIANCE_PASS" and all(appliance["checks"].values()),
        "three_boots_snapshot_restore_crash": len(appliance["cycles"]) == 3 and appliance["checks"]["snapshot_restore"] and appliance["checks"]["crash_recovery"],
        "launchers_and_feedback": appliance["checks"]["launchers_parse"] and "COLLECT_T85_FEEDBACK.vbs" in release_manifest["entrypoints"],
        "s_authority": sovereignty["s_authority"] >= 0.85,
        "critical_authority": all(item["degree"] == 1.0 for item in critical) and sovereignty["c_critical"] == 1.0,
        "s_execution": sovereignty["s_execution"] >= 0.60,
        "three_nontrivial_holdouts": ts7["checks"]["three_holdouts"] and ts7["checks"]["all_multimodule"] and ts7["checks"]["all_executed"],
        "false_hard_completion_zero": ts6["false_hard_completion"] == 0 and ts6["FCR"] == 0.0,
        "critical_semantic_loss_zero": ts10["metrics"]["critical_semantic_loss"] == 0.0,
        "project_bleed_zero": ts10["metrics"]["project_bleed"] == 0,
        "physical_sparse_ratio": ts10["metrics"]["sparse_to_all_hot_managed_ratio"] <= 0.70,
        "ts14_integrated": ts14["gate"] == "TS14_INTEGRATED_REHEARSAL_PASS" and all(ts14["checks"].values()),
        "security_zero_p0_p1": security["state"] == "PASS" and security["metrics"]["P0"] == security["metrics"]["P1_on_supported_human_path"] == 0,
        "public_private_zero": public_audit["private_components_absent"] is True,
        "edition_signatures": all(
            receipt.startswith('Good "casulo-release" signature for ')
            for receipt in edition_signature_receipts.values()
        ),
        "cloud_locked": cloud_manifest["release_state"] == "RELEASE_LOCKED" and release_manifest["boundaries"]["cloud"] == "RELEASE_LOCKED",
        "hard_boundaries": release_manifest["boundaries"] == {"cloud": "RELEASE_LOCKED", "guest_network_default": "OFF", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED", "usb_block_devices": "PROHIBITED"},
        "development_signature_only": release_manifest["signature"] == "DEVELOPMENT_NOT_COMMERCIAL",
        "human_proof_pending": release_manifest["human_proof"] == "PENDING_GUILHERME",
        "bootstrap_hash": content_registry["model"]["sha256"] == "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
        "old_release_preserved": old_release.is_dir() and sha256(old_release / "MANIFEST.json") == "f10be0ad2f7022b001e1775ba9e6e91909db48ff1960ac8d85bb51d9f338dfb3",
        "xray_present": (ROOT / "product-demos/human-proof/engine-xray-t85-2026-08-15/CASULO_T85_ENGINE_CURRENT_STATE.md").is_file(),
        "reserve_25_gib": free >= 25 * 1024**3,
    }
    passed = all(checks.values())
    result = {
        "schema": "casulo.t85-final-handoff/1.0",
        "gate": "TS15_RESEAL_HANDOFF_PASS" if passed else "TS15_FAIL",
        "state": "READY_FOR_GUILHERME_CASULO_T85_VM_HUMAN_PROOF" if passed else "IN_PROGRESS_CHECKPOINTED",
        "checks": checks,
        "regression": {"product": product, "compiler_system": compiler, "rc": {name: item["gate_id"] for name, item in rc.items()}, "ts": ts},
        "authority": {"s_authority": sovereignty["s_authority"], "s_execution": sovereignty["s_execution"], "c_critical": sovereignty["c_critical"], "critical_degrees": {item["id"]: item["degree"] for item in critical}},
        "release": {"path": str(release), "manifest_sha256": release_hash, "sha256sums_sha256": release_sums_hash, "files": len(release_manifest["files"]), "bytes": sum(item["bytes"] for item in release_manifest["files"]), "signature": release_manifest["signature"]},
        "model": {"candidate_id": content_registry["model"]["candidate_id"], "sha256": content_registry["model"]["sha256"], "embedded": content_registry["model"]["embedded"]},
        "free_bytes": free,
        "open_p0": 0 if checks["security_zero_p0_p1"] else 1,
        "open_p1": 0 if checks["security_zero_p0_p1"] else 1,
        "human_proof": "PENDING_GUILHERME",
        "limitations": ["physical symlink test skipped for host privilege and not counted", "physical voice, chemistry, utility and design remain Guilherme-only", "host Python/QEMU/third-party primitives remain declared", "development signature is not a commercial release"],
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"gate": result["gate"], "state": result["state"], "checks": sum(checks.values()), "total_checks": len(checks), "product": product, "authority": result["authority"]}, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
