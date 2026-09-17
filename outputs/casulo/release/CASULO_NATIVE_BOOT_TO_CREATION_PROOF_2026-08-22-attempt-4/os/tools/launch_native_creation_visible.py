#!/usr/bin/env python3
"""Launch the sealed NP10 image with a visible display and append-only serial log.

This is a human-observation launcher, not an acceptance oracle. The sealed
automated reports remain the authority for PASS/FAIL. Paths are validated and
QEMU is always invoked with shell=False, networking disabled and regular
read-only image/model inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_native_model_paged_qemu import MODEL, MODEL_SHA256, build_command, verified_model  # noqa: E402
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256  # noqa: E402


# Updated by the append-only NP10 reseal after the final telemetry build.
SEALED_IMAGE_SHA256 = "25193857a96d6c14328d92fb128d6e666a31478dee05cc8cca6a35252932a534"
PASS_MARKERS = (
    "CASULO_NATIVE_CREATION_GATE=PASS",
    "CASULO_NATIVE_CREATION_STATE=MATERIALIZED",
    "CASULO_NATIVE_CREATION_LATE_OUTPUT_PUBLISHED=NO",
    "CASULO_NATIVE_NEURAL_INFERENCE=BOOT_TO_CREATION_T_AUTHORIZED",
    "G7_DEMO_COMPLETE=PASS",
)


def _reader(stream, lines: queue.Queue[str | None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.put(line)
    finally:
        lines.put(None)


def _visible_command(command: list[str]) -> list[str]:
    result = list(command)
    index = result.index("-display")
    if result[index + 1] != "none":
        raise RuntimeError("unexpected bounded QEMU display contract")
    result[index + 1] = "default"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the sealed Casulo Native boot-to-creation proof")
    parser.add_argument(
        "--image",
        type=Path,
        default=ROOT / "release/casulo-native-neural-port-np10-attempt-5.img",
    )
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    parser.add_argument("--accelerator", choices=("whpx", "tcg"), default="whpx")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    if not 120 <= args.timeout <= 1800:
        raise SystemExit("timeout must be between 120 and 1800 seconds")

    image = safe_regular_workspace_file(args.image)
    if sha256(image) != SEALED_IMAGE_SHA256:
        raise SystemExit("sealed NP10 image hash mismatch")
    model = verified_model(args.model)
    if sha256(model) != MODEL_SHA256:
        raise SystemExit("adopted owner model hash mismatch")
    qemu = args.qemu.resolve(strict=True)
    code = args.ovmf_code.resolve(strict=True)
    vars_template = args.ovmf_vars.resolve(strict=True)

    session_root = Path(os.environ.get("LOCALAPPDATA", str(ROOT / ".tmp"))) / "Casulo/native-creation-proof"
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    session = session_root / session_id
    session.mkdir(parents=True, exist_ok=False)
    variables = session / "OVMF_VARS.fd"
    serial_path = session / "serial.log"
    report_path = session / "session.json"
    shutil.copyfile(vars_template, variables)

    command = _visible_command(build_command(qemu, code, variables, image, model, args.accelerator, 6144))
    print("Casulo Native — boot-to-creation proof", flush=True)
    print(f"Serial append-only: {serial_path}", flush=True)
    print("A janela grafica mostra apenas estados derivados de eventos reais.", flush=True)
    print("Ctrl-C durante uma janela de token solicita cancelamento cooperativo.", flush=True)

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        shell=False,
    )
    assert process.stdout is not None
    lines: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_reader, args=(process.stdout, lines), daemon=True)
    reader.start()
    serial: list[str] = []
    cancellation_sent = False
    try:
        while True:
            line = lines.get()
            if line is None:
                break
            serial.append(line)
            print(line, end="", flush=True)
    except KeyboardInterrupt:
        if process.stdin is not None and process.poll() is None:
            process.stdin.write("\x03")
            process.stdin.flush()
            cancellation_sent = True
            print("\nCancelamento encaminhado ao kernel; aguardando boundary seguro...", flush=True)
            while True:
                line = lines.get()
                if line is None:
                    break
                serial.append(line)
                print(line, end="", flush=True)

    returncode = process.wait(timeout=30)
    reader.join(timeout=2)
    serial_text = "".join(serial)
    serial_path.write_text(serial_text, encoding="utf-8", newline="\n")
    completed = all(marker in serial_text for marker in PASS_MARKERS)
    cancelled = "CASULO_NATIVE_CREATION_STATE=CANCELLED_CLEAN" in serial_text
    result = {
        "schema": "casulo-native-visible-session/1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "image_sha256": sha256(image),
        "model_sha256": sha256(model),
        "serial_sha256": hashlib.sha256(serial_text.encode("utf-8")).hexdigest(),
        "returncode": returncode,
        "completed_gate_markers": completed,
        "cancelled_clean": cancelled,
        "cancellation_sent": cancellation_sent,
        "network": False,
        "physical_device": False,
        "image_read_only": True,
        "model_read_only": True,
        "shell": False,
        "claim_boundary": "human observation only; sealed automated reports decide acceptance",
    }
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0 if returncode == 33 and (completed or cancelled) else 2


if __name__ == "__main__":
    raise SystemExit(main())
