from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, boot_once, safe_regular_workspace_file


def validate_panic(serial: str, returncode: int) -> dict[str, object]:
    required = (
        "PANIC_PROBE=TRIGGERED",
        "CASULO_PANIC_DUMP",
        "PANIC_SCHEMA=casulo-panic-dump/0.1",
        "PANIC_KIND=intentional-probe",
        "PANIC_ACTION=isa-debug-exit-failure",
    )
    forbidden = ("G1_BOOT_SMOKE=PASS", "G7_DEMO_COMPLETE=PASS")
    missing = [marker for marker in required if marker not in serial]
    observed_forbidden = [marker for marker in forbidden if marker in serial]
    return {
        "expected_debug_exit_failure": returncode == 35,
        "missing_markers": missing,
        "forbidden_markers": observed_forbidden,
        "pass": returncode == 35 and not missing and not observed_forbidden,
    }


def validate_reboot(serial: str, returncode: int, timed_out: bool) -> dict[str, object]:
    requested = "REBOOT_PROBE=REQUESTED" in serial
    returned = "REBOOT_PROBE=RETURNED" in serial
    return {
        "request_marker": requested,
        "request_returned_unexpectedly": returned,
        "qemu_no_reboot_exit": returncode == 0,
        "timed_out": timed_out,
        "pass": requested and not returned and returncode == 0 and not timed_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated panic and reboot QEMU probes.")
    parser.add_argument("--panic-image", type=Path, required=True)
    parser.add_argument("--reboot-image", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    panic_image = safe_regular_workspace_file(args.panic_image)
    reboot_image = safe_regular_workspace_file(args.reboot_image)
    for dependency in (DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS):
        if not dependency.is_file():
            raise SystemExit(f"missing QEMU dependency: {dependency}")
    panic_boot = boot_once(panic_image, DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS, args.timeout)
    reboot_boot = boot_once(reboot_image, DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS, args.timeout)
    panic_check = validate_panic(str(panic_boot["serial"]), int(panic_boot["returncode"]))
    reboot_check = validate_reboot(
        str(reboot_boot["serial"]),
        int(reboot_boot["returncode"]),
        bool(reboot_boot["timed_out"]),
    )
    passed = bool(panic_check["pass"]) and bool(reboot_check["pass"])
    summary = {
        "schema": "casulo-qemu-platform-probes/0.1",
        "all_pass": passed,
        "panic": {
            "image_sha256": hashlib.sha256(panic_image.read_bytes()).hexdigest(),
            "boot": panic_boot,
            "validation": panic_check,
        },
        "reboot": {
            "image_sha256": hashlib.sha256(reboot_image.read_bytes()).hexdigest(),
            "boot": reboot_boot,
            "validation": reboot_check,
        },
        "normal_release_image_modified": False,
        "host_block_devices_attached": False,
        "image_attached_read_only": True,
        "network_attached": False,
        "qemu_acceleration": "tcg",
    }
    output = ROOT / "evidence/casulo-os-rp01/g2/platform-probes/qemu-platform-probes.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": summary["schema"],
                "all_pass": passed,
                "panic_validation": panic_check,
                "reboot_validation": reboot_check,
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
