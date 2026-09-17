from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from run_qemu import (
    DEFAULT_CODE,
    DEFAULT_QEMU,
    DEFAULT_VARS,
    ROOT,
    boot_once,
    safe_regular_workspace_file,
)


REQUIRED_MARKERS = (
    "G1_BOOT_SMOKE=PASS",
    "G2_KERNEL_PRIMITIVES=PASS",
    "SMP_SCOPE=bounded-qemu-2vcpu",
    "SMP_MADT_VALID=PASS",
    "SMP_APS_EXPECTED=1",
    "SMP_APS_STARTED=1",
    "SMP_GATE=PASS",
    "RING3_PROCESSES=4",
    "RING3_EXIT_STATUS=42",
    "PROCESS_SEPARATE_CR3=PASS",
    "KERNEL_USER_ACCESS=DENIED",
    "USER_PAGING_BRANCH_PRIVATE=PASS",
    "USER_CODE_RX=PASS",
    "USER_STACK_NX=PASS",
    "SYSCALL_ABI=syscall-sysretq/0.1",
    "SYSCALL_COUNT=8",
    "SYSCALL_DEFINED_MASK=0x3ff",
    "SYSCALL_PERMISSION_MASK=0x7f",
    "SYSCALL_ENOSYS=PASS",
    "SYSCALL_IPC_ROUNDTRIP=PASS",
    "SYSCALL_TRACE_EVENTS=1",
    "YIELD_KERNEL_RETURNS=1",
    "RING3_PAGE_FAULT_CONTAINMENT=PASS",
    "PROCESS_ROOTS_DISTINCT=PASS",
    "PROCESS_A_PRIVATE_READ=PASS",
    "PROCESS_B_CROSS_ACCESS=DENIED",
    "USER_WATCHDOG_BUDGET_TICKS=3",
    "NON_YIELDING_PREEMPTION=PASS",
    "POST_PREEMPT_KERNEL_PROGRESS=PASS",
    "G2_FULL_GATE=PASS",
)

FORBIDDEN_MARKERS = (
    "G2_FULL_GATE=OPEN",
    "G2_FULL_GATE=FAIL",
    "SMP_APS_STARTED=0",
    "RING3_PROCESSES=0",
    "SYSCALL_ABI=unimplemented",
)


def validate(serial: str, returncode: int) -> dict[str, object]:
    missing = [marker for marker in REQUIRED_MARKERS if marker not in serial]
    forbidden = [marker for marker in FORBIDDEN_MARKERS if marker in serial]
    logical = re.search(r"^TOPOLOGY_LOGICAL_CPUS=(\d+)$", serial, re.MULTILINE)
    started = re.search(r"^SMP_APS_STARTED=(\d+)$", serial, re.MULTILINE)
    watchdog = re.search(r"^USER_WATCHDOG_ELAPSED_TICKS=(\d+)$", serial, re.MULTILINE)
    return {
        "qemu_debug_exit_success": returncode == 33,
        "missing_markers": missing,
        "forbidden_markers": forbidden,
        "logical_cpus_detected": int(logical.group(1)) if logical else 0,
        "aps_started": int(started.group(1)) if started else 0,
        "watchdog_elapsed_ticks": int(watchdog.group(1)) if watchdog else None,
        "pass": returncode == 33
        and not missing
        and not forbidden
        and logical is not None
        and int(logical.group(1)) == 2
        and started is not None
        and int(started.group(1)) == 1
        and watchdog is not None
        and 3 <= int(watchdog.group(1)) <= 5,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the complete, bounded G2 kernel gate on QEMU x86-64."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        raise SystemExit("repeat must be between 1 and 20")
    image = safe_regular_workspace_file(args.image)
    for dependency in (DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS):
        if not dependency.is_file():
            raise SystemExit(f"missing QEMU dependency: {dependency}")

    records: list[dict[str, object]] = []
    for attempt in range(1, args.repeat + 1):
        boot = boot_once(image, DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS, args.timeout)
        validation = validate(str(boot["serial"]), int(boot["returncode"]))
        records.append({"attempt": attempt, "boot": boot, "validation": validation})

    image_sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
    all_pass = all(bool(record["validation"]["pass"]) for record in records)
    summary = {
        "schema": "casulo-qemu-g2-full/0.2",
        "scope": "bounded two-vCPU QEMU x86-64 gate; SMP, ring-3 fault isolation and IRQ0 watchdog",
        "attempts": len(records),
        "passed": sum(bool(record["validation"]["pass"]) for record in records),
        "all_pass": all_pass,
        "full_g2_claimed": all_pass,
        "smp_general_machine_support_claimed": False,
        "host_block_devices_attached": False,
        "image_attached_read_only": True,
        "network_attached": False,
        "qemu_acceleration": "tcg",
        "qemu_vcpus": 2,
        "image_sha256": image_sha256,
        "required_markers": list(REQUIRED_MARKERS),
        "forbidden_markers": list(FORBIDDEN_MARKERS),
        "results": records,
    }
    evidence = ROOT / "evidence/casulo-os-rp01/g2"
    evidence.mkdir(parents=True, exist_ok=True)
    output = evidence / f"qemu-g2-full-{args.repeat}.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "results"}, indent=2
        )
    )
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
