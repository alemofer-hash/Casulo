#!/usr/bin/env python3
"""Seal the append-only Casulo Native boot-to-creation proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = "CASULO_NATIVE_BOOT_TO_CREATION_PROOF"
SIGNATURE_LABEL = "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE"
SIGNING_NAMESPACE = "casulo-native-boot-to-creation"
SIGNING_IDENTITY = "casulo-native-owner"
EXPECTED_IMAGE_SHA256 = "25193857a96d6c14328d92fb128d6e666a31478dee05cc8cca6a35252932a534"
EXPECTED_MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
EXPECTED_PACK_SHA256 = "4f5e9fb34de09a3fe59b49c233802312a1c2e4d86ec7d00ca2d1dc1638f7eeb1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def fresh(parent: Path, name: str) -> Path:
    for attempt in range(1, 100):
        suffix = "" if attempt == 1 else f"-attempt-{attempt}"
        target = parent / f"{name}{suffix}"
        if not target.exists():
            target.mkdir(parents=True)
            return target
    raise RuntimeError("append-only attempt space exhausted")


def command_output(command: list[str]) -> str:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=True)
    return (completed.stdout + completed.stderr).strip()


def zip_reproducible(source: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 8, 22, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal current NP10 evidence without altering historical attempts")
    parser.add_argument("--signing-key", type=Path, required=True)
    args = parser.parse_args()
    signing_key = args.signing_key.resolve(strict=True)
    public_key = Path(str(signing_key) + ".pub")
    if not public_key.is_file():
        raise SystemExit("development signing public key is missing")

    image = ROOT / "release/casulo-native-neural-port-np10-attempt-5.img"
    pack = ROOT / "release/casulo-native-neural-port-system-pack-np10.cspk"
    pack_manifest = ROOT / "release/casulo-native-neural-port-system-pack-np10.cspk.manifest.json"
    normal = ROOT / "outputs/casulo/native-boot-to-creation/2026-08-22-np10-attempt-11/normal-three-final.json"
    cancelled = ROOT / "outputs/casulo/native-boot-to-creation/2026-08-22-np10-attempt-12/cancel-final.json"
    host_oracle = ROOT / "outputs/casulo/native-boot-to-creation/2026-08-22-np10-attempt-3/creation-host-oracle.json"
    model = Path(os.environ["LOCALAPPDATA"]) / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362/model/Qwen3-4B-Q4_K_M.gguf"
    required = (image, pack, pack_manifest, normal, cancelled, host_oracle, model)
    if not all(path.is_file() for path in required):
        raise SystemExit("one or more sealed inputs are missing")
    if sha256(image) != EXPECTED_IMAGE_SHA256 or sha256(model) != EXPECTED_MODEL_SHA256 or sha256(pack) != EXPECTED_PACK_SHA256:
        raise SystemExit("sealed image/model/system-pack hash mismatch")

    normal_report = json.loads(normal.read_text(encoding="utf-8"))
    cancel_report = json.loads(cancelled.read_text(encoding="utf-8"))
    oracle = json.loads(host_oracle.read_text(encoding="utf-8"))
    if normal_report.get("passed") is not True or len(normal_report.get("boots", [])) != 3:
        raise SystemExit("three-boot positive report is not approved")
    if not all(boot.get("validation", {}).get("passed") is True for boot in normal_report["boots"]):
        raise SystemExit("one or more positive boots failed independent validation")
    expected_output_hex = (
        "4e4f4d453d536f6d65446f69734e756d65726f733b46554e43414f3d536f6d65"
        "446f69734e756d65726f733b454e54524144413d6e756d65726f312c6e756d6572"
        "6f323b53414944413d726573756c7461646f2e"
    )
    for boot in normal_report["boots"]:
        metrics = boot.get("metrics", {})
        if not (
            metrics.get("CASULO_NATIVE_CREATION_STATE") == "MATERIALIZED"
            and metrics.get("CASULO_NATIVE_CREATION_GATE") == "PASS"
            and metrics.get("CASULO_NATIVE_CREATION_OUTPUT_TOKENS") == "34"
            and metrics.get("CASULO_NATIVE_CREATION_OUTPUT_TEXT_HEX") == expected_output_hex
            and metrics.get("CASULO_NATIVE_CREATION_MODEL_SOURCE_BYTES_LOADED") == "2497280256"
            and metrics.get("CASULO_NATIVE_CREATION_ARTIFACT_RESULT") == "18"
            and metrics.get("CASULO_NATIVE_CREATION_SIMULATION") == "PASS"
            and metrics.get("CASULO_NATIVE_CREATION_ACCEPTANCE") == "PASS"
        ):
            raise SystemExit("positive boot work/result accounting is incomplete")
        serial_text = (ROOT / boot["serial_file"]).read_text(encoding="utf-8", errors="replace")
        if not (
            "CASULO_NATIVE_FULL_MODEL_RESIDENT=YES" in serial_text
            and "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=YES" in serial_text
        ):
            raise SystemExit("positive boot lacks authoritative aggregate model markers")
    if cancel_report.get("passed") is not True or len(cancel_report.get("boots", [])) != 1:
        raise SystemExit("cancellation report is not approved")
    cancel_metrics = cancel_report["boots"][0]["metrics"]
    if not (
        cancel_metrics.get("CASULO_NATIVE_CREATION_STATE") == "CANCELLED_CLEAN"
        and cancel_metrics.get("CASULO_NATIVE_CREATION_LATE_OUTPUT_PUBLISHED") == "NO"
        and cancel_metrics.get("CASULO_NATIVE_CREATION_ACCEPTANCE") == "NOT_PUBLISHED"
        and cancel_metrics.get("CASULO_NATIVE_CREATION_MATERIALIZATION_SHA256") == "0" * 64
    ):
        raise SystemExit("cancellation did not fail closed")
    oracle_checks = oracle.get("checks", {})
    if not (
        oracle.get("state") == "PASS"
        and oracle_checks.get("process_exit_zero") is True
        and oracle_checks.get("model_hash_before_exact") is True
        and oracle_checks.get("model_hash_after_unchanged") is True
        and oracle_checks.get("output_ids_match_frozen_llama_cpp_oracle") is True
        and oracle_checks.get("per_token_evidence_complete") is True
    ):
        raise SystemExit("independent host oracle is not approved")

    output = fresh(ROOT / "outputs/casulo/native-boot-to-creation", "2026-08-22-np10-final")
    release = fresh(ROOT / "release", "CASULO_NATIVE_BOOT_TO_CREATION_PROOF_2026-08-22")
    public_audit = output / "public-audit.json"
    subprocess.run(
        [sys.executable, "tools/audit_public_artifact.py", "editions/casulo-public", "--output", str(public_audit)],
        cwd=ROOT,
        check=True,
        shell=False,
    )

    payload_sources = {
        "release/casulo-native-neural-port-np10-attempt-5.img": image,
        "release/casulo-native-neural-port-system-pack-np10.cspk": pack,
        "release/casulo-native-neural-port-system-pack-np10.cspk.manifest.json": pack_manifest,
        "release/START_CASULO_NATIVE_CREATION_PROOF.vbs": ROOT / "release/START_CASULO_NATIVE_CREATION_PROOF.vbs",
        "release/CASULO_NATIVE_BOOT_TO_CREATION_PROOF.ps1": ROOT / "release/CASULO_NATIVE_BOOT_TO_CREATION_PROOF.ps1",
        "os/tools/launch_native_creation_visible.py": ROOT / "os/tools/launch_native_creation_visible.py",
        "os/tools/run_native_model_paged_qemu.py": ROOT / "os/tools/run_native_model_paged_qemu.py",
        "os/tools/run_product_alpha_qemu.py": ROOT / "os/tools/run_product_alpha_qemu.py",
        "os/tools/run_qemu.py": ROOT / "os/tools/run_qemu.py",
        "README_FIRST.md": ROOT / "docs/product/NATIVE_BOOT_TO_CREATION_PROOF.md",
        "docs/product/NATIVE_BOOT_TO_CREATION_PROOF.md": ROOT / "docs/product/NATIVE_BOOT_TO_CREATION_PROOF.md",
        "docs/product/NP9_DECODER_FIDELITY_ERRATA.md": ROOT / "docs/product/NP9_DECODER_FIDELITY_ERRATA.md",
    }
    for name, source in payload_sources.items():
        destination = release / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    source_files = (
        "os/kernel/src/main.rs",
        "os/kernel/src/fw_cfg.rs",
        "os/kernel/src/memory.rs",
        "os/kernel/src/model_creation_probe.rs",
        "os/kernel/src/system_pack.rs",
        "os/native-model/src/lib.rs",
        "os/tools/build_native_neural_port_image.py",
        "os/tools/build_native_creation_pack.py",
        "os/tools/run_native_creation_qemu.py",
        "os/tools/launch_native_creation_visible.py",
        "tools/build_native_system_pack.py",
        "private/casulo-owner/t-v2/native-creation-token-policy.t",
        "private/casulo-owner/t-v2/native-creation-add.t",
        "private/casulo-owner/t-v2/native-creation-acceptance.t",
        "private/casulo-owner/native-creation-prompt.json",
        "os/Cargo.lock",
    )
    source_manifest = {
        "schema": "casulo-native-source-provenance/1.0",
        "git_commit": command_output(["git", "rev-parse", "HEAD"]),
        "worktree_dirty_preserved": True,
        "rebuild_command": "python os/tools/build_native_neural_port_image.py --stage np10 --system-pack release/casulo-native-neural-port-system-pack-np10.cspk",
        "files": [
            {"path": relative, "bytes": (ROOT / relative).stat().st_size, "sha256": sha256(ROOT / relative)}
            for relative in source_files
        ],
    }
    write_json(release / "SOURCE_PROVENANCE.json", source_manifest)

    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "Casulo-Native-Boot-to-Creation-Proof",
        "documentNamespace": f"https://teloscorp.invalid/casulo/native/{EXPECTED_IMAGE_SHA256}",
        # Reproducible release metadata: the actual seal wall clock remains in
        # append-only evidence outside the archive, never in hashed payloads.
        "creationInfo": {"created": "2026-08-22T00:00:00Z", "creators": ["Organization: Teloscorp", "Tool: seal_native_creation_proof.py"]},
        "packages": [
            {"name": "Casulo kernel, Native model runtime and T policies", "SPDXID": "SPDXRef-Casulo", "licenseConcluded": "NOASSERTION", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
            {"name": "Qwen3-4B-Q4_K_M", "SPDXID": "SPDXRef-Qwen3", "versionInfo": "bc640142c66e1fdd12af0bd68f40445458f3869b", "licenseConcluded": "Apache-2.0", "downloadLocation": "NOASSERTION", "filesAnalyzed": False, "comment": f"required from owner cache by SHA-256 {EXPECTED_MODEL_SHA256}; not redistributed"},
            {"name": "QEMU", "SPDXID": "SPDXRef-QEMU", "versionInfo": "11.0.50", "licenseConcluded": "GPL-2.0-only", "downloadLocation": "NOASSERTION", "filesAnalyzed": False, "comment": "host-only, not redistributed"},
            {"name": "rust-osdev bootloader", "SPDXID": "SPDXRef-Bootloader", "versionInfo": "0.11.15", "licenseConcluded": "MIT OR Apache-2.0", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
        ],
    }
    write_json(release / "SBOM.spdx.json", sbom)

    evidence = {
        "schema": "casulo-native-boot-to-creation-final/1.0",
        "state": STATE,
        "claim": normal_report["claim"],
        "normal_boots": 3,
        "normal_report": {"path": normal.relative_to(ROOT).as_posix(), "sha256": sha256(normal)},
        "cancellation_boots": 1,
        "cancellation_report": {"path": cancelled.relative_to(ROOT).as_posix(), "sha256": sha256(cancelled)},
        "host_oracle": {"path": host_oracle.relative_to(ROOT).as_posix(), "sha256": sha256(host_oracle)},
        "image_sha256": EXPECTED_IMAGE_SHA256,
        "model_sha256": EXPECTED_MODEL_SHA256,
        "system_pack_sha256": EXPECTED_PACK_SHA256,
        "output_text": "NOME=SomeDoisNumeros;FUNCAO=SomeDoisNumeros;ENTRADA=numero1,numero2;SAIDA=resultado.",
        "artifact_result": 18,
        "materialization_sha256": "e9442e34f04d7498de01d277d5465671128bcc9811ecebe45cee809a365c2ef4",
        "token_receipt_chain_tail": "84723086bc187d40479ec5ad631859fc662bc966841d9edc1a1d7806b1b411cf",
        "public_audit": {"path": public_audit.relative_to(ROOT).as_posix(), "sha256": sha256(public_audit)},
        "guest_network": "OFF",
        "cloud": "RELEASE_LOCKED",
        "physical_device_written": False,
        "usb_authorized": False,
        "performance_claim": False,
        "energy_claim": False,
        "signature": "DEVELOPMENT_NOT_COMMERCIAL",
    }
    write_json(output / "report.json", evidence)

    manifest_files = sorted(path for path in release.rglob("*") if path.is_file())
    manifest = {
        "schema": "casulo-native-boot-to-creation-release/1.0",
        "state": STATE,
        "owner": "Guilherme Moura Fernandes",
        "signature": "DEVELOPMENT_NOT_COMMERCIAL",
        "model_embedded": False,
        "external_api": False,
        "guest_network": "OFF",
        "physical_device_written": False,
        "files": [
            {"path": path.relative_to(release).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in manifest_files
        ],
    }
    manifest_path = release / "MANIFEST.json"
    write_json(manifest_path, manifest)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(signing_key), "-n", SIGNING_NAMESPACE, str(manifest_path)], check=True, capture_output=True, text=True, shell=False)
    signature_path = Path(str(manifest_path) + ".sig")
    allowed = release / "ALLOWED_SIGNERS"
    allowed.write_text(f"{SIGNING_IDENTITY} {public_key.read_text(encoding='utf-8').strip()}\n", encoding="utf-8", newline="\n")
    verification = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", SIGNING_IDENTITY, "-n", SIGNING_NAMESPACE, "-s", str(signature_path)],
        input=manifest_path.read_bytes(), capture_output=True, shell=False,
    )
    if verification.returncode != 0:
        raise RuntimeError("development signature verification failed")
    signature_meta = {
        "schema": "casulo.development-signature/1.0",
        "label": SIGNATURE_LABEL,
        "algorithm": "ssh-ed25519",
        "namespace": SIGNING_NAMESPACE,
        "manifest_sha256": sha256(manifest_path),
        "signature_sha256": sha256(signature_path),
        "verified": True,
    }
    write_json(release / "DEVELOPMENT_SIGNATURE.json", signature_meta)
    sums = release / "SHA256SUMS"
    sums.write_text(
        "".join(
            f"{sha256(path)}  {path.relative_to(release).as_posix()}\n"
            for path in sorted(item for item in release.rglob("*") if item.is_file() and item != sums)
        ),
        encoding="ascii",
        newline="\n",
    )

    archive = release.with_suffix(".zip")
    if archive.exists():
        raise SystemExit("append-only release archive already exists")
    zip_reproducible(release, archive)
    seal = {
        **evidence,
        "release_directory": release.relative_to(ROOT).as_posix(),
        "release_manifest_sha256": sha256(manifest_path),
        "release_signature_sha256": sha256(signature_path),
        "release_sha256sums_sha256": sha256(sums),
        "archive": archive.relative_to(ROOT).as_posix(),
        "archive_sha256": sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "free_space_bytes": shutil.disk_usage(ROOT).free,
    }
    write_json(output / "seal.json", seal)
    (output / "report.md").write_text(
        "# Casulo Native boot-to-creation proof\n\n"
        f"Estado: `{STATE}`.\n\n"
        "Três boots independentes produziram a mesma CreationSpec por inferência Qwen3-4B dentro do kernel Native. "
        "Cada token foi julgado por T antes da publicação; a fonte T content-addressed foi compilada, simulada, "
        "executada com resultado 18, materializada e aceita por T. Um quarto boot cancelado publicou somente o "
        "primeiro token e não publicou artefato nem materialização.\n\n"
        "Fronteira: prova bounded em QEMU/WHPX, CPU, greedy congelado e prompt congelado. Não é SO de uso diário, "
        "modelo frontier, benchmark de desempenho/energia, boot físico ou autorização de USB.\n",
        encoding="utf-8", newline="\n",
    )
    output_sums = output / "SHA256SUMS"
    output_sums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in sorted(item for item in output.iterdir() if item.is_file() and item != output_sums)), encoding="ascii", newline="\n")
    print(json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
