from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OS_ROOT = ROOT / "os"
RELEASE = ROOT / "release"
IMAGE = RELEASE / "casulo-native-x86_64.img"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    result = subprocess.run(
        ["cargo", "run", "--release", "--locked"],
        cwd=OS_ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
    )
    generated = Path(result.stdout.strip().splitlines()[-1]).resolve()
    if not generated.is_file() or OS_ROOT.resolve() not in generated.parents:
        raise RuntimeError(f"unsafe or missing generated image: {generated}")
    RELEASE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(generated, IMAGE)
    digest = sha256(IMAGE)
    (RELEASE / "casulo-native-x86_64.img.sha256").write_text(
        f"{digest}  {IMAGE.name}\n", encoding="ascii"
    )
    record = {
        "schema": "casulo-native-image/0.1",
        "image": IMAGE.relative_to(ROOT).as_posix(),
        "bytes": IMAGE.stat().st_size,
        "sha256": digest,
        "bootloader": "rust-osdev-bootloader/0.11.15",
        "target": "x86_64-unknown-none",
        "physical_device_written": False,
    }
    (RELEASE / "image-build.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

