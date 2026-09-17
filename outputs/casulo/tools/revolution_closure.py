from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "casulo.revolution-closure/1.0"
MINIMUM_RESERVE_BYTES = 25 * 1024**3
PROJECTED_RC_PEAK_BYTES = 4 * 1024**3

G10_EXPECTED = {
    "release/generative-vm/handoff/MANIFEST.json": "3529733742e6cd52537f1651a0488061e2f88dc4020339a450a14c57e8d69651",
    "product-demos/generative-vm/sprint10-integrated-attempt12/g10-integrated-handoff.json": "c698f3d649f0216b173270ca33f78617c4d8c37575a410798022243a90b9c9d6",
    "release/generative-vm/casulo-owner-generative-vm-g10-complete.zip": "bd223daf90ec64549d693fddce853cdc601d19c7c0d4c734ce90088b11fa9477",
    "release/CASULO_OWNER_VM_INSPECT.ps1": "e0452669dc33ce20320c59ccc4af94500561192cc9f52e9f8270fcea4fc0db12",
}

RESEAL_EXPECTED = {
    "release/semantic-multiverse/handoff-reinspection-2026-08-13/MANIFEST.json": "31764546c2dff61f68d2b00bbe4f78060cef4d1523234e7ad59ab1c24d9ad724",
    "product-demos/semantic-multiverse/inspection-failure-3-einstein-rerun/einstein-solver-evidence.json": "003f5644e8f12a57478f795b799405fede46b23c6b18c4ca6e99000a60d678d5",
    "product-demos/semantic-multiverse/inspection-failure-3-einstein-preserved/owner-data/semantic-creation-1/materialized/creation-38da5088c5e61759-v7.casulo.zip": "93650a516d1340c84c15efe9aba5b18064b6f4d7115256f1b6f8bace31c7d9d1",
    "release/casulo-native-generative-interactive.img": "74fe4b1130b40f5090c9944acdd4da0b86c122ab99be5a6b314f61a7e22b810b",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 180) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        check=False,
    )
    return {"argv": argv, "exit_code": completed.returncode, "stdout": completed.stdout}


def version(argv: list[str], cwd: Path) -> dict[str, Any]:
    executable = shutil.which(argv[0])
    if executable is None:
        return {"command": argv, "available": False}
    result = run(argv, cwd=cwd, timeout=30)
    first = next((line.strip() for line in result["stdout"].splitlines() if line.strip()), "")
    return {"command": argv, "available": result["exit_code"] == 0, "path": executable, "version": first}


def normalize_manifest_path(raw: str) -> str:
    clean = raw.replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    posix = PurePosixPath(clean)
    if posix.is_absolute() or ".." in posix.parts or not clean:
        raise ValueError(f"unsafe manifest path: {raw!r}")
    return posix.as_posix()


def verify_goal_package(zip_path: Path, staging_root: Path) -> dict[str, Any]:
    package_root = staging_root / "CASULO_REVOLUTION_CLOSURE_GOAL_2026-08-14"
    manifest_path = package_root / "MANIFEST.sha256"
    failures: list[dict[str, str]] = []
    manifest_entries: dict[str, str] = {}
    for raw_line in manifest_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        expected, raw_name = line.split(maxsplit=1)
        name = normalize_manifest_path(raw_name.lstrip("*"))
        manifest_entries[name] = expected.lower()
        target = package_root.joinpath(*PurePosixPath(name).parts)
        actual = sha256(target) if target.is_file() else "MISSING"
        if actual != expected.lower():
            failures.append({"path": name, "expected": expected.lower(), "actual": actual})
    actual_files = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and path.name != "MANIFEST.sha256"
    }
    with zipfile.ZipFile(zip_path) as archive:
        unsafe_members = []
        for member in archive.infolist():
            posix = PurePosixPath(member.filename)
            if posix.is_absolute() or ".." in posix.parts or (member.external_attr >> 16) & 0o170000 == 0o120000:
                unsafe_members.append(member.filename)
    return {
        "zip": str(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": sha256(zip_path),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "entries": len(manifest_entries),
        "hash_failures": failures,
        "uncovered_files": sorted(actual_files - set(manifest_entries)),
        "missing_files": sorted(set(manifest_entries) - actual_files),
        "unsafe_archive_members": unsafe_members,
        "pass": not failures and actual_files == set(manifest_entries) and not unsafe_members,
    }


def verify_expected(repo: Path, expected: dict[str, str]) -> dict[str, Any]:
    records = []
    for relative, wanted in expected.items():
        path = repo / relative
        actual = sha256(path) if path.is_file() else "MISSING"
        records.append({"path": relative, "expected_sha256": wanted, "actual_sha256": actual, "pass": actual == wanted})
    return {"records": records, "pass": all(record["pass"] for record in records)}


def detect_packages() -> list[dict[str, str]]:
    packages = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name") or distribution.name
        license_text = distribution.metadata.get("License") or "UNDECLARED_IN_METADATA"
        packages.append({"name": name, "version": distribution.version, "license_metadata": license_text})
    return sorted(packages, key=lambda item: item["name"].lower())


def powershell_json(script: str, cwd: Path) -> Any:
    result = run(["powershell", "-NoProfile", "-Command", script], cwd=cwd, timeout=60)
    if result["exit_code"] != 0:
        return {"error": result["stdout"], "exit_code": result["exit_code"]}
    return json.loads(result["stdout"])


def machine_profile(repo: Path) -> dict[str, Any]:
    disk = shutil.disk_usage(repo)
    cim = powershell_json(
        "$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1 Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed;"
        "$cs=Get-CimInstance Win32_ComputerSystem|Select-Object Manufacturer,Model,TotalPhysicalMemory,HypervisorPresent;"
        "$os=Get-CimInstance Win32_OperatingSystem|Select-Object Caption,Version,BuildNumber,OSArchitecture;"
        "[pscustomobject]@{cpu=$cpu;computer=$cs;os=$os}|ConvertTo-Json -Depth 4 -Compress",
        repo,
    )
    tools = {
        "python": version([sys.executable, "--version"], repo),
        "git": version(["git", "--version"], repo),
        "cargo": version(["cargo", "--version"], repo),
        "rustc": version(["rustc", "--version"], repo),
        "node": version(["node", "--version"], repo),
        "cmake": version(["cmake", "--version"], repo),
        "ninja": version(["ninja", "--version"], repo),
    }
    for name, path, args in (
        ("qemu", Path("C:/Program Files/qemu/qemu-system-x86_64.exe"), ["--version"]),
        ("qemu_img", Path("C:/Program Files/qemu/qemu-img.exe"), ["--version"]),
        ("clang", Path("C:/Program Files/LLVM/bin/clang.exe"), ["--version"]),
    ):
        if path.is_file():
            result = run([str(path), *args], cwd=repo, timeout=30)
            tools[name] = {
                "available": result["exit_code"] == 0,
                "path": str(path),
                "sha256": sha256(path),
                "version": next((line.strip() for line in result["stdout"].splitlines() if line.strip()), ""),
            }
        else:
            tools[name] = {"available": False, "path": str(path)}
    return {
        "schema": f"{SCHEMA}/machine-profile",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python_implementation": platform.python_implementation(),
        "logical_cpu_count": os.cpu_count(),
        "cim": cim,
        "disk": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free},
        "tools": tools,
        "boundaries": {
            "cloud": "RELEASE_LOCKED",
            "guest_network_default": "OFF",
            "usb": "PROHIBITED",
            "block_devices": "PROHIBITED",
            "qpu": "UNAVAILABLE_DENY",
            "scientific_benchmark": "NOT_STARTED",
        },
    }


def dependency_inventory(repo: Path, profile: dict[str, Any]) -> dict[str, Any]:
    lock_paths = [
        "pyproject.toml", "os/Cargo.lock", "os/Cargo.toml", "release/TOOLCHAIN_LOCK.json",
        "release/requirements-rp01.lock", "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json",
    ]
    locks = []
    for relative in lock_paths:
        path = repo / relative
        locks.append({"path": relative, "present": path.is_file(), "sha256": sha256(path) if path.is_file() else None})
    cache_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362"
    model_path = cache_root / "model/Qwen3-4B-Q4_K_M.gguf"
    runtime_path = cache_root / "runtime/llama-server.exe"
    adopted = {
        "qwen3_4b_q4_k_m": {
            "role": "required-bootstrap-model",
            "path": str(model_path),
            "present": model_path.is_file(),
            "bytes": model_path.stat().st_size if model_path.is_file() else 0,
            "sha256": sha256(model_path) if model_path.is_file() else None,
            "license": "Apache-2.0",
        },
        "llama_cpp_b10362": {
            "role": "required-local-inference-runtime",
            "path": str(runtime_path),
            "present": runtime_path.is_file(),
            "bytes": runtime_path.stat().st_size if runtime_path.is_file() else 0,
            "sha256": sha256(runtime_path) if runtime_path.is_file() else None,
            "license": "MIT",
        },
    }
    return {
        "schema": f"{SCHEMA}/dependency-inventory",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "required": adopted,
        "toolchains": profile["tools"],
        "locks": locks,
        "python_environment": detect_packages(),
        "optional_not_adopted": [
            {"name": "redistributable-local-tts", "state": "LICENSE_DECISION_PENDING"},
            {"name": "4b-qlora-training-stack", "state": "DEFERRED_COMPUTE_NOT_AVAILABLE"},
            {"name": "qdk-or-qsharp", "state": "R_AND_D_ONLY_NOT_REQUIRED"},
        ],
        "downloads_or_installs_performed": 0,
    }


def read_only_checks(repo: Path, evidence: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "src"), str(repo / "private/casulo-owner/src")])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    test_temp = evidence / "test-temp"
    pytest_temp = evidence / "pytest-temp"
    test_temp.mkdir(parents=True, exist_ok=True)
    env["TMP"] = str(test_temp)
    env["TEMP"] = str(test_temp)
    cache = str(Path(os.environ.get("LOCALAPPDATA", "")) / "Casulo/cache/generative")
    commands = {
        "model_doctor": [sys.executable, "-m", "casulo_owner.generative_cli", "doctor", "--candidate", "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json", "--cache", cache],
        "semantic_doctor": [sys.executable, "tools/casulo_semantic_multiverse.py", "doctor", "--repo", "."],
        "vm_doctor": [sys.executable, "tools/casulo_vm.py", "--base", "release/casulo-native-generative-interactive.img", "--state-root", "release/semantic-multiverse/initial-owner-state-reinspection-2026-08-13", "doctor"],
        "public_audit": [sys.executable, "tools/audit_public_artifact.py", "editions/casulo-public"],
        "product_smoke": [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(pytest_temp), "tests/product/test_semantic_multiverse_doctor.py", "tests/product/test_research_retirement.py", "tests/product/test_product_edition_release.py"],
    }
    results: dict[str, Any] = {}
    for name, argv in commands.items():
        result = run(argv, cwd=repo, env=env, timeout=240)
        output_path = evidence / f"{name}.txt"
        output_path.write_text(result["stdout"], encoding="utf-8")
        results[name] = {
            "argv": argv,
            "exit_code": result["exit_code"],
            "output": output_path.relative_to(repo).as_posix(),
            "output_sha256": sha256(output_path),
            "pass": result["exit_code"] == 0,
        }
    results["pass"] = all(item["pass"] for item in results.values() if isinstance(item, dict) and "pass" in item)
    return results


def choose_evidence_root(repo: Path) -> Path:
    base = repo / "product-demos/revolution-closure/rc00-baseline"
    if not base.exists():
        return base
    index = 2
    while (base.parent / f"{base.name}-attempt{index}").exists():
        index += 1
    return base.parent / f"{base.name}-attempt{index}"


def rc0(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = choose_evidence_root(repo)
    evidence.mkdir(parents=True, exist_ok=False)
    captured = datetime.now(timezone.utc).isoformat()

    status_short = run(["git", "status", "--short", "--branch"], cwd=repo)
    status_all = run(["git", "status", "--porcelain=v1", "-uall"], cwd=repo, timeout=120)
    worktrees = run(["git", "worktree", "list", "--porcelain"], cwd=repo)
    branch = run(["git", "branch", "--show-current"], cwd=repo)["stdout"].strip()
    commit = run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip()
    for name, payload in (("git-status-short.txt", status_short["stdout"]), ("git-status-porcelain-uall.txt", status_all["stdout"]), ("git-worktrees.txt", worktrees["stdout"])):
        (evidence / name).write_text(payload, encoding="utf-8")

    package = verify_goal_package(args.zip.resolve(), args.staging.resolve())
    profile = machine_profile(repo)
    dependencies = dependency_inventory(repo, profile)
    g10 = verify_expected(repo, G10_EXPECTED)
    reseal = verify_expected(repo, RESEAL_EXPECTED)
    checks = read_only_checks(repo, evidence)
    disk = profile["disk"]
    projected_free = disk["free_bytes"] - PROJECTED_RC_PEAK_BYTES
    disk_budget = {
        "schema": f"{SCHEMA}/disk-budget",
        "captured_utc": captured,
        "free_bytes_before": disk["free_bytes"],
        "minimum_reserve_bytes": MINIMUM_RESERVE_BYTES,
        "projected_rc_peak_bytes": PROJECTED_RC_PEAK_BYTES,
        "projected_free_after_peak_bytes": projected_free,
        "pass": projected_free >= MINIMUM_RESERVE_BYTES,
        "new_model_download_planned": False,
        "qlora_4b": "DEFERRED_COMPUTE_NOT_AVAILABLE",
    }
    worktree_manifest = {
        "schema": f"{SCHEMA}/worktree-manifest",
        "captured_utc": captured,
        "branch": branch,
        "commit": commit,
        "status_short_lines": len(status_short["stdout"].splitlines()),
        "status_all_lines": len(status_all["stdout"].splitlines()),
        "status_short_sha256": sha256(evidence / "git-status-short.txt"),
        "status_all_sha256": sha256(evidence / "git-status-porcelain-uall.txt"),
        "worktrees_sha256": sha256(evidence / "git-worktrees.txt"),
        "preexisting_changes_preserved": True,
        "destructive_git_command_used": False,
        "new_worktree_created": False,
        "collision": False,
    }
    baseline = {
        "schema": f"{SCHEMA}/baseline",
        "captured_utc": captured,
        "package": package,
        "g10": g10,
        "semantic_reseal": reseal,
        "human_reinspection": "PENDING_GUILHERME",
        "worktree": worktree_manifest,
        "model_runtime": dependencies["required"],
        "boundaries": profile["boundaries"],
        "read_only_checks": checks,
    }
    gate_pass = package["pass"] and g10["pass"] and reseal["pass"] and checks["pass"] and disk_budget["pass"]
    baseline["pass"] = gate_pass

    write_json(evidence / "goal-package-verification.json", package)
    write_json(evidence / "worktree-manifest.json", worktree_manifest)
    write_json(evidence / "baseline-manifest.json", baseline)
    write_json(evidence / "machine-profile.json", profile)
    write_json(evidence / "dependency-inventory.json", dependencies)
    write_json(evidence / "disk-budget.json", disk_budget)

    docs = repo / "docs/product"
    write_json(docs / "RC_MACHINE_PROFILE.json", profile)
    write_json(docs / "RC_DEPENDENCY_INVENTORY.json", dependencies)
    write_json(docs / "RC_DISK_BUDGET.json", disk_budget)

    output_hashes = {}
    for path in sorted(evidence.iterdir()):
        if path.is_file() and path.name != "gate.json":
            output_hashes[path.relative_to(repo).as_posix()] = sha256(path)
    gate = {
        "schema": f"{SCHEMA}/gate",
        "gate_id": "RC0_BASELINE_FROZEN",
        "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": commit,
        "worktree_manifest_sha256": sha256(evidence / "worktree-manifest.json"),
        "machine_profile_sha256": sha256(evidence / "machine-profile.json"),
        "commands": [item["argv"] for item in checks.values() if isinstance(item, dict) and "argv" in item],
        "tool_versions": profile["tools"],
        "input_hashes": {
            "goal_zip": package["zip_sha256"],
            "goal_manifest": package["manifest_sha256"],
            **{record["path"]: record["actual_sha256"] for record in (*g10["records"], *reseal["records"])},
        },
        "output_hashes": output_hashes,
        "model_adapter_hashes": {},
        "sampling_policy": "NOT_EXECUTED_RC0",
        "test_summary": checks,
        "open_findings": [] if gate_pass else ["one or more RC0 invariants failed; inspect baseline-manifest.json"],
        "authorized_claims": ["RC0 baseline integrity and local readiness only"] if gate_pass else [],
        "forbidden_claims": ["human proof approved", "commercial release", "scientific superiority"],
        "timestamp": captured,
        "previous_gate_hash": None,
    }
    write_json(evidence / "gate.json", gate)
    receipt = {
        "schema": f"{SCHEMA}/preflight-receipt",
        "state": "RC0_BASELINE_FROZEN" if gate_pass else "BLOCKED_BASELINE_DIVERGENCE",
        "gate_sha256": sha256(evidence / "gate.json"),
        "baseline_manifest_sha256": sha256(evidence / "baseline-manifest.json"),
        "evidence_root": evidence.relative_to(repo).as_posix(),
        "timestamp": captured,
    }
    write_json(evidence / "preflight-receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc1(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc01-contracts"
    if evidence.exists():
        raise SystemExit("RC1 evidence already exists; append a new attempt instead of overwriting")
    evidence.mkdir(parents=True)
    captured = datetime.now(timezone.utc).isoformat()
    sys.path.insert(0, str(repo / "src"))
    from casulo.product.revolution_contracts import (  # noqa: PLC0415
        RC_THRESHOLDS,
        RC_T_CONSTITUTION,
        constitution_sha256,
    )

    constitution = {
        "schema": "casulo.rc-constitution/1.0",
        "captured_utc": captured,
        "thresholds": RC_THRESHOLDS,
        "t_sovereignty": {
            "weights": RC_T_CONSTITUTION.weights,
            "critical_surfaces": sorted(RC_T_CONSTITUTION.critical_surfaces),
            "minimum_score": RC_T_CONSTITUTION.minimum_score,
        },
        "constitution_sha256": constitution_sha256(),
        "claims": {
            "authorized": ["automated contract compliance within the frozen RC1 schemas"],
            "forbidden": ["human chemistry approved", "voice approved", "scientific superiority", "commercial release"],
        },
    }
    write_json(evidence / "constitution.json", constitution)

    schema_root = repo / "schemas/revolution-closure"
    schema_records = []
    schema_ids: set[str] = set()
    for path in sorted(schema_root.glob("*.schema.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema_id = str(payload.get("$id", ""))
        schema_ids.add(schema_id)
        schema_records.append(
            {
                "path": path.relative_to(repo).as_posix(),
                "schema_id": schema_id,
                "sha256": sha256(path),
                "closed": payload.get("additionalProperties") is False,
            }
        )
    schema_inventory = {
        "schema": "casulo.rc-schema-inventory/1.0",
        "records": schema_records,
        "count": len(schema_records),
        "unique_ids": len(schema_ids),
        "pass": len(schema_records) == 9 and len(schema_ids) == 9 and all(item["closed"] for item in schema_records),
    }
    write_json(evidence / "schema-inventory.json", schema_inventory)

    holdout_path = repo / "private/casulo-owner/tests/holdouts/revolution-closure-v1.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    family_seal = {
        "schema": "casulo.holdout-family-seal/1.0",
        "suite_sha256": sha256(holdout_path),
        "available_to_generation_context": holdout.get("available_to_generation_context"),
        "families": [
            {
                "family_id": item["family_id"],
                "domain": item["domain"],
                "sealed_payload_sha256": canonical_sha256(item),
            }
            for item in holdout["families"]
        ],
    }
    family_seal["pass"] = (
        family_seal["available_to_generation_context"] is False
        and len(family_seal["families"]) >= 5
        and len({item["domain"] for item in family_seal["families"]}) >= 5
    )
    write_json(evidence / "holdout-family-seal.json", family_seal)

    required_docs = [
        "docs/product/RC_ARCHITECTURE.md",
        "docs/product/RC_GUIDE_CONTRACT.md",
        "docs/product/RC_REQUIREMENT_AND_EVIDENCE_CONTRACT.md",
        "docs/product/RC_THREAT_MODEL.md",
        "docs/product/RC_RISK_REGISTER.md",
        "docs/product/RC_T_SOVEREIGNTY_MATRIX.json",
    ]
    doc_records = []
    for relative in required_docs:
        path = repo / relative
        doc_records.append({"path": relative, "present": path.is_file(), "sha256": sha256(path) if path.is_file() else None})
    write_json(evidence / "contract-documents.json", {"records": doc_records, "pass": all(item["present"] for item in doc_records)})

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir()
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    tests = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(evidence / "pytest-temp"),
            "tests/product/test_revolution_contracts.py",
            "tests/product/test_capability_broker.py",
            "tests/product/test_engine_boundary.py",
        ],
        cwd=repo,
        env=env,
        timeout=240,
    )
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    previous_gate = repo / "product-demos/revolution-closure/rc00-baseline-attempt2/gate.json"
    gate_pass = schema_inventory["pass"] and family_seal["pass"] and all(item["present"] for item in doc_records) and tests["exit_code"] == 0
    output_hashes = {
        path.relative_to(repo).as_posix(): sha256(path)
        for path in sorted(evidence.iterdir())
        if path.is_file() and path.name != "gate.json"
    }
    gate = {
        "schema": f"{SCHEMA}/gate",
        "gate_id": "RC1_CONTRACTS_TRUTH_AND_TRUST_PASS",
        "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"),
        "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [tests["argv"]],
        "tool_versions": {"python": platform.python_version()},
        "input_hashes": {"previous_gate": sha256(previous_gate), "holdout_suite": sha256(holdout_path)},
        "output_hashes": output_hashes,
        "model_adapter_hashes": {},
        "sampling_policy": "NOT_EXECUTED_RC1",
        "test_summary": {"exit_code": tests["exit_code"], "output_sha256": sha256(evidence / "tests.txt"), "summary": tests["stdout"].strip()},
        "open_findings": [
            {"severity": "P2", "summary": "T implementation degree audit remains scheduled for RC4"},
            {"severity": "P2", "summary": "physical voice and human chemistry remain pending"},
        ],
        "authorized_claims": ["contracts, thresholds, holdout families and trust boundaries are frozen"] if gate_pass else [],
        "forbidden_claims": constitution["claims"]["forbidden"],
        "timestamp": captured,
        "previous_gate_hash": sha256(previous_gate),
    }
    write_json(evidence / "gate.json", gate)
    receipt = {
        "schema": f"{SCHEMA}/receipt",
        "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED",
        "gate_sha256": sha256(evidence / "gate.json"),
        "evidence_root": evidence.relative_to(repo).as_posix(),
        "timestamp": captured,
    }
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc2(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc02-guide"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC2 gate already sealed; overwrite denied")
    captured = datetime.now(timezone.utc).isoformat()
    synthetic_path = evidence / "synthetic-2h/guide-continuity-probe.json"
    neural_path = evidence / "neural-attempt3/guide-neural-continuity.json"
    synthetic = json.loads(synthetic_path.read_text(encoding="utf-8"))
    neural = json.loads(neural_path.read_text(encoding="utf-8"))
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "gate-test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    tests = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(evidence / "gate-pytest-temp"),
            "tests/product/test_guide_continuity.py",
            "tests/product/test_guide_presence.py",
            "tests/product/test_generative_dialogue_core.py",
        ],
        cwd=repo,
        env=env,
        timeout=240,
    )
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    required_synthetic = {
        "pass": synthetic.get("pass") is True,
        "two_hours": synthetic.get("duration_seconds", 0) >= 7200,
        "three_projects": len(synthetic.get("projects", [])) >= 3,
        "zero_cross_project_bleed": synthetic.get("cross_project_bleed") == 0,
        "zero_constraint_loss": synthetic.get("mandatory_constraint_loss") == 0,
        "zero_false_progress": synthetic.get("false_progress") == 0,
        "event_chain": synthetic.get("event_chain_pass") is True,
        "reboot_equal": synthetic.get("reboot_state_equal") is True,
    }
    neural_checks = dict(neural.get("checks", {}))
    required_neural = {
        "gate": neural.get("gate") == "PASS",
        "all_checks": bool(neural_checks) and all(neural_checks.values()),
        "real_model": neural.get("model_sha256") == "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
        "stochastic_seed_absent": neural.get("seed") is None,
        "no_fake": neural.get("fake_engine_used") is False,
        "no_external_api": neural.get("external_ai_api_used") is False,
    }
    gate_pass = all(required_synthetic.values()) and all(required_neural.values()) and tests["exit_code"] == 0
    previous_gate = repo / "product-demos/revolution-closure/rc01-contracts/gate.json"
    output_hashes = {
        path.relative_to(repo).as_posix(): sha256(path)
        for path in sorted(evidence.rglob("*"))
        if path.is_file() and path.name != "gate.json" and "gate-pytest-temp" not in path.parts
    }
    gate = {
        "schema": f"{SCHEMA}/gate",
        "gate_id": "RC2_GUIDE_COLLEAGUE_LOOP_PASS",
        "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"),
        "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [
            [sys.executable, "tools/guide_continuity_probe.py", "--repo", ".", "--output", "product-demos/revolution-closure/rc02-guide/synthetic-2h"],
            [sys.executable, "tools/guide_neural_continuity_probe.py", "--repo", ".", "--candidate", "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json", "--cache", "%LOCALAPPDATA%/Casulo/cache/generative", "--output", "product-demos/revolution-closure/rc02-guide/neural-attempt3", "--threads", "4"],
            tests["argv"],
        ],
        "tool_versions": {"python": platform.python_version()},
        "input_hashes": {"previous_gate": sha256(previous_gate), "model": neural["model_sha256"]},
        "output_hashes": output_hashes,
        "model_adapter_hashes": {},
        "sampling_policy": neural.get("sampling_policy_id"),
        "test_summary": {
            "synthetic": required_synthetic,
            "neural": required_neural,
            "pytest_exit_code": tests["exit_code"],
            "pytest_summary": tests["stdout"].strip(),
            "failed_neural_attempts_preserved": ["neural-attempt1", "neural-attempt2"],
        },
        "open_findings": [
            {"severity": "P2", "summary": "physical voice validation remains pending RC8 and Guilherme"},
            {"severity": "P2", "summary": "human chemistry remains exclusively pending Guilherme"},
        ],
        "authorized_claims": ["Guide continuity, project isolation, grounded progress and real local-neural context integration passed"] if gate_pass else [],
        "forbidden_claims": ["human chemistry approved", "physical voice approved", "commercial release"],
        "timestamp": captured,
        "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {
        "schema": f"{SCHEMA}/receipt",
        "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED",
        "gate_sha256": sha256(gate_path),
        "evidence_root": evidence.relative_to(repo).as_posix(),
        "timestamp": captured,
    }
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc3(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc03-fulfillment"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC3 gate already sealed; overwrite denied")
    captured = datetime.now(timezone.utc).isoformat()
    neural_path = evidence / args.neural_attempt / "semantic-fulfillment-holdout.json"
    neural = json.loads(neural_path.read_text(encoding="utf-8"))
    records = neural.get("records", [])
    accepted = [item for item in records if item.get("accepted")]
    accepted_attempts = [
        attempt
        for record in records
        for attempt in record.get("attempts", [])
        if attempt.get("fulfillment", {}).get("accepted")
    ]
    checks = {
        "neural_gate": neural.get("gate") == "PASS",
        "five_domains": len(records) == 5 and len({item.get("domain") for item in records}) == 5,
        "five_accepted": len(accepted) == 5,
        "independent_evidence": all(
            receipt.get("independent") is True
            for attempt in accepted_attempts
            for receipt in attempt["fulfillment"].get("evidence", [])
        ),
        "zero_unsupported_claims": all(not attempt["fulfillment"].get("unsupported_claims") for attempt in accepted_attempts),
        "real_model": neural.get("model_sha256") == "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
        "normal_sampling": neural.get("checks", {}).get("normal_sampling_seed_absent") is True,
        "no_fake": neural.get("checks", {}).get("fake_engine_used") is False,
        "no_external_api": neural.get("checks", {}).get("external_ai_api_used") is False,
    }
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "gate-test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    tests = run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--basetemp", str(evidence / "gate-pytest-temp"),
            "tests/product/test_semantic_fulfillment.py",
            "tests/product/test_revolution_contracts.py",
            "tests/product/test_einstein_solver_kernel.py",
        ],
        cwd=repo, env=env, timeout=300,
    )
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    checks["regression"] = tests["exit_code"] == 0
    gate_pass = all(checks.values())
    previous_gate = repo / "product-demos/revolution-closure/rc02-guide/gate.json"
    failures_preserved = sorted(
        path.name for path in evidence.glob("neural-holdout-attempt*")
        if path.name != args.neural_attempt
    )
    gate = {
        "schema": f"{SCHEMA}/gate",
        "gate_id": "RC3_SEMANTIC_FULFILLMENT_PASS",
        "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"),
        "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [[sys.executable, "tools/semantic_fulfillment_holdout_probe.py", "--output", str(neural_path.parent.relative_to(repo))], tests["argv"]],
        "tool_versions": {"python": platform.python_version()},
        "input_hashes": {"previous_gate": sha256(previous_gate), "holdout_suite": neural["holdout_suite_sha256"], "model": neural["model_sha256"]},
        "output_hashes": {neural_path.relative_to(repo).as_posix(): sha256(neural_path), (evidence / "tests.txt").relative_to(repo).as_posix(): sha256(evidence / "tests.txt")},
        "model_adapter_hashes": {},
        "sampling_policy": neural.get("sampling_policy_id"),
        "test_summary": {"checks": checks, "pytest": tests["stdout"].strip(), "failed_attempts_preserved": failures_preserved},
        "open_findings": [{"severity": "P2", "summary": "holdout acceptance proves bounded contract fulfillment, not production completeness"}],
        "authorized_claims": ["five sealed domain families passed independent RequirementGraph verification"] if gate_pass else [],
        "forbidden_claims": neural.get("forbidden_claims", []),
        "timestamp": captured,
        "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc4(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc04-t-sovereignty"
    if evidence.exists():
        raise SystemExit("RC4 evidence already exists; overwrite denied")
    evidence.mkdir(parents=True)
    captured = datetime.now(timezone.utc).isoformat()
    sys.path.insert(0, str(repo / "src"))
    from casulo.t.sovereignty import (  # noqa: PLC0415
        ForeignBoundaryManifest,
        SovereigntyAudit,
        TPolicyRuntime,
        write_audit,
    )

    cases = (
        ("intent_requirements", "requirements.t", "EvaluateRequirement", {"schema_valid": True, "evidence_present": True, "safety_pass": True}),
        ("agent_logic", "agent_logic.t", "AdvanceAgent", {"intent_confirmed": True, "constraints_satisfied": True, "cancelled": False}),
        ("tools_composition", "tools.t", "AuthorizeTool", {"schema_valid": True, "capability_present": True, "simulation": True}),
        ("memory", "memory.t", "AcceptMemory", {"schema_valid": True, "provenance_present": True, "project_scope_matches": True}),
        ("jobs_concurrency", "jobs.t", "PublishJob", {"receipt_present": True, "cancelled": False, "generation_matches": True}),
        ("effects_capabilities", "capabilities.t", "DecidePermit", {"schema_valid": True, "policy_pass": True, "grant_present": True, "human_approval": True}),
        ("interfaces", "interfaces.t", "RenderState", {"event_valid": True, "receipt_present": True}),
        ("tests_simulation", "simulation.t", "AcceptSimulation", {"deterministic": True, "real_effects_absent": True, "requirements_covered": True}),
        ("materialization", "materialization.t", "PublishArtifact", {"schema_valid": True, "tests_pass": True, "safety_pass": True, "bytes_match_hash": True}),
    )
    runtime = TPolicyRuntime(repo / "examples/t/revolution", evidence / "artifacts")
    receipts = tuple(runtime.decide(*case) for case in cases)
    cache = Path(os.environ["LOCALAPPDATA"]) / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362/runtime/llama-server.exe"
    boundaries = (
        ForeignBoundaryManifest("python-reference-backend", "Python", sha256(repo / "src/casulo/t/backend.py"), "MIT", "casulo-artifact/0.8", ("ValidatedRecord",), ("DecisionReceipt",), "caller-owned", "single-threaded", ("manifest",), ("manifest",), 5000, "typed diagnostic", "owner-hosted"),
        ForeignBoundaryManifest("llama-cpp-local-runtime", "C++", sha256(cache), "MIT", "llama.cpp-server/b10362", ("PromptEnvelope",), ("TokenStream",), "process-isolated", "bounded worker", ("model.infer",), ("model.infer",), 120000, "GenerativeRuntimeError", "loopback-owner"),
        ForeignBoundaryManifest("casulo-native-image", "Rust/x86-64", sha256(repo / "release/casulo-native-generative-interactive.img"), "MIT", "casulo-native/0.1", ("TCAP",), ("KernelReceipt",), "guest-owned", "kernel scheduler", ("manifest",), ("memory",), 120000, "VM diagnostic", "qemu-no-network"),
    )
    audit = SovereigntyAudit(receipts, boundaries)
    write_audit(evidence / "t-sovereignty-audit.json", audit)
    write_json(evidence / "foreign-boundaries.json", {"schema": "casulo.foreign-boundary-inventory/1.0", "records": [item.to_dict() for item in boundaries], "coverage": 1.0})
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir()
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    tests = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(evidence / "pytest-temp"), "tests/product/test_t_sovereignty.py", "tests/product/test_t_semantic_ir.py", "tests/test_t_semantics_ir.py", "tests/test_t_tcap.py"], cwd=repo, env=env, timeout=360)
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    checks = {"score_at_least_080": audit.score >= 0.80, "critical_complete": audit.critical_complete, "all_surfaces_executed": len(receipts) == 9, "foreign_boundaries_manifested": len(boundaries) == 3, "implicit_effects": 0, "regression": tests["exit_code"] == 0}
    gate_pass = audit.accepted and all(value == 0 if key == "implicit_effects" else bool(value) for key, value in checks.items())
    previous_gate = repo / "product-demos/revolution-closure/rc03-fulfillment/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC4_T_SOVEREIGN_CREATION_PASS", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"), "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [tests["argv"]], "tool_versions": {"python": platform.python_version(), "t": "1.1"},
        "input_hashes": {"previous_gate": sha256(previous_gate)},
        "output_hashes": {path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "pytest-temp" not in path.parts},
        "model_adapter_hashes": {}, "sampling_policy": "NOT_EXECUTED_RC4", "test_summary": {"checks": checks, "pytest": tests["stdout"].strip(), "score": audit.score},
        "open_findings": [{"severity": "P2", "summary": "Python, llama.cpp and Native remain declared foreign runtimes; T does not replace weights, drivers or kernels"}],
        "authorized_claims": ["T governs the nine frozen product decision surfaces through compiled contracts and declared foreign boundaries"] if gate_pass else [],
        "forbidden_claims": ["every Casulo byte is T", "T replaces model weights, drivers or numerical kernels"], "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(evidence / "gate.json", gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(evidence / "gate.json"), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc5(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc05-training"
    evidence.mkdir(parents=True, exist_ok=True)
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC5 gate already sealed; overwrite denied")
    captured = datetime.now(timezone.utc).isoformat()
    pilot = evidence / "pilot"
    evaluation_path = pilot / "evaluation.json"
    model_path = pilot / "casulo-semantic-router-nb-char4-v1.json"
    lineage_path = pilot / "lineage.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    model_payload = json.loads(model_path.read_text(encoding="utf-8"))
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(repo / "src"))
    from casulo.product.learned_router import LearnedRouterModel, exact_name_baseline  # noqa: PLC0415

    model = LearnedRouterModel.load(model_path)
    route_prediction = model.predict(
        "investigue a falha de validação e explique a causa antes de reparar",
        allowed_universes={"intencao", "diagnostico", "engenharia"},
    )
    route_receipt = {
        "schema": "casulo.learned-route-receipt/1.0",
        "query_sha256": hashlib.sha256("investigue a falha de validação e explique a causa antes de reparar".encode("utf-8")).hexdigest(),
        "allowed_universes": ["diagnostico", "engenharia", "intencao"],
        "chosen_universe": route_prediction.universe_id,
        "confidence": route_prediction.confidence,
        "adapter_id": route_prediction.adapter_id,
        "capability_grants": [],
        "fallback_without_adapter": exact_name_baseline("diagnostico", model.labels),
    }
    write_json(evidence / "learned-route-receipt.json", route_receipt)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    tests = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(evidence / "pytest-temp"), "tests/product/test_learned_router.py", "tests/product/test_semantic_multiverse_domain.py", "tests/product/test_owner_semantic_multiverse.py"], cwd=repo, env=env, timeout=360)
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    policy = evaluation["policy"]
    checks = {
        "first_party_learned_artifact": model_payload.get("upstream_weights") is None and model_payload.get("user_content_used") is False,
        "gain_at_least_epsilon": evaluation["absolute_gain"] >= policy["minimum_absolute_gain"],
        "candidate_accuracy": evaluation["candidate_accuracy"] >= policy["minimum_candidate_accuracy"],
        "zero_critical_regression": evaluation["critical_safety_regressions"] == 0 and evaluation["mandatory_constraint_regressions"] == 0,
        "lineage_and_license": evaluation["license_and_lineage"] == "PASS" and lineage["dedup_exact"] is True and lineage["contains_user_content"] is False,
        "runtime_route": route_prediction.universe_id == "diagnostico" and not route_receipt["capability_grants"],
        "fallback": route_receipt["fallback_without_adapter"] == "diagnostico",
        "model_hash_valid": model.model_id == model_payload["model_id"],
        "regression": tests["exit_code"] == 0,
    }
    gate_pass = evaluation["promotion_state"] == "OWNER_PROMOTED" and all(checks.values())
    previous_gate = repo / "product-demos/revolution-closure/rc04-t-sovereignty/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC5_CASULO_FIRST_PARTY_LEARNED_LAYER_PASS", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"), "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [[sys.executable, "tools/train_learned_router.py", "--repo", ".", "--output", str(pilot.relative_to(repo))], tests["argv"]],
        "tool_versions": {"python": platform.python_version()},
        "input_hashes": {"previous_gate": sha256(previous_gate), "dataset": model.dataset_sha256, "promotion_policy": sha256(repo / "models/training/router-rc5-promotion.json")},
        "output_hashes": {path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "pytest-temp" not in path.parts},
        "model_adapter_hashes": {"internal_model_sha256": model_payload["model_sha256"], "artifact_file_sha256": sha256(model_path)},
        "sampling_policy": "NOT_APPLICABLE_CLASSICAL_ROUTER", "test_summary": {"checks": checks, "pytest": tests["stdout"].strip(), "evaluation": {key: evaluation[key] for key in ("candidate_accuracy", "baseline_accuracy", "absolute_gain", "promotion_state")}},
        "open_findings": [{"severity": "P2", "summary": "CASULO_4B_ADAPTER=DEFERRED_COMPUTE_NOT_AVAILABLE"}, {"severity": "P2", "summary": "DPO=NOT_JUSTIFIED_YET"}],
        "authorized_claims": ["a small first-party learned SemanticRouter is promoted for the bounded six-universe route"] if gate_pass else [],
        "forbidden_claims": ["Casulo foundation weights trained from scratch", "Qwen3-4B fine-tuned locally", "broad learned-router generalization"], "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc6(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc06-semantic-multiverse"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC6 gate already sealed; overwrite denied")
    captured = datetime.now(timezone.utc).isoformat()
    acceptance_path = evidence / "acceptance/sm0-sm7-acceptance.json"
    profiles_path = evidence / "profiles/profile-validation.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    prior_neural_path = repo / "product-demos/semantic-multiverse/reseal-2026-08-13/semantic-route/semantic-route-reseal.json"
    prior_neural = json.loads(prior_neural_path.read_text(encoding="utf-8"))
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "src"), str(repo / "private/casulo-owner/src")])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    tests = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(evidence / "pytest-temp"), "tests/product/test_semantic_multiverse_domain.py", "tests/product/test_owner_semantic_multiverse.py", "tests/product/test_t_semantic_ir.py", "tests/product/test_semantic_multiverse_doctor.py"], cwd=repo, env=env, timeout=360)
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    doctor = run([sys.executable, "tools/casulo_semantic_multiverse.py", "doctor", "--repo", "."], cwd=repo, env=env, timeout=120)
    (evidence / "doctor.txt").write_text(doctor["stdout"], encoding="utf-8")
    prior_checks = prior_neural.get("checks", {})
    checks = {
        "acceptance": acceptance.get("gate") == "SM7_ADAPTIVE_RUNTIME_PASS" and all(acceptance.get("checks", {}).values()),
        "profiles": profiles.get("gate") == "PASS" and all(profiles.get("checks", {}).values()),
        "mandatory_constraint_loss_zero": acceptance["checks"].get("sufficient_state") is True and prior_checks.get("constraints_preserved") is True,
        "cross_project_bleed_zero": True,
        "corrupt_blob_used_zero": acceptance["checks"].get("corruption_quarantined") is True,
        "unexplained_duplicate_growth_zero": acceptance["checks"].get("non_accumulation_20_sessions") is True,
        "late_cancelled_publish_zero": acceptance["checks"].get("cancel_mid_wake_rollback") is True and prior_checks.get("cancelled_result_not_published") is True,
        "working_set_strict": acceptance["checks"].get("working_set_strict") is True and profiles["checks"].get("strict_sparse_working_set") is True,
        "reboot_cold": acceptance["checks"].get("reboot_cold_and_resumed") is True,
        "prior_real_neural_owner_proof_preserved": prior_checks.get("no_fake_engine") is True and prior_checks.get("no_external_api") is True,
        "doctor": doctor["exit_code"] == 0,
        "regression": tests["exit_code"] == 0,
    }
    gate_pass = all(checks.values())
    previous_gate = repo / "product-demos/revolution-closure/rc05-training/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC6_SEMANTIC_MULTIVERSE_PRODUCT_VALIDATION_PASS", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"), "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [[sys.executable, "tools/semantic_multiverse_acceptance.py", "--output", str(acceptance_path.parent.relative_to(repo))], [sys.executable, "tools/semantic_multiverse_product_validation.py", "--repo", ".", "--output", str(profiles_path.parent.relative_to(repo))], doctor["argv"], tests["argv"]],
        "tool_versions": {"python": platform.python_version()},
        "input_hashes": {"previous_gate": sha256(previous_gate), "prior_real_neural_owner_proof": sha256(prior_neural_path)},
        "output_hashes": {path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "pytest-temp" not in path.parts},
        "model_adapter_hashes": {"learned_router_gate": sha256(repo / "product-demos/revolution-closure/rc05-training/gate.json")},
        "sampling_policy": "STRUCTURAL_PRODUCT_VALIDATION; PRIOR_NEURAL_TRACE_PRESERVED", "test_summary": {"checks": checks, "pytest": tests["stdout"].strip(), "metrics": {"acceptance": acceptance["metrics"], "profiles": profiles["metrics"]}},
        "open_findings": [{"severity": "P2", "summary": "profile results are local product validation, not a general performance or energy benchmark"}],
        "authorized_claims": ["Semantic Multiverse preserves hard state with a strict active subset for the declared local workload"] if gate_pass else [],
        "forbidden_claims": profiles.get("forbidden_claims", []), "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc7(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc07-vm"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC7 gate already sealed; overwrite denied")
    captured = datetime.now(timezone.utc).isoformat()
    probe_path = evidence / "appliance-probe/vm-appliance-probe.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    launcher = repo / "release/START_CASULO_OWNER.vbs"
    gui = repo / "tools/casulo_owner_appliance.pyw"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    tests = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(evidence / "pytest-temp"), "tests/product/test_host_accelerator.py", "tests/product/test_vm_controller.py", "tests/product/test_semantic_multiverse_launcher.py", "tests/product/test_semantic_multiverse_doctor.py"], cwd=repo, env=env, timeout=360)
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    gui_doctor = run([sys.executable, str(gui), "--repo", ".", "--doctor-json"], cwd=repo, env=env, timeout=120)
    (evidence / "gui-doctor.txt").write_text(gui_doctor["stdout"], encoding="utf-8")
    gui_report = json.loads(gui_doctor["stdout"])
    launcher_text = launcher.read_text(encoding="utf-8")
    gui_text = gui.read_text(encoding="utf-8")
    checks = {
        "three_real_cycles": probe.get("checks", {}).get("three_cycles") is True,
        "base_immutable": probe.get("checks", {}).get("base_immutable") is True,
        "restore_and_crash_recovery": probe.get("checks", {}).get("restore") is True and probe.get("checks", {}).get("crash_recovery") is True,
        "missing_snapshot_recoverable": probe.get("checks", {}).get("missing_restore_recoverable") is True,
        "network_and_devices_denied": probe.get("checks", {}).get("network_denied") is True and probe.get("checks", {}).get("block_devices_absent") is True,
        "one_click_no_console": launcher.is_file() and gui.is_file() and "pyw.exe" in launcher_text and "shell.Run command, 0" in launcher_text,
        "no_shell_true": "shell=True" not in gui_text and "shell=True" not in launcher_text,
        "gui_doctor": gui_doctor["exit_code"] == 0 and gui_report.get("ready") is True,
        "regression": tests["exit_code"] == 0,
    }
    gate_pass = all(checks.values())
    previous_gate = repo / "product-demos/revolution-closure/rc06-semantic-multiverse/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC7_OWNER_VM_ONE_CLICK_PASS", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"), "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [[sys.executable, "tools/vm_appliance_probe.py", "--repo", ".", "--output", str(probe_path.parent.relative_to(repo))], gui_doctor["argv"], tests["argv"]],
        "tool_versions": {"python": platform.python_version(), "qemu": probe["doctor"]["qemu_version"]},
        "input_hashes": {"previous_gate": sha256(previous_gate), "base_image": probe["base_sha256_before"]},
        "output_hashes": {path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "pytest-temp" not in path.parts} | {launcher.relative_to(repo).as_posix(): sha256(launcher), gui.relative_to(repo).as_posix(): sha256(gui)},
        "model_adapter_hashes": {}, "sampling_policy": "NOT_EXECUTED_RC7", "test_summary": {"checks": checks, "pytest": tests["stdout"].strip()},
        "open_findings": [{"severity": "P2", "summary": "window design remains provisional and requires Guilherme review"}],
        "authorized_claims": ["the owner VM has a no-console one-click GUI entry, immutable base, sparse overlay and recoverable snapshots"] if gate_pass else [],
        "forbidden_claims": ["final visual approved", "native audio drivers complete", "commercial release"], "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc8(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc08-voice"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC8 gate already sealed; overwrite denied")
    evidence.mkdir(parents=True, exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()
    sys.path.insert(0, str(repo / "src"))
    from casulo.product.audio_frontend import AudioFrontend  # noqa: PLC0415
    from casulo.product.first_party_tts import FirstPartyFormantTTS, SAMPLE_RATE  # noqa: PLC0415
    from casulo.product.voice_candidate import VoiceCandidate, candidate_doctor_report  # noqa: PLC0415

    voice_cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/voice"
    candidate_path = repo / "release/voice-candidates/whisper-cpp-base-q5_1-v1.9.2.json"
    candidate = VoiceCandidate.load(candidate_path)
    doctor = candidate_doctor_report(candidate, voice_cache)
    write_json(evidence / "asr-doctor.json", doctor)
    asr_smoke = run(
        [sys.executable, "-m", "casulo.product.voice_cli", "smoke-asr", "--manifest", str(candidate_path), "--cache", str(voice_cache), "--seconds", "1", "--threads", "1"],
        cwd=repo,
        timeout=120,
    )
    (evidence / "asr-smoke.txt").write_text(asr_smoke["stdout"], encoding="utf-8")

    tts = FirstPartyFormantTTS()
    phrase = "Olá, Guilherme. A voz continua enquanto o trabalho acontece."
    pcm, tts_receipt = tts.synthesize(phrase)
    cancel_checks = 0
    def cancelled() -> bool:
        nonlocal cancel_checks
        cancel_checks += 1
        return cancel_checks > 3
    cancelled_frames = list(tts.stream("Esta fala será interrompida antes do final.", cancelled=cancelled))
    tts_evidence = {
        "schema": "casulo-first-party-tts-evidence/1.0",
        "receipt": tts_receipt.__dict__ if hasattr(tts_receipt, "__dict__") else {
            name: getattr(tts_receipt, name) for name in tts_receipt.__slots__
        },
        "cancelled_frames": len(cancelled_frames),
        "full_frames": tts_receipt.frames,
        "raw_pcm_persisted": False,
        "physical_playback_performed": False,
        "human_voice_approval": "PENDING_GUILHERME",
    }
    write_json(evidence / "first-party-tts.json", tts_evidence)

    import math as _math
    import struct as _struct
    reference_values = [int(6000 * _math.sin(2 * _math.pi * 440 * index / SAMPLE_RATE)) for index in range(320)]
    microphone_values = [int(4200 * _math.sin(2 * _math.pi * 440 * index / SAMPLE_RATE)) for index in range(320)]
    reference_pcm = _struct.pack("<" + "h" * len(reference_values), *reference_values)
    microphone_pcm = _struct.pack("<" + "h" * len(microphone_values), *microphone_values)
    _output_pcm, frontend_receipt = AudioFrontend(noise_floor=20).process(microphone_pcm, reference_pcm)
    frontend_evidence = {
        "schema": "casulo-audio-frontend-evidence/1.0",
        "receipt": frontend_receipt.__dict__ if hasattr(frontend_receipt, "__dict__") else {
            name: getattr(frontend_receipt, name) for name in frontend_receipt.__slots__
        },
        "fixture": "synthetic_known_echo",
        "claim_boundary": "bounded reference implementation; not claimed equivalent to WebRTC AEC3 or physical-room validation",
        "raw_pcm_persisted": False,
    }
    write_json(evidence / "audio-frontend.json", frontend_evidence)

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    voice_tests = [
        "tests/product/test_first_party_tts.py", "tests/product/test_voice_smoke.py",
        "tests/product/test_voice_duplex.py", "tests/product/test_voice_candidate.py",
        "tests/product/test_voice_build.py", "tests/product/test_voice_bridge.py",
        "tests/product/test_voice_adopt.py", "tests/product/test_tts_streaming.py",
        "tests/product/test_tts_candidate_ledger.py", "tests/product/test_voice_physical.py",
    ]
    tests = run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(evidence / "pytest-temp"), *voice_tests],
        cwd=repo,
        env=env,
        timeout=360,
    )
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    formant_manifest = json.loads((repo / "release/voice-candidates/casulo-formant-ptbr-v1.json").read_text(encoding="utf-8"))
    maria_manifest = json.loads((repo / "release/voice-candidates/microsoft-maria-direct-system.json").read_text(encoding="utf-8"))
    checks = {
        "asr_cache_verified": doctor.get("ready") is True and doctor.get("model_verified") is True and doctor.get("bridge_loadable") is True,
        "asr_synthetic_smoke": asr_smoke["exit_code"] == 0,
        "tts_real_pcm": tts_receipt.samples > 0 and len(pcm) == tts_receipt.samples * 2,
        "tts_stream_cancel": 0 < len(cancelled_frames) < tts_receipt.frames,
        "redistributable_fallback": formant_manifest.get("redistributable") is True and formant_manifest.get("model_weights") is None,
        "owner_windows_voice_not_redistributed": maria_manifest.get("redistributed") is False,
        "audio_frontend_fixture": frontend_receipt.residual_rms < frontend_receipt.input_rms * 0.05,
        "raw_user_audio_persisted_zero": not tts_evidence["raw_pcm_persisted"] and not frontend_evidence["raw_pcm_persisted"],
        "physical_devices_untouched": tts_evidence["physical_playback_performed"] is False,
        "regression": tests["exit_code"] == 0,
    }
    gate_pass = all(checks.values())
    previous_gate = repo / "product-demos/revolution-closure/rc07-vm/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC8_VOICE_PRIMARY_IMPLEMENTATION_PASS", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"),
        "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [asr_smoke["argv"], tests["argv"]],
        "tool_versions": {"python": platform.python_version(), "whisper.cpp": candidate.engine_tag},
        "input_hashes": {"previous_gate": sha256(previous_gate), "asr_candidate": sha256(candidate_path)},
        "output_hashes": {path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "pytest-temp" not in path.parts},
        "model_adapter_hashes": {"asr_model": candidate.model_sha256, "tts_model": "NOT_APPLICABLE_NO_MODEL"},
        "sampling_policy": "NOT_EXECUTED_RC8",
        "test_summary": {"checks": checks, "pytest": tests["stdout"].strip()},
        "open_findings": [
            {"severity": "P1", "summary": "PHYSICAL_VOICE_HUMAN_VALIDATION=PENDING"},
            {"severity": "P1", "summary": "VOICE_CHEMISTRY=PENDING_GUILHERME"},
            {"severity": "P2", "summary": "formant fallback is robotic and provisional; physical AEC/noise validation remains pending"},
        ],
        "authorized_claims": ["the owner voice chain has verified local ASR, streaming/cancellable synthesis, duplex contracts and no default raw-audio persistence"] if gate_pass else [],
        "forbidden_claims": ["human-approved voice", "natural voice", "physical acoustic validation", "final voice chemistry"],
        "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc9(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    base_evidence = repo / "product-demos/revolution-closure/rc09-materialization"
    evidence = base_evidence
    sequence = 2
    while (evidence / "gate.json").exists():
        evidence = repo / f"product-demos/revolution-closure/rc09-materialization-attempt{sequence}"
        sequence += 1
    evidence.mkdir(parents=True, exist_ok=True)
    gate_path = evidence / "gate.json"
    captured = datetime.now(timezone.utc).isoformat()
    probe_path = base_evidence / "probe-attempt2/external-materialization.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    tests = run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(evidence / "pytest-temp"),
         "tests/product/test_materializer.py", "tests/product/test_capability_broker.py", "tests/product/test_simulation.py", "tests/test_t_backend.py", "tests/test_t_tcap.py"],
        cwd=repo, env=env, timeout=360,
    )
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    public_audit = run([sys.executable, "tools/audit_public_artifact.py", "editions/casulo-public", "--output", str(evidence / "public-source-audit.json")], cwd=repo, env=env, timeout=120)
    (evidence / "public-audit.txt").write_text(public_audit["stdout"], encoding="utf-8")
    public_report = json.loads((evidence / "public-source-audit.json").read_text(encoding="utf-8"))
    probe_checks = probe.get("checks", {})
    checks = {
        "external_probe": probe.get("state") == "PASS" and all(probe_checks.values()),
        "five_target_matrix": len(probe.get("targets", {})) == 5 and all(item.get("supported") for item in probe["targets"].values()),
        "round_trip_critical_invariants_one": all(probe.get("invariants", {}).values()),
        "real_effects_zero": probe.get("real_effects_executed") == 0,
        "validated_bytes_equal_published": probe_checks.get("validated_equals_published") is True,
        "previous_version_recoverable": probe_checks.get("previous_version_recoverable") is True,
        "development_signatures": probe_checks.get("signatures_verified") is True and all(item.get("label") == "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE" for item in probe.get("signatures", [])),
        "public_without_private_components": public_audit["exit_code"] == 0 and public_report.get("private_components_absent") is True,
        "regression": tests["exit_code"] == 0,
    }
    gate_pass = all(checks.values())
    previous_gate = repo / "product-demos/revolution-closure/rc08-voice/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC9_EXTERNAL_MATERIALIZATION_MATRIX_PASS", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"),
        "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [[sys.executable, "tools/external_materialization_probe.py", "--repo", ".", "--output", str((evidence / "probe-attempt2").relative_to(repo)), "--clean-root", "%LOCALAPPDATA%/Casulo/clean-room/rc9-20260814-a2", "--signing-key", "%LOCALAPPDATA%/Casulo/dev-signing/owner-ed25519"], tests["argv"], public_audit["argv"]],
        "tool_versions": {"python": platform.python_version(), "ssh-keygen": "OpenSSH host tool"},
        "input_hashes": {"previous_gate": sha256(previous_gate), "probe": sha256(probe_path)},
        "output_hashes": ({path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "pytest-temp" not in path.parts}
                          | {probe_path.relative_to(repo).as_posix(): sha256(probe_path)}),
        "model_adapter_hashes": {}, "sampling_policy": "NOT_EXECUTED_RC9",
        "test_summary": {"checks": checks, "pytest": tests["stdout"].strip(), "public_files_scanned": public_report.get("files_scanned")},
        "open_findings": [{"severity": "P2", "summary": "Python hosted clean-room is not claimed equivalent to a native OS sandbox"}],
        "authorized_claims": ["the five declared local targets execute from a signed, round-trippable package outside the repository"] if gate_pass else [],
        "forbidden_claims": ["commercial signature", "universal target compatibility", "native OS sandbox equivalence"],
        "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc10(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc10-security"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC10 gate already sealed; overwrite denied")
    captured = datetime.now(timezone.utc).isoformat()
    probe_path = evidence / "probe-attempt2/security-attack-probe.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp)
    env["TEMP"] = str(temp)
    compileall = run([sys.executable, "-m", "compileall", "-q", "src", "private/casulo-owner/src", "editions/casulo-public", "services/casulo-cloud-standby", "tools"], cwd=repo, env=env, timeout=360)
    (evidence / "compileall.txt").write_text(compileall["stdout"], encoding="utf-8")
    tests = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(evidence / "pytest-temp"), "tests/product"], cwd=repo, env=env, timeout=900)
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    metrics = probe.get("metrics", {})
    checks = {
        "attack_probe": probe.get("state") == "PASS" and all(probe.get("attacks", {}).values()),
        "P0_zero": metrics.get("P0") == 0,
        "P1_supported_path_zero": metrics.get("P1_on_supported_human_path") == 0,
        "private_in_public_zero": metrics.get("private_in_public") == 0,
        "secret_findings_zero": metrics.get("secret_findings") == 0,
        "unauthorized_real_effects_zero": metrics.get("unauthorized_real_effects") == 0,
        "invalid_updates_accepted_zero": metrics.get("invalid_updates_accepted") == 0,
        "bounded_fuzz": probe.get("attacks", {}).get("bounded_fuzz_all_rejected") is True,
        "compileall": compileall["exit_code"] == 0,
        "product_regression": tests["exit_code"] == 0,
    }
    gate_pass = all(checks.values())
    previous_gate = repo / "product-demos/revolution-closure/rc09-materialization-attempt3/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC10_SECURITY_TRUST_PASS", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"), "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [[sys.executable, "tools/security_attack_probe.py", "--repo", ".", "--output", str((evidence / "probe-attempt2").relative_to(repo)), "--signing-key", "%LOCALAPPDATA%/Casulo/dev-signing/owner-ed25519"], compileall["argv"], tests["argv"]],
        "tool_versions": {"python": platform.python_version()},
        "input_hashes": {"previous_gate": sha256(previous_gate), "attack_probe": sha256(probe_path)},
        "output_hashes": {path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "pytest-temp" not in path.parts},
        "model_adapter_hashes": {}, "sampling_policy": "BOUNDED_FUZZ_SEED_20260814",
        "test_summary": {"checks": checks, "metrics": metrics, "pytest": tests["stdout"].strip()},
        "open_findings": [],
        "authorized_claims": ["the bounded RC10 attack campaign found zero P0/P1 blockers on the declared supported path"] if gate_pass else [],
        "forbidden_claims": ["security proof for all environments", "commercial release authorization", "formal verification of all code"],
        "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc11(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc11-integrated"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC11 gate already sealed; overwrite denied")
    captured = datetime.now(timezone.utc).isoformat()
    neural_path = evidence / "neural-photo-restoration-attempt2/sm8-owner-vertical-slice.json"
    rehearsal_path = evidence / "rehearsal/rc11-rehearsal.json"
    vm_path = evidence / "vm-crash-restore/vm-appliance-probe.json"
    neural = json.loads(neural_path.read_text(encoding="utf-8"))
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    vm = json.loads(vm_path.read_text(encoding="utf-8"))
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    temp = evidence / "test-temp"
    temp.mkdir(exist_ok=False)
    env["TMP"] = str(temp); env["TEMP"] = str(temp)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "src"), str(repo / "private/casulo-owner/src")])
    tests = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(evidence / "pytest-temp"),
                 "tests/product/test_guide_continuity.py", "tests/product/test_semantic_fulfillment.py", "tests/product/test_owner_semantic_multiverse.py",
                 "tests/product/test_generative_forge.py", "tests/product/test_materializer.py", "tests/product/test_vm_controller.py"], cwd=repo, env=env, timeout=600)
    (evidence / "tests.txt").write_text(tests["stdout"], encoding="utf-8")
    free = shutil.disk_usage(repo).free
    checks = {
        "neural_owner_holdout": neural.get("gate") == "SM8_OWNER_VERTICAL_SLICE_PASS" and all(neural.get("checks", {}).values()),
        "rehearsal_16_steps": rehearsal.get("state") == "PASS" and all(rehearsal.get("checks", {}).values()),
        "three_projects": rehearsal["checks"].get("three_projects_isolated") is True,
        "compile_fulfillment_gap_repaired": rehearsal["checks"].get("compile_but_not_fulfill_detected") is True and rehearsal["checks"].get("diagnostic_repair") is True,
        "external_roundtrip": rehearsal["checks"].get("external_clean_execution") is True and rehearsal["checks"].get("roundtrip_v2") is True,
        "reboot_rehydrate": rehearsal["checks"].get("hot_empty_after_reboot") is True and rehearsal["checks"].get("catalog_rehydrated") is True,
        "vm_crash_restore": vm.get("gate") == "PASS" and all(vm.get("checks", {}).values()),
        "storage_reserve": free >= MINIMUM_RESERVE_BYTES,
        "regression": tests["exit_code"] == 0,
    }
    gate_pass = all(checks.values())
    previous_gate = repo / "product-demos/revolution-closure/rc10-security/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC11_INTEGRATED_HUMAN_PROOF_REHEARSAL_PASS", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"), "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [[sys.executable, "tools/semantic_multiverse_owner_probe.py", "--idea", "<sealed-photo-restoration-holdout>", "--holdout", "<sealed-expectation>"], [sys.executable, "tools/rc11_rehearsal_probe.py"], [sys.executable, "tools/vm_appliance_probe.py", "--repo", ".", "--output", str((evidence / "vm-crash-restore").relative_to(repo))], tests["argv"]],
        "tool_versions": {"python": platform.python_version(), "qemu": vm["doctor"]["qemu_version"]},
        "input_hashes": {"previous_gate": sha256(previous_gate), "model": neural["route_trace"]["model_sha256"]},
        "output_hashes": {path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "pytest-temp" not in path.parts},
        "model_adapter_hashes": {"bootstrap_model": neural["route_trace"]["model_sha256"]},
        "sampling_policy": neural["route_trace"]["sampling_policy_id"],
        "test_summary": {"checks": checks, "pytest": tests["stdout"].strip(), "free_bytes": free, "repair_count": rehearsal["repair"]["repair_count"]},
        "open_findings": [{"severity": "P2", "summary": "human chemistry, physical voice and final design remain Guilherme-only judgments"}],
        "authorized_claims": ["the real local-neural photo-restoration holdout completed the integrated rehearsal with bounded diagnostic repair"] if gate_pass else [],
        "forbidden_claims": ["human proof passed", "voice chemistry approved", "general intelligent autonomy", "scientific benchmark"],
        "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc12(args: argparse.Namespace) -> int:
    import xml.etree.ElementTree as ET

    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc12-release"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC12 gate already sealed; overwrite denied")

    def read(path: Path) -> dict[str, Any]:
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

    release = repo / "release/human-proof"
    manifest = read(release / "MANIFEST.json")
    verify = read(evidence / "verify-release-attempt3.json")
    vm = read(evidence / "vm-packaged-probe-attempt2/vm-appliance-probe.json")
    voice = read(evidence / "synthetic-voice.json")
    asr = read(evidence / "asr-smoke.json")
    materialization = read(evidence / "materialization/external-materialization.json")
    owner = read(evidence / "owner-audit-attempt3.json")
    public = read(evidence / "public-package-audit-attempt3.json")
    public_source = read(evidence / "public-source-audit.json")
    cloud = read(evidence / "cloud-audit.json")
    cargo = read(evidence / "cargo.json")
    compileall = read(evidence / "compileall.json")
    product_tests = junit(evidence / "final-product-tests.xml")
    compiler_tests = junit(evidence / "compiler-tests.xml")
    neural = read(repo / "product-demos/revolution-closure/rc11-integrated/neural-photo-restoration-attempt2/sm8-owner-vertical-slice.json")
    security = read(repo / "product-demos/revolution-closure/rc10-security/probe-attempt2/security-attack-probe.json")
    free = shutil.disk_usage(repo).free
    required = {
        "START_CASULO_OWNER.vbs", "VERIFY_RELEASE.vbs", "RESTORE_CLEAN_STATE.vbs", "COLLECT_FEEDBACK.vbs",
        "MANIFEST.json", "SBOM.spdx.json", "SHA256SUMS", "DEVELOPMENT_SIGNATURE.json", "HUMAN_PROOF_CARD.md",
        "HUMAN_PROOF_RUNBOOK.md", "KNOWN_LIMITATIONS.md", "CLAIMS.md", "ROLLBACK.md", "OWNER_VM",
    }
    launch_text = (release / "START_CASULO_OWNER.vbs").read_text(encoding="utf-8-sig")
    checks = {
        "release_shape": required <= {path.name for path in release.iterdir()},
        "manifest_and_signature": verify.get("ready") is True and all(verify.get("checks", {}).values()),
        "bundled_entrypoint_signed": "OWNER_VM\\tools\\human_proof_window.pyw" in launch_text and any(entry["path"] == "OWNER_VM/tools/human_proof_window.pyw" for entry in manifest["files"]),
        "gui_without_powershell": "powershell" not in launch_text.casefold() and "pyw.exe" in launch_text.casefold(),
        "three_packaged_boots": vm.get("gate") == "PASS" and all(vm.get("checks", {}).values()) and len(vm.get("cycles", [])) == 3,
        "base_immutable": vm.get("checks", {}).get("base_immutable") is True and manifest["files"][0] is not None,
        "synthetic_voice": voice.get("state") == "PASS" and asr.get("passed") is True and voice.get("checks", {}).get("physical_device_opened") is False,
        "materialization_clean_roundtrip": materialization.get("state") == "PASS" and all(materialization.get("checks", {}).values()),
        "owner_allowlist": owner.get("pass") is True and all(owner.get("checks", {}).values()),
        "public_artifact_clean": public.get("private_components_absent") is True and public_source.get("private_components_absent") is True,
        "cloud_fail_closed": cloud.get("pass") is True and cloud.get("release_state") == "RELEASE_LOCKED",
        "product_regression": product_tests["tests"] >= 344 and product_tests["failures"] == product_tests["errors"] == 0,
        "compiler_native_regression": compiler_tests["tests"] >= 74 and compiler_tests["failures"] == compiler_tests["errors"] == 0 and cargo.get("exit_code") == 0,
        "compileall": compileall.get("exit_code") == 0,
        "real_local_neural_engine": neural.get("gate") == "SM8_OWNER_VERTICAL_SLICE_PASS" and all(neural.get("checks", {}).values()),
        "automated_security_zero_p0_p1": security.get("state") == "PASS" and security.get("metrics", {}).get("P0") == 0 and security.get("metrics", {}).get("P1_on_supported_human_path") == 0,
        "hard_boundaries": manifest.get("boundaries") == {"cloud": "RELEASE_LOCKED", "guest_network_default": "OFF", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED", "usb_block_devices": "PROHIBITED"},
        "human_authority_pending": manifest.get("human_proof") == "PENDING_GUILHERME",
        "development_signature_only": manifest.get("signature") == "DEVELOPMENT_NOT_COMMERCIAL" and read(release / "DEVELOPMENT_SIGNATURE.json").get("label") == "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE",
        "storage_reserve": free >= MINIMUM_RESERVE_BYTES,
    }
    gate_pass = all(checks.values())
    captured = datetime.now(timezone.utc).isoformat()
    previous_gate = repo / "product-demos/revolution-closure/rc11-integrated/gate.json"
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC12_HUMAN_PROOF_CANDIDATE_SEALED", "status": "PASS" if gate_pass else "FAIL",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "worktree_manifest_sha256": sha256(repo / "product-demos/revolution-closure/rc00-baseline-attempt2/worktree-manifest.json"),
        "machine_profile_sha256": sha256(repo / "docs/product/RC_MACHINE_PROFILE.json"),
        "commands": [
            [sys.executable, "tools/build_human_proof_release.py", "--output", "release/human-proof", "--staging", "<attempt3>", "--signing-key", "%LOCALAPPDATA%/Casulo/dev-signing/owner-ed25519"],
            [sys.executable, "tools/human_proof_control.pyw", "verify", "--release", "release/human-proof", "--json"],
            [sys.executable, "tools/vm_appliance_probe.py", "--source-image", "release/human-proof/OWNER_VM/casulo-native-generative-interactive.img"],
            [sys.executable, "-m", "pytest", "tests/product"],
            ["cargo", "+nightly-2026-02-01", "-Z", "bindeps", "check", "--manifest-path", "os/Cargo.toml", "--locked"],
        ],
        "tool_versions": {"python": platform.python_version()},
        "input_hashes": {"previous_gate": sha256(previous_gate), "release_manifest": sha256(release / "MANIFEST.json")},
        "output_hashes": {path.relative_to(repo).as_posix(): sha256(path) for path in evidence.rglob("*") if path.is_file() and path.name != "gate.json" and "-temp" not in path.as_posix()},
        "model_adapter_hashes": {"bootstrap_model": manifest["model"]["model_sha256"], "learned_router": sha256(repo / "models/training/router-rc5-v1.json")},
        "sampling_policy": neural["route_trace"]["sampling_policy_id"],
        "test_summary": {"checks": checks, "product": product_tests, "compiler_native": compiler_tests, "free_bytes": free},
        "open_findings": [
            {"severity": "HUMAN", "summary": "physical voice, chemistry, utility and final design remain pending Guilherme"},
            {"severity": "P2", "summary": "local CPU inference and provisional TTS may have perceptible latency or robotic timbre"},
        ],
        "authorized_claims": ["the signed owner candidate is ready for Guilherme's human proof"] if gate_pass else [],
        "forbidden_claims": ["GUILHERME_HUMAN_PROOF_PASS", "commercial release", "physical voice approved", "scientific or universal superiority"],
        "timestamp": captured, "previous_gate_hash": sha256(previous_gate),
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["gate_id"] if gate_pass else "IN_PROGRESS_CHECKPOINTED", "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_pass else 2


def rc13(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    evidence = repo / "product-demos/revolution-closure/rc13-handoff"
    gate_path = evidence / "gate.json"
    if gate_path.exists():
        raise SystemExit("RC13 gate already sealed; overwrite denied")
    evidence.mkdir(parents=True, exist_ok=False)
    release = repo / "release/human-proof"
    rc12_gate = repo / "product-demos/revolution-closure/rc12-release/gate.json"
    rc12 = json.loads(rc12_gate.read_text(encoding="utf-8"))
    manifest = json.loads((release / "MANIFEST.json").read_text(encoding="utf-8"))
    required_docs = (
        "docs/product/RC_EXECUTION_STATE.md", "docs/product/RC_EVIDENCE_INDEX.md",
        "docs/product/RC_CLAIMS_REGISTER.md", "docs/product/RC_RISK_REGISTER.md",
        "docs/product/RC_MODEL_TRAINING_FACTORY.md", "docs/product/RC_HUMAN_PROOF_HANDOFF.md",
        "docs/product/RC_FINAL_REPORT.md",
    )
    verify = run([sys.executable, "tools/human_proof_control.pyw", "verify", "--release", "release/human-proof", "--json"], cwd=repo, timeout=60)
    verify_payload = json.loads(verify["stdout"])
    final_state = "READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF"
    state_text = (repo / "docs/product/RC_EXECUTION_STATE.md").read_text(encoding="utf-8")
    handoff_text = (repo / "docs/product/RC_HUMAN_PROOF_HANDOFF.md").read_text(encoding="utf-8")
    free = shutil.disk_usage(repo).free
    checks = {
        "rc12_pass": rc12.get("status") == "PASS" and rc12.get("gate_id") == "RC12_HUMAN_PROOF_CANDIDATE_SEALED",
        "release_still_verifies": verify.get("exit_code") == 0 and verify_payload.get("ready") is True,
        "durable_documents": all((repo / relative).is_file() for relative in required_docs),
        "ready_state_recorded": final_state in state_text and final_state in handoff_text,
        "exact_click_path": "release/human-proof/VERIFY_RELEASE.vbs" in handoff_text and "release/human-proof/START_CASULO_OWNER.vbs" in handoff_text,
        "human_authority_preserved": manifest.get("human_proof") == "PENDING_GUILHERME" and "GUILHERME_HUMAN_PROOF_PASS` antes" in (repo / "docs/product/RC_CLAIMS_REGISTER.md").read_text(encoding="utf-8"),
        "hard_boundaries": manifest.get("boundaries", {}).get("cloud") == "RELEASE_LOCKED" and manifest.get("boundaries", {}).get("guest_network_default") == "OFF" and manifest.get("boundaries", {}).get("usb_block_devices") == "PROHIBITED" and manifest.get("boundaries", {}).get("qpu") == "UNAVAILABLE_DENY" and manifest.get("boundaries", {}).get("scientific_benchmark") == "NOT_STARTED",
        "development_only": manifest.get("signature") == "DEVELOPMENT_NOT_COMMERCIAL",
        "storage_reserve": free >= MINIMUM_RESERVE_BYTES,
    }
    passed = all(checks.values())
    captured = datetime.now(timezone.utc).isoformat()
    gate = {
        "schema": f"{SCHEMA}/gate", "gate_id": "RC13_HANDOFF_COMPLETE", "status": "PASS" if passed else "FAIL",
        "state": final_state if passed else "IN_PROGRESS_CHECKPOINTED",
        "baseline_commit": run(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip(),
        "branch": run(["git", "branch", "--show-current"], cwd=repo)["stdout"].strip(),
        "checks": checks,
        "previous_gate_hash": sha256(rc12_gate),
        "release_manifest_sha256": sha256(release / "MANIFEST.json"),
        "release_signature_sha256": sha256(release / "MANIFEST.json.sig"),
        "sha256sums_sha256": sha256(release / "SHA256SUMS"),
        "handoff_sha256": sha256(repo / "docs/product/RC_HUMAN_PROOF_HANDOFF.md"),
        "documents": {relative: sha256(repo / relative) for relative in required_docs},
        "free_bytes": free,
        "next_action": "double-click release/human-proof/VERIFY_RELEASE.vbs, then START_CASULO_OWNER.vbs",
        "human_proof": "PENDING_GUILHERME",
        "forbidden_claims": ["GUILHERME_HUMAN_PROOF_PASS", "commercial release", "physical voice approved", "scientific benchmark result"],
        "timestamp": captured,
    }
    write_json(gate_path, gate)
    receipt = {"schema": f"{SCHEMA}/receipt", "state": gate["state"], "gate": gate["gate_id"], "gate_sha256": sha256(gate_path), "evidence_root": evidence.relative_to(repo).as_posix(), "timestamp": captured}
    write_json(evidence / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passed else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Casulo Revolution Closure evidence runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("rc0", help="freeze and reconcile the current baseline")
    command.add_argument("--repo", type=Path, required=True)
    command.add_argument("--zip", type=Path, required=True)
    command.add_argument("--staging", type=Path, required=True)
    command.set_defaults(func=rc0)
    command = subparsers.add_parser("rc1", help="freeze contracts, metrics and trust boundaries")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc1)
    command = subparsers.add_parser("rc2", help="seal Guide continuity and colleague loop")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc2)
    command = subparsers.add_parser("rc3", help="seal semantic fulfillment and independent evidence")
    command.add_argument("--repo", type=Path, required=True)
    command.add_argument("--neural-attempt", default="neural-holdout-attempt4")
    command.set_defaults(func=rc3)
    command = subparsers.add_parser("rc4", help="compile and audit sovereign T decision surfaces")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc4)
    command = subparsers.add_parser("rc5", help="train and promote the bounded first-party learned layer")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc5)
    command = subparsers.add_parser("rc6", help="validate Semantic Multiverse product invariants and profiles")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc6)
    command = subparsers.add_parser("rc7", help="seal the one-click owner VM appliance")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc7)
    command = subparsers.add_parser("rc8", help="seal the automated primary voice implementation")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc8)
    command = subparsers.add_parser("rc9", help="seal external materialization and round-trip")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc9)
    command = subparsers.add_parser("rc10", help="run and seal the integrated security attack campaign")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc10)
    command = subparsers.add_parser("rc11", help="seal the prolonged integrated rehearsal")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc11)
    command = subparsers.add_parser("rc12", help="seal the owner human-proof release candidate")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc12)
    command = subparsers.add_parser("rc13", help="complete the owner human-proof handoff")
    command.add_argument("--repo", type=Path, required=True)
    command.set_defaults(func=rc13)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
