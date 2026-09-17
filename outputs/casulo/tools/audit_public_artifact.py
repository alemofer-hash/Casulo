from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


FORBIDDEN = (
    b"OwnerEngineAdapter",
    b"casulo_owner",
    b"OwnerMotor",
    b"private/casulo-owner",
    b"CASULO_OWNER",
)

FORBIDDEN_ASSET_SUFFIXES = (
    ".gguf", ".safetensors", ".onnx", ".pt", ".pth", ".key", ".pem",
)


def audit(path: Path) -> dict[str, object]:
    path = path.resolve()
    findings: list[dict[str, str]] = []
    files = 0
    digest = hashlib.sha256()

    def inspect(name: str, payload: bytes) -> None:
        nonlocal files
        files += 1
        digest.update(name.encode("utf-8") + b"\0" + payload)
        for forbidden in FORBIDDEN:
            if forbidden.lower() in payload.lower() or forbidden.decode().lower() in name.lower():
                findings.append({"file": name, "forbidden": forbidden.decode()})
        lowered_name = name.lower()
        if lowered_name.endswith(FORBIDDEN_ASSET_SUFFIXES):
            findings.append({"file": name, "forbidden": "private-model-or-key-asset"})

    if path.is_dir():
        for file in sorted(item for item in path.rglob("*") if item.is_file()):
            inspect(file.relative_to(path).as_posix(), file.read_bytes())
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith("/"):
                    inspect(name, archive.read(name))
    else:
        raise ValueError("artefato public precisa ser diretório ou ZIP/wheel")
    return {
        "schema": "casulo-public-audit/1.0",
        "artifact": str(path),
        "files_scanned": files,
        "content_tree_sha256": digest.hexdigest(),
        "forbidden_findings": findings,
        "private_components_absent": not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.artifact)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["private_components_absent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
