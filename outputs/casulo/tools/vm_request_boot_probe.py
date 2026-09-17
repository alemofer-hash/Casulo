from __future__ import annotations

import argparse
import hashlib
import json
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output already exists; overwrite denied")
    (output / "images").mkdir(parents=True)
    base = output / "images" / "casulo-generative-request-base.img"
    shutil.copyfile(args.source_image.resolve(strict=True), base)
    base.chmod(stat.S_IREAD)
    profile = VMProfile(
        Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe"),
        Path(r"C:\Program Files\qemu\qemu-img.exe"),
        Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd"),
        Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd"),
        base,
        output / "state",
    )
    controller = CasuloVMController(profile)
    doctor = controller.doctor()
    controller.create()
    boot = controller.boot(timeout=45)
    checks = {
        "doctor_ready": doctor["ready"],
        "casulo_native_boot": boot["passed"],
        "job_submit_capability": "OWNER_BRIDGE_CAPABILITY=guide.job.submit" in boot["serial"],
        "job_request_emitted": "OWNER_BRIDGE_REQUEST=create-owner-agent" in boot["serial"],
        "job_receipt_emitted": "OWNER_JOB_SUBMITTED=1" in boot["serial"],
        "base_immutable": boot["base_unchanged"],
        "network_denied": boot["network"] == "denied",
    }
    passed = all(checks.values())
    evidence = {
        "schema": "casulo.vm-request-boot/1.0",
        "gate": "VM_REQUEST_BOOT_PASS" if passed else "VM_REQUEST_BOOT_FAIL",
        "doctor": doctor,
        "boot": boot,
        "base_sha256": sha(base),
        "checks": checks,
        "cloud": "RELEASE_LOCKED",
        "usb": "PROHIBITED",
    }
    (output / "g7-vm-request-boot.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"gate": evidence["gate"], "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
