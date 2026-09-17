from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _first_file(environment: str, candidates: tuple[str | Path | None, ...]) -> Path:
    configured = os.environ.get(environment)
    ordered = (configured, *candidates)
    for candidate in ordered:
        if candidate:
            path = Path(candidate).expanduser()
            if path.is_file():
                return path.resolve()
    return Path(configured or str(next(item for item in candidates if item is not None)))


DEFAULT_QEMU = _first_file(
    "CASULO_QEMU",
    (
        shutil.which("qemu-system-x86_64"),
        Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe"),
        Path("/usr/bin/qemu-system-x86_64"),
    ),
)
DEFAULT_CODE = _first_file(
    "CASULO_OVMF_CODE",
    (
        Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd"),
        Path("/usr/share/OVMF/OVMF_CODE.fd"),
        Path("/usr/share/edk2/x64/OVMF_CODE.fd"),
    ),
)
DEFAULT_VARS = _first_file(
    "CASULO_OVMF_VARS",
    (
        Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd"),
        Path("/usr/share/OVMF/OVMF_VARS.fd"),
        Path("/usr/share/edk2/x64/OVMF_VARS.fd"),
    ),
)
SUCCESS_MARKER = "G1_BOOT_SMOKE=PASS"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_regular_workspace_file(path: Path) -> Path:
    raw = str(path)
    normalized = raw.replace("\\", "/").lower()
    forbidden = ("//./", "//?/globalroot", "physicaldrive")
    if any(token in normalized for token in forbidden) or normalized.startswith("/dev/"):
        raise ValueError(f"device path refused: {path}")
    if path.is_symlink():
        raise ValueError(f"symbolic-link image refused: {path}")
    resolved = path.resolve(strict=True)
    if ROOT.resolve() not in resolved.parents or not resolved.is_file():
        raise ValueError(f"image must be a regular workspace file: {resolved}")
    return resolved


def boot_once(image: Path, qemu: Path, code: Path, vars_template: Path, timeout: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="casulo-ovmf-", dir=ROOT / ".tmp") as temporary:
        vars_copy = Path(temporary) / "OVMF_VARS.fd"
        shutil.copyfile(vars_template, vars_copy)
        command = [
            str(qemu), "-machine", "q35,accel=tcg", "-m", "256M", "-smp", "2",
            "-nodefaults", "-display", "none", "-serial", "stdio", "-monitor", "none",
            "-nic", "none", "-no-reboot",
            "-device", "VGA",
            "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
            "-drive", f"if=pflash,format=raw,unit=1,file={vars_copy}",
            "-drive", f"if=none,id=casulo,format=raw,readonly=on,file={image}",
            "-device", "virtio-blk-pci,drive=casulo",
            "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
        ]
        try:
            completed = subprocess.run(
                command, timeout=timeout, text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            returncode = completed.returncode
            output = completed.stdout
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            returncode = -1
            partial = exc.stdout or ""
            output = partial.decode("utf-8", errors="replace") if isinstance(partial, bytes) else partial
            timed_out = True
        return {
            "returncode": returncode,
            "timed_out": timed_out,
            "marker": SUCCESS_MARKER in output,
            "framebuffer_painted": "FRAMEBUFFER=painted" in output,
            "serial": output,
            "pass": returncode == 33 and SUCCESS_MARKER in output,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--cooldown-seconds", type=float, default=0.0)
    parser.add_argument("--qemu", type=Path, default=DEFAULT_QEMU)
    parser.add_argument("--ovmf-code", type=Path, default=DEFAULT_CODE)
    parser.add_argument("--ovmf-vars", type=Path, default=DEFAULT_VARS)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        raise SystemExit("repeat must be between 1 and 100")
    batch_size = args.batch_size or args.repeat
    if not 1 <= batch_size <= args.repeat:
        raise SystemExit("batch-size must be between 1 and repeat")
    if not 0.0 <= args.cooldown_seconds <= 60.0:
        raise SystemExit("cooldown-seconds must be between 0 and 60")
    image = safe_regular_workspace_file(args.image)
    qemu = args.qemu.expanduser().resolve()
    code = args.ovmf_code.expanduser().resolve()
    vars_template = args.ovmf_vars.expanduser().resolve()
    for dependency in (qemu, code, vars_template):
        if not dependency.is_file():
            raise SystemExit(f"missing QEMU dependency: {dependency}")
    results: list[dict[str, object]] = []
    batches: list[dict[str, object]] = []
    while len(results) < args.repeat:
        first = len(results)
        count = min(batch_size, args.repeat - first)
        batch = [
            boot_once(image, qemu, code, vars_template, args.timeout)
            for _ in range(count)
        ]
        results.extend(batch)
        batches.append(
            {
                "first_attempt": first + 1,
                "last_attempt": len(results),
                "passed": sum(bool(item["pass"]) for item in batch),
                "all_pass": all(bool(item["pass"]) for item in batch),
            }
        )
        if len(results) < args.repeat and args.cooldown_seconds:
            time.sleep(args.cooldown_seconds)
    summary = {
        "schema": "casulo-qemu-boot/0.1",
        "image": image.relative_to(ROOT).as_posix(),
        "image_sha256": sha256(image),
        "attempts": len(results),
        "passed": sum(bool(item["pass"]) for item in results),
        "all_pass": all(bool(item["pass"]) for item in results),
        "framebuffer_painted_all": all(bool(item["framebuffer_painted"]) for item in results),
        "host_block_devices_attached": False,
        "execution_mode": "segmented-correctness-not-performance",
        "batch_size": batch_size,
        "cooldown_seconds_between_batches": args.cooldown_seconds,
        "batches": batches,
        "thermal_telemetry": {"status": "unavailable", "maximum_c": None},
        "energy": {"status": "unavailable", "joules": None},
        "performance_measured": False,
        "results": results,
    }
    evidence = ROOT / "evidence/casulo-os-rp01/g1"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"qemu-boot-{args.repeat}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))
    return 0 if summary["all_pass"] and summary["framebuffer_painted_all"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
