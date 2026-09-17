from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Append-only seal for T85 sprint evidence")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--gate", required=True)
    args = parser.parse_args()
    root = args.directory.resolve(strict=True)
    manifest_path = root / "MANIFEST.json"
    sums_path = root / "SHA256SUMS"
    if manifest_path.exists() or sums_path.exists():
        raise SystemExit("evidence is already sealed; overwrite denied")
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path not in {manifest_path, sums_path}
    )
    entries = {path.relative_to(root).as_posix(): sha256(path) for path in files}
    manifest = {
        "schema": "casulo.t85.evidence-manifest/1.0",
        "gate": args.gate,
        "append_only": True,
        "files": entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    lines = [f"{value}  {name}\n" for name, value in sorted(entries.items())]
    lines.append(f"{sha256(manifest_path)}  MANIFEST.json\n")
    sums_path.write_text("".join(lines), encoding="ascii", newline="\n")
    print(json.dumps({"gate": args.gate, "files": len(entries), "manifest_sha256": sha256(manifest_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
