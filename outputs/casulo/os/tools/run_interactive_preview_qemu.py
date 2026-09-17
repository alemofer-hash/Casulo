from __future__ import annotations

import argparse
import hashlib
import json
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256
from run_virtual_usb_qemu import build_command


REQUIRED = (
    "G7_DEMO_COMPLETE=PASS",
    "CASULO_NATIVE_RENDERER_GATE=PASS",
    "CASULO_NATIVE_SYSTEM_PACK_GATE=PASS",
    "CASULO_NATIVE_PERSISTENCE_JOURNAL_GATE=PASS",
    "CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED",
    "CASULO_NATIVE_INTERACTIVE_PREVIEW=READY",
    "CASULO_NATIVE_INTERACTIVE_LIMIT=NO_NEURAL_CONVERSATION",
)


def boot_until_ready(image: Path, timeout: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="casulo-interactive-", dir=ROOT / ".tmp") as temporary:
        variables = Path(temporary) / "OVMF_VARS.fd"
        shutil.copyfile(DEFAULT_VARS, variables)
        process = subprocess.Popen(
            build_command(DEFAULT_QEMU, DEFAULT_CODE, variables, image),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        lines: queue.Queue[str | None] = queue.Queue()

        def read_serial() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read_serial, daemon=True)
        reader.start()
        serial: list[str] = []
        deadline = time.monotonic() + timeout
        ready_while_running = False
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if line is None:
                break
            serial.append(line)
            if "CASULO_NATIVE_INTERACTIVE_LIMIT=NO_NEURAL_CONVERSATION" in line and process.poll() is None:
                ready_while_running = True
                break
        was_running = process.poll() is None
        if was_running:
            process.terminate()
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait(timeout=5)
        reader.join(timeout=1)
        while True:
            try:
                line = lines.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                serial.append(line)
        return {
            "returncode": returncode,
            "ready_while_running": ready_while_running,
            "terminated_by_runner": was_running,
            "serial": "".join(serial),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded smoke gate for the non-exiting Native preview")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 5:
        raise SystemExit("repeat must be between 1 and 5")
    image = safe_regular_workspace_file(args.image)
    before = sha256(image)
    boots: list[dict[str, object]] = []
    for attempt in range(1, args.repeat + 1):
        boot = boot_until_ready(image, args.timeout)
        serial = str(boot["serial"])
        missing = [marker for marker in REQUIRED if marker not in serial]
        forbidden = [marker for marker in ("CASULO_KERNEL_FATAL", "CASULO_PANIC_DUMP") if marker in serial]
        boots.append({
            "attempt": attempt,
            "expected_non_exit_observed": boot["ready_while_running"] is True,
            "terminated_by_runner_after_ready": boot["terminated_by_runner"] is True,
            "missing_markers": missing,
            "forbidden_markers": forbidden,
            "serial_sha256": hashlib.sha256(serial.encode("utf-8")).hexdigest(),
            "passed": boot["ready_while_running"] is True and not missing and not forbidden,
        })
    after = sha256(image)
    report = {
        "schema": "casulo-native-interactive-preview-gate/0.1",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": before,
        "image_sha256_after": after,
        "image_unchanged": before == after,
        "boots": boots,
        "network": False,
        "virtual_usb_read_only": True,
        "physical_device_written": False,
        "native_neural_inference": False,
        "passed": before == after and all(boot["passed"] for boot in boots),
    }
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
