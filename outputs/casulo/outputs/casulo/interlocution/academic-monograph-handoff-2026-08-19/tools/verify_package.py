from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
errors: list[str] = []
seen: set[str] = set()
for item in manifest["files"]:
    rel = item["path"]
    seen.add(rel)
    path = ROOT / Path(rel)
    if not path.is_file():
        errors.append(f"MISSING {rel}")
        continue
    if path.stat().st_size != item["bytes"]:
        errors.append(f"SIZE {rel}")
    if sha256(path) != item["sha256"]:
        errors.append(f"SHA256 {rel}")

actual = {
    path.relative_to(ROOT).as_posix()
    for path in ROOT.rglob("*")
    if path.is_file()
    and path.name not in {"MANIFEST.json", "SHA256SUMS"}
    and path.suffix.lower() != ".zip"
}
for rel in sorted(actual - seen):
    errors.append(f"UNMANIFESTED {rel}")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f'PASS files={len(seen)} bytes={manifest["total_bytes"]}')
