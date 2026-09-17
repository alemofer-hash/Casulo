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
    sha256,
)


PRODUCT_MARKERS = (
    "G1_BOOT_SMOKE=PASS",
    "UEFI=true",
    "PAGING=active",
    "HEAP_ALLOC=PASS",
    "GDT_IDT=loaded",
    "WATCHDOG_CONTRACT=PASS",
    "SMP_GATE=PASS",
    "PROCESS_SEPARATE_CR3=PASS",
    "USER_CODE_RX=PASS",
    "USER_STACK_NX=PASS",
    "SYSCALL_ABI=syscall-sysretq/0.1",
    "SYSCALL_IPC_ROUNDTRIP=PASS",
    "RING3_PAGE_FAULT_CONTAINMENT=PASS",
    "TCAP_VALIDATION=PASS",
    "TCAP_CODE_RX=PASS",
    "TCAP_DATA_RW_NX=PASS",
    "TCAP_STACK_RW_NX=PASS",
    "TCAP_PERMISSION_NEGATIVE=PASS",
    "TCAP_CORRUPTION=QUARANTINE_EXECUTION_COUNT_0:PASS",
    "TCAP_CORRUPT_EXECUTED=0",
    "G3_TCAP_GATE=PASS",
    "CASULO_NATIVE_UX_CONTRACT_SCHEMA=casulo.hosted-native-ux-contract/1.0",
    "CASULO_NATIVE_UX_WIRE_SCHEMA=casulo.owner-ux-event/1.0",
    "CASULO_NATIVE_UX_CONTRACT_SHA256=4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9",
    "CASULO_NATIVE_PRESENCE_PRIORITY=PASS",
    "CASULO_NATIVE_MODEL_LIFECYCLE=PASS",
    "CASULO_NATIVE_ASSISTANT_STREAM=PASS",
    "CASULO_NATIVE_JOB_LIFECYCLE=PASS",
    "CASULO_NATIVE_LATE_COMPLETION_REJECTED=PASS",
    "CASULO_NATIVE_UX_QUEUE_BOUNDED=PASS",
    "CASULO_NATIVE_UX_CONTRACT_GATE=PASS",
    "CASULO_NATIVE_SCENE_SCHEMA=casulo.stark-jobs-scene/1.0",
    "CASULO_NATIVE_SCENE_SHA256=804ceb12b510f250cfd41a6e49185fe8db73f13c09a7f3288703368889435a8d",
    "CASULO_NATIVE_SCENE_HAPPY_PATH=PASS",
    "CASULO_NATIVE_SCENE_REJECTIONS=PASS",
    "CASULO_NATIVE_SCENE_TRANSACTIONAL=PASS",
    "CASULO_NATIVE_SCENE_GATE=PASS",
    "CASULO_NATIVE_RENDERER=stark-jobs-gop/0.1",
    "CASULO_NATIVE_RENDERER_GATE=PASS",
    "CASULO_NATIVE_INPUT_ABI=ps2-set1-bounded/0.1",
    "CASULO_NATIVE_INPUT_DECODER_GATE=PASS",
    "CASULO_NATIVE_NEURAL_ABI=ring3-capability-primitives/0.1",
    "CASULO_NATIVE_NEURAL_ABI_MODEL_BYTES=0",
    "CASULO_NATIVE_NEURAL_ABI_MODEL_ASSERTS=1",
    "CASULO_NATIVE_NEURAL_ABI_PRIMITIVE_CALLS=1",
    "CASULO_NATIVE_NEURAL_ABI_TOKEN_EVENTS=1",
    "CASULO_NATIVE_NEURAL_ABI_LAST_TOKEN=42",
    "CASULO_NATIVE_NEURAL_ABI_DENIED_WITHOUT_CAPABILITY=1",
    "CASULO_NATIVE_NEURAL_ABI_GATE=PASS",
    "CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED",
    "SHUTDOWN_PATH=isa-debug-exit/0.1",
)

FORBIDDEN_MARKERS = (
    "CASULO_PANIC_DUMP",
    "CASULO_KERNEL_FATAL",
    "UNCONTAINED_PAGE_FAULT",
    "G1_BOOT_SMOKE=FAIL",
    "G2_FULL_GATE=FAIL",
    "G3_TCAP_GATE=FAIL",
)


def validate_product_boot(
    boot: dict[str, object], tcap_sha256: str, require_system_pack: bool = False
) -> dict[str, object]:
    serial = str(boot.get("serial", ""))
    expected_hash = f"TCAP_HASH_SHA256={tcap_sha256}"
    extra = (
        "CASULO_NATIVE_SYSTEM_PACK_PRESENT=YES",
        "CASULO_NATIVE_SYSTEM_PACK_ENTRIES=3",
        "CASULO_NATIVE_SYSTEM_PACK_UX_CONTRACT=PRESENT",
        "CASULO_NATIVE_SYSTEM_PACK_GUIDE_T_SOURCE=PRESENT_NOT_EXECUTED",
        "CASULO_NATIVE_SYSTEM_PACK_CORRUPTION=QUARANTINE",
        "CASULO_NATIVE_SYSTEM_PACK_GATE=PASS",
    ) if require_system_pack else ()
    missing = [marker for marker in (*PRODUCT_MARKERS, *extra, expected_hash) if marker not in serial]
    forbidden = [marker for marker in FORBIDDEN_MARKERS if marker in serial]
    passed = (
        boot.get("returncode") == 33
        and boot.get("timed_out") is False
        and not missing
        and not forbidden
    )
    return {
        "passed": passed,
        "missing_markers": missing,
        "forbidden_markers": forbidden,
        "serial_sha256": hashlib.sha256(serial.encode("utf-8")).hexdigest(),
        "validated_markers": list(PRODUCT_MARKERS),
        "system_pack_required": require_system_pack,
        "system_pack_markers": list(extra),
        "tcap_hash_marker": expected_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo Native Product Alpha correctness gate")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--tcap", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--require-system-pack", action="store_true")
    parser.add_argument("--require-persistence-contract", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "product-demos/native-sprint13/native-acceptance.json",
    )
    args = parser.parse_args()
    if not 1.0 <= args.timeout <= 60.0:
        raise SystemExit("timeout must be between 1 and 60 seconds")
    image = safe_regular_workspace_file(args.image)
    tcap = safe_regular_workspace_file(args.tcap)
    qemu = args.qemu.expanduser().resolve()
    code = args.ovmf_code.expanduser().resolve()
    variables = args.ovmf_vars.expanduser().resolve()
    for dependency in (qemu, code, variables):
        if not dependency.is_file():
            raise SystemExit(f"missing QEMU dependency: {dependency}")
    boot = boot_once(image, qemu, code, variables, args.timeout)
    validation = validate_product_boot(boot, sha256(tcap), args.require_system_pack)
    if args.require_persistence_contract:
        required = (
            "CASULO_NATIVE_PERSISTENCE_ABI=casulo.native-journal/0.1",
            "CASULO_NATIVE_PERSISTENCE_JOURNAL_GATE=PASS",
            "CASULO_NATIVE_PERSISTENCE_MEDIA_WRITES=0",
            "CASULO_NATIVE_REBOOT_PERSISTENCE=NOT_PROVEN",
        )
        serial_validation = boot.get("serial", "")
        missing = [marker for marker in required if marker not in str(serial_validation)]
        validation["persistence_contract_required"] = True
        validation["persistence_contract_markers"] = list(required)
        validation["missing_markers"].extend(missing)
        validation["passed"] = bool(validation["passed"] and not missing)
    report = {
        "schema": "casulo-native-product-alpha/1.0",
        "profile": "NATIVE_FOUNDATION",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256": sha256(image),
        "tcap": tcap.relative_to(ROOT).as_posix(),
        "tcap_sha256": sha256(tcap),
        "qemu": {"acceleration": "tcg", "vcpus": 2, "network": False},
        "image_attached_read_only": True,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "performance_measured": False,
        "energy_measured": False,
        "scientific_benchmark": False,
        "validation": validation,
    }
    output = args.output.expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("output must remain inside the repository") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if validation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
