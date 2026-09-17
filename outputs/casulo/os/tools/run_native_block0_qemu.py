from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_native_model_paged_qemu import MODEL, MODEL_BYTES, MODEL_SHA256, boot_once, verified_model
from run_product_alpha_qemu import validate_product_boot
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256


NP6_MARKERS = (
    "CASULO_NATIVE_BLOCK0=PRESENT",
    "CASULO_NATIVE_BLOCK0_ARCHITECTURE=qwen3",
    "CASULO_NATIVE_BLOCK0_TOKEN_IDS=49242",
    "CASULO_NATIVE_BLOCK0_CONTEXTS=1",
    "CASULO_NATIVE_BLOCK0_TOKENS_COMPLETED=1",
    "CASULO_NATIVE_BLOCK0_DESCRIPTORS_SCANNED=398",
    "CASULO_NATIVE_BLOCK0_MATVEC_CALLS=7",
    "CASULO_NATIVE_BLOCK0_QUANTIZED_BLOCKS=394240",
    "CASULO_NATIVE_BLOCK0_WEIGHT_BYTES_READ=63866880",
    "CASULO_NATIVE_BLOCK0_MULTIPLY_ACCUMULATES=100925440",
    "CASULO_NATIVE_BLOCK0_ATTENTION_SCORES=32",
    "CASULO_NATIVE_BLOCK0_ARENA_BYTES=259328",
    "CASULO_NATIVE_BLOCK0_ORACLE_STAGES=19",
    "CASULO_NATIVE_BLOCK0_ORACLE_MISMATCH_MASK=0000000000000000",
    "CASULO_NATIVE_BLOCK0_OUTPUT_SHA256=487179f486f1df8a132b66f7ef1f542a4f1a8768278dfe67d8e5bcaab77b0b51",
    "CASULO_NATIVE_BLOCK0_SHAPE_MUTATION=REJECTED",
    "CASULO_NATIVE_BLOCK0_WIDER_ROPE=REJECTED",
    "CASULO_NATIVE_BLOCK0_WIDER_CONTEXT=REJECTED",
    "CASULO_NATIVE_BLOCK0_LOGITS=NOT_EXECUTED",
    "CASULO_NATIVE_BLOCK0_OUTPUT_TOKEN=NO",
    "CASULO_NATIVE_BLOCK0_GATE=PASS",
    "CASULO_NATIVE_NEURAL_INFERENCE=BLOCK0_ONLY_NO_OUTPUT_TOKEN",
)


def metrics(serial: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in serial.splitlines():
        if line.startswith("CASULO_NATIVE_BLOCK0_") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def finalize_np6_validation(
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
    parser = argparse.ArgumentParser(description="Validate one complete Qwen3 transformer block in Casulo Native")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--tcap", type=Path, default=ROOT / "release/FloodSurrogate.tcap")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--accelerator", choices=("whpx", "tcg"), default="whpx")
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 3 or not 30 <= args.timeout <= 300:
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
        )
        serial = str(boot["serial"])
        validation = validate_product_boot(boot, sha256(tcap), require_system_pack=False)
        # The generic G10 validator predates NP6 and requires the historical
        # marker saying no inference ran. NP6 supersedes exactly that marker
        # with a bounded block-only state while preserving every other gate.
        missing = [marker for marker in NP6_MARKERS if marker not in serial]
        forbidden = [
            marker
            for marker in (
                "CASULO_NATIVE_BLOCK0_GATE=FAIL",
                "CASULO_NATIVE_BLOCK0_OUTPUT_TOKEN=YES",
                "CASULO_NATIVE_NEURAL_INFERENCE=EXECUTED_FULL",
            )
            if marker in serial
        ]
        validation = finalize_np6_validation(boot, validation, missing, forbidden)
        boots.append(
            {
                "attempt": attempt,
                "returncode": boot["returncode"],
                "timed_out": boot["timed_out"],
                "accelerator": args.accelerator,
                "metrics": metrics(serial),
                "serial_sha256": validation["serial_sha256"],
                "validation": validation,
            }
        )

    controls: list[dict[str, object]] = []
    missing_boot = boot_once(
        image,
        None,
        qemu,
        code,
        variables,
        args.timeout,
        accelerator=args.accelerator,
    )
    missing_serial = str(missing_boot["serial"])
    controls.append(
        {
            "case": "missing-model-item",
            "passed": (
                "CASULO_NATIVE_MODEL_PAGED_REJECT=Transport(ModelMissing)" in missing_serial
                and "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL" in missing_serial
                and "CASULO_NATIVE_BLOCK0_GATE=PASS" not in missing_serial
            ),
            "returncode": missing_boot["returncode"],
            "timed_out": missing_boot["timed_out"],
        }
    )
    with tempfile.TemporaryDirectory(prefix="casulo-native-block0-truncated-", dir=ROOT / ".tmp") as temporary:
        truncated = Path(temporary) / "truncated.gguf"
        with model.open("rb") as source, truncated.open("wb") as target:
            target.write(source.read(4096))
        truncated_boot = boot_once(
            image,
            truncated,
            qemu,
            code,
            variables,
            args.timeout,
            accelerator=args.accelerator,
        )
        truncated_serial = str(truncated_boot["serial"])
        controls.append(
            {
                "case": "truncated-model-item",
                "bytes": truncated.stat().st_size,
                "sha256": sha256(truncated),
                "passed": (
                    "CASULO_NATIVE_MODEL_PAGED_REJECT=Transport(ModelSize)" in truncated_serial
                    and "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL" in truncated_serial
                    and "CASULO_NATIVE_BLOCK0_GATE=PASS" not in truncated_serial
                ),
                "returncode": truncated_boot["returncode"],
                "timed_out": truncated_boot["timed_out"],
            }
        )

    image_after, model_after = sha256(image), sha256(model)
    report = {
        "schema": "casulo-native-qwen-block0-qemu/0.1",
        "state": "NATIVE_ONE_COMPLETE_QWEN3_BLOCK_VALIDATED",
        "claim": "one authentic token position completed Qwen3 block zero and 19 intermediate tensors matched the independent oracle; no later block, logits, sampling, or output token",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": image_before,
        "image_sha256_after": image_after,
        "image_unchanged": image_before == image_after,
        "model": {
            "file_name": model.name,
            "bytes": MODEL_BYTES,
            "sha256_before": model_before,
            "sha256_after": model_after,
            "expected_sha256": MODEL_SHA256,
            "unchanged": model_before == model_after,
        },
        "oracle": {
            "implementation": "independent Python/NumPy GGUF decoder and Qwen3 block",
            "stages": 19,
            "output_scalar_runtime_sha256": "487179f486f1df8a132b66f7ef1f542a4f1a8768278dfe67d8e5bcaab77b0b51",
        },
        "accelerator": args.accelerator,
        "guest_network": False,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "later_transformer_blocks_executed": False,
        "logits_executed": False,
        "first_model_derived_output_token": False,
        "performance_measured": False,
        "energy_measured": False,
        "boots": boots,
        "negative_controls": controls,
        "passed": (
            image_before == image_after
            and model_before == model_after == MODEL_SHA256
            and all(boot["validation"]["passed"] for boot in boots)
            and all(control["passed"] for control in controls)
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
