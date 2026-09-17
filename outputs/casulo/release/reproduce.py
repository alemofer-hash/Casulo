from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPRO_TMP = ROOT / "reproduce-tmp"


def run(*arguments: str) -> None:
    REPRO_TMP.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    # The host's global pytest temp root can be ACL-blocked.  A workspace-local
    # temp root is part of the reproducible runner contract and also keeps
    # generated executables on the same volume as the checkout.
    environment["TMP"] = str(REPRO_TMP)
    environment["TEMP"] = str(REPRO_TMP)
    subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild and validate the locally executable Casulo SO evidence chain."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="retained compatibility flag; G7 always requires ten rehearsals",
    )
    parser.add_argument("--skip-host-tests", action="store_true")
    args = parser.parse_args()

    run("release/verify_toolchain.py")
    if not args.skip_host_tests:
        run(
            "-m",
            "pytest",
            "-q",
            "--basetemp=reproduce-tmp/pytest",
            "tests/test_t_tcap.py",
            "tests/test_t_learn_native.py",
            "tests/test_livelab_ablations.py",
            "tests/test_livelab_workloads.py",
            "tests/test_demo_harness.py",
            "tests/test_release_package.py",
        )
    run("tools/rebuild_flood_tcap.py")
    run("tools/verify_flood_tcap.py")
    run("os/tools/build_image.py")
    image = "release/casulo-native-x86_64.img"
    tcap = "release/FloodSurrogate.tcap"
    run("os/tools/run_g2_full_qemu.py", "--image", image, "--repeat", "1")
    run(
        "os/tools/run_g3_qemu.py",
        "--image",
        image,
        "--tcap",
        tcap,
        "--repeat",
        "1",
    )
    run("os/tools/run_g4_qemu.py", "--image", image, "--repeat", "1")
    run("release/package_release.py", "--verify-only")
    run(
        "release/demo_harness.py",
        "--repeat",
        "10",
    )
    run("release/package_release.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
