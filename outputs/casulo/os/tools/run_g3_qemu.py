from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from run_qemu import (
    DEFAULT_CODE,
    DEFAULT_QEMU,
    DEFAULT_VARS,
    ROOT,
    boot_once,
    safe_regular_workspace_file,
)


REQUIRED = (
    "G1_BOOT_SMOKE=PASS",
    "G2_FULL_GATE=PASS",
    "TCAP_HEADER_VERSION=1.0",
    "TCAP_TARGET=x86_64-casulo-none",
    "TCAP_ABI=casulo-learn-context-sysv64/0.1",
    "TCAP_VALIDATION=PASS",
    "TCAP_ARTIFACT=FloodSurrogate.tcap",
    "TCAP_RESOURCE_CEILINGS=PASS",
    "TCAP_SSE2_STATE=PASS",
    "TCAP_CODE_RX=PASS",
    "TCAP_DATA_RW_NX=PASS",
    "TCAP_STACK_RW_NX=PASS",
    "TCAP_RING3_EXIT_STATUS=0",
    "TCAP_RING3_SYSCALLS=1",
    "TCAP_SYSCALL_PERMISSION_MASK=0x3",
    "TCAP_PERMISSION_DENIED_SYSCALLS=1",
    "TCAP_PERMISSION_AUDIT_EVENTS=1",
    "TCAP_PERMISSION_NEGATIVE=PASS",
    "TCAP_EPOCHS=400",
    "TCAP_RECORDS=8",
    "TCAP_NUMERICAL_EQUIVALENCE=PASS",
    "TCAP_CORRUPTION=QUARANTINE_EXECUTION_COUNT_0:PASS",
    "TCAP_PERFORMANCE_CLAIM=NONE",
    "FLOOD_SURROGATE_EXECUTION=PASS",
    "FLOOD_SURROGATE_EXIT_STATUS=0",
    "TCAP_CORRUPT_RESULT=QUARANTINE",
    "TCAP_CORRUPT_EXECUTED=0",
    "G3_TCAP_GATE=PASS",
    "G7_DEMO_PAYLOAD_GATE=PASS",
)

FORBIDDEN = (
    "CASULO_PANIC_DUMP",
    "CASULO_KERNEL_FATAL",
    "UNCONTAINED_PAGE_FAULT",
    "TCAP_VALIDATION=QUARANTINE",
    "G2_FULL_GATE=FAIL",
    "G3_TCAP_GATE=FAIL",
)


def validate(serial: str, returncode: int, tcap_sha256: str) -> dict[str, object]:
    expected_hash_marker = f"TCAP_HASH_SHA256={tcap_sha256}"
    missing = [marker for marker in (*REQUIRED, expected_hash_marker) if marker not in serial]
    forbidden = [marker for marker in FORBIDDEN if marker in serial]
    return {
        "qemu_debug_exit_success": returncode == 33,
        "missing_markers": missing,
        "forbidden_markers": forbidden,
        "tcap_sha256_matches_ramdisk": expected_hash_marker in serial,
        "pass": returncode == 33 and not missing and not forbidden,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict G3 TCAP validation, isolation and numerical canary gate."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--tcap", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        raise SystemExit("repeat must be between 1 and 20")
    image = safe_regular_workspace_file(args.image)
    tcap = safe_regular_workspace_file(args.tcap)
    for dependency in (DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS):
        if not dependency.is_file():
            raise SystemExit(f"missing QEMU dependency: {dependency}")
    tcap_sha256 = hashlib.sha256(tcap.read_bytes()).hexdigest()
    records: list[dict[str, object]] = []
    for attempt in range(1, args.repeat + 1):
        boot = boot_once(image, DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS, args.timeout)
        check = validate(str(boot["serial"]), int(boot["returncode"]), tcap_sha256)
        records.append({"attempt": attempt, "boot": boot, "validation": check})
    all_pass = all(bool(record["validation"]["pass"]) for record in records)
    summary = {
        "schema": "casulo-qemu-g3-tcap/0.1",
        "scope": "bounded correctness only: TCAP fail-closed loader plus 8-record/400-epoch ring-3 canary",
        "attempts": len(records),
        "passed": sum(bool(record["validation"]["pass"]) for record in records),
        "all_pass": all_pass,
        "performance_claimed": False,
        "energy_measured": False,
        "host_block_devices_attached": False,
        "image_attached_read_only": True,
        "network_attached": False,
        "qemu_acceleration": "tcg",
        "qemu_vcpus": 2,
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "tcap_sha256": tcap_sha256,
        "required_markers": list(REQUIRED),
        "forbidden_markers": list(FORBIDDEN),
        "results": records,
    }
    evidence = ROOT / "evidence/casulo-os-rp01/g3"
    evidence.mkdir(parents=True, exist_ok=True)
    output = evidence / f"qemu-tcap-ring3-{args.repeat}.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
