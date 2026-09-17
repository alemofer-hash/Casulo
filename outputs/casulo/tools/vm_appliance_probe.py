from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-image", type=Path)
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output.resolve()
    if output.exists():
        raise SystemExit("output exists; overwrite denied")
    sys.path.insert(0, str(repo / "src"))
    from casulo.product.vm_controller import CasuloVMController, VMControllerError, VMProfile

    qemu = Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe")
    qemu_img = Path(r"C:\Program Files\qemu\qemu-img.exe")
    code = Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd")
    variables = Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd")
    base = args.source_image.resolve(strict=True) if args.source_image else repo / "release/casulo-native-generative-interactive.img"
    output.mkdir(parents=True)
    controller = CasuloVMController(VMProfile(qemu, qemu_img, code, variables, base, output / "state"))
    doctor_before = controller.doctor()
    base_before = hashlib.sha256(base.read_bytes()).hexdigest()
    controller.create()
    missing_restore = None
    try:
        controller.restore("owner-live")
    except VMControllerError as error:
        missing_restore = {"recoverable": True, "message": str(error), "overlay_preserved": controller.overlay_path.is_file()}
    clean = controller.snapshot("clean-owner")
    cycles = [controller.bridge_boot(f"owner-appliance-cycle-{index}", acceleration="tcg", timeout=60) for index in range(1, 4)]
    live = controller.snapshot("owner-live")
    restored = controller.restore("owner-live")
    crash = controller.crash_recovery_probe()
    base_after = hashlib.sha256(base.read_bytes()).hexdigest()
    checks = {
        "doctor": doctor_before["ready"] is True,
        "missing_restore_recoverable": bool(missing_restore and missing_restore["recoverable"]),
        "three_cycles": len(cycles) == 3 and all(item["passed"] for item in cycles),
        "base_immutable": base_before == base_after and all(item["base_unchanged"] for item in cycles),
        "network_denied": all(item["network"] == "denied" for item in cycles),
        "block_devices_absent": all(item["host_block_devices"] is False for item in cycles),
        "snapshots_distinct": clean["snapshot"] == "clean-owner" and live["snapshot"] == "owner-live",
        "restore": restored["restored"] == "owner-live",
        "crash_recovery": crash["process_terminated"] and crash["overlay_check_returncode"] == 0 and crash["base_unchanged"],
    }
    report = {
        "schema": "casulo.vm-appliance-probe/1.0",
        "gate": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "doctor": doctor_before,
        "missing_restore": missing_restore,
        "clean_snapshot": clean,
        "live_snapshot": live,
        "restore": restored,
        "cycles": cycles,
        "crash": crash,
        "base_sha256_before": base_before,
        "base_sha256_after": base_after,
        "guest_network_default": "OFF",
        "usb_block_devices": "PROHIBITED",
    }
    write_json(output / "vm-appliance-probe.json", report)
    print(json.dumps({"gate": report["gate"], "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if report["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
