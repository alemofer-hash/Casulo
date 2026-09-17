from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the image and run the fail-closed G7 ten-step rehearsal."
    )
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-tcap-build", action="store_true")
    args = parser.parse_args()
    if not args.skip_tcap_build:
        subprocess.run(
            [sys.executable, str(ROOT / "tools/rebuild_flood_tcap.py")],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "tools/verify_flood_tcap.py")],
            cwd=ROOT,
            check=True,
        )
    if not args.skip_build:
        subprocess.run([sys.executable, str(ROOT / "os/tools/build_image.py")], cwd=ROOT, check=True)
    package = subprocess.run(
        [sys.executable, str(ROOT / "release/package_release.py"), "--verify-only"],
        cwd=ROOT,
        check=False,
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "release/demo_harness.py"),
            "--image",
            str(ROOT / "release/casulo-native-x86_64.img"),
            "--tcap",
            str(ROOT / "release/FloodSurrogate.tcap"),
            "--manifest",
            str(ROOT / "release/RELEASE_MANIFEST.json"),
            "--repeat",
            str(args.repeat),
            "--timeout",
            str(args.timeout),
        ],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode if package.returncode == 0 else package.returncode


if __name__ == "__main__":
    raise SystemExit(main())
