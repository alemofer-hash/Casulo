from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


FORBIDDEN_SUFFIXES = (".gguf", ".safetensors", ".onnx", ".pt", ".pth", ".key", ".pem")
FORBIDDEN_TEXT = (b"DeterministicFakeEngine", b"api.openai.com", b"api.anthropic.com")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def audit_and_extract(archive_path: Path, destination: Path) -> dict[str, object]:
    archive_path = archive_path.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("extraction destination already exists; overwrite denied")
    findings: list[dict[str, str]] = []
    files: list[dict[str, object]] = []
    with zipfile.ZipFile(archive_path) as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        for info in infos:
            logical = PurePosixPath(info.filename)
            if logical.is_absolute() or ".." in logical.parts or ":" in info.filename:
                raise RuntimeError(f"unsafe archive member: {info.filename}")
        destination.mkdir(parents=True)
        for info in infos:
            payload = archive.read(info)
            target = destination.joinpath(*PurePosixPath(info.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            for marker in FORBIDDEN_TEXT:
                if marker.lower() in payload.lower():
                    findings.append({"file": info.filename, "forbidden": marker.decode("ascii")})
            if info.filename.casefold().endswith(FORBIDDEN_SUFFIXES):
                findings.append({"file": info.filename, "forbidden": "model-weight-or-secret-asset"})
            files.append({"path": info.filename, "bytes": len(payload), "sha256": sha256_bytes(payload)})

    artifact_manifest = json.loads((destination / "OWNER_ARTIFACT.json").read_text(encoding="utf-8"))
    expected = {item["path"]: item["sha256"] for item in artifact_manifest["files"]}
    actual = {item["path"]: item["sha256"] for item in files if item["path"] != "OWNER_ARTIFACT.json"}
    checks = {
        "safe_member_paths": True,
        "manifest_exact": actual == expected,
        "no_fake_or_external_api": not findings,
        "weights_not_embedded": not any(item["path"].casefold().endswith(FORBIDDEN_SUFFIXES) for item in files),
        "owner_profile": artifact_manifest.get("profile") == "casulo-owner",
        "semantic_multiverse": artifact_manifest.get("semantic_multiverse") is True,
        "cloud_locked": artifact_manifest.get("cloud_state") == "RELEASE_LOCKED",
    }
    return {
        "schema": "casulo-owner-extracted-artifact-audit/1.0",
        "archive": str(archive_path),
        "destination": str(destination),
        "checks": checks,
        "findings": findings,
        "files": files,
        "pass": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_and_extract(args.archive, args.destination)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
