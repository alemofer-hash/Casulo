from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False)
    return {"argv": argv, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--signing-root", type=Path, required=True)
    args = parser.parse_args()
    repo, release, output = args.repo.resolve(strict=True), args.release.resolve(strict=True), args.output.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output exists; append-only identity required")
    output.mkdir(parents=True)
    sys.path[:0] = [str(repo / "src"), str(repo / "private/casulo-owner/src")]

    candidate = json.loads((repo / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json").read_text(encoding="utf-8"))
    cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/generative" / candidate["candidate_id"]
    adoption_path = cache / "ADOPTION.json"
    adoption = json.loads(adoption_path.read_text(encoding="utf-8"))
    expected = {str(item["path"]): (int(item["bytes"]), str(item["sha256"])) for item in adoption["runtime_files"]}
    actual = {
        path.relative_to(cache).as_posix(): (path.stat().st_size, sha256(path))
        for path in sorted((cache / "runtime").iterdir()) if path.is_file()
    }
    server = cache / adoption["runtime_executable"]
    version = run([str(server), "--version"], cwd=repo)
    objdump_path = shutil.which("objdump")
    objdump = run([str(objdump_path), "-p", str(server)], cwd=repo) if objdump_path else {"returncode": 127, "stdout": "", "stderr": "objdump unavailable"}
    implementation = cache / "runtime/llama-server-impl.dll"
    provenance = {
        "schema": "casulo.t85-neural-runtime-provenance/1.0",
        "candidate_id": candidate["candidate_id"],
        "upstream_repository": candidate["runtime"]["repository"],
        "tag": candidate["runtime"]["tag"],
        "commit": candidate["runtime"]["commit"],
        "archive_bytes": candidate["runtime"]["bytes"],
        "archive_sha256": candidate["runtime"]["sha256"],
        "adoption_receipt_sha256": sha256(adoption_path),
        "all_adopted_runtime_files_match": actual == expected,
        "runtime_file_count": len(actual),
        "launcher": {"path": "runtime/llama-server.exe", "bytes": server.stat().st_size, "sha256": sha256(server), "pe_magic": server.read_bytes()[:2] == b"MZ"},
        "implementation": {"path": "runtime/llama-server-impl.dll", "bytes": implementation.stat().st_size, "sha256": sha256(implementation)},
        "small_executable_explanation": "llama-server.exe is the upstream PE launcher shim; llama-server-impl.dll contains the large server implementation",
        "version": version,
        "objdump": {"tool": objdump_path, "returncode": objdump["returncode"], "imports_implementation": "llama-server-impl.dll" in objdump["stdout"], "output_sha256": hashlib.sha256(objdump["stdout"].encode()).hexdigest()},
        "license": candidate["runtime"]["license"],
    }
    write(output / "llama-runtime-provenance.json", provenance)

    editions = run([
        sys.executable, "tools/build_product_editions.py", "--output", str(output / "editions"),
        "--owner-key", str(args.signing_root / "owner-ed25519"),
        "--public-key", str(args.signing_root / "public-ed25519"),
        "--cloud-key", str(args.signing_root / "cloud-standby-ed25519"),
    ], cwd=repo)
    write(output / "edition-build-command.json", editions)
    public_wheels = list((output / "editions/public").glob("*.whl")) if (output / "editions/public").is_dir() else []
    public_audit = run([sys.executable, "tools/audit_public_artifact.py", str(public_wheels[0])], cwd=repo) if len(public_wheels) == 1 else {"returncode": 2, "stdout": "{}", "stderr": "public wheel missing"}
    try:
        public_report = json.loads(public_audit["stdout"])
    except json.JSONDecodeError:
        public_report = {}
    write(output / "public-audit.json", {"command": public_audit, "report": public_report})
    edition_manifests = {
        profile: json.loads((output / f"editions/{profile}/MANIFEST.json").read_text(encoding="utf-8"))
        for profile in ("owner", "public", "cloud-standby")
        if (output / f"editions/{profile}/MANIFEST.json").is_file()
    }

    attack = run([
        sys.executable, "tools/security_attack_probe.py", "--repo", str(repo),
        "--output", str(output / "attack-probe"), "--signing-key", str(args.signing_root / "owner-ed25519"),
    ], cwd=repo)
    write(output / "attack-command.json", attack)
    attack_report = json.loads((output / "attack-probe/security-attack-probe.json").read_text(encoding="utf-8")) if (output / "attack-probe/security-attack-probe.json").is_file() else {}

    from casulo.product.materializer import MaterializationError
    from casulo.product.sovereign_materializer import SovereignPackageImporter
    from casulo.product.vm_controller import VMControllerError, VMProfile
    from casulo.t.v2_tcap import TcapV2Error, verify_tcap_v2

    path_checks: dict[str, Any] = {}
    path_root = output / "path-attacks"
    path_root.mkdir()
    fake_files = []
    for name in ("qemu.exe", "qemu-img.exe", "code.fd", "vars.fd", "base.img"):
        path = path_root / name
        path.write_bytes(name.encode())
        fake_files.append(path)
    junction_target = path_root / "real-state"
    junction_target.mkdir()
    junction = path_root / "state-junction"
    junction_result = run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(junction_target)], cwd=repo)
    path_checks["junction_created"] = junction_result["returncode"] == 0 and junction.is_junction()
    try:
        VMProfile(*fake_files, junction)
        path_checks["junction_rejected"] = False
    except VMControllerError:
        path_checks["junction_rejected"] = True
    ads = Path(str(fake_files[-1]) + ":casulo")
    ads.write_bytes(b"alternate-stream")
    try:
        VMProfile(*fake_files[:-1], ads, path_root / "state")
        path_checks["ads_rejected"] = False
    except VMControllerError:
        path_checks["ads_rejected"] = True
    symlink = path_root / "base-link.img"
    try:
        os.symlink(fake_files[-1], symlink)
    except OSError as error:
        path_checks["physical_symlink"] = {"status": "NOT_EXECUTED_HOST_PRIVILEGE", "error": f"{type(error).__name__}: {error}"}
    else:
        try:
            VMProfile(*fake_files[:-1], symlink, path_root / "state-2")
            rejected = False
        except VMControllerError:
            rejected = True
        path_checks["physical_symlink"] = {"status": "PASS" if rejected else "FAIL", "rejected": rejected}
    ads_zip = path_root / "ads.casulo.zip"
    with zipfile.ZipFile(ads_zip, "w") as archive:
        archive.writestr("payload.txt:stream", b"x")
    try:
        SovereignPackageImporter().import_archive(ads_zip)
        path_checks["package_ads_rejected"] = False
    except MaterializationError:
        path_checks["package_ads_rejected"] = True
    write(output / "path-boundary-tests.json", path_checks)

    valid_tcap = repo / "product-demos/t85-sovereign-engine/ts07-nontrivial-holdouts-attempt7/agents/data-01/agent.tcap"
    verify_tcap_v2(valid_tcap)
    rng = random.Random(20260815)
    fuzz: list[dict[str, Any]] = []
    mutable_files = [path.relative_to(valid_tcap) for path in valid_tcap.rglob("*.json") if path.name != "MANIFEST.json"]
    fuzz_root = output / "tcap-fuzz"
    fuzz_root.mkdir()
    for index in range(64):
        case = fuzz_root / f"case-{index:03d}"
        shutil.copytree(valid_tcap, case)
        relative = mutable_files[rng.randrange(len(mutable_files))]
        target = case / relative
        data = bytearray(target.read_bytes())
        offset = rng.randrange(len(data))
        data[offset] ^= 0x01
        target.write_bytes(data)
        try:
            verify_tcap_v2(case)
            rejected, error_type = False, None
        except (TcapV2Error, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as error:
            rejected, error_type = True, type(error).__name__
        fuzz.append({"case": index, "mutated": relative.as_posix(), "offset": offset, "rejected": rejected, "error_type": error_type})
    write(output / "tcap-fuzz.json", {"schema": "casulo.t85-tcap-fuzz/1.0", "seed": 20260815, "cases": fuzz, "all_rejected": all(item["rejected"] for item in fuzz)})

    release_manifest = json.loads((release / "MANIFEST.json").read_text(encoding="utf-8"))
    checks = {
        "runtime_receipt_tree_exact": provenance["all_adopted_runtime_files_match"],
        # llama.cpp's --version prints the release build number and a
        # nine-hex abbreviated commit (4801e3c56 for the pinned commit).
        "runtime_version_matches": version["returncode"] == 0 and "10362" in (version["stdout"] + version["stderr"]) and candidate["runtime"]["commit"][:9] in (version["stdout"] + version["stderr"]),
        "runtime_launcher_explained": provenance["launcher"]["bytes"] == 9216 and provenance["objdump"]["imports_implementation"] and provenance["implementation"]["bytes"] > 1_000_000,
        "edition_build": editions["returncode"] == 0 and set(edition_manifests) == {"owner", "public", "cloud-standby"},
        "edition_boundaries_distinct": len({item.get("engine_boundary") for item in edition_manifests.values()}) == 3,
        "public_private_zero": public_audit["returncode"] == 0 and public_report.get("private_components_absent") is True,
        "cloud_locked": edition_manifests.get("cloud-standby", {}).get("release_state") == "RELEASE_LOCKED",
        "development_signature": release_manifest.get("signature") == "DEVELOPMENT_NOT_COMMERCIAL",
        "attack_probe": attack["returncode"] == 0 and attack_report.get("state") == "PASS",
        "zero_p0_p1": attack_report.get("metrics", {}).get("P0") == 0 and attack_report.get("metrics", {}).get("P1_on_supported_human_path") == 0,
        "junction_ads": path_checks.get("junction_created") and path_checks.get("junction_rejected") and path_checks.get("ads_rejected") and path_checks.get("package_ads_rejected"),
        "tcap_fuzz": all(item["rejected"] for item in fuzz),
        "license_ledger": (repo / "docs/product/T85_DEPENDENCY_LICENSE_LEDGER.md").is_file(),
        "private_keys_absent_release": not any(path.name in {"owner-ed25519", "public-ed25519", "cloud-standby-ed25519"} for path in release.rglob("*")),
    }
    report = {
        "schema": "casulo.t85-supply-chain-gate/1.0",
        "gate": "TS13_SUPPLY_CHAIN_PASS" if all(checks.values()) else "TS13_SUPPLY_CHAIN_FAIL",
        "checks": checks,
        "physical_symlink": path_checks["physical_symlink"],
        "skips": [{"test": "physical Windows symlink", "status": path_checks["physical_symlink"]["status"], "counted_as_pass": path_checks["physical_symlink"]["status"] == "PASS"}],
        "release_manifest_sha256": sha256(release / "MANIFEST.json"),
        "boundaries": release_manifest["boundaries"],
    }
    write(output / "supply-chain-gate.json", report)
    print(json.dumps({"gate": report["gate"], "checks": checks, "physical_symlink": report["physical_symlink"]}, ensure_ascii=False, indent=2))
    return 0 if report["gate"] == "TS13_SUPPLY_CHAIN_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
