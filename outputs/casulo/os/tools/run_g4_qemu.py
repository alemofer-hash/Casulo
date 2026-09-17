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


REFERENCE = "c76b1fd397b2a5e84fc6443c027e3d9545ee9dca78f005dfb5c8c962035ae766"
REQUIRED = (
    "G1_BOOT_SMOKE=PASS",
    "G2_FULL_GATE=PASS",
    "RING3_PAGE_FAULT_CONTAINMENT=PASS",
    "PROCESS_ROOTS_DISTINCT=PASS",
    "PROCESS_A_PRIVATE_READ=PASS",
    "PROCESS_B_CROSS_ACCESS=DENIED",
    "USER_WATCHDOG_BUDGET_TICKS=3",
    "NON_YIELDING_PREEMPTION=PASS",
    "POST_PREEMPT_KERNEL_PROGRESS=PASS",
    "G3_TCAP_GATE=PASS",
    "CASULO_G4_POLICY_ID=semantic_v1",
    "CASULO_G4_HARD_GATES=integrity,permissions,quality,isolation",
    "CASULO_G4_AUDIT_BOUND_TICKS=4",
    "CASULO_G4_QUARANTINE_DISPATCHES=0",
    "CASULO_G4_QUARANTINED_TASKS=5",
    f"CASULO_G4_REFERENCE_VECTOR_SHA256={REFERENCE}",
    "CASULO_G4_REFERENCE_TRACE_MATCH=PASS",
    "CASULO_G4_RING3_DISPATCHES=90",
    "CASULO_G4_YIELD_KERNEL_RETURNS=90",
    "CASULO_G4_FINITE_WORK=PASS",
    "CASULO_G4_HELP_P95_LOGICAL_TICKS=semantic:5,conventional:10",
    "CASULO_G4_NO_HELP_P95_LOGICAL_TICKS=semantic:6,conventional:6",
    "CASULO_G4_METRIC_SCOPE=logical-operation-count-not-wall-clock",
    "CONVENTIONAL_POLICY=PASS",
    "SEMANTIC_POLICY=PASS",
    "EQUIVALENCE_JUDGE=PASS",
    "SCHEDULER_TIMELINE=PASS",
    "FLOW_DISPATCHES=4",
    "ATTRACTOR_AUDIT_DISPATCHES=4",
    "NON_STARVATION=PASS",
    "AUDIT_STARVATION=0",
    "AUDIT_MAX_GAP_LOGICAL_TICKS=4",
    "TCAP_CORRUPT_RESULT=QUARANTINE",
    "TCAP_CORRUPT_EXECUTED=0",
    "TIMING_STATUS=unavailable",
    "ENERGY_STATUS=unavailable",
    "CASULO_SHELL_SCOPE=bounded-read-only-parser/0.1",
    "CASULO_SHELL_COMMANDS=help,status,topology,scheduler",
    "CASULO_SHELL_SELF_TEST=PASS",
    "G4_SEMANTIC_SCHEDULER_GATE=PASS",
    "G7_DEMO_COMPLETE=PASS",
    "SHUTDOWN_PATH=isa-debug-exit/0.1",
    "REBOOT_PATH=8042-reset-probe-validated/0.1",
)
ORDERED = (
    "G1_BOOT_SMOKE=PASS",
    "TCAP_VALIDATION=PASS",
    "FLOOD_SURROGATE_EXECUTION=PASS",
    "CONVENTIONAL_POLICY=PASS",
    "SEMANTIC_POLICY=PASS",
    "EQUIVALENCE_JUDGE=PASS",
    "SCHEDULER_TIMELINE=PASS",
    "NON_STARVATION=PASS",
    "TCAP_CORRUPT_RESULT=QUARANTINE",
    "G7_DEMO_COMPLETE=PASS",
)
FORBIDDEN = (
    "CASULO_PANIC_DUMP",
    "CASULO_KERNEL_FATAL",
    "UNCONTAINED_PAGE_FAULT",
    "G2_FULL_GATE=FAIL",
    "G3_TCAP_GATE=FAIL",
    "G4_SEMANTIC_SCHEDULER_GATE=FAIL",
    "G7_DEMO_COMPLETE=FAIL",
    "CASULO_G4_METRIC_SCOPE=wall-clock",
)


def validate(serial: str, returncode: int) -> dict[str, object]:
    missing = [marker for marker in REQUIRED if marker not in serial]
    forbidden = [marker for marker in FORBIDDEN if marker in serial]
    positions = [serial.find(marker) for marker in ORDERED]
    ordered = all(position >= 0 for position in positions) and positions == sorted(positions)
    elapsed = _integer_value(serial, "USER_WATCHDOG_ELAPSED_TICKS")
    bounded_watchdog = elapsed is not None and 3 <= elapsed <= 5
    passed = returncode == 33 and not missing and not forbidden and ordered and bounded_watchdog
    return {
        "qemu_debug_exit_success": returncode == 33,
        "missing_markers": missing,
        "forbidden_markers": forbidden,
        "ordered_demo_protocol": ordered,
        "watchdog_elapsed_ticks": elapsed,
        "watchdog_within_declared_bound": bounded_watchdog,
        "pass": passed,
    }


def _integer_value(serial: str, key: str) -> int | None:
    prefix = key + "="
    values = [line[len(prefix) :] for line in serial.splitlines() if line.startswith(prefix)]
    if len(values) != 1:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def negative_validator_tests() -> dict[str, bool]:
    fixture = (
        "\n".join((*ORDERED, *(marker for marker in REQUIRED if marker not in ORDERED)))
        + "\nUSER_WATCHDOG_ELAPSED_TICKS=3\n"
    )
    cases = {
        "missing_hard_gate_rejected": fixture.replace(
            "CASULO_G4_HARD_GATES=integrity,permissions,quality,isolation\n", ""
        ),
        "quarantine_dispatch_rejected": fixture.replace(
            "CASULO_G4_QUARANTINE_DISPATCHES=0",
            "CASULO_G4_QUARANTINE_DISPATCHES=1",
        ),
        "reference_mismatch_rejected": fixture.replace(REFERENCE, "0" * 64),
        "unbounded_watchdog_rejected": fixture.replace(
            "USER_WATCHDOG_ELAPSED_TICKS=3", "USER_WATCHDOG_ELAPSED_TICKS=99"
        ),
        "unsupported_exit_rejected": fixture,
    }
    results = {
        "valid_fixture_accepted": bool(validate(fixture, 33)["pass"]),
        **{
        name: not bool(validate(serial, 32 if name == "unsupported_exit_rejected" else 33)["pass"])
        for name, serial in cases.items()
        },
    }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict G2-adversarial and G4 kernel replay gate; logical ticks are not time."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=35.0)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        raise SystemExit("repeat must be between 1 and 20")
    image = safe_regular_workspace_file(args.image)
    for dependency in (DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS):
        if not dependency.is_file():
            raise SystemExit(f"missing QEMU dependency: {dependency}")
    negative = negative_validator_tests()
    records: list[dict[str, object]] = []
    for attempt in range(1, args.repeat + 1):
        boot = boot_once(image, DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS, args.timeout)
        check = validate(str(boot["serial"]), int(boot["returncode"]))
        records.append({"attempt": attempt, "boot": boot, "validation": check})
    all_pass = all(bool(record["validation"]["pass"]) for record in records) and all(
        negative.values()
    )
    summary = {
        "schema": "casulo-qemu-g4-kernel-replay/0.1",
        "claim_scope": "bounded QEMU correctness and deterministic logical operation-count replay",
        "attempts": len(records),
        "passed": sum(bool(record["validation"]["pass"]) for record in records),
        "all_pass": all_pass,
        "reference_vector_sha256": REFERENCE,
        "negative_validator_tests": negative,
        "wall_clock_performance_claimed": False,
        "energy_measured": False,
        "logical_ticks_labeled_as_time": False,
        "host_block_devices_attached": False,
        "image_attached_read_only": True,
        "network_attached": False,
        "qemu_acceleration": "tcg",
        "qemu_vcpus": 2,
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "results": records,
    }
    evidence = ROOT / "evidence/casulo-os-rp01/g4/kernel"
    evidence.mkdir(parents=True, exist_ok=True)
    output = evidence / f"qemu-g4-kernel-{args.repeat}.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
