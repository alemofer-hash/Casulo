from __future__ import annotations

import argparse
import json
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_native_model_paged_qemu import (  # noqa: E402
    MODEL,
    MODEL_SHA256,
    build_command,
    verified_model,
)
from run_product_alpha_qemu import validate_product_boot  # noqa: E402
from run_qemu import (  # noqa: E402
    DEFAULT_CODE,
    DEFAULT_QEMU,
    DEFAULT_VARS,
    ROOT,
    safe_regular_workspace_file,
    sha256,
)


POLICY_ID = "greedy-incremental-v1"
BASE_MARKERS = (
    "CASULO_NATIVE_DECODER_GATE=PASS",
    f"CASULO_NATIVE_SAMPLING_POLICY={POLICY_ID}",
    "CASULO_NATIVE_SAMPLING_AUTHORITY=T/2.0",
    "CASULO_NATIVE_STREAM_TOKEN_0_ID=6237",
    "CASULO_NATIVE_STREAM_TOKEN_0_TEXT_HEX=756d73",
    "CASULO_NATIVE_STREAM_TOKEN_0_PUBLICATION=PASS",
    "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=PASS",
    "CASULO_NATIVE_SAMPLING_GATE=PASS",
)
NORMAL_MARKERS = (
    "CASULO_NATIVE_INCREMENTAL_TOKENS_COMPLETED=2",
    "CASULO_NATIVE_SAMPLING_TOKENS_AUTHORIZED=2",
    "CASULO_NATIVE_STREAM_TOKEN_1_ID=374",
    "CASULO_NATIVE_STREAM_TOKEN_1_TEXT_HEX=c4a06973",
    "CASULO_NATIVE_STREAM_TOKEN_1_PUBLICATION=PASS",
    "CASULO_NATIVE_OUTPUT_TOKEN_1_PUBLICATION=PASS",
    "CASULO_NATIVE_INCREMENTAL_CANCELLED_AFTER_TOKEN_BOUNDARY=NO",
    "CASULO_NATIVE_NEURAL_INFERENCE=MULTI_TOKEN_INCREMENTAL_STREAM_T_AUTHORIZED",
)
CANCEL_MARKERS = (
    "CASULO_NATIVE_STREAM_CANCEL=ACCEPTED",
    "CASULO_NATIVE_INCREMENTAL_TOKENS_COMPLETED=1",
    "CASULO_NATIVE_SAMPLING_TOKENS_AUTHORIZED=1",
    "CASULO_NATIVE_INCREMENTAL_CANCELLED_AFTER_TOKEN_BOUNDARY=YES",
    "CASULO_NATIVE_NEURAL_INFERENCE=TOKEN_STREAM_T_AUTHORIZED_CANCELLED_AT_BOUNDARY",
)


def _reader(stream, lines: queue.Queue[str | None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.put(line)
    finally:
        lines.put(None)


def boot_streaming(
    image: Path,
    model: Path,
    qemu: Path,
    code: Path,
    vars_template: Path,
    timeout: float,
    *,
    accelerator: str,
    memory_mib: int,
    cancel_after_token0: bool,
) -> dict[str, object]:
    temporary_root = ROOT / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="casulo-native-incremental-", dir=temporary_root) as temporary:
        variables = Path(temporary) / "OVMF_VARS.fd"
        shutil.copyfile(vars_template, variables)
        command = build_command(qemu, code, variables, image, model, accelerator, memory_mib)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        lines: queue.Queue[str | None] = queue.Queue()
        reader = threading.Thread(target=_reader, args=(process.stdout, lines), daemon=True)
        reader.start()
        serial_parts: list[str] = []
        cancellation_sent = False
        timed_out = False
        started = time.monotonic()
        reader_finished = False
        while not reader_finished:
            if time.monotonic() - started > timeout:
                timed_out = True
                process.kill()
                break
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is None:
                reader_finished = True
                continue
            serial_parts.append(line)
            print(line, end="", flush=True)
            if (
                cancel_after_token0
                and not cancellation_sent
                and "CASULO_NATIVE_STREAM_CANCEL_WINDOW=OPEN" in line
            ):
                assert process.stdin is not None
                process.stdin.write("\x03")
                process.stdin.flush()
                cancellation_sent = True
        if timed_out:
            process.wait(timeout=10)
        else:
            process.wait(timeout=10)
        reader.join(timeout=2)
        return {
            "returncode": process.returncode,
            "timed_out": timed_out,
            "serial": "".join(serial_parts),
            "cancellation_requested": cancel_after_token0,
            "cancellation_sent": cancellation_sent,
            "command_contract": {
                "shell": False,
                "network": False,
                "image_read_only": True,
                "model_fw_cfg_read_only": True,
                "physical_device": False,
                "accelerator": accelerator,
                "memory_mib": memory_mib,
                "serial_streamed_live": True,
            },
        }


def extract_metrics(serial: str) -> dict[str, str]:
    prefixes = (
        "CASULO_NATIVE_STREAM_",
        "CASULO_NATIVE_INCREMENTAL_",
        "CASULO_NATIVE_SAMPLING_",
        "CASULO_NATIVE_OUTPUT_TOKEN",
        "CASULO_NATIVE_NEURAL_INFERENCE",
    )
    metrics: dict[str, str] = {}
    for line in serial.splitlines():
        if line.startswith(prefixes) and "=" in line:
            key, value = line.split("=", 1)
            metrics[key] = value
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stream and validate incremental model-derived tokens judged per-step by T in Casulo Native"
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--tcap", type=Path, default=ROOT / "release/FloodSurrogate.tcap")
    parser.add_argument("--policy-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument("--cancel-after-token0", action="store_true")
    parser.add_argument("--accelerator", choices=("whpx", "tcg"), default="whpx")
    parser.add_argument("--memory-mib", type=int, choices=(6144,), default=6144)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 3 or not 60 <= args.timeout <= 300:
        raise SystemExit("invalid repeat/timeout")

    image = safe_regular_workspace_file(args.image)
    tcap = safe_regular_workspace_file(args.tcap)
    policy_manifest = safe_regular_workspace_file(args.policy_manifest)
    policy_record = json.loads(policy_manifest.read_text(encoding="utf-8"))
    expected_policy_hash = policy_record["t_sampling_policy"]["tcap_hash"]
    if policy_record["t_sampling_policy"].get("policy_id") != POLICY_ID:
        raise SystemExit("incremental policy identity mismatch")
    model = verified_model(args.model)
    qemu = args.qemu.resolve(strict=True)
    code = args.ovmf_code.resolve(strict=True)
    variables = args.ovmf_vars.resolve(strict=True)

    image_before, model_before = sha256(image), sha256(model)
    boots: list[dict[str, object]] = []
    for attempt in range(1, args.repeat + 1):
        boot = boot_streaming(
            image,
            model,
            qemu,
            code,
            variables,
            args.timeout,
            accelerator=args.accelerator,
            memory_mib=args.memory_mib,
            cancel_after_token0=args.cancel_after_token0,
        )
        serial = str(boot["serial"])
        validation = validate_product_boot(boot, sha256(tcap), require_system_pack=False)
        validation["missing_markers"] = [
            item
            for item in validation["missing_markers"]
            if item != "CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED"
        ]
        expected = BASE_MARKERS + (CANCEL_MARKERS if args.cancel_after_token0 else NORMAL_MARKERS)
        expected += (f"CASULO_NATIVE_SAMPLING_TCAP_HASH={expected_policy_hash}",)
        missing = [marker for marker in expected if marker not in serial]
        forbidden = [
            marker
            for marker in (
                "CASULO_NATIVE_DECODER_GATE=FAIL",
                "CASULO_NATIVE_SAMPLING_GATE=FAIL",
                "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=NO",
                "CASULO_NATIVE_STREAM_TOKEN_1_PUBLICATION=PASS"
                if args.cancel_after_token0
                else "CASULO_NATIVE_STREAM_CANCEL=ACCEPTED",
            )
            if marker in serial
        ]
        validation["missing_markers"].extend(missing)
        validation["forbidden_markers"].extend(forbidden)
        validation["passed"] = bool(
            boot["returncode"] == 33
            and not boot["timed_out"]
            and (not args.cancel_after_token0 or boot["cancellation_sent"])
            and not validation["missing_markers"]
            and not validation["forbidden_markers"]
        )
        boots.append(
            {
                "attempt": attempt,
                "returncode": boot["returncode"],
                "timed_out": boot["timed_out"],
                "cancellation_sent": boot["cancellation_sent"],
                "metrics": extract_metrics(serial),
                "serial": serial,
                "serial_sha256": validation["serial_sha256"],
                "validation": validation,
            }
        )

    image_after, model_after = sha256(image), sha256(model)
    report = {
        "schema": "casulo-native-incremental-stream-qemu/0.1",
        "state": "NATIVE_INCREMENTAL_STREAM_AND_CANCELLATION_VALIDATED",
        "mode": "cancel-after-token0" if args.cancel_after_token0 else "two-token-normal",
        "claim": "each published token was derived by the adopted local model and accepted by the compiled T/2.0 policy against runtime evidence before publication",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": image_before,
        "image_sha256_after": image_after,
        "image_unchanged": image_before == image_after,
        "model_sha256_before": model_before,
        "model_sha256_after": model_after,
        "model_unchanged": model_before == model_after == MODEL_SHA256,
        "sampling_policy": POLICY_ID,
        "sampling_policy_tcap_hash": expected_policy_hash,
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
