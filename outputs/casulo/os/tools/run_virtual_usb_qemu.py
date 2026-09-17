from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from run_product_alpha_qemu import validate_product_boot
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, ROOT, safe_regular_workspace_file, sha256


PERSISTENCE_MARKERS = (
    "CASULO_NATIVE_PERSISTENCE_ABI=casulo.native-journal/0.1",
    "CASULO_NATIVE_PERSISTENCE_JOURNAL_GATE=PASS",
    "CASULO_NATIVE_PERSISTENCE_MEDIA_WRITES=0",
    "CASULO_NATIVE_REBOOT_PERSISTENCE=NOT_PROVEN",
)


def build_command(qemu: Path, code: Path, variables: Path, image: Path) -> list[str]:
    return [
        str(qemu), "-machine", "q35,accel=tcg", "-m", "256M", "-smp", "2",
        "-nodefaults", "-display", "none", "-serial", "stdio", "-monitor", "none",
        "-nic", "none", "-no-reboot", "-boot", "order=c,strict=on", "-device", "VGA",
        "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
        "-drive", f"if=pflash,format=raw,unit=1,file={variables}",
        "-device", "qemu-xhci,id=casulo-xhci",
        "-drive", f"if=none,id=casulo-usb,format=raw,readonly=on,file={image}",
        "-device", "usb-storage,bus=casulo-xhci.0,drive=casulo-usb,removable=true",
        "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
    ]


def boot_once(image: Path, qemu: Path, code: Path, vars_template: Path, timeout: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="casulo-virtual-usb-", dir=ROOT / ".tmp") as temporary:
        variables = Path(temporary) / "OVMF_VARS.fd"
        shutil.copyfile(vars_template, variables)
        command = build_command(qemu, code, variables, image)
        try:
            completed = subprocess.run(
                command, timeout=timeout, text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            returncode, serial, timed_out = completed.returncode, completed.stdout, False
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or ""
            serial = partial.decode("utf-8", errors="replace") if isinstance(partial, bytes) else partial
            returncode, timed_out = -1, True
        return {"returncode": returncode, "timed_out": timed_out, "serial": serial}


def main() -> int:
    parser = argparse.ArgumentParser(description="Boot Casulo from read-only virtual USB")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--tcap", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10 or not 5 <= args.timeout <= 60:
        raise SystemExit("invalid repeat/timeout")
    image = safe_regular_workspace_file(args.image)
    tcap = safe_regular_workspace_file(args.tcap)
    qemu, code, variables = args.qemu.resolve(), args.ovmf_code.resolve(), args.ovmf_vars.resolve()
    if not all(path.is_file() for path in (qemu, code, variables)):
        raise SystemExit("missing QEMU/OVMF dependency")
    before = sha256(image)
    boots: list[dict[str, object]] = []
    for attempt in range(1, args.repeat + 1):
        boot = boot_once(image, qemu, code, variables, args.timeout)
        validation = validate_product_boot(boot, sha256(tcap), require_system_pack=True)
        missing = [marker for marker in PERSISTENCE_MARKERS if marker not in str(boot["serial"])]
        validation["missing_markers"].extend(missing)
        validation["passed"] = bool(validation["passed"] and not missing)
        boots.append({
            "attempt": attempt,
            "returncode": boot["returncode"],
            "timed_out": boot["timed_out"],
            "validation": validation,
        })
    after = sha256(image)
    report = {
        "schema": "casulo-native-virtual-usb-gate/0.1",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256_before": before,
        "image_sha256_after": after,
        "image_unchanged": before == after,
        "transport": "qemu-xhci/usb-storage",
        "image_read_only": True,
        "guest_network": False,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "boots": boots,
        "passed": before == after and all(boot["validation"]["passed"] for boot in boots),
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
