from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_native_model_paged_qemu import MODEL, MODEL_SHA256, boot_once, verified_model
from run_product_alpha_qemu import validate_product_boot
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256


NP7_MARKERS = (
    "CASULO_NATIVE_DECODER=PRESENT",
    "CASULO_NATIVE_DECODER_ARCHITECTURE=qwen3",
    "CASULO_NATIVE_DECODER_INPUT_TOKEN_ID=49242",
    "CASULO_NATIVE_DECODER_BLOCKS_COMPLETED=36",
    "CASULO_NATIVE_DECODER_MATVEC_CALLS=253",
    "CASULO_NATIVE_DECODER_QUANTIZED_BLOCKS=15712000",
    "CASULO_NATIVE_DECODER_WEIGHT_BYTES_READ=2490539520",
    "CASULO_NATIVE_DECODER_MULTIPLY_ACCUMULATES=4022272000",
    "CASULO_NATIVE_DECODER_ATTENTION_SCORES=1152",
    "CASULO_NATIVE_DECODER_ARENA_BYTES=848512",
    "CASULO_NATIVE_DECODER_HIDDEN_CHAIN_SHA256=9b1a775cf3155060f8d8e1898822a684db5e1848a601e6c60a37b7a8b8b6079b",
    "CASULO_NATIVE_DECODER_LOGITS_SHA256=4760c2d93598f80a1b3b44cdbcb20fe4785af71127c6fe544c2996c07035a509",
    "CASULO_NATIVE_DECODER_GREEDY_CANDIDATE_ID=6237",
    "CASULO_NATIVE_DECODER_GREEDY_CANDIDATE_LOGIT_BITS=4155235e",
    "CASULO_NATIVE_DECODER_CANCELLATION_CONTROL=PASS",
    "CASULO_NATIVE_DECODER_OUTPUT_TOKEN=NO_POLICY_GATE_PENDING",
    "CASULO_NATIVE_DECODER_GATE=PASS",
    "CASULO_NATIVE_NEURAL_INFERENCE=FULL_DECODER_LOGITS_CANDIDATE_NO_PUBLICATION",
)


def decoder_metrics(serial: str) -> dict[str, str]:
    observed: dict[str, str] = {}
    for line in serial.splitlines():
        if line.startswith("CASULO_NATIVE_DECODER_") and "=" in line:
            key, value = line.split("=", 1)
            if key in observed:
                raise ValueError(f"duplicate decoder marker: {key}")
            observed[key] = value
    return observed


def finalize_np7_validation(
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
    parser = argparse.ArgumentParser(description="Validate the complete Qwen3 decoder-to-logits path in Casulo Native")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--tcap", type=Path, default=ROOT / "release/FloodSurrogate.tcap")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--accelerator", choices=("whpx", "tcg"), default="whpx")
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 3 or not 60 <= args.timeout <= 600:
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
        boot = boot_once(image, model, qemu, code, variables, args.timeout, accelerator=args.accelerator)
        serial = str(boot["serial"])
        validation = validate_product_boot(boot, sha256(tcap), require_system_pack=False)
        missing = [marker for marker in NP7_MARKERS if marker not in serial]
        forbidden = [
            marker
            for marker in (
                "CASULO_NATIVE_DECODER_GATE=FAIL",
                "CASULO_NATIVE_DECODER_OUTPUT_TOKEN=UNAUTHORIZED",
                "CASULO_NATIVE_DECODER_OUTPUT_TOKEN=YES",
            )
            if marker in serial
        ]
        validation = finalize_np7_validation(boot, validation, missing, forbidden)
        boots.append(
            {
                "attempt": attempt,
                "returncode": boot["returncode"],
                "timed_out": boot["timed_out"],
                "accelerator": args.accelerator,
                "metrics": decoder_metrics(serial),
                "serial_sha256": validation["serial_sha256"],
                "serial_tail": serial[-16_384:],
                "validation": validation,
            }
        )

    controls: list[dict[str, object]] = []
    if args.negative_controls:
        missing_boot = boot_once(image, None, qemu, code, variables, args.timeout, accelerator=args.accelerator)
        missing_serial = str(missing_boot["serial"])
        controls.append(
            {
                "case": "missing-model-item",
                "passed": (
                    "CASULO_NATIVE_MODEL_PAGED_REJECT=Transport(ModelMissing)" in missing_serial
                    and "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL" in missing_serial
                    and "CASULO_NATIVE_DECODER_GATE=PASS" not in missing_serial
                ),
                "returncode": missing_boot["returncode"],
                "timed_out": missing_boot["timed_out"],
            }
        )
        with tempfile.TemporaryDirectory(prefix="casulo-native-decoder-truncated-", dir=ROOT / ".tmp") as temporary:
            truncated = Path(temporary) / "truncated.gguf"
            with model.open("rb") as source, truncated.open("wb") as target:
                target.write(source.read(4096))
            truncated_boot = boot_once(
                image, truncated, qemu, code, variables, args.timeout, accelerator=args.accelerator
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
                        and "CASULO_NATIVE_DECODER_GATE=PASS" not in truncated_serial
                    ),
                    "returncode": truncated_boot["returncode"],
                    "timed_out": truncated_boot["timed_out"],
                }
            )

    image_after, model_after = sha256(image), sha256(model)
    report = {
        "schema": "casulo-native-qwen-decoder-qemu/0.1",
        "state": "NATIVE_COMPLETE_QWEN3_DECODER_TO_LOGITS_VALIDATED",
        "claim": "one authentic token position completed all 36 Qwen3 blocks, output normalization and tied logits projection inside Casulo Native; candidate verified but not sampled or published",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": image_before,
        "image_sha256_after": image_after,
        "image_unchanged": image_before == image_after,
        "model_sha256_before": model_before,
        "model_sha256_after": model_after,
        "model_unchanged": model_before == model_after == MODEL_SHA256,
        "accelerator": args.accelerator,
        "guest_network": False,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "blocks_executed": 36,
        "logits_executed": True,
        "sampling_executed": False,
        "output_token_published": False,
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
