from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import time
from pathlib import Path

from casulo.product.vm_controller import CasuloVMController, VMProfile


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe bounded bidirectional Casulo VM serial bridge")
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output already exists; overwrite denied")
    (output / "images").mkdir(parents=True)
    base = output / "images" / "casulo-generative-bridge-base.img"
    shutil.copyfile(args.source_image.expanduser().resolve(strict=True), base)
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
    response = "x"
    if not 0 <= args.delay_seconds <= 30:
        raise SystemExit("delay outside bounded probe range")
    def provider() -> str:
        time.sleep(args.delay_seconds)
        return response
    boot = controller.bridge_boot(provider if args.delay_seconds else response, timeout=60, acceleration="tcg")
    checks = {
        "doctor_ready": doctor["ready"],
        "guest_requested_scoped_capability": boot["request_seen"],
        "host_answered_after_guest_ready": boot["response_sent"],
        "guest_received_exact_byte_count": boot["passed"],
        "base_immutable": boot["base_unchanged"],
        "network_denied": boot["network"] == "denied",
        "physical_devices_absent": boot["host_block_devices"] is False,
        "neural_claimed": False,
    }
    passed = all(value is (False if key == "neural_claimed" else True) for key, value in checks.items())
    evidence = {
        "schema": "casulo.vm-bridge-transport/1.0",
        "gate": "VM_BRIDGE_TRANSPORT_PASS" if passed else "VM_BRIDGE_TRANSPORT_FAIL",
        "purpose": "transport-only; this probe is not generative evidence",
        "delay_seconds": args.delay_seconds,
        "base_sha256": sha(base),
        "doctor": doctor,
        "boot": boot,
        "checks": checks,
        "cloud": "RELEASE_LOCKED",
        "usb": "PROHIBITED",
    }
    (output / "g7-bridge-transport.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"gate": evidence["gate"], "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
