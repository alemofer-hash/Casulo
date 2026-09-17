from __future__ import annotations

import argparse
import json
from pathlib import Path

from casulo.product.vm_controller import CasuloVMController, VMProfile

try:
    from tools.casulo_owner_vm_inspect import QEMU, QEMU_IMG, OVMF_CODE, OVMF_VARS
except ModuleNotFoundError:
    from casulo_owner_vm_inspect import QEMU, QEMU_IMG, OVMF_CODE, OVMF_VARS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    controller = CasuloVMController(
        VMProfile(QEMU, QEMU_IMG, OVMF_CODE, OVMF_VARS, args.base.resolve(strict=True), args.state.resolve())
    )
    created = controller.create()
    boot_before = controller.bridge_boot("einstein-local-solver-before-snapshot", acceleration="tcg", timeout=60)
    snapshotted = controller.snapshot("einstein-solver-clean")
    boot_after_snapshot = controller.bridge_boot("einstein-local-solver-after-snapshot", acceleration="tcg", timeout=60)
    restored = controller.restore("einstein-solver-clean")
    boot_after_restore = controller.bridge_boot("einstein-local-solver-after-restore", acceleration="tcg", timeout=60)
    payload = {
        "schema": "casulo.einstein-vm-restore-probe/1.0",
        "created": created,
        "snapshot": snapshotted,
        "restore": restored,
        "snapshots_after": list(controller.snapshots()),
        "boot_before": boot_before,
        "boot_after_snapshot": boot_after_snapshot,
        "boot_after_restore": boot_after_restore,
        "passed": all(item["passed"] for item in (boot_before, boot_after_snapshot, boot_after_restore)),
        "base_unchanged": all(item["base_unchanged"] for item in (boot_before, boot_after_snapshot, boot_after_restore)),
        "network": "DENIED",
        "usb": "PROHIBITED",
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"passed": payload["passed"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if payload["passed"] and payload["base_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
