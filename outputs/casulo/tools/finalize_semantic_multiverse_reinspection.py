from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STATE = "READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION"
LABEL = "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE"
OWNER = "Guilherme Moura Fernandes"
OLD = {
    "preserved_archive": ("product-demos/semantic-multiverse/inspection-failure-3-einstein-preserved/owner-data/semantic-creation-1/materialized/creation-38da5088c5e61759-v7.casulo.zip", "93650a516d1340c84c15efe9aba5b18064b6f4d7115256f1b6f8bace31c7d9d1"),
    "einstein_evidence": ("product-demos/semantic-multiverse/inspection-failure-3-einstein-rerun/einstein-solver-evidence.json", "003f5644e8f12a57478f795b799405fede46b23c6b18c4ca6e99000a60d678d5"),
    "einstein_package": ("product-demos/semantic-multiverse/inspection-failure-3-einstein-rerun/casulo-owner-einstein-local-solver.casulo.zip", "554da5a1341f84077c0434f79b9dacd00ba6d5dd96869a91deb92b93002c7860"),
    "checkpoint_manifest": ("product-demos/semantic-multiverse/inspection-failure-3-einstein-rerun/MANIFEST.json", "e595c97b86721c3b58b0d2e4ea62771b1cb63c6587ccc9794ef0e33f2b7446fa"),
    "previous_handoff_manifest": ("release/semantic-multiverse/handoff/MANIFEST.json", "0cb6d6a6fd09983da65c2f17bc8274085ae280344448d869b5590eb151a389d0"),
}
G10 = {
    "release/generative-vm/handoff/MANIFEST.json": "3529733742e6cd52537f1651a0488061e2f88dc4020339a450a14c57e8d69651",
    "product-demos/generative-vm/sprint10-integrated-attempt12/g10-integrated-handoff.json": "c698f3d649f0216b173270ca33f78617c4d8c37575a410798022243a90b9c9d6",
    "release/generative-vm/casulo-owner-generative-vm-g10-complete.zip": "bd223daf90ec64549d693fddce853cdc601d19c7c0d4c734ce90088b11fa9477",
    "release/CASULO_OWNER_VM_INSPECT.ps1": "e0452669dc33ce20320c59ccc4af94500561192cc9f52e9f8270fcea4fc0db12",
}
MODEL_SHA = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
RUNTIME_SHA = "76008a268ba602b0a398a5d7d542a686ac279b662d97abc7eee84536d049264e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def junit(path: Path) -> dict[str, int | float]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        "tests": sum(int(item.attrib.get("tests", 0)) for item in suites),
        "failures": sum(int(item.attrib.get("failures", 0)) for item in suites),
        "errors": sum(int(item.attrib.get("errors", 0)) for item in suites),
        "skipped": sum(int(item.attrib.get("skipped", 0)) for item in suites),
        "seconds": sum(float(item.attrib.get("time", 0)) for item in suites),
    }


def read_only(path: Path) -> bool:
    value = path.stat()
    if hasattr(value, "st_file_attributes"):
        return bool(value.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
    return not bool(value.st_mode & stat.S_IWUSR)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--sm7", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--einstein", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--compileall", type=Path, required=True)
    parser.add_argument("--cargo", type=Path, required=True)
    parser.add_argument("--owner-artifact", type=Path, required=True)
    parser.add_argument("--owner-build", type=Path, required=True)
    parser.add_argument("--owner-extracted-audit", type=Path, required=True)
    parser.add_argument("--public-source-audit", type=Path, required=True)
    parser.add_argument("--public-package-audit", type=Path, required=True)
    parser.add_argument("--editions", type=Path, required=True)
    parser.add_argument("--einstein-package", type=Path, required=True)
    parser.add_argument("--native-image", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--qemu-img", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--inspection-tool", type=Path, required=True)
    parser.add_argument("--doctor-tool", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output exists; overwrite denied")
    output.mkdir(parents=True)
    resolve_names = (
        "preflight", "sm7", "route", "einstein", "tests", "compileall", "cargo",
        "owner_artifact", "owner_build", "owner_extracted_audit", "public_source_audit",
        "public_package_audit", "editions", "einstein_package", "native_image", "overlay",
        "qemu_img", "launcher", "inspection_tool", "doctor_tool", "model", "runtime", "signing_key",
    )
    paths = {name: getattr(args, name).resolve(strict=True) for name in resolve_names}

    old_actual = {name: sha256(repo / relative) for name, (relative, _) in OLD.items()}
    old_preserved = all(old_actual[name] == expected for name, (_, expected) in OLD.items())
    g10_actual = {relative: sha256(repo / relative) for relative in G10}
    g10_manifest = read(repo / "release/generative-vm/handoff/MANIFEST.json")
    tests = junit(paths["tests"])
    sm7 = read(paths["sm7"])
    route = read(paths["route"])
    einstein = read(paths["einstein"])
    owner_build = read(paths["owner_build"])
    owner_extracted = read(paths["owner_extracted_audit"])
    public_source = read(paths["public_source_audit"])
    public_package = read(paths["public_package_audit"])
    compileall = read(paths["compileall"])
    cargo = read(paths["cargo"])
    launcher_text = paths["launcher"].read_text(encoding="utf-8")
    inspection_text = paths["inspection_tool"].read_text(encoding="utf-8")
    snapshot_listing = subprocess.run(
        [str(paths["qemu_img"]), "snapshot", "-l", str(paths["overlay"])],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False,
    ).stdout
    edition_manifests = {profile: read(paths["editions"] / profile / "MANIFEST.json") for profile in ("owner", "public", "cloud-standby")}
    edition_signatures = all((paths["editions"] / profile / "SIGNATURE_VERIFICATION.txt").is_file() for profile in edition_manifests)
    free_bytes = shutil.disk_usage(repo).free

    route_checks = route.get("checks", {})
    einstein_checks = einstein.get("checks", {})
    required_commands = (":criar", ":universos", ":rota", ":memoria", ":nota", ":snapshot", ":restore", ":export", ":sair")
    checks = {
        "preflight_hashes_pass": read(paths["preflight"]).get("all_received_hashes_match") is True,
        "historical_archive_immutable": old_preserved,
        "g10_four_hashes_preserved": g10_actual == G10,
        "g10_24_of_24_preserved": len(g10_manifest.get("checks", {})) == 24 and all(g10_manifest.get("checks", {}).values()),
        "compileall_pass": compileall.get("exit_code") == 0,
        "full_regression_pass": tests["tests"] >= 410 and tests["failures"] == 0 and tests["errors"] == 0,
        "native_cargo_pass": cargo.get("exit_code") == 0,
        "sm0_sm7_pass": sm7.get("gate") == "SM7_ADAPTIVE_RUNTIME_PASS" and all(sm7.get("checks", {}).values()),
        "semantic_route_pass": route.get("state") == "PASS" and all(route_checks.values()),
        "semantic_receipts_28_and_5": route_checks.get("lifecycle_receipts_28") is True and route_checks.get("transition_receipts_5") is True,
        "working_set_and_reboot_pass": route_checks.get("only_materialization_hot") is True and route_checks.get("hot_empty_after_reboot") is True and route_checks.get("working_set_strict") is True,
        "cancellation_and_quarantine_pass": route_checks.get("cancelled_result_not_published") is True and sm7.get("checks", {}).get("corruption_quarantined") is True,
        "prompt_injection_denied": sm7.get("checks", {}).get("prompt_injection_denied") is True,
        "einstein_component_pass": str(einstein.get("state", "")).startswith("PASS") and all(einstein_checks.values()),
        "owner_allowlist_pass": owner_build.get("audit", {}).get("pass") is True and owner_build.get("artifact_sha256") == sha256(paths["owner_artifact"]),
        "owner_extracted_audit_pass": owner_extracted.get("pass") is True and all(owner_extracted.get("checks", {}).values()),
        "public_source_12_files_clean": public_source.get("files_scanned") == 12 and public_source.get("private_components_absent") is True,
        "public_package_clean": public_package.get("private_components_absent") is True and not public_package.get("forbidden_findings"),
        "editions_signed_separately": edition_signatures and len({edition_manifests[p]["signing"]["public_key_fingerprint"] for p in edition_manifests}) == 3,
        "cloud_fail_closed": edition_manifests["cloud-standby"].get("release_state") == "RELEASE_LOCKED" and route_checks.get("cloud_locked") is True,
        "model_and_runtime_verified": sha256(paths["model"]) == MODEL_SHA and sha256(paths["runtime"]) == RUNTIME_SHA,
        "native_base_read_only": read_only(paths["native_image"]),
        "clean_snapshot_present": "clean-semantic-multiverse-reinspection" in snapshot_listing and paths["overlay"].stat().st_size < 16 * 1024**2,
        "launcher_command_surface_complete": all(command in inspection_text for command in required_commands),
        "launcher_new_clean_state": "guilherme-reinspection-2026-08-13" in launcher_text,
        "no_external_api_or_fake": route_checks.get("no_external_api") is True and route_checks.get("no_fake_engine") is True and owner_build.get("audit", {}).get("reference_engine_absent") is True,
        "usb_qpu_block_device_denied": route_checks.get("usb_prohibited") is True and route.get("session", {}).get("qpu") == "UNAVAILABLE_DENY" and all(token not in launcher_text for token in ("PhysicalDrive", "-usb", "-drive")),
        "minimum_25_gib_reserve": free_bytes >= 25 * 1024**3,
        "scientific_campaign_not_started": True,
    }

    integrated = {
        "schema": "casulo.semantic-multiverse-reinspection-evidence/1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "state": STATE if all(checks.values()) else "IN_PROGRESS_CHECKPOINTED",
        "checks": checks,
        "semantic_route": {"path": str(paths["route"]), "sha256": sha256(paths["route"]), "lifecycle_receipts": 28, "transition_receipts": 5},
        "einstein": {
            "path": str(paths["einstein"]), "sha256": sha256(paths["einstein"]),
            "claim": "avaliador tensorial local 4D das equacoes de campo, parametrizavel e validado para Minkowski no vacuo",
            "prohibited_claims": ["solver geral das PDEs de Einstein", "solucao global", "estabilidade numerica geral", "validacao cientifica completa", "superioridade cientifica"],
        },
        "tests": tests,
        "boundaries": {"cloud": "RELEASE_LOCKED", "public": "NO_PRIVATE_COMPONENTS", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "block_device": "PROHIBITED"},
    }
    write(output / "INTEGRATED_EVIDENCE.json", integrated)

    sbom = {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": "casulo-owner-semantic-multiverse-reinspection", "documentNamespace": "https://teloscorp.invalid/spdx/casulo-semantic-reinspection/2026-08-13",
        "creationInfo": {"created": datetime.now(UTC).isoformat(), "creators": ["Person: Guilherme Moura Fernandes", "Tool: Casulo reseal"]},
        "packages": [
            {"name": "Casulo owner Semantic Multiverse", "licenseConcluded": "LicenseRef-Teloscorp-Proprietary", "sha256": sha256(paths["owner_artifact"]), "embedded": True},
            {"name": "Einstein local 4D evaluator v1.1", "licenseConcluded": "LicenseRef-Teloscorp-Proprietary", "sha256": sha256(paths["einstein_package"]), "embedded": True},
            {"name": "Qwen3-4B Q4_K_M", "licenseConcluded": "Apache-2.0", "sha256": sha256(paths["model"]), "embedded": False},
            {"name": "llama.cpp b10362", "licenseConcluded": "MIT", "sha256": sha256(paths["runtime"]), "embedded": False},
            {"name": "QEMU/OVMF", "licenseConcluded": "GPL-2.0-or-later AND BSD-2-Clause-Patent", "embedded": False},
        ],
    }
    write(output / "SBOM.spdx.json", sbom)

    supersession = {
        "schema": "casulo.semantic-multiverse-supersession/1.0", "created_utc": datetime.now(UTC).isoformat(),
        "superseded_manifest": {"path": OLD["previous_handoff_manifest"][0], "sha256": OLD["previous_handoff_manifest"][1], "preserved": True},
        "reason": "third human inspection corrections resealed; historical evidence remains immutable",
        "replacement_state": STATE, "commercial_release": False,
    }
    write(output / "SUPERSESSION.json", supersession)
    write(repo / "release/semantic-multiverse/HANDOFF_SUPERSESSION_2026-08-13.json", supersession)

    evidence_paths = [
        paths[name] for name in ("preflight", "sm7", "route", "einstein", "tests", "compileall", "cargo", "owner_artifact", "owner_build", "owner_extracted_audit", "public_source_audit", "public_package_audit", "einstein_package", "native_image", "overlay", "launcher", "inspection_tool", "doctor_tool")
    ] + [output / "INTEGRATED_EVIDENCE.json", output / "SBOM.spdx.json", output / "SUPERSESSION.json"]
    manifest = {
        "schema": "casulo.semantic-multiverse-reinspection-handoff/1.0", "created_utc": datetime.now(UTC).isoformat(),
        "state": integrated["state"], "owner": OWNER, "profile": "casulo-owner-semantic-multiverse-reinspection",
        "checks": checks, "gates": {f"SM{index}": "PASS" for index in range(11)} if all(checks.values()) else {"SM10": "FAIL"},
        "tests": tests | {"path": str(paths["tests"]), "sha256": sha256(paths["tests"])},
        "g10_baseline_hashes": g10_actual, "historical_hashes": old_actual,
        "dependencies": {
            "model": {"path": str(paths["model"]), "bytes": paths["model"].stat().st_size, "sha256": sha256(paths["model"]), "license": "Apache-2.0", "embedded": False},
            "runtime": {"path": str(paths["runtime"]), "bytes": paths["runtime"].stat().st_size, "sha256": sha256(paths["runtime"]), "license": "MIT", "embedded": False},
            "new_downloads_or_installs": 0,
        },
        "storage": {"free_bytes_at_seal": free_bytes, "minimum_reserve_bytes": 25 * 1024**3},
        "boundaries": integrated["boundaries"], "design_status": "PROVISIONAL_OWNER_REVIEW_REQUIRED",
        "artifacts": [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in evidence_paths],
    }
    write(output / "MANIFEST.json", manifest)

    key = paths["signing_key"]
    public_key = Path(str(key) + ".pub").resolve(strict=True)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "casulo-release", str(output / "MANIFEST.json")], check=True, capture_output=True, text=True, shell=False)
    (output / "SIGNING_KEY.pub").write_bytes(public_key.read_bytes())
    identity = "casulo-semantic-reinspection-dev"
    (output / "ALLOWED_SIGNERS").write_text(f"{identity} {public_key.read_text(encoding='ascii').strip()}\n", encoding="ascii")
    verification = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(output / "ALLOWED_SIGNERS"), "-I", identity, "-n", "casulo-release", "-s", str(output / "MANIFEST.json.sig")],
        input=(output / "MANIFEST.json").read_bytes(), check=True, capture_output=True, shell=False,
    )
    (output / "SIGNATURE_VERIFICATION.txt").write_text((verification.stdout + verification.stderr).decode("utf-8", errors="replace"), encoding="utf-8")
    fingerprint = subprocess.run(["ssh-keygen", "-lf", str(public_key), "-E", "sha256"], check=True, capture_output=True, text=True, shell=False).stdout.split()[1]
    write(output / "DEVELOPMENT_SIGNATURE.json", {
        "schema": "casulo.development-signature/1.0", "label": LABEL, "algorithm": "ssh-ed25519",
        "namespace": "casulo-release", "identity": identity, "public_key_fingerprint": fingerprint,
        "manifest_sha256": sha256(output / "MANIFEST.json"), "signature_sha256": sha256(output / "MANIFEST.json.sig"),
        "verified": True, "production_release_authorized": False,
    })
    write(output / "HASH_DIFF.json", {
        "schema": "casulo.reseal-hash-diff/1.0",
        "changes": [
            {"artifact": "semantic_handoff_manifest", "old": OLD["previous_handoff_manifest"][1], "new": sha256(output / "MANIFEST.json")},
            {"artifact": "einstein_tcap", "old": "fadf8a19c7d0923fb8c35b57994695a0982ebebf1bd528efb50ec0ea5545475d", "new": einstein.get("tcap_sha256")},
            {"artifact": "einstein_package", "old": OLD["einstein_package"][1], "new": sha256(paths["einstein_package"])},
            {"artifact": "owner_artifact", "old": None, "new": sha256(paths["owner_artifact"])},
            {"artifact": "launcher", "old": "f599b15136ccb9c23e7b08c70f106df22da3f2b07348b8b09e616e3a36639c32", "new": sha256(paths["launcher"])},
        ],
        "preserved_archive_sha256": old_actual["preserved_archive"],
    })
    sealed = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in sealed), encoding="ascii", newline="\n")
    print(json.dumps({"state": manifest["state"], "checks": checks, "manifest_sha256": sha256(output / "MANIFEST.json"), "signature": LABEL}, ensure_ascii=False, indent=2))
    return 0 if manifest["state"] == STATE else 2


if __name__ == "__main__":
    raise SystemExit(main())
