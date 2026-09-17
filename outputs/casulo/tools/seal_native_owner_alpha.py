from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNATURE_LABEL = "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE"
NAMESPACE = "casulo-native-owner-alpha"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fresh_directory(parent: Path, name: str) -> Path:
    attempt = 1
    while True:
        suffix = "" if attempt == 1 else f"-attempt-{attempt}"
        candidate = parent / f"{name}{suffix}"
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate
        attempt += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal append-only Casulo Native owner-alpha preview")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--output-parent", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    key = args.signing_key.resolve(strict=True)
    public_key = key.with_suffix(key.suffix + ".pub")
    if ROOT.resolve() not in image.parents or not public_key.is_file():
        raise SystemExit("image must be in repository and signing public key must exist")
    output_parent = args.output_parent.resolve()
    if ROOT.resolve() not in output_parent.parents and output_parent != ROOT.resolve():
        raise SystemExit("output must remain inside repository")
    output = fresh_directory(output_parent, "CASULO_NATIVE_OWNER_ALPHA_PREVIEW_2026-08-20")
    sealed_image = output / "casulo-native-owner-alpha-preview.img"
    shutil.copyfile(image, sealed_image)
    source_hash = sha256(image)
    if sha256(sealed_image) != source_hash:
        raise RuntimeError("sealed image copy hash mismatch")

    readme = output / "README_FIRST.md"
    readme.write_text(
        "# Casulo Native owner-alpha preview\n\n"
        "Este artefato UEFI passou três boots como USB virtual read-only. Ele contém "
        "renderer Stark + Jobs, decoder limitado, TCAP, system pack, ABI neural e journal.\n\n"
        "**Não é ainda a primeira conversa Native.** O Qwen não executou: o runtime local "
        "é PE/COFF Windows e o loader/grafo freestanding não existe. Não apresente o evento "
        "de token do ABI como inferência neural.\n\n"
        "Nenhuma mídia física foi gravada. A seleção do pendrive e a confirmação destrutiva "
        "pertencem a um gate humano posterior.\n",
        encoding="utf-8",
    )
    launcher = output / "START_PREVIEW_QEMU.ps1"
    launcher.write_text(
        r'''$ErrorActionPreference = "Stop"
$bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$image = Join-Path $bundle "casulo-native-owner-alpha-preview.img"
$qemu = "C:\Program Files\qemu\qemu-system-x86_64.exe"
$ovmfCode = "C:\Program Files\qemu\share\edk2-x86_64-code.fd"
$ovmfTemplate = "C:\Program Files\qemu\share\edk2-i386-vars.fd"
foreach ($dependency in @($image, $qemu, $ovmfCode, $ovmfTemplate)) {
  if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) { throw "Dependencia ausente: $dependency" }
}
$session = Join-Path $env:LOCALAPPDATA ("Casulo\native-preview\" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $session | Out-Null
$ovmfVars = Join-Path $session "OVMF_VARS.fd"
$serial = Join-Path $session "serial.log"
Copy-Item -LiteralPath $ovmfTemplate -Destination $ovmfVars
$qemuArgs = @(
  "-machine", "q35,accel=tcg", "-m", "256M", "-smp", "2",
  "-nic", "none", "-no-reboot", "-boot", "order=c,strict=on",
  "-device", "VGA",
  "-drive", "if=pflash,format=raw,unit=0,readonly=on,file=$ovmfCode",
  "-drive", "if=pflash,format=raw,unit=1,file=$ovmfVars",
  "-device", "qemu-xhci,id=casulo-xhci",
  "-drive", "if=none,id=casulo-usb,format=raw,readonly=on,file=$image",
  "-device", "usb-storage,bus=casulo-xhci.0,drive=casulo-usb,removable=true",
  "-serial", "file:$serial", "-monitor", "none"
)
Write-Host "Casulo Native preview: $image"
Write-Host "Serial append-only desta sessao: $serial"
Write-Host "Limite atual: superficie visual; sem conversa neural Native."
& $qemu @qemuArgs
''',
        encoding="utf-8",
    )
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "Casulo-Native-Owner-Alpha-Preview",
        "documentNamespace": f"https://teloscorp.invalid/casulo/native/{source_hash}",
        "creationInfo": {
            "created": datetime.now(timezone.utc).isoformat(),
            "creators": ["Organization: Teloscorp", "Tool: seal_native_owner_alpha.py"],
        },
        "packages": [
            {"name": "Casulo kernel and presentation core", "SPDXID": "SPDXRef-Casulo", "licenseConcluded": "NOASSERTION", "downloadLocation": "NOASSERTION", "filesAnalyzed": False},
            {"name": "rust-osdev bootloader", "SPDXID": "SPDXRef-Bootloader", "licenseConcluded": "MIT OR Apache-2.0", "downloadLocation": "NOASSERTION", "versionInfo": "0.11.15", "filesAnalyzed": False},
            {"name": "sha2 crate", "SPDXID": "SPDXRef-Sha2", "licenseConcluded": "MIT OR Apache-2.0", "downloadLocation": "NOASSERTION", "versionInfo": "0.10.9", "filesAnalyzed": False},
            {"name": "Qwen3-4B Q4_K_M reference", "SPDXID": "SPDXRef-Qwen", "licenseConcluded": "Apache-2.0", "downloadLocation": "NOASSERTION", "filesAnalyzed": False, "comment": "not embedded and not executed by this image"},
            {"name": "llama.cpp b10362 reference", "SPDXID": "SPDXRef-LlamaCpp", "licenseConcluded": "MIT", "downloadLocation": "NOASSERTION", "filesAnalyzed": False, "comment": "Windows runtime not embedded"},
        ],
    }
    sbom_path = output / "SBOM.spdx.json"
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence = ROOT / "outputs/casulo/native-first-conversation/2026-08-20-nf8/interactive-preview-3boots.json"
    manifest = {
        "schema": "casulo-native-owner-alpha-preview/0.1",
        "state": "FLASHABLE_PREVIEW_NOT_CONVERSATIONAL",
        "owner": "Guilherme Moura Fernandes",
        "signature": "DEVELOPMENT_NOT_COMMERCIAL",
        "image": {"file": sealed_image.name, "bytes": sealed_image.stat().st_size, "sha256": source_hash},
        "virtual_usb_gate": {"path": evidence.relative_to(ROOT).as_posix(), "sha256": sha256(evidence), "boots": 3, "passed": True},
        "system_pack": {"sha256": "9af383a88b06d4365cbf526e55243cad4ff0b8e1ba173e3869d28a35ee9c344a", "embedded": True},
        "native_neural_inference": "BLOCKED_NATIVE_QWEN_RUNTIME_PORT",
        "first_model_derived_token": False,
        "model_embedded": False,
        "guest_network_default": "OFF",
        "cloud": "RELEASE_LOCKED",
        "physical_device_written": False,
        "usb_write_authorized": False,
        "files": [
            {"path": readme.name, "bytes": readme.stat().st_size, "sha256": sha256(readme)},
            {"path": launcher.name, "bytes": launcher.stat().st_size, "sha256": sha256(launcher)},
            {"path": sbom_path.name, "bytes": sbom_path.stat().st_size, "sha256": sha256(sbom_path)},
            {"path": sealed_image.name, "bytes": sealed_image.stat().st_size, "sha256": source_hash},
        ],
    }
    manifest_path = output / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    signature_path = output / "MANIFEST.json.sig"
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", NAMESPACE, str(manifest_path)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    generated = Path(str(manifest_path) + ".sig")
    if generated != signature_path and generated.is_file():
        shutil.move(generated, signature_path)
    allowed = output / "allowed_signers"
    allowed.write_text(f"casulo-native-owner-alpha {public_key.read_text(encoding='utf-8').strip()}\n", encoding="utf-8")
    verification = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", "casulo-native-owner-alpha", "-n", NAMESPACE, "-s", str(signature_path)],
        input=manifest_path.read_text(encoding="utf-8"), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if verification.returncode != 0:
        raise RuntimeError(f"development signature verification failed: {verification.stdout}")
    signature_metadata = {
        "schema": "casulo.development-signature/1.0",
        "label": SIGNATURE_LABEL,
        "algorithm": "ssh-ed25519",
        "namespace": NAMESPACE,
        "manifest_sha256": sha256(manifest_path),
        "signature_sha256": sha256(signature_path),
        "verified": True,
    }
    signature_metadata_path = output / "DEVELOPMENT_SIGNATURE.json"
    signature_metadata_path.write_text(json.dumps(signature_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums = output / "SHA256SUMS"
    files = sorted(path for path in output.iterdir() if path.is_file() and path != sums)
    sums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in files), encoding="ascii")
    result = {
        "state": manifest["state"],
        "directory": output.relative_to(ROOT).as_posix(),
        "image_sha256": source_hash,
        "manifest_sha256": sha256(manifest_path),
        "signature": SIGNATURE_LABEL,
        "signature_verified": True,
        "physical_device_written": False,
        "first_model_derived_token": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
