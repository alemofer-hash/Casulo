from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

from casulo.product.vm_controller import CasuloVMController, VMProfile


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output already exists; overwrite denied")
    output.mkdir(parents=True)
    base_dir = output / "images"
    state = output / "state"
    base_dir.mkdir()
    base = base_dir / "casulo-native-base.img"
    shutil.copyfile(args.source_image.expanduser().resolve(strict=True), base)
    base.chmod(stat.S_IREAD)
    profile = VMProfile(
        Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe"),
        Path(r"C:\Program Files\qemu\qemu-img.exe"),
        Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd"),
        Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd"),
        base,
        state,
    )
    controller = CasuloVMController(profile)
    doctor = controller.doctor()
    created = controller.create()
    first_boot = controller.boot(timeout=40)
    snapshot = controller.snapshot("clean-generative-owner")
    restored = controller.restore("clean-generative-owner")
    crash = controller.crash_recovery_probe()
    second_boot = controller.boot(timeout=40)
    checks = {
        "doctor_read_only": doctor["read_only"],
        "doctor_ready": doctor["ready"],
        "qemu_and_ovmf_pinned": bool(doctor["qemu_sha256"] and doctor["ovmf_code_sha256"]),
        "base_read_only": doctor["base_os_read_only"],
        "overlay_qcow2": created["overlay_format"] == "qcow2",
        "qmp_local": created["qmp"] == "tcp-loopback-ephemeral-only",
        "network_denied": created["network"] == "denied",
        "no_physical_devices": created["physical_devices"] is False,
        "first_boot": first_boot["passed"] and first_boot["base_unchanged"],
        "snapshot_restore": snapshot["snapshot"] == restored["restored"],
        "crash_recovery": crash["process_terminated"] and crash["overlay_check_returncode"] == 0 and crash["base_unchanged"],
        "second_boot": second_boot["passed"] and second_boot["base_unchanged"],
        "external_media_used": False,
        "scientific_benchmark": False,
    }
    passed = all(value is (False if key in {"external_media_used", "scientific_benchmark"} else True) for key, value in checks.items())
    evidence = {
        "schema": "casulo.vm-lifecycle-evidence/1.0",
        "gate": "CASULO_VM_LIFECYCLE_PASS" if passed else "CASULO_VM_LIFECYCLE_FAIL",
        "doctor": doctor,
        "created": created,
        "first_boot": first_boot,
        "snapshot": snapshot,
        "restored": restored,
        "crash_recovery": crash,
        "second_boot": second_boot,
        "base_sha256": sha(base),
        "overlay_allocated_bytes": controller.overlay_path.stat().st_size,
        "checks": checks,
        "cloud": "RELEASE_LOCKED",
        "usb": "PROHIBITED",
    }
    write(output / "g6-vm-lifecycle.json", evidence)
    print(json.dumps({"gate": evidence["gate"], "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
