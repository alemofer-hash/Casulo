from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_product_alpha_qemu import validate_product_boot
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256


MODEL_ITEM = "opt/com.teloscorp.casulo/model.gguf"
MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
MODEL_BYTES = 2_497_280_256
MODEL = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362/model/Qwen3-4B-Q4_K_M.gguf"
)

EXPECTED_MARKERS = (
    "CASULO_NATIVE_MODEL_PAGED_IO=PRESENT",
    "CASULO_NATIVE_MODEL_PAGED_TRANSPORT=qemu-fw-cfg-dma-read-only/0.1",
    "CASULO_NATIVE_MODEL_PAGED_ITEM=" + MODEL_ITEM,
    "CASULO_NATIVE_MODEL_PAGED_SOURCE_SHA256_HOST_VERIFIED=" + MODEL_SHA256,
    "CASULO_NATIVE_MODEL_PAGED_SOURCE_BYTES=2497280256",
    "CASULO_NATIVE_MODEL_PAGED_GGUF_VERSION=3",
    "CASULO_NATIVE_MODEL_PAGED_METADATA=28",
    "CASULO_NATIVE_MODEL_PAGED_TENSORS=398",
    "CASULO_NATIVE_MODEL_PAGED_DATA_OFFSET=5956352",
    "CASULO_NATIVE_MODEL_PAGED_F32_OFFSET=5956352",
    "CASULO_NATIVE_MODEL_PAGED_Q6_K_OFFSET=5966592",
    "CASULO_NATIVE_MODEL_PAGED_Q4_K_OFFSET=325032192",
    "CASULO_NATIVE_MODEL_PAGED_Q4_K_DOT_F32_BITS=3e294826",
    "CASULO_NATIVE_MODEL_PAGED_Q6_K_DOT_F32_BITS=bc705310",
    "CASULO_NATIVE_MODEL_PAGED_TAIL_OFFSET=2497280192",
    "CASULO_NATIVE_MODEL_PAGED_CORRUPTION=QUARANTINE",
    "CASULO_NATIVE_MODEL_PAGED_OOB=QUARANTINE",
    "CASULO_NATIVE_MODEL_PAGED_FULL_FILE_ACCESSIBLE=YES",
    "CASULO_NATIVE_MODEL_PAGED_FULL_FILE_RESIDENT=NO",
    "CASULO_NATIVE_MODEL_PAGED_FULL_SHA256_IN_GUEST=NOT_COMPUTED",
    "CASULO_NATIVE_MODEL_PAGED_FIRST_TOKEN=NO",
    "CASULO_NATIVE_MODEL_PAGED_GATE=PASS",
    "CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED",
)


def build_command(
    qemu: Path,
    code: Path,
    variables: Path,
    image: Path,
    model: Path | None,
    accelerator: str = "tcg",
    memory_mib: int = 256,
) -> list[str]:
    if accelerator not in {"tcg", "whpx"}:
        raise ValueError("unsupported QEMU accelerator")
    if memory_mib not in {256, 4096, 6144}:
        raise ValueError("guest memory profile must be 256, 4096 or 6144 MiB")
    command = [
        str(qemu),
        "-machine",
        f"q35,accel={accelerator}",
        "-m",
        f"{memory_mib}M",
        "-smp",
        "2",
        "-nodefaults",
        "-display",
        "none",
        "-serial",
        "stdio",
        "-monitor",
        "none",
        "-nic",
        "none",
        "-no-reboot",
        "-boot",
        "order=c,strict=on",
        "-device",
        "VGA",
        "-drive",
        f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
        "-drive",
        f"if=pflash,format=raw,unit=1,file={variables}",
        "-device",
        "qemu-xhci,id=casulo-xhci",
        "-drive",
        f"if=none,id=casulo-usb,format=raw,readonly=on,file={image}",
        "-device",
        "usb-storage,bus=casulo-xhci.0,drive=casulo-usb,removable=true",
    ]
    if model is not None:
        if "," in str(model):
            raise ValueError("model path containing comma is not supported by the bounded QEMU command")
        command.extend(["-fw_cfg", f"name={MODEL_ITEM},file={model}"])
    command.extend(["-device", "isa-debug-exit,iobase=0xf4,iosize=0x04"])
    return command


def boot_once(
    image: Path,
    model: Path | None,
    qemu: Path,
    code: Path,
    vars_template: Path,
    timeout: float,
    accelerator: str = "tcg",
    memory_mib: int = 256,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="casulo-native-model-paged-", dir=ROOT / ".tmp") as temporary:
        variables = Path(temporary) / "OVMF_VARS.fd"
        shutil.copyfile(vars_template, variables)
        command = build_command(qemu, code, variables, image, model, accelerator, memory_mib)
        try:
            completed = subprocess.run(
                command,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            returncode, serial, timed_out = completed.returncode, completed.stdout, False
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or ""
            serial = partial.decode("utf-8", errors="replace") if isinstance(partial, bytes) else partial
            returncode, timed_out = -1, True
        return {
            "returncode": returncode,
            "timed_out": timed_out,
            "serial": serial,
            "command_contract": {
                "shell": False,
                "network": False,
                "image_read_only": True,
                "model_fw_cfg_read_only": model is not None,
                "physical_device": False,
                "accelerator": accelerator,
                "memory_mib": memory_mib,
            },
        }


def verified_model(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    expected = MODEL.expanduser().resolve(strict=True)
    if resolved != expected or resolved.is_symlink() or not resolved.is_file():
        raise SystemExit("only the exact adopted owner model cache path is allowed")
    if resolved.stat().st_size != MODEL_BYTES:
        raise SystemExit("adopted model size mismatch")
    if sha256(resolved) != MODEL_SHA256:
        raise SystemExit("adopted model SHA-256 mismatch")
    return resolved


def paged_metrics(serial: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for line in serial.splitlines():
        if line.startswith("CASULO_NATIVE_MODEL_PAGED_") and "=" in line:
            key, value = line.split("=", 1)
            metrics[key] = value
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate paged access to the complete owner GGUF in Native")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--tcap", type=Path, default=ROOT / "release/FloodSurrogate.tcap")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 3 or not 20 <= args.timeout <= 300:
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
        missing = [marker for marker in EXPECTED_MARKERS if marker not in serial]
        forbidden = [
            marker
            for marker in (
                "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL",
                "CASULO_NATIVE_MODEL_PAGED_FIRST_TOKEN=YES",
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
                "paged_metrics": paged_metrics(serial),
                "validation": validation,
            }
        )

    # Two negative controls use no private content beyond the first 4 KiB of a
    # temporary, automatically removed truncation. Neither control can PASS.
    controls: list[dict[str, object]] = []
    missing_boot = boot_once(image, None, qemu, code, variables, args.timeout)
    missing_serial = str(missing_boot["serial"])
    controls.append(
        {
            "case": "missing-model-item",
            "passed": (
                "CASULO_NATIVE_MODEL_PAGED_REJECT=Transport(ModelMissing)" in missing_serial
                and "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL" in missing_serial
                and "CASULO_NATIVE_MODEL_PAGED_GATE=PASS" not in missing_serial
            ),
            "returncode": missing_boot["returncode"],
            "timed_out": missing_boot["timed_out"],
        }
    )
    with tempfile.TemporaryDirectory(prefix="casulo-native-model-truncated-", dir=ROOT / ".tmp") as temporary:
        truncated = Path(temporary) / "truncated.gguf"
        with model.open("rb") as source, truncated.open("wb") as target:
            target.write(source.read(4096))
        truncated_sha = sha256(truncated)
        truncated_boot = boot_once(image, truncated, qemu, code, variables, args.timeout)
        truncated_serial = str(truncated_boot["serial"])
        controls.append(
            {
                "case": "truncated-model-item",
                "bytes": truncated.stat().st_size,
                "sha256": truncated_sha,
                "passed": (
                    "CASULO_NATIVE_MODEL_PAGED_REJECT=Transport(ModelSize)" in truncated_serial
                    and "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL" in truncated_serial
                    and "CASULO_NATIVE_MODEL_PAGED_GATE=PASS" not in truncated_serial
                ),
                "returncode": truncated_boot["returncode"],
                "timed_out": truncated_boot["timed_out"],
            }
        )

    image_after, model_after = sha256(image), sha256(model)
    report = {
        "schema": "casulo-native-model-paged-qemu/0.1",
        "state": "NATIVE_COMPLETE_MODEL_PAGED_IO_VALIDATED",
        "claim": "the complete host-verified owner GGUF was exposed read-only and authentic pages were consumed across the file; no full inference or token",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": image_before,
        "image_sha256_after": image_after,
        "image_unchanged": image_before == image_after,
        "model": {
            "file_name": model.name,
            "bytes": model.stat().st_size,
            "sha256_before": model_before,
            "sha256_after": model_after,
            "unchanged": model_before == model_after,
            "full_sha256_verified_by_host": True,
            "full_sha256_computed_by_guest": False,
        },
        "transport": "qemu-fw-cfg-dma/read-only",
        "guest_network": False,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "full_model_resident_in_guest": False,
        "first_model_derived_token": False,
        "boots": boots,
        "negative_controls": controls,
        "passed": (
            image_before == image_after
            and model_before == model_after
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
