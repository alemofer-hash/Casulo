from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "qwen3-4b-q4km-llamacpp-b10362"
RELEASE_NAME = "t85-human-proof"
SIGNING_IDENTITY = "casulo-owner-t85-human-proof-dev"
SIGNING_NAMESPACE = "casulo-t85-human-proof"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(argv: list[str], *, cwd: Path = ROOT, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=input_bytes is None,
        encoding="utf-8" if input_bytes is None else None,
        errors="replace" if input_bytes is None else None,
        check=False,
        shell=False,
    )
    if completed.returncode:
        stdout = completed.stdout.decode("utf-8", "replace") if isinstance(completed.stdout, bytes) else completed.stdout
        stderr = completed.stderr.decode("utf-8", "replace") if isinstance(completed.stderr, bytes) else completed.stderr
        raise RuntimeError(f"command failed ({completed.returncode}): {argv}\n{stdout[-2000:]}\n{stderr[-2000:]}")
    return completed


def copy_python_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache"),
    )


def launcher(script: str, action: str = "") -> str:
    arguments = f" {action}" if action else ""
    return f'''Option Explicit
Dim shell, fso, releaseDir, pyw, helper, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
releaseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = shell.ExpandEnvironmentStrings("%WINDIR%") & "\\pyw.exe"
helper = releaseDir & "\\OWNER_VM\\app\\tools\\{script}"
If shell.ExpandEnvironmentStrings("%CASULO_LAUNCHER_DRY_RUN%") = "1" Then
  WScript.Echo "CASULO_T85_VBS_PARSE_PASS"
  WScript.Quit 0
End If
If Not fso.FileExists(pyw) Or Not fso.FileExists(helper) Then
  MsgBox "Componente local ausente. Nenhum estado foi alterado.", 16, "Casulo T85"
  WScript.Quit 2
End If
shell.CurrentDirectory = releaseDir
command = Chr(34) & pyw & Chr(34) & " " & Chr(34) & helper & Chr(34) & "{arguments} --release " & Chr(34) & releaseDir & Chr(34)
shell.Run command, 0, False
'''


def _copy_application(app: Path) -> list[str]:
    copy_python_tree(ROOT / "src/casulo", app / "src/casulo")
    copy_python_tree(ROOT / "private/casulo-owner/src/casulo_owner", app / "private/casulo-owner/src/casulo_owner")
    (app / "private/casulo-owner/t-v2").mkdir(parents=True)
    for source in sorted((ROOT / "private/casulo-owner/t-v2").glob("*.t")):
        shutil.copy2(source, app / "private/casulo-owner/t-v2" / source.name)
    tools = (
        "human_proof_window.pyw",
        "human_proof_control.pyw",
        "casulo_semantic_multiverse_vm_inspect.py",
        "casulo_owner_vm_inspect.py",
        "stark_jobs_vm_probe.py",
        "t85_appliance_probe.py",
        "run_t85_integrated_rehearsal.py",
    )
    (app / "tools").mkdir(parents=True)
    for name in tools:
        shutil.copy2(ROOT / "tools" / name, app / "tools" / name)
    (app / "t-runtime/target/release").mkdir(parents=True)
    shutil.copy2(ROOT / "t-runtime/target/release/casulo-t-runtime.exe", app / "t-runtime/target/release/casulo-t-runtime.exe")
    (app / "registry").mkdir(parents=True)
    candidate = ROOT / "release/generative-candidates" / f"{MODEL_ID}.json"
    shutil.copy2(candidate, app / "registry" / candidate.name)
    (app / "release/generative-candidates").mkdir(parents=True)
    shutil.copy2(candidate, app / "release/generative-candidates" / candidate.name)
    voice = ROOT / "release/voice-candidates"
    if voice.is_dir():
        shutil.copytree(voice, app / "release/voice-candidates")
    return list(tools)


def build(output: Path, staging: Path, signing_key: Path) -> dict[str, Any]:
    output, staging = output.resolve(), staging.resolve()
    if output.name.casefold() != RELEASE_NAME or output.parent.name.casefold() != "release":
        raise RuntimeError("output deve ser release/t85-human-proof")
    if output.exists() or output.is_symlink():
        raise RuntimeError("release T85 existente; overwrite negado")
    if staging.exists() or staging.is_symlink():
        raise RuntimeError("staging existente; use identidade append-only")
    signing_key = signing_key.resolve(strict=True)
    public_key = signing_key.with_suffix(signing_key.suffix + ".pub")
    if not public_key.is_file():
        raise RuntimeError("chave publica de desenvolvimento ausente")

    staging.mkdir(parents=True)
    owner = staging / "OWNER_VM"
    app = owner / "app"
    app.mkdir(parents=True)
    tools = _copy_application(app)

    candidate_path = app / "registry" / f"{MODEL_ID}.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/generative" / MODEL_ID
    model = cache / "model" / candidate["model"]["file"]
    runtime = cache / "runtime" / candidate["runtime"]["required_executable"]
    if not model.is_file() or sha256(model) != candidate["model"]["sha256"]:
        raise RuntimeError("peso owner consentido ausente ou com hash divergente")
    if not runtime.is_file():
        raise RuntimeError("runtime neural registrado ausente")
    adoption_path = cache / "ADOPTION.json"
    adoption = json.loads(adoption_path.read_text(encoding="utf-8"))
    runtime_entries = adoption.get("runtime_files", [])
    expected_runtime = {str(item["path"]): (int(item["bytes"]), str(item["sha256"])) for item in runtime_entries}
    actual_runtime = {
        path.relative_to(cache).as_posix(): (path.stat().st_size, sha256(path))
        for path in sorted((cache / "runtime").iterdir()) if path.is_file()
    }
    if not expected_runtime or actual_runtime != expected_runtime:
        raise RuntimeError("runtime neural nao corresponde ao receipt de adocao")
    runtime_version = run([str(runtime), "--version"]).stdout.strip()

    base_source = ROOT / "release/casulo-native-generative-interactive.img"
    base = owner / base_source.name
    shutil.copy2(base_source, base)
    base.chmod(stat.S_IREAD)

    registry = {
        "schema": "casulo.t85-content-registry/1.0",
        "model": {
            "candidate_id": MODEL_ID,
            "cache_relative": f"{MODEL_ID}/model/{candidate['model']['file']}",
            "bytes": model.stat().st_size,
            "sha256": sha256(model),
            "license": candidate["model"]["license"],
            "embedded": False,
        },
        "neural_runtime": {
            "cache_relative": f"{MODEL_ID}/runtime/{candidate['runtime']['required_executable']}",
            "binary_bytes": runtime.stat().st_size,
            "binary_sha256": sha256(runtime),
            "archive_sha256": candidate["runtime"]["sha256"],
            "commit": candidate["runtime"]["commit"],
            "license": candidate["runtime"]["license"],
            "embedded": False,
            "adoption_receipt_sha256": sha256(adoption_path),
            "version_output": runtime_version,
            "launcher_role": "small PE launcher paired with llama-server-impl.dll",
            "implementation_binary": {
                "path": "runtime/llama-server-impl.dll",
                "bytes": expected_runtime["runtime/llama-server-impl.dll"][0],
                "sha256": expected_runtime["runtime/llama-server-impl.dll"][1],
            },
            "runtime_tree": [{"path": name, "bytes": value[0], "sha256": value[1]} for name, value in sorted(expected_runtime.items())],
        },
        "t_runtime": {
            "relative": "app/t-runtime/target/release/casulo-t-runtime.exe",
            "sha256": sha256(app / "t-runtime/target/release/casulo-t-runtime.exe"),
            "embedded": True,
        },
        "base_vm": {"relative": base.name, "bytes": base.stat().st_size, "sha256": sha256(base)},
    }
    (owner / "CONTENT_REGISTRY.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    profile = {
        "schema": "casulo.t85-vm-profile/1.0",
        "base": base.name,
        "base_sha256": sha256(base),
        "base_read_only": True,
        "state_root": "%LOCALAPPDATA%/Casulo/t85-human-proof/owner-vm",
        "overlay": "sparse-qcow2-runtime-created",
        "overlay_quota_bytes": 12 * 1024**3,
        "clean_snapshot": "t85-human-proof-clean",
        "machine": "q35",
        "firmware": "OVMF",
        "accelerator_profile": ["whpx", "tcg"],
        "guest_network_default": "OFF",
        "shared_folders": False,
        "usb_block_devices": "PROHIBITED",
        "qpu": "UNAVAILABLE_DENY",
    }
    (owner / "VM_PROFILE.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    launchers = {
        "START_CASULO_OWNER_T85.vbs": launcher("human_proof_window.pyw"),
        "VERIFY_CASULO_OWNER_T85.vbs": launcher("human_proof_control.pyw", "verify"),
        "RESTORE_CASULO_OWNER_T85.vbs": launcher("human_proof_control.pyw", "restore"),
        "COLLECT_T85_FEEDBACK.vbs": launcher("human_proof_control.pyw", "feedback"),
    }
    for name, content in launchers.items():
        (staging / name).write_text(content, encoding="cp1252", newline="\r\n")

    docs = {
        "T85_HUMAN_PROOF_RUNBOOK.md": ROOT / "docs/product/T85_HUMAN_PROOF_RUNBOOK.md",
        "T85_CLAIMS_AND_LIMITATIONS.md": ROOT / "docs/product/T85_CLAIMS_AND_LIMITATIONS.md",
        "T85_ROLLBACK.md": ROOT / "docs/product/T85_ROLLBACK.md",
        "T85_INTEGRATED_REHEARSAL.md": ROOT / "docs/product/T85_INTEGRATED_REHEARSAL.md",
    }
    for name, source in docs.items():
        shutil.copy2(source, staging / name)

    shutil.copy2(public_key, staging / "SIGNING_KEY.pub")
    (staging / "ALLOWED_SIGNERS").write_text(f"{SIGNING_IDENTITY} {public_key.read_text(encoding='ascii').strip()}\n", encoding="ascii", newline="\n")
    fingerprint = run(["ssh-keygen", "-lf", str(public_key), "-E", "sha256"]).stdout.split()[1]
    signature = {
        "schema": "casulo.development-signature/1.0",
        "label": "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE",
        "algorithm": "ssh-ed25519",
        "identity": SIGNING_IDENTITY,
        "namespace": SIGNING_NAMESPACE,
        "public_key_fingerprint": fingerprint,
        "private_key_embedded": False,
    }
    (staging / "DEVELOPMENT_SIGNATURE.json").write_text(json.dumps(signature, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "casulo-owner-t85-human-proof",
        "documentNamespace": "https://teloscorp.invalid/spdx/casulo-owner-t85/2026-08-15",
        "creationInfo": {"created": datetime.now(timezone.utc).isoformat(), "creators": ["Organization: Teloscorp"]},
        "packages": [
            {"name": "Casulo owner T85 private application", "SPDXID": "SPDXRef-CasuloT85", "licenseConcluded": "LicenseRef-Teloscorp-Proprietary", "downloadLocation": "NOASSERTION"},
            {"name": "Casulo T runtime", "SPDXID": "SPDXRef-TRuntime", "licenseConcluded": "LicenseRef-Teloscorp-Proprietary", "downloadLocation": "NOASSERTION"},
            {"name": "Qwen3-4B Q4_K_M bootstrap reference", "SPDXID": "SPDXRef-Qwen", "licenseConcluded": "Apache-2.0", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
            {"name": "llama.cpp b10362 runtime reference", "SPDXID": "SPDXRef-LlamaCpp", "licenseConcluded": "MIT", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
            {"name": "Python runtime host dependency", "SPDXID": "SPDXRef-Python", "licenseConcluded": "PSF-2.0", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
            {"name": "QEMU host dependency", "SPDXID": "SPDXRef-QEMU", "licenseConcluded": "GPL-2.0-only", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
        ],
        "annotations": [{"annotationType": "OTHER", "annotator": "Organization: Teloscorp", "annotationDate": datetime.now(timezone.utc).isoformat(), "comment": "Weights and private signing keys are not embedded. This is a development candidate."}],
    }
    sbom["files"] = [
        {
            "fileName": path.relative_to(staging).as_posix(),
            "SPDXID": f"SPDXRef-File-{index:04d}",
            "checksums": [{"algorithm": "SHA256", "checksumValue": sha256(path)}],
        }
        for index, path in enumerate(sorted(item for item in staging.rglob("*") if item.is_file()), 1)
    ]
    (staging / "SBOM.spdx.json").write_text(json.dumps(sbom, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    excluded = {"MANIFEST.json", "MANIFEST.json.sig", "SHA256SUMS"}
    files = [path for path in sorted(staging.rglob("*")) if path.is_file() and path.name not in excluded]
    manifest = {
        "schema": "casulo.t85-human-proof-release/1.0",
        "state": "T85_TECHNICAL_CANDIDATE_PENDING_HUMAN_PROOF",
        "human_proof": "PENDING_GUILHERME",
        "signature": "DEVELOPMENT_NOT_COMMERCIAL",
        "checkout_dependency": False,
        "pythonpath_dependency": False,
        "content_registry_sha256": sha256(owner / "CONTENT_REGISTRY.json"),
        "boundaries": {"cloud": "RELEASE_LOCKED", "guest_network_default": "OFF", "usb_block_devices": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
        "entrypoints": sorted(launchers),
        "bundled_tools": tools,
        "files": [{"path": path.relative_to(staging).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in files],
        "created": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = staging / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    run(["ssh-keygen", "-Y", "sign", "-f", str(signing_key), "-n", SIGNING_NAMESPACE, str(manifest_path)])
    run(
        ["ssh-keygen", "-Y", "verify", "-f", str(staging / "ALLOWED_SIGNERS"), "-I", SIGNING_IDENTITY, "-n", SIGNING_NAMESPACE, "-s", str(staging / "MANIFEST.json.sig")],
        input_bytes=manifest_path.read_bytes(),
    )
    payloads = [path for path in sorted(staging.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"]
    (staging / "SHA256SUMS").write_text("".join(f"{sha256(path)}  {path.relative_to(staging).as_posix()}\n" for path in payloads), encoding="ascii", newline="\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(output)
    return {
        "schema": "casulo.t85-human-proof-build/1.0",
        "output": str(output),
        "manifest_sha256": sha256(output / "MANIFEST.json"),
        "sha256sums_sha256": sha256(output / "SHA256SUMS"),
        "signature_verified": True,
        "files": len([p for p in output.rglob("*") if p.is_file()]),
        "bytes": sum(p.stat().st_size for p in output.rglob("*") if p.is_file()),
        "model_sha256": candidate["model"]["sha256"],
        "runtime_sha256": sha256(runtime),
        "checkout_dependency": False,
        "pythonpath_dependency": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output, args.staging, args.signing_key)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
