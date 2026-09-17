from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OS_ROOT = ROOT / "os"
RELEASE = ROOT / "release"
NATIVE_TARGET = OS_ROOT / "targets/x86_64-casulo-native.json"
sys.path.insert(0, str(ROOT))
from tools.build_casulo_uefi_image import Fat32Writer  # noqa: E402
from tools.extract_casulo_uefi_bundle import FatImage  # noqa: E402
# v1/v2 are historical evidence. v3 contains the corrected Q4_K projection
# sealed by NP3/NP4 and is the only valid default for subsequent stages.
DEFAULT_PACK = RELEASE / "casulo-native-neural-port-system-pack-v3.cspk"
BOOTLOADER_SOURCE_IMAGE = RELEASE / "casulo-native-neural-port-np10-attempt-5.img"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_only_pair(stage: str) -> tuple[Path, Path]:
    attempt = 1
    while True:
        suffix = "" if attempt == 1 else f"-attempt-{attempt}"
        image = RELEASE / f"casulo-native-neural-port-{stage}{suffix}.img"
        manifest = image.with_suffix(".manifest.json")
        checksum = image.with_suffix(".img.sha256")
        if not any(path.exists() for path in (image, manifest, checksum)):
            return image, manifest
        attempt += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Build append-only Native neural-port image")
    parser.add_argument("--stage", choices=("np1", "np2", "np3", "np4", "np5", "np6", "np7", "np8", "np9", "np10", "np11"), default="np1")
    parser.add_argument("--system-pack", type=Path, default=DEFAULT_PACK)
    args = parser.parse_args()
    pack = args.system_pack.expanduser().resolve(strict=True)
    if ROOT.resolve() not in pack.parents:
        raise SystemExit("system pack must remain inside repository")
    image, manifest = append_only_pair(args.stage)
    environment = os.environ.copy()
    environment.pop("CASULO_GENERATIVE_BRIDGE", None)
    environment.pop("CASULO_NATIVE_INTERACTIVE", None)
    environment.pop("RUSTFLAGS", None)
    environment["RUST_TARGET_PATH"] = str(NATIVE_TARGET.parent)
    environment["RUSTFLAGS"] = "-Zunstable-options"
    environment["CASULO_TCAP_RAMDISK"] = str(pack)
    environment["CASULO_NATIVE_MODEL_PROBE"] = "1"
    environment["CASULO_NATIVE_MODEL_PAGED_IO"] = "1" if args.stage in ("np4", "np5", "np6", "np7", "np8", "np9", "np10", "np11") else "0"
    environment["CASULO_NATIVE_TOKENIZER_EMBEDDING"] = "1" if args.stage in ("np5", "np6", "np7", "np8", "np9", "np10", "np11") else "0"
    environment["CASULO_NATIVE_MODEL_BLOCK0"] = "1" if args.stage == "np6" else "0"
    environment["CASULO_NATIVE_MODEL_DECODER"] = "1" if args.stage in ("np7", "np8", "np9", "np10", "np11") else "0"
    environment["CASULO_NATIVE_MODEL_SAMPLING"] = "1" if args.stage in ("np8", "np9", "np10", "np11") else "0"
    environment["CASULO_NATIVE_MODEL_RESIDENT"] = "1" if args.stage in ("np9", "np10", "np11") else "0"
    environment["CASULO_NATIVE_CREATION"] = "1" if args.stage in ("np10", "np11") else "0"
    cargo_command = ["cargo", "run", "--release", "--locked", "--offline"]
    if args.stage in ("np9", "np10", "np11"):
        subprocess.run(
            [
                "cargo",
                "build",
                "--release",
                "--locked",
                "-p",
                "casulo-kernel",
                "--target",
                "x86_64-casulo-native",
                "-Z",
                "build-std=core,alloc,compiler_builtins",
                "-Z",
                "build-std-features=compiler-builtins-mem",
            ],
            cwd=OS_ROOT,
            env=environment,
            check=True,
        )
        kernel = OS_ROOT / "target/x86_64-casulo-native/release/casulo-kernel"
        if not kernel.is_file():
            raise RuntimeError(f"prebuilt Native kernel missing: {kernel}")
        environment["CASULO_PREBUILT_KERNEL"] = str(kernel)
        cargo_command.append("--no-default-features")
    RELEASE.mkdir(parents=True, exist_ok=True)
    if args.stage == "np11":
        if not BOOTLOADER_SOURCE_IMAGE.is_file():
            raise RuntimeError(f"sealed NP10 bootloader source missing: {BOOTLOADER_SOURCE_IMAGE}")
        kernel = OS_ROOT / "target/x86_64-casulo-native/release/casulo-kernel"
        temporary_parent = ROOT / ".tmp"
        temporary_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="casulo-np11-image-", dir=temporary_parent) as temporary:
            temp_root = Path(temporary)
            bootloader = temp_root / "CasuloX64.efi"
            reader = FatImage(BOOTLOADER_SOURCE_IMAGE)
            try:
                reader.extract("efi/boot/bootx64.efi", bootloader)
            finally:
                reader.close()
            generated = temp_root / "casulo-native-np11.img"
            Fat32Writer(
                generated,
                {"bootx64": bootloader, "kernel": kernel, "ramdisk": pack},
            ).build()
            generated.replace(image)
    else:
        result = subprocess.run(
            cargo_command,
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
        shutil.copyfile(generated, image)
    digest = sha256(image)
    record = {
        "schema": "casulo-native-neural-port-image/0.1",
        "stage": {
            "np1": "NP1_AUTHENTIC_Q4_K_WEIGHT_PROBE",
            "np2": "NP2_ALL_MODEL_WEIGHT_FORMATS_PROBE_SUPERSEDED_Q4_K",
            "np3": "NP3_CORRECTED_ALL_MODEL_WEIGHT_FORMATS_PROBE",
            "np4": "NP4_COMPLETE_MODEL_PAGED_IO",
            "np5": "NP5_BOUNDED_TOKENIZER_AND_Q6_K_EMBEDDING",
            "np6": "NP6_ONE_COMPLETE_QWEN3_TRANSFORMER_BLOCK",
            "np7": "NP7_COMPLETE_QWEN3_DECODER_TO_LOGITS",
            "np8": "NP8_FIRST_T_AUTHORIZED_MODEL_TOKEN",
            "np9": "NP9_RESIDENT_INCREMENTAL_MODEL_RUNTIME",
            "np10": "NP10_NATIVE_BOOT_TO_CREATION",
            "np11": "NP11_PHYSICAL_RAMDISK_MODEL_TRANSPORT",
        }[args.stage],
        "image": image.relative_to(ROOT).as_posix(),
        "bytes": image.stat().st_size,
        "sha256": digest,
        "system_pack": pack.relative_to(ROOT).as_posix(),
        "system_pack_sha256": sha256(pack),
        "target": "x86_64-casulo-native",
        "target_spec": NATIVE_TARGET.relative_to(ROOT).as_posix(),
        "target_spec_sha256": sha256(NATIVE_TARGET),
        "host_bridge": False,
        "network": False,
        "physical_device_written": False,
        "full_model_mapped": args.stage == "np11",
        "first_model_derived_token": args.stage in ("np8", "np9", "np10", "np11"),
        "full_model_resident_after_admission": args.stage in ("np9", "np10", "np11"),
        "kernel_float_profile": "sse2-hardware-f32" if args.stage in ("np9", "np10", "np11") else "stock-target",
        "claim": {
            "np1": "authentic adopted-model Q4_K block parsed and executed in Native; not decoder inference",
            "np2": "authentic adopted-model F32/Q4_K/Q6_K samples parsed and executed in Native; Q4_K result superseded by NP3",
            "np3": "authentic adopted-model F32/Q4_K/Q6_K samples parsed and executed in Native; not decoder inference",
            "np4": "complete adopted model exposed read-only and accessed sparsely in Native; not decoder inference",
            "np5": "bounded ordinary-text tokenization and one authentic Q6_K embedding row executed in Native; no transformer/logits/output token",
            "np6": "one authentic token position executed through complete Qwen3 block zero and compared at 19 stages; no later block/logits/output token",
            "np7": "one authentic token position executed through all 36 Qwen3 blocks, output normalization and tied logits projection; candidate verified but not sampled or published",
            "np8": "one authentic model-derived token published only after the compiled T/2.0 greedy-debug policy consumed the complete decoder receipt",
            "np9": "the admitted adopted model is resident in guest-owned RAM so incremental Native decoding can avoid fw_cfg I/O in the hot path; mult-token proof is a separate gate",
            "np10": "bounded natural-language request is decoded by the adopted model, judged token-by-token by T, mapped to a content-addressed compiled T artifact, simulated, materialized and projected in Native",
            "np11": "the exact adopted owner model is validated from the UEFI ramdisk and drives the NP10 creation path without QEMU fw_cfg or a host filesystem",
        }[args.stage],
    }
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    image.with_suffix(".img.sha256").write_text(f"{digest}  {image.name}\n", encoding="ascii")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
