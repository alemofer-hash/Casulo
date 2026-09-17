from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_product_alpha_qemu import validate_product_boot
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256
from run_virtual_usb_qemu import boot_once


EXPECTED_MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
EXPECTED_MARKERS = (
    "CASULO_NATIVE_SYSTEM_PACK_ENTRIES=4",
    "CASULO_NATIVE_SYSTEM_PACK_MODEL_GGUF_PROBE=PRESENT",
    "CASULO_NATIVE_SYSTEM_PACK_GATE=PASS",
    "CASULO_NATIVE_GGUF_PROBE_PRESENT=YES",
    "CASULO_NATIVE_GGUF_PROBE_VERSION=3",
    "CASULO_NATIVE_GGUF_SOURCE_MODEL_SHA256=" + EXPECTED_MODEL_SHA256,
    "CASULO_NATIVE_GGUF_SOURCE_MODEL_BYTES=2497280256",
    "CASULO_NATIVE_GGUF_SOURCE_TENSOR=blk.0.attn_k.weight",
    "CASULO_NATIVE_GGUF_SOURCE_TENSOR_OFFSET=325032192",
    "CASULO_NATIVE_GGUF_Q4_K_BLOCK_BYTES=144",
    "CASULO_NATIVE_GGUF_PROBE_CORRUPTION=QUARANTINE",
    "CASULO_NATIVE_GGUF_PROBE_GATE=PASS",
    "CASULO_NATIVE_MODEL_WEIGHT_BYTES_CONSUMED=144",
    "CASULO_NATIVE_FULL_MODEL_MAPPED=NO",
    "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=NO",
    "CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate authentic GGUF/Q4_K weight consumption in QEMU")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--tcap", type=Path, default=ROOT / "release/FloodSurrogate.tcap")
    parser.add_argument("--probe-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 5 or not 5 <= args.timeout <= 90:
        raise SystemExit("invalid repeat/timeout")
    image = safe_regular_workspace_file(args.image)
    tcap = safe_regular_workspace_file(args.tcap)
    probe_manifest_path = safe_regular_workspace_file(args.probe_manifest)
    probe_manifest = json.loads(probe_manifest_path.read_text(encoding="utf-8"))
    if probe_manifest["source_model"]["sha256"] != EXPECTED_MODEL_SHA256:
        raise SystemExit("probe manifest model hash mismatch")
    all_formats = probe_manifest.get("schema") == "casulo-native-gguf-probe/0.2"
    expected_markers = list(EXPECTED_MARKERS)
    projection = probe_manifest["projection"]
    expected_markers.append(
        "CASULO_NATIVE_GGUF_Q4_K_EXPECTED_F32_BITS="
        + str(projection.get("q4_dot_f32_bits", projection["dot_f32_bits"]))
    )
    if all_formats:
        sources = probe_manifest["source_tensors"]
        expected_markers.extend(
            [
                "CASULO_NATIVE_GGUF_PROBE_TENSORS=3",
                "CASULO_NATIVE_GGUF_SOURCE_Q6_TENSOR=" + sources["q6_k"]["name"],
                "CASULO_NATIVE_GGUF_SOURCE_Q6_TENSOR_OFFSET=" + str(sources["q6_k"]["absolute_offset"]),
                "CASULO_NATIVE_GGUF_Q6_K_BLOCK_BYTES=210",
                "CASULO_NATIVE_GGUF_Q6_K_EXPECTED_F32_BITS=" + projection["q6_dot_f32_bits"],
                "CASULO_NATIVE_GGUF_SOURCE_F32_TENSOR=" + sources["f32"]["name"],
                "CASULO_NATIVE_GGUF_SOURCE_F32_TENSOR_OFFSET=" + str(sources["f32"]["absolute_offset"]),
                "CASULO_NATIVE_GGUF_F32_VALUES=16",
            ]
        )
    qemu, code, variables = args.qemu.resolve(), args.ovmf_code.resolve(), args.ovmf_vars.resolve()
    if not all(path.is_file() for path in (qemu, code, variables)):
        raise SystemExit("missing QEMU/OVMF dependency")
    image_before = sha256(image)
    boots: list[dict[str, object]] = []
    for attempt in range(1, args.repeat + 1):
        boot = boot_once(image, qemu, code, variables, args.timeout)
        validation = validate_product_boot(boot, sha256(tcap), require_system_pack=False)
        serial = str(boot["serial"])
        missing = [marker for marker in expected_markers if marker not in serial]
        forbidden = [
            marker
            for marker in (
                "CASULO_NATIVE_GGUF_PROBE_GATE=FAIL",
                "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=YES",
                "CASULO_NATIVE_NEURAL_INFERENCE=EXECUTED",
            )
            if marker in serial
        ]
        dot_markers = [
            line
            for line in serial.splitlines()
            if line.startswith(("CASULO_NATIVE_GGUF_Q4_K_DOT_F32_BITS=", "CASULO_NATIVE_GGUF_Q6_K_DOT_F32_BITS="))
        ]
        validation["missing_markers"].extend(missing)
        validation["forbidden_markers"].extend(forbidden)
        required_dot_count = 2 if all_formats else 1
        validation["passed"] = bool(validation["passed"] and not missing and not forbidden and len(dot_markers) == required_dot_count)
        boots.append(
            {
                "attempt": attempt,
                "returncode": boot["returncode"],
                "timed_out": boot["timed_out"],
                "dot_markers": dot_markers,
                "validation": validation,
            }
        )
    image_after = sha256(image)
    report = {
        "schema": "casulo-native-model-weight-probe-qemu/0.1",
        "state": (
            "NATIVE_ALL_MODEL_WEIGHT_FORMATS_VALIDATED"
            if all_formats
            else "NATIVE_AUTHENTIC_WEIGHT_PRIMITIVE_VALIDATED"
        ),
        "claim": (
            "authentic F32/Q4_K/Q6_K samples consumed in Native; no full inference or token"
            if all_formats
            else "one authentic Q4_K block consumed in Native; no full inference or token"
        ),
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": image_before,
        "image_sha256_after": image_after,
        "image_unchanged": image_before == image_after,
        "probe_manifest": probe_manifest_path.relative_to(ROOT).as_posix(),
        "probe_manifest_sha256": sha256(probe_manifest_path),
        "model_sha256": EXPECTED_MODEL_SHA256,
        "full_model_mapped": False,
        "first_model_derived_token": False,
        "guest_network": False,
        "image_read_only": True,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "boots": boots,
        "passed": image_before == image_after and all(boot["validation"]["passed"] for boot in boots),
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
