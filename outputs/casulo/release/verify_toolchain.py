from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "release/TOOLCHAIN_LOCK.json"
REQUIREMENTS = ROOT / "release/requirements-rp01.lock"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def _executable(name: str, common: str | None = None) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if common and Path(common).is_file():
        return common
    return None


def main() -> int:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    checks: dict[str, dict[str, object]] = {}

    expected_python = lock["validated_host"]["python"]
    actual_python = ".".join(str(item) for item in sys.version_info[:3])
    checks["python"] = {
        "expected": expected_python,
        "actual": actual_python,
        "pass": actual_python == expected_python,
    }
    packages: dict[str, dict[str, object]] = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==", 1)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        packages[name] = {
            "expected": expected,
            "actual": actual,
            "pass": actual == expected,
        }
    checks["python_packages"] = {
        "pass": all(item["pass"] for item in packages.values()),
        "packages": packages,
    }

    rust = lock["rust"]
    rustc_code, rustc_output = _run(
        ["rustc", f"+{rust['toolchain']}", "--version"]
    )
    cargo_code, cargo_output = _run(
        ["cargo", f"+{rust['toolchain']}", "--version"]
    )
    checks["rust"] = {
        "pass": (
            rustc_code == 0
            and cargo_code == 0
            and rustc_output == f"rustc {rust['rustc']}"
            and cargo_output == f"cargo {rust['cargo']}"
            and sha256(ROOT / "os/Cargo.lock") == rust["cargo_lock_sha256"]
            and sha256(ROOT / "os/rust-toolchain.toml")
            == rust["rust_toolchain_sha256"]
        ),
        "rustc": rustc_output,
        "cargo": cargo_output,
        "cargo_lock_sha256": sha256(ROOT / "os/Cargo.lock"),
        "rust_toolchain_sha256": sha256(ROOT / "os/rust-toolchain.toml"),
    }

    commands = {
        "qemu": (
            _executable(
                "qemu-system-x86_64",
                os.environ.get("CASULO_QEMU")
                or r"C:\Program Files\qemu\qemu-system-x86_64.exe",
            ),
            ["--version"],
            lock["native_tools"]["qemu"],
        ),
        "gcc": (_executable("gcc"), ["--version"], lock["native_tools"]["gcc"]),
        "nasm": (_executable("nasm"), ["-v"], lock["native_tools"]["nasm"]),
        "cmake": (
            _executable("cmake"),
            ["--version"],
            lock["native_tools"]["cmake"],
        ),
        "ninja": (
            _executable("ninja"),
            ["--version"],
            lock["native_tools"]["ninja"],
        ),
    }
    for name, (executable, arguments, expected) in commands.items():
        if executable is None:
            checks[name] = {"pass": False, "expected": expected, "actual": None}
            continue
        code, output = _run([executable, *arguments])
        checks[name] = {
            "pass": code == 0 and expected in output,
            "expected_contains": expected,
            "actual": output.splitlines()[0] if output else "",
            "executable": executable,
        }

    passed = all(bool(item["pass"]) for item in checks.values())
    result = {
        "schema": "casulo-so-toolchain-verification/0.1",
        "status": "PASS" if passed else "BLOCKED",
        "checks": checks,
        "installation_performed_by_verifier": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
