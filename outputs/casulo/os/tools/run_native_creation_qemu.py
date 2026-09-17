from __future__ import annotations

import argparse
import json
import queue
import re
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

from run_native_model_paged_qemu import MODEL, MODEL_SHA256, build_command, verified_model  # noqa: E402
from run_product_alpha_qemu import validate_product_boot  # noqa: E402
from run_qemu import (  # noqa: E402
    DEFAULT_CODE,
    DEFAULT_QEMU,
    DEFAULT_VARS,
    ROOT,
    safe_regular_workspace_file,
    sha256,
)


EXPECTED_OUTPUT_IDS = (
    45, 11408, 28, 8373, 5404, 285, 67737, 436, 26, 62721, 5049, 46, 28,
    8373, 5404, 285, 67737, 436, 26, 1825, 49, 32293, 28, 32615, 16, 11,
    32615, 17, 26, 7778, 51171, 28, 32361, 13,
)
EXPECTED_TEXT = "NOME=SomeDoisNumeros;FUNCAO=SomeDoisNumeros;ENTRADA=numero1,numero2;SAIDA=resultado."
EXPECTED_POSITIONS = 83
EXPECTED_BLOCKS = EXPECTED_POSITIONS * 36
EXPECTED_MATVECS = EXPECTED_POSITIONS * 253
EXPECTED_QUANTIZED_BLOCKS = EXPECTED_POSITIONS * 15_712_000
EXPECTED_WEIGHT_BYTES = EXPECTED_POSITIONS * 2_490_539_520
EXPECTED_MACS = EXPECTED_POSITIONS * 4_022_272_000


def _reader(stream, lines: queue.Queue[str | None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.put(line)
    finally:
        lines.put(None)


def boot_streaming(
    image: Path,
    model: Path | None,
    qemu: Path,
    code: Path,
    vars_template: Path,
    timeout: float,
    *,
    accelerator: str,
    memory_mib: int,
    cancel_after_first_token: bool,
) -> dict[str, object]:
    temporary_root = ROOT / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="casulo-native-creation-", dir=temporary_root) as temporary:
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
                cancel_after_first_token
                and not cancellation_sent
                and "CASULO_NATIVE_CREATION_CANCEL_WINDOW=OPEN" in line
            ):
                assert process.stdin is not None
                process.stdin.write("\x03")
                process.stdin.flush()
                cancellation_sent = True
        process.wait(timeout=10)
        reader.join(timeout=2)
        return {
            "returncode": process.returncode,
            "timed_out": timed_out,
            "elapsed_seconds": time.monotonic() - started,
            "serial": "".join(serial_parts),
            "cancellation_sent": cancellation_sent,
            "command_contract": {
                "shell": False,
                "network": False,
                "image_read_only": True,
                "model_fw_cfg_read_only": model is not None,
                "model_transport": "qemu-fw-cfg" if model is not None else "uefi-ramdisk",
                "physical_device": False,
                "accelerator": accelerator,
                "memory_mib": memory_mib,
                "serial_streamed_live": True,
            },
        }


def extract_metrics(serial: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for line in serial.splitlines():
        if line.startswith(("CASULO_NATIVE_CREATION_", "CASULO_NATIVE_NEURAL_INFERENCE")) and "=" in line:
            key, value = line.split("=", 1)
            metrics[key] = value
    return metrics


def _expected_markers(
    manifest: dict[str, object], cancelled: bool, *, physical_model: bool = False
) -> tuple[str, ...]:
    policies = manifest["policies"]
    assert isinstance(policies, dict)
    token = policies["token"]
    artifact = policies["artifact"]
    acceptance = policies["acceptance"]
    assert isinstance(token, dict) and isinstance(artifact, dict) and isinstance(acceptance, dict)
    common = (
        f"CASULO_NATIVE_SYSTEM_PACK_ENTRIES={9 if physical_model else 8}",
        "CASULO_NATIVE_SYSTEM_PACK_CREATION_PROMPT=PRESENT",
        "CASULO_NATIVE_SYSTEM_PACK_CREATION_ARTIFACT=PRESENT",
        "CASULO_NATIVE_SYSTEM_PACK_CREATION_ACCEPTANCE=PRESENT",
        "CASULO_NATIVE_SYSTEM_PACK_FULL_MODEL="
        + ("PRESENT_VALIDATED" if physical_model else "ABSENT"),
        "CASULO_NATIVE_SYSTEM_PACK_GATE=PASS",
        "CASULO_NATIVE_CREATION=EXECUTED",
        f"CASULO_NATIVE_CREATION_TOKEN_POLICY_TCAP_HASH={token['tcap_hash']}",
        "CASULO_NATIVE_CREATION_GATE=PASS",
        "CASULO_NATIVE_CREATION_LATE_OUTPUT_PUBLISHED=NO",
        "G7_DEMO_COMPLETE=PASS",
    )
    if cancelled:
        return common + (
            "CASULO_NATIVE_CREATION_CANCEL=ACCEPTED",
            "CASULO_NATIVE_CREATION_STATE=CANCELLED_CLEAN",
            "CASULO_NATIVE_CREATION_OUTPUT_TOKENS=1",
            "CASULO_NATIVE_CREATION_CANCELLED=YES",
            "CASULO_NATIVE_CREATION_ACCEPTANCE=NOT_PUBLISHED",
            "CASULO_NATIVE_NEURAL_INFERENCE=NATIVE_CREATION_CANCELLED_CLEAN",
        )
    return common + (
        "CASULO_NATIVE_CREATION_STATE=MATERIALIZED",
        "CASULO_NATIVE_CREATION_MODEL_TRANSPORT="
        + ("uefi-ramdisk-content-addressed/1.0" if physical_model else "qemu-fw-cfg-resident/0.1"),
        "CASULO_NATIVE_FULL_MODEL_RESIDENT=YES",
        "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=YES",
        f"CASULO_NATIVE_CREATION_MODEL_SOURCE_BYTES_LOADED={MODEL.stat().st_size}",
        "CASULO_NATIVE_CREATION_PROMPT_TOKENS=50",
        "CASULO_NATIVE_CREATION_OUTPUT_TOKENS=34",
        "CASULO_NATIVE_CREATION_OUTPUT_IDS=" + ",".join(str(value) for value in EXPECTED_OUTPUT_IDS),
        "CASULO_NATIVE_CREATION_OUTPUT_TEXT_HEX=" + EXPECTED_TEXT.encode("utf-8").hex(),
        f"CASULO_NATIVE_CREATION_MODEL_POSITIONS={EXPECTED_POSITIONS}",
        f"CASULO_NATIVE_CREATION_BLOCKS_COMPLETED={EXPECTED_BLOCKS}",
        f"CASULO_NATIVE_CREATION_MATVEC_CALLS={EXPECTED_MATVECS}",
        f"CASULO_NATIVE_CREATION_QUANTIZED_BLOCKS={EXPECTED_QUANTIZED_BLOCKS}",
        f"CASULO_NATIVE_CREATION_WEIGHT_BYTES_READ={EXPECTED_WEIGHT_BYTES}",
        f"CASULO_NATIVE_CREATION_MULTIPLY_ACCUMULATES={EXPECTED_MACS}",
        "CASULO_NATIVE_CREATION_SPEC=PASS",
        f"CASULO_NATIVE_CREATION_GENERATED_T_SOURCE_SHA256={artifact['source_sha256']}",
        f"CASULO_NATIVE_CREATION_COMPILED_T_SOURCE_SHA256={artifact['source_sha256']}",
        "CASULO_NATIVE_CREATION_CONTENT_ADDRESS_GATE=PASS",
        f"CASULO_NATIVE_CREATION_ARTIFACT_TCAP_HASH={artifact['tcap_hash']}",
        "CASULO_NATIVE_CREATION_ARTIFACT_RESULT=18",
        "CASULO_NATIVE_CREATION_SIMULATION=PASS",
        f"CASULO_NATIVE_CREATION_ACCEPTANCE_TCAP_HASH={acceptance['tcap_hash']}",
        "CASULO_NATIVE_CREATION_ACCEPTANCE=PASS",
        "CASULO_NATIVE_CREATION_CANCELLED=NO",
        "CASULO_NATIVE_CREATION_SCENE_FORM=Materialized",
        "CASULO_NATIVE_NEURAL_INFERENCE=BOOT_TO_CREATION_T_AUTHORIZED",
    )


def _dynamic_markers_valid(serial: str, cancelled: bool) -> list[str]:
    failures: list[str] = []
    for key in (
        "CASULO_NATIVE_CREATION_TOKEN_RECEIPT_CHAIN_TAIL",
        "CASULO_NATIVE_CREATION_FRAMEBUFFER_FINGERPRINT",
    ):
        match = re.search(rf"(?m)^{re.escape(key)}=([0-9a-f]+)$", serial)
        if match is None or int(match.group(1), 16) == 0:
            failures.append(f"{key}=nonzero-hex")
    if not cancelled:
        for key in (
            "CASULO_NATIVE_CREATION_MATERIALIZATION_SHA256",
            "CASULO_NATIVE_CREATION_ACCEPTANCE_RECEIPT_HASH",
        ):
            match = re.search(rf"(?m)^{re.escape(key)}=([0-9a-f]{{64}})$", serial)
            if match is None or int(match.group(1), 16) == 0:
                failures.append(f"{key}=nonzero-sha256")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Native Qwen3 boot-to-creation with causal T gates")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--model-source", choices=("fw-cfg", "ramdisk"), default="fw-cfg")
    parser.add_argument("--tcap", type=Path, default=ROOT / "release/FloodSurrogate.tcap")
    parser.add_argument("--pack-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--cancel-after-first-token", action="store_true")
    parser.add_argument("--accelerator", choices=("whpx", "tcg"), default="whpx")
    parser.add_argument("--memory-mib", type=int, choices=(6144,), default=6144)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 3 or not 120 <= args.timeout <= 1800:
        raise SystemExit("invalid repeat/timeout")

    image = safe_regular_workspace_file(args.image)
    tcap = safe_regular_workspace_file(args.tcap)
    pack_manifest_path = safe_regular_workspace_file(args.pack_manifest)
    manifest = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    expected_schema = (
        "casulo-native-physical-creation-system-pack/1.0"
        if args.model_source == "ramdisk"
        else "casulo-native-creation-system-pack/1.0"
    )
    if manifest.get("schema") != expected_schema:
        raise SystemExit("creation pack manifest schema mismatch")
    if args.model_source == "ramdisk":
        if manifest.get("model_sha256") != MODEL_SHA256 or manifest.get("model_embedded") is not True:
            raise SystemExit("physical pack model identity mismatch")
        base_manifest = safe_regular_workspace_file(ROOT / str(manifest["base_pack_manifest"]))
        base = json.loads(base_manifest.read_text(encoding="utf-8"))
        if base.get("sha256") != manifest.get("base_pack_sha256") or not isinstance(base.get("policies"), dict):
            raise SystemExit("physical pack base policy identity mismatch")
        manifest = {**manifest, "policies": base["policies"]}
        model = None
    else:
        model = verified_model(args.model)
    qemu = args.qemu.resolve(strict=True)
    code = args.ovmf_code.resolve(strict=True)
    variables = args.ovmf_vars.resolve(strict=True)
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    if output.exists():
        raise SystemExit(f"append-only output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    image_before = sha256(image)
    model_before = sha256(model) if model is not None else MODEL_SHA256
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
            cancel_after_first_token=args.cancel_after_first_token,
        )
        serial = str(boot["serial"])
        serial_path = output.with_name(f"{output.stem}.boot-{attempt:02d}.serial.log")
        if serial_path.exists():
            raise SystemExit(f"append-only serial output exists: {serial_path}")
        serial_path.write_text(serial, encoding="utf-8")
        validation = validate_product_boot(boot, sha256(tcap), require_system_pack=False)
        validation["missing_markers"] = [
            marker for marker in validation["missing_markers"]
            if marker != "CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED"
        ]
        expected = _expected_markers(
            manifest,
            args.cancel_after_first_token,
            physical_model=args.model_source == "ramdisk",
        )
        validation["missing_markers"].extend(marker for marker in expected if marker not in serial)
        validation["missing_markers"].extend(_dynamic_markers_valid(serial, args.cancel_after_first_token))
        forbidden = (
            "CASULO_NATIVE_CREATION_GATE=FAIL",
            "CASULO_NATIVE_CREATION=QUARANTINE",
            "CASULO_NATIVE_CREATION_LATE_OUTPUT_PUBLISHED=YES",
            "OWNER_GENERATIVE_BRIDGE=PASS",
        )
        validation["forbidden_markers"].extend(marker for marker in forbidden if marker in serial)
        validation["passed"] = bool(
            boot["returncode"] == 33
            and not boot["timed_out"]
            and (not args.cancel_after_first_token or boot["cancellation_sent"])
            and not validation["missing_markers"]
            and not validation["forbidden_markers"]
        )
        boots.append({
            "attempt": attempt,
            "returncode": boot["returncode"],
            "timed_out": boot["timed_out"],
            "elapsed_seconds": boot["elapsed_seconds"],
            "cancellation_sent": boot["cancellation_sent"],
            "serial_file": serial_path.relative_to(ROOT).as_posix(),
            "serial_sha256": sha256(serial_path),
            "metrics": extract_metrics(serial),
            "validation": validation,
        })

    image_after = sha256(image)
    model_after = sha256(model) if model is not None else MODEL_SHA256
    report = {
        "schema": "casulo-native-boot-to-creation-qemu/1.0",
        "state": "NATIVE_CREATION_CANCELLATION_VALIDATED" if args.cancel_after_first_token else "CASULO_NATIVE_BOOT_TO_CREATION_PROOF",
        "mode": "cancel-after-first-token" if args.cancel_after_first_token else "complete-creation",
        "claim": "a bounded natural-language request was decoded by the adopted local Qwen3 model in the Native kernel, every token was accepted by compiled T before publication, and the complete output was mapped to a content-addressed T artifact, simulated, materialized and accepted by T" if not args.cancel_after_first_token else "a token derived by the adopted model was published under T and cancellation prevented all later publication and materialization",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": image_before,
        "image_sha256_after": image_after,
        "image_unchanged": image_before == image_after,
        "model_sha256_before": model_before,
        "model_sha256_after": model_after,
        "model_unchanged": model_before == model_after == MODEL_SHA256,
        "pack_manifest": pack_manifest_path.relative_to(ROOT).as_posix(),
        "pack_manifest_sha256": sha256(pack_manifest_path),
        "model_transport": args.model_source,
        "guest_network": False,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "external_api": False,
        "performance_claim": False,
        "energy_claim": False,
        "boots": boots,
        "passed": image_before == image_after and model_before == model_after == MODEL_SHA256
        and all(bool(boot["validation"]["passed"]) for boot in boots),
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "boots"}, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
