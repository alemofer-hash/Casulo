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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(argv: list[str], *, cwd: Path = ROOT) -> dict[str, Any]:
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {argv}\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}")
    return {"argv": argv, "stdout": completed.stdout, "stderr": completed.stderr, "returncode": completed.returncode}


def vbs(script: str, action: str) -> str:
    return f'''Option Explicit
Dim shell, fso, releaseDir, repoDir, pyw, helper, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
releaseDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoDir = fso.GetParentFolderName(fso.GetParentFolderName(releaseDir))
pyw = shell.ExpandEnvironmentStrings("%WINDIR%") & "\\pyw.exe"
helper = releaseDir & "\\OWNER_VM\\tools\\{script}"
If shell.ExpandEnvironmentStrings("%CASULO_LAUNCHER_DRY_RUN%") = "1" Then
  WScript.Echo "CASULO_VBS_PARSE_PASS"
  WScript.Quit 0
End If
If Not fso.FileExists(pyw) Or Not fso.FileExists(helper) Then
  MsgBox "Componente local ausente. Nenhum estado foi alterado.", 16, "Casulo"
  WScript.Quit 2
End If
shell.CurrentDirectory = repoDir
command = Chr(34) & pyw & Chr(34) & " " & Chr(34) & helper & Chr(34) & " {action} --release " & Chr(34) & releaseDir & Chr(34)
shell.Run command, 0, False
'''


def build(output: Path, signing_key: Path, staging: Path) -> dict[str, Any]:
    output = output.resolve()
    staging = staging.resolve()
    if output.exists() or output.is_symlink():
        raise RuntimeError("release/human-proof já existe; overwrite negado")
    if staging.exists() or staging.is_symlink():
        raise RuntimeError("staging já existe; escolha uma identidade nova")
    signing_key = signing_key.resolve(strict=True)
    public_key = signing_key.with_suffix(signing_key.suffix + ".pub")
    if not public_key.is_file():
        raise RuntimeError("chave pública de desenvolvimento ausente")
    staging.mkdir(parents=True)
    owner_vm = staging / "OWNER_VM"
    owner_vm.mkdir()
    bundled_tools = owner_vm / "tools"
    bundled_tools.mkdir()
    shutil.copy2(ROOT / "tools/human_proof_control.pyw", bundled_tools / "human_proof_control.pyw")
    shutil.copy2(ROOT / "tools/human_proof_window.pyw", bundled_tools / "human_proof_window.pyw")

    candidate_path = ROOT / "release/generative-candidates" / f"{MODEL_ID}.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/generative" / MODEL_ID
    model = cache / "model" / candidate["model"]["file"]
    runtime = cache / "runtime" / candidate["runtime"]["required_executable"]
    if not model.is_file() or sha256(model) != candidate["model"]["sha256"] or not runtime.is_file():
        raise RuntimeError("modelo/runtime owner verificados não estão disponíveis")

    base_source = ROOT / "release/casulo-native-generative-interactive.img"
    base_target = owner_vm / base_source.name
    shutil.copy2(base_source, base_target)
    base_target.chmod(stat.S_IREAD)

    owner_artifact = owner_vm / "casulo-owner-generative-semantic-multiverse.zip"
    owner_report = owner_vm / "OWNER_ARTIFACT_BUILD.json"
    run([sys.executable, "tools/build_generative_owner_artifact.py", "--output", str(owner_artifact), "--candidate", str(candidate_path), "--report", str(owner_report), "--semantic-multiverse"])
    extracted = owner_vm / "owner-artifact-extracted-audit"
    extracted_report = owner_vm / "OWNER_ARTIFACT_EXTRACTED_AUDIT.json"
    run([sys.executable, "tools/audit_owner_artifact_extracted.py", str(owner_artifact), "--destination", str(extracted), "--output", str(extracted_report)])

    key_root = signing_key.parent
    edition_root = owner_vm / "editions"
    editions = run([
        sys.executable, "tools/build_product_editions.py", "--output", str(edition_root),
        "--owner-key", str(signing_key), "--public-key", str(key_root / "public-ed25519"),
        "--cloud-key", str(key_root / "cloud-standby-ed25519"),
    ])
    (owner_vm / "EDITION_BUILD.json").write_text(editions["stdout"], encoding="utf-8", newline="\n")
    public_wheel = next((edition_root / "public").glob("*.whl"))
    public_audit = run([sys.executable, "tools/audit_public_artifact.py", str(public_wheel)])
    (owner_vm / "PUBLIC_BOUNDARY_AUDIT.json").write_text(public_audit["stdout"], encoding="utf-8", newline="\n")

    profile = {
        "schema": "casulo.human-proof-vm-profile/1.0",
        "base": base_target.name,
        "base_sha256": sha256(base_target),
        "base_read_only": not os.access(base_target, os.W_OK),
        "state_root": "%LOCALAPPDATA%/Casulo/human-proof/owner-vm",
        "overlay": "sparse-qcow2-runtime-created",
        "clean_snapshot": "human-proof-clean",
        "network": "denied",
        "shared_folders": False,
        "usb_block_devices": "PROHIBITED",
        "qpu": "UNAVAILABLE_DENY",
    }
    (owner_vm / "VM_PROFILE.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    model_ref = {
        "schema": "casulo.human-proof-model-reference/1.0",
        "candidate_id": MODEL_ID,
        "model_sha256": candidate["model"]["sha256"],
        "model_license": candidate["model"]["license"],
        "model_embedded": False,
        "runtime_archive_sha256": candidate["runtime"]["sha256"],
        "runtime_license": candidate["runtime"]["license"],
        "runtime_executable_sha256": sha256(runtime),
        "cache_private": True,
    }
    (owner_vm / "MODEL_REFERENCE.json").write_text(json.dumps(model_ref, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    launchers = {
        "START_CASULO_OWNER.vbs": vbs("human_proof_window.pyw", ""),
        "VERIFY_RELEASE.vbs": vbs("human_proof_control.pyw", "verify"),
        "RESTORE_CLEAN_STATE.vbs": vbs("human_proof_control.pyw", "restore"),
        "COLLECT_FEEDBACK.vbs": vbs("human_proof_control.pyw", "feedback"),
    }
    for name, text in launchers.items():
        # Windows Script Host 5.x treats an UTF-8 BOM as a VBScript token and
        # fails at line 1, character 1.  These launchers contain only text that
        # is representable in the Windows-1252 system code page, so emit that
        # encoding without a BOM for direct double-click compatibility.
        (staging / name).write_text(text, encoding="cp1252", newline="\r\n")

    documents = {
        "HUMAN_PROOF_CARD.md": ROOT / "docs/product/RC_HUMAN_PROOF_CARD.md",
        "HUMAN_PROOF_RUNBOOK.md": ROOT / "docs/product/RC_HUMAN_PROOF_RUNBOOK.md",
        "KNOWN_LIMITATIONS.md": ROOT / "docs/product/RC_HUMAN_PROOF_LIMITATIONS.md",
        "CLAIMS.md": ROOT / "docs/product/RC_HUMAN_PROOF_CLAIMS.md",
        "ROLLBACK.md": ROOT / "docs/product/RC_HUMAN_PROOF_ROLLBACK.md",
    }
    for name, source in documents.items():
        shutil.copy2(source, staging / name)

    shutil.copy2(public_key, staging / "SIGNING_KEY.pub")
    identity = "casulo-owner-human-proof-dev"
    (staging / "ALLOWED_SIGNERS").write_text(f"{identity} {public_key.read_text(encoding='ascii').strip()}\n", encoding="ascii", newline="\n")
    fingerprint = run(["ssh-keygen", "-lf", str(public_key), "-E", "sha256"])["stdout"].split()[1]
    signature_metadata = {
        "schema": "casulo.development-signature/1.0",
        "label": "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE",
        "algorithm": "ssh-ed25519",
        "namespace": "casulo-human-proof",
        "identity": identity,
        "public_key_fingerprint": fingerprint,
        "private_key_embedded": False,
    }
    (staging / "DEVELOPMENT_SIGNATURE.json").write_text(json.dumps(signature_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    sbom = {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": "casulo-owner-human-proof-candidate", "documentNamespace": "https://teloscorp.invalid/spdx/casulo-owner-human-proof/2026-08-14",
        "creationInfo": {"created": datetime.now(timezone.utc).isoformat(), "creators": ["Organization: Teloscorp"]},
        "packages": [
            {"name": "Casulo owner", "SPDXID": "SPDXRef-CasuloOwner", "licenseConcluded": "LicenseRef-Teloscorp-Proprietary", "downloadLocation": "NOASSERTION"},
            {"name": "Qwen3-4B Q4_K_M bootstrap reference", "SPDXID": "SPDXRef-Qwen", "licenseConcluded": "Apache-2.0", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
            {"name": "llama.cpp b10362 runtime reference", "SPDXID": "SPDXRef-LlamaCpp", "licenseConcluded": "MIT", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
        ],
        "annotations": [{"annotationType": "OTHER", "annotator": "Organization: Teloscorp", "annotationDate": datetime.now(timezone.utc).isoformat(), "comment": "Weights and signing private keys are not embedded."}],
    }
    (staging / "SBOM.spdx.json").write_text(json.dumps(sbom, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    excluded = {"MANIFEST.json", "MANIFEST.json.sig", "SHA256SUMS"}
    files = [path for path in sorted(staging.rglob("*")) if path.is_file() and path.name not in excluded]
    manifest = {
        "schema": "casulo.human-proof-release/1.0",
        "state": "RC12_CANDIDATE_PENDING_GATE",
        "human_proof": "PENDING_GUILHERME",
        "signature": "DEVELOPMENT_NOT_COMMERCIAL",
        "model": model_ref,
        "boundaries": {"cloud": "RELEASE_LOCKED", "guest_network_default": "OFF", "usb_block_devices": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
        "files": [{"path": path.relative_to(staging).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in files],
        "created": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = staging / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    run(["ssh-keygen", "-Y", "sign", "-f", str(signing_key), "-n", "casulo-human-proof", str(manifest_path)])
    verified = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(staging / "ALLOWED_SIGNERS"), "-I", identity, "-n", "casulo-human-proof", "-s", str(staging / "MANIFEST.json.sig")],
        input=manifest_path.read_bytes(), capture_output=True, check=False, shell=False,
    )
    if verified.returncode:
        raise RuntimeError("assinatura de desenvolvimento não verificou")
    payloads = [path for path in sorted(staging.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"]
    (staging / "SHA256SUMS").write_text("".join(f"{sha256(path)}  {path.relative_to(staging).as_posix()}\n" for path in payloads), encoding="ascii", newline="\n")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(output)
    return {
        "schema": "casulo.human-proof-build/1.0", "output": str(output),
        "manifest_sha256": sha256(output / "MANIFEST.json"), "signature_verified": True,
        "files": len(list(output.rglob("*"))), "base_sha256": sha256(output / "OWNER_VM" / base_source.name),
        "model_sha256": candidate["model"]["sha256"], "public_boundary_audit": json.loads((output / "OWNER_VM/PUBLIC_BOUNDARY_AUDIT.json").read_text(encoding="utf-8")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output, args.signing_key, args.staging)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
