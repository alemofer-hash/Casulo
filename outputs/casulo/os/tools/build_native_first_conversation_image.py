from __future__ import annotations

import hashlib
import json
import os
import argparse
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OS_ROOT = ROOT / "os"
RELEASE = ROOT / "release"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_only_artifact(stage: str) -> tuple[Path, Path]:
    """Return a fresh image/manifest pair without replacing prior evidence."""
    base = f"casulo-native-first-conversation-{stage}"
    attempt = 1
    while True:
        suffix = "" if attempt == 1 else f"-attempt-{attempt}"
        image = RELEASE / f"{base}{suffix}.img"
        manifest = RELEASE / f"{base}{suffix}.manifest.json"
        checksum = image.with_suffix(image.suffix + ".sha256")
        if not image.exists() and not manifest.exists() and not checksum.exists():
            return image, manifest
        attempt += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an append-only Casulo Native First Conversation image")
    parser.add_argument(
        "--stage",
        choices=("nf1", "nf2", "nf3", "nf4", "nf5", "nf6", "nf7", "nf8"),
        default="nf1",
    )
    args = parser.parse_args()
    image, manifest = append_only_artifact(args.stage)
    environment = os.environ.copy()
    environment.pop("CASULO_GENERATIVE_BRIDGE", None)
    environment.pop("CASULO_NATIVE_INTERACTIVE", None)
    if args.stage in {"nf5", "nf6", "nf7", "nf8"}:
        system_pack = RELEASE / "casulo-native-first-conversation-system-pack-v1.cspk"
        if not system_pack.is_file():
            raise RuntimeError(f"NF5+ system pack missing: {system_pack}")
        environment["CASULO_TCAP_RAMDISK"] = str(system_pack)
    if args.stage == "nf8":
        environment["CASULO_NATIVE_INTERACTIVE"] = "1"
    result = subprocess.run(
        ["cargo", "run", "--release", "--locked", "--offline"],
        cwd=OS_ROOT,
        env=environment,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
    )
    generated = Path(result.stdout.strip().splitlines()[-1]).resolve()
    if not generated.is_file() or OS_ROOT.resolve() not in generated.parents:
        raise RuntimeError(f"unsafe or missing generated image: {generated}")
    RELEASE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(generated, image)
    digest = sha256(image)
    stage_name = {
        "nf1": "NF1_PRESENTATION_CORE",
        "nf2": "NF2_GOP_RENDERER",
        "nf3": "NF3_NATIVE_INFERENCE_ABI",
        "nf4": "NF4_NATIVE_NEURAL_TOKEN",
        "nf5": "NF5_T_SYSTEM_PACK",
        "nf6": "NF6_PERSISTENCE_CONTRACT",
        "nf7": "NF7_QEMU_VIRTUAL_MEDIA",
        "nf8": "NF8_OWNER_ALPHA_FLASHABLE",
    }[args.stage]
    claim = {
        "nf1": "bounded presentation projection booted; no native neural inference",
        "nf2": "receipt-driven GOP renderer and bounded input decoder booted; no native neural inference",
        "nf3": "ring-3 neural capability ABI exercised with zero model bytes; no native neural inference",
        "nf4": "reserved for a real model-derived token; builder label alone is never proof",
        "nf5": "content-addressed system pack booted; guide T source present but not executed; no native neural inference",
        "nf6": "persistence contract gate only; no unsupported physical storage claim",
        "nf7": "virtual-media validation only; no physical device written",
        "nf8": "flashable owner-alpha preview; neural conversation remains blocked until NF4",
    }[args.stage]
    record = {
        "schema": "casulo-native-first-conversation-image/0.1",
        "stage": stage_name,
        "image": image.relative_to(ROOT).as_posix(),
        "bytes": image.stat().st_size,
        "sha256": digest,
        "bootloader": "rust-osdev-bootloader/0.11.15",
        "target": "x86_64-unknown-none",
        "ux_contract_sha256": "4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9",
        "scene_contract_sha256": "804ceb12b510f250cfd41a6e49185fe8db73f13c09a7f3288703368889435a8d",
        "host_bridge": False,
        "network": False,
        "physical_device_written": False,
        "historical_image_overwritten": False,
        "claim": claim,
    }
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (image.with_suffix(image.suffix + ".sha256")).write_text(
        f"{digest}  {image.name}\n", encoding="ascii"
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
