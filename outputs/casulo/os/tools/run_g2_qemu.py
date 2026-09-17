from __future__ import annotations

import argparse
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
    "PAGING=active",
    "HEAP_ALLOC=PASS",
    "HEAP_KERNEL_ONLY=PASS",
    "GUARD_PAGE_UNMAPPED=PASS",
    "GDT_IDT=loaded",
    "TIMER_SOURCE=8254_PIT_IRQ0",
    "WATCHDOG_CONTRACT=PASS",
    "GUARD_FAULT_CONTAINMENT=PASS",
    "G2_KERNEL_PRIMITIVES=PASS",
    "G2_FULL_GATE=OPEN",
    "SMP_APS_STARTED=0",
    "RING3_PROCESSES=0",
    "SYSCALL_ABI=unimplemented",
)


def validate(serial: str) -> dict[str, object]:
    missing = [marker for marker in REQUIRED_MARKERS if marker not in serial]
    logical_match = re.search(r"^TOPOLOGY_LOGICAL_CPUS=(\d+)$", serial, re.MULTILINE)
    tick_match = re.search(r"^TIMER_TICKS=(\d+)$", serial, re.MULTILINE)
    fault_match = re.search(r"^FAULTS_CONTAINED=(\d+)$", serial, re.MULTILINE)
    logical = int(logical_match.group(1)) if logical_match else 0
    ticks = int(tick_match.group(1)) if tick_match else 0
    faults = int(fault_match.group(1)) if fault_match else 0
    return {
        "missing_markers": missing,
        "logical_cpus_detected": logical,
        "timer_ticks": ticks,
        "faults_contained": faults,
        "pass": not missing and logical >= 2 and ticks >= 3 and faults == 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Boot and validate incremental G2 kernel primitives without host disks."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        raise SystemExit("repeat must be between 1 and 20")
    image = safe_regular_workspace_file(args.image)
    for dependency in (DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS):
        if not dependency.is_file():
            raise SystemExit(f"missing QEMU dependency: {dependency}")

    records: list[dict[str, object]] = []
    for _ in range(args.repeat):
        boot = boot_once(image, DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS, args.timeout)
        validation = validate(str(boot["serial"]))
        records.append({"boot": boot, "validation": validation})

    summary = {
        "schema": "casulo-qemu-g2-primitives/0.1",
        "scope": "incremental kernel primitives; not full G2",
        "attempts": len(records),
        "passed": sum(bool(record["validation"]["pass"]) for record in records),
        "all_pass": all(bool(record["validation"]["pass"]) for record in records),
        "host_block_devices_attached": False,
        "image_attached_read_only": True,
        "full_g2_claimed": False,
        "open_requirements": ["AP startup/SMP", "ring-3 process", "syscall ABI", "separate address spaces"],
        "results": records,
    }
    evidence = ROOT / "evidence/casulo-os-rp01/g2"
    evidence.mkdir(parents=True, exist_ok=True)
    # Preserve the original incremental-gate evidence after the full G2 serial
    # contract supersedes these deliberately OPEN markers.
    output = evidence / f"qemu-g2-incremental-legacy-run-{args.repeat}.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
