from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_native_model_paged_qemu import (
    EXPECTED_MARKERS as NP4_MARKERS,
    MODEL,
    MODEL_BYTES,
    MODEL_SHA256,
    boot_once,
    verified_model,
)
from run_product_alpha_qemu import validate_product_boot
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256


NP5_MARKERS = (
    "CASULO_NATIVE_TOKENIZER_EMBEDDING=PRESENT",
    "CASULO_NATIVE_TOKENIZER_MODEL=gpt2",
    "CASULO_NATIVE_TOKENIZER_PRE=qwen2-bounded-latin/0.1",
    "CASULO_NATIVE_TOKENIZER_ORACLE=llama-tokenize-b10362-offline",
    "CASULO_NATIVE_TOKENIZER_ORACLE_SHA256=4b63587d19ac1fecabce65aa4e7da41212865cb323804882b9f68ed44a5ec573",
    "CASULO_NATIVE_TOKENIZER_VOCAB=151936",
    "CASULO_NATIVE_TOKENIZER_MERGES=151387",
    "CASULO_NATIVE_TOKENIZER_BOS=151643",
    "CASULO_NATIVE_TOKENIZER_EOS=151645",
    "CASULO_NATIVE_TOKENIZER_PADDING=151643",
    "CASULO_NATIVE_TOKENIZER_CHAT_TEMPLATE_BYTES=4100",
    "CASULO_NATIVE_TOKENIZER_CHAT_TEMPLATE_EXECUTED=NO",
    "CASULO_NATIVE_TOKENIZER_CASE_CASULO=49242,8763",
    "CASULO_NATIVE_TOKENIZER_CASE_HELLO_WORLD=14990,1879",
    "CASULO_NATIVE_TOKENIZER_CASE_OLA_CASULO=42719,1953,11,11054,8763,13",
    "CASULO_NATIVE_TOKENIZER_CASES=3",
    "CASULO_NATIVE_TOKENIZER_UNSUPPORTED_SPECIAL=REJECTED",
    "CASULO_NATIVE_TOKENIZER_UNSUPPORTED_SCRIPT=REJECTED",
    "CASULO_NATIVE_EMBEDDING_TOKEN_ID=49242",
    "CASULO_NATIVE_EMBEDDING_ROW_OFFSET=109374792",
    "CASULO_NATIVE_EMBEDDING_ROW_BYTES=2100",
    "CASULO_NATIVE_EMBEDDING_WIDTH=2560",
    "CASULO_NATIVE_EMBEDDING_SUM_F32_BITS=3f7e76a4",
    "CASULO_NATIVE_EMBEDDING_INVALID_TOKEN=REJECTED",
    "CASULO_NATIVE_TOKENIZER_FIRST_OUTPUT_TOKEN=NO",
    "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=PASS",
    "CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED",
)


def native_metrics(serial: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for line in serial.splitlines():
        if (
            line.startswith("CASULO_NATIVE_MODEL_PAGED_")
            or line.startswith("CASULO_NATIVE_TOKENIZER_")
            or line.startswith("CASULO_NATIVE_EMBEDDING_")
        ) and "=" in line:
            key, value = line.split("=", 1)
            metrics[key] = value
    return metrics


def gate_trace(serial: str) -> list[str]:
    allowed_prefixes = (
        "G1_",
        "G2_",
        "G3_",
        "G4_",
        "G7_",
        "CASULO_NATIVE_",
        "TCAP_",
        "SYSTEM_PACK_",
    )
    return [
        line
        for line in serial.splitlines()
        if line.startswith(allowed_prefixes)
        and ("GATE=" in line or "COMPLETE=" in line or "REJECT=" in line or line.endswith("=FAIL"))
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate bounded Native tokenizer and Q6_K embedding")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--tcap", type=Path, default=ROOT / "release/FloodSurrogate.tcap")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
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
        boot = boot_once(image, model, qemu, code, variables, args.timeout)
        validation = validate_product_boot(boot, sha256(tcap), require_system_pack=False)
        serial = str(boot["serial"])
        missing = [marker for marker in NP4_MARKERS + NP5_MARKERS if marker not in serial]
        forbidden = [
            marker
            for marker in (
                "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=FAIL",
                "CASULO_NATIVE_TOKENIZER_FIRST_OUTPUT_TOKEN=YES",
                "CASULO_NATIVE_NEURAL_INFERENCE=EXECUTED",
            )
            if marker in serial
        ]
        validation["missing_markers"].extend(missing)
        validation["forbidden_markers"].extend(forbidden)
        validation["passed"] = bool(validation["passed"] and not missing and not forbidden)
        boots.append(
            {
                "attempt": attempt,
                "returncode": boot["returncode"],
                "timed_out": boot["timed_out"],
                "metrics": native_metrics(serial),
                "gate_trace": gate_trace(serial),
                "serial_sha256": validation["serial_sha256"],
                "validation": validation,
            }
        )

    controls: list[dict[str, object]] = []
    missing_boot = boot_once(image, None, qemu, code, variables, args.timeout)
    missing_serial = str(missing_boot["serial"])
    controls.append(
        {
            "case": "missing-model-item",
            "passed": (
                "CASULO_NATIVE_MODEL_PAGED_REJECT=Transport(ModelMissing)" in missing_serial
                and "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL" in missing_serial
                and "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=PASS" not in missing_serial
            ),
            "returncode": missing_boot["returncode"],
            "timed_out": missing_boot["timed_out"],
        }
    )
    with tempfile.TemporaryDirectory(prefix="casulo-native-tokenizer-truncated-", dir=ROOT / ".tmp") as temporary:
        truncated = Path(temporary) / "truncated.gguf"
        with model.open("rb") as source, truncated.open("wb") as target:
            target.write(source.read(4096))
        truncated_boot = boot_once(image, truncated, qemu, code, variables, args.timeout)
        truncated_serial = str(truncated_boot["serial"])
        controls.append(
            {
                "case": "truncated-model-item",
                "bytes": truncated.stat().st_size,
                "sha256": sha256(truncated),
                "passed": (
                    "CASULO_NATIVE_MODEL_PAGED_REJECT=Transport(ModelSize)" in truncated_serial
                    and "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL" in truncated_serial
                    and "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=PASS" not in truncated_serial
                ),
                "returncode": truncated_boot["returncode"],
                "timed_out": truncated_boot["timed_out"],
            }
        )

    image_after, model_after = sha256(image), sha256(model)
    report = {
        "schema": "casulo-native-tokenizer-embedding-qemu/0.1",
        "state": "NATIVE_BOUNDED_TOKENIZER_AND_EMBEDDING_VALIDATED",
        "claim": "three frozen ordinary-text cases matched the offline adopted llama.cpp tokenizer and one authentic Q6_K embedding row was decoded; no chat-template execution, transformer, logits or output token",
        "scope": "bounded ASCII/Latin ordinary text; unsupported syntax fails closed",
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
            "runtime": "llama-tokenize.exe b10362",
            "sha256": "4b63587d19ac1fecabce65aa4e7da41212865cb323804882b9f68ed44a5ec573",
            "offline": True,
        },
        "guest_network": False,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "chat_template_executed": False,
        "transformer_executed": False,
        "first_model_derived_output_token": False,
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
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
