from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from run_qemu import (
    DEFAULT_CODE,
    DEFAULT_QEMU,
    DEFAULT_VARS,
    ROOT,
    SUCCESS_MARKER,
    safe_regular_workspace_file,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def boot_usb_once(
    image: Path,
    qemu: Path,
    code: Path,
    vars_template: Path,
    timeout: float,
) -> dict[str, object]:
    """Boot a regular workspace image through an emulated USB mass-storage device."""
    with tempfile.TemporaryDirectory(prefix="casulo-usb-ovmf-", dir=ROOT / ".tmp") as temporary:
        vars_copy = Path(temporary) / "OVMF_VARS.fd"
        shutil.copyfile(vars_template, vars_copy)
        command = [
            str(qemu),
            "-machine",
            "q35,accel=tcg",
            "-m",
            "256M",
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
            "-device",
            "VGA",
            "-drive",
            f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
            "-drive",
            f"if=pflash,format=raw,unit=1,file={vars_copy}",
            "-device",
            "qemu-xhci,id=xhci",
            "-drive",
            f"if=none,id=casulo_usb,format=raw,readonly=on,file={image}",
            "-device",
            "usb-storage,drive=casulo_usb,removable=on,bootindex=1",
            "-device",
            "isa-debug-exit,iobase=0xf4,iosize=0x04",
        ]
        completed = subprocess.run(
            command,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        serial = completed.stdout
        return {
            "returncode": completed.returncode,
            "marker": SUCCESS_MARKER in serial,
            "framebuffer_painted": "FRAMEBUFFER=painted" in serial,
            "serial": serial,
            "pass": completed.returncode == 33 and SUCCESS_MARKER in serial,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Boot a regular-file Casulo image as read-only virtual USB; physical devices are refused."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        raise SystemExit("repeat must be between 1 and 100")
    image = safe_regular_workspace_file(args.image)
    for dependency in (DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS):
        if not dependency.is_file():
            raise SystemExit(f"missing QEMU dependency: {dependency}")

    records = [
        boot_usb_once(image, DEFAULT_QEMU, DEFAULT_CODE, DEFAULT_VARS, args.timeout)
        for _ in range(args.repeat)
    ]
    summary = {
        "schema": "casulo-qemu-virtual-usb/0.1",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256": sha256(image),
        "attempts": len(records),
        "passed": sum(bool(record["pass"]) for record in records),
        "all_pass": all(bool(record["pass"]) for record in records),
        "framebuffer_painted_all": all(bool(record["framebuffer_painted"]) for record in records),
        "transport": "qemu-xhci/usb-storage",
        "image_attached_read_only": True,
        "host_block_devices_attached": False,
        "physical_device_written": False,
        "results": records,
    }
    evidence = ROOT / "evidence/casulo-os-rp01/g6"
    evidence.mkdir(parents=True, exist_ok=True)
    output = evidence / f"qemu-virtual-usb-{args.repeat}.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))
    return 0 if summary["all_pass"] and summary["framebuffer_painted_all"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
