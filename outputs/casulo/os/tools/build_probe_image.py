from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OS_ROOT = ROOT / "os"
PROBE_ROOT = ROOT / "evidence/casulo-os-rp01/g2/platform-probes"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an isolated fail-closed kernel probe image.")
    parser.add_argument("mode", choices=("panic", "reboot"))
    args = parser.parse_args()
    output = PROBE_ROOT / f"casulo-{args.mode}-probe.img"
    environment = os.environ.copy()
    environment["CASULO_BOOT_PROBE"] = args.mode
    completed = subprocess.run(
        ["cargo", "run", "--release", "--locked"],
        cwd=OS_ROOT,
        env=environment,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
    )
    generated = Path(completed.stdout.strip().splitlines()[-1]).resolve(strict=True)
    if OS_ROOT.resolve() not in generated.parents:
        raise RuntimeError(f"generated probe escaped bounded build roots: {generated}")
    PROBE_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(generated, output)
    record = {
        "schema": "casulo-kernel-probe-image/0.1",
        "mode": args.mode,
        "path": output.relative_to(ROOT).as_posix(),
        "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "normal_release_image_modified": False,
        "physical_device_written": False,
    }
    (PROBE_ROOT / f"{args.mode}-build.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
