from __future__ import annotations

import argparse
import json
from pathlib import Path

from casulo.product.vm_controller import CasuloVMController, VMProfile


def failure(operation: str, error: Exception) -> dict[str, object]:
    return {
        "schema": "casulo.vm-command-error/1.0",
        "status": "RECOVERABLE_FAILURE",
        "operation": operation,
        "error_type": type(error).__name__,
        "message": " ".join(str(error).split())[:1000],
        "overlay_preserved": True,
        "base_preserved": True,
    }


def profile(args) -> VMProfile:
    return VMProfile(
        args.qemu, args.qemu_img, args.ovmf_code, args.ovmf_vars,
        args.base, args.state_root,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo VM Controller")
    parser.add_argument("command", choices=("doctor", "create", "boot", "snapshot", "restore", "reset", "crash-probe"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--qemu", type=Path, default=Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe"))
    parser.add_argument("--qemu-img", type=Path, default=Path(r"C:\Program Files\qemu\qemu-img.exe"))
    parser.add_argument("--ovmf-code", type=Path, default=Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd"))
    parser.add_argument("--ovmf-vars", type=Path, default=Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd"))
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args()
    controller = CasuloVMController(profile(args))
    if args.command == "doctor": result = controller.doctor()
    elif args.command == "create": result = controller.create()
    elif args.command == "boot": result = controller.boot()
    elif args.command == "snapshot": result = controller.snapshot(args.name or "")
    elif args.command == "restore": result = controller.restore(args.name or "")
    elif args.command == "reset": result = controller.reset_to_snapshot(args.name or "")
    else: result = controller.crash_recovery_probe()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps(failure("vm-command", error), ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(2)
