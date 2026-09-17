from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_native_model_paged_qemu import MODEL, MODEL_SHA256, boot_once, verified_model
from run_product_alpha_qemu import validate_product_boot
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256


POLICY_TCAP_HASH = "75cea2db98a664fcf7f5f7c402b528c334fbf14bdc056c88493f9939936d4d9a"
NP8_MARKERS = (
    "CASULO_NATIVE_DECODER_BLOCKS_COMPLETED=36",
    "CASULO_NATIVE_DECODER_LOGITS_SHA256=4760c2d93598f80a1b3b44cdbcb20fe4785af71127c6fe544c2996c07035a509",
    "CASULO_NATIVE_DECODER_GATE=PASS",
    "CASULO_NATIVE_SAMPLING_POLICY=greedy-debug-v1",
    "CASULO_NATIVE_SAMPLING_AUTHORITY=T/2.0",
    f"CASULO_NATIVE_SAMPLING_TCAP_HASH={POLICY_TCAP_HASH}",
    "CASULO_NATIVE_OUTPUT_TOKEN_ID=6237",
    "CASULO_NATIVE_OUTPUT_TOKEN_TEXT_HEX=756d73",
    "CASULO_NATIVE_OUTPUT_TOKEN_MODEL_DERIVED=YES",
    "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=PASS",
    "CASULO_NATIVE_SAMPLING_GATE=PASS",
    "CASULO_NATIVE_NEURAL_INFERENCE=FIRST_MODEL_DERIVED_TOKEN_T_AUTHORIZED",
)


def first_token_metrics(serial: str) -> dict[str, str]:
    result: dict[str, str] = {}
    prefixes = ("CASULO_NATIVE_DECODER_", "CASULO_NATIVE_SAMPLING_", "CASULO_NATIVE_OUTPUT_TOKEN_")
    for line in serial.splitlines():
        if line.startswith(prefixes) and "=" in line:
            key, value = line.split("=", 1)
            if key in result:
                raise ValueError(f"duplicate NP8 marker: {key}")
            result[key] = value
    return result


def finalize_np8_validation(
    boot: dict[str, object],
    validation: dict[str, object],
    missing: list[str],
    forbidden: list[str],
) -> dict[str, object]:
    validation["missing_markers"] = [
        marker
        for marker in validation["missing_markers"]
        if marker != "CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED"
    ]
    validation["missing_markers"].extend(missing)
    validation["forbidden_markers"].extend(forbidden)
    validation["passed"] = bool(
        boot["returncode"] == 33
        and not boot["timed_out"]
        and not validation["missing_markers"]
        and not validation["forbidden_markers"]
    )
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the first model-derived token authorized by compiled T in Casulo Native")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--tcap", type=Path, default=ROOT / "release/FloodSurrogate.tcap")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--accelerator", choices=("whpx", "tcg"), default="whpx")
    parser.add_argument("--memory-mib", type=int, choices=(256, 4096, 6144), default=256)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 3 or not 60 <= args.timeout <= 900:
        raise SystemExit("invalid repeat/timeout")
    image = safe_regular_workspace_file(args.image)
    tcap = safe_regular_workspace_file(args.tcap)
    model = verified_model(args.model)
    qemu, code, variables = args.qemu.resolve(), args.ovmf_code.resolve(), args.ovmf_vars.resolve()
    if not all(path.is_file() for path in (qemu, code, variables)):
        raise SystemExit("missing QEMU/OVMF dependency")

    image_before, model_before = sha256(image), sha256(model)
    boots: list[dict[str, object]] = []
    for attempt in range(1, args.repeat + 1):
        boot = boot_once(
            image,
            model,
            qemu,
            code,
            variables,
            args.timeout,
            accelerator=args.accelerator,
            memory_mib=args.memory_mib,
        )
        serial = str(boot["serial"])
        validation = validate_product_boot(boot, sha256(tcap), require_system_pack=False)
        missing = [marker for marker in NP8_MARKERS if marker not in serial]
        forbidden = [
            marker
            for marker in (
                "CASULO_NATIVE_DECODER_GATE=FAIL",
                "CASULO_NATIVE_SAMPLING_GATE=FAIL",
                "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=NO",
                "CASULO_NATIVE_DECODER_OUTPUT_TOKEN=UNAUTHORIZED",
            )
            if marker in serial
        ]
        validation = finalize_np8_validation(boot, validation, missing, forbidden)
        boots.append(
            {
                "attempt": attempt,
                "returncode": boot["returncode"],
                "timed_out": boot["timed_out"],
                "accelerator": args.accelerator,
                "memory_mib": args.memory_mib,
                "metrics": first_token_metrics(serial),
                "serial_sha256": validation["serial_sha256"],
                "serial_tail": serial[-16_384:],
                "validation": validation,
            }
        )

    image_after, model_after = sha256(image), sha256(model)
    report = {
        "schema": "casulo-native-first-t-authorized-token-qemu/0.1",
        "state": "NATIVE_FIRST_T_AUTHORIZED_MODEL_TOKEN_VALIDATED",
        "claim": "the first authentic model-derived token was published in Casulo Native only after a compiled T/2.0 policy consumed and accepted the complete decoder evidence",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": image_before,
        "image_sha256_after": image_after,
        "image_unchanged": image_before == image_after,
        "model_sha256_before": model_before,
        "model_sha256_after": model_after,
        "model_unchanged": model_before == model_after == MODEL_SHA256,
        "sampling_policy_tcap_hash": POLICY_TCAP_HASH,
        "sampling_policy": "greedy-debug-v1",
        "output_token_id": 6237,
        "output_token_text_hex": "756d73",
        "guest_network": False,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "external_api": False,
        "performance_measured": False,
        "energy_measured": False,
        "boots": boots,
        "passed": (
            image_before == image_after
            and model_before == model_after == MODEL_SHA256
            and all(boot["validation"]["passed"] for boot in boots)
        ),
    }
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit(f"append-only output exists: {output}")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "boots"}, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
