#!/usr/bin/env python3
"""Embed the exact adopted owner model in a streaming UEFI system pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from build_native_system_pack import KINDS, build_from_paths, parse_file, sha256_file  # noqa: E402


MODEL_BYTES = 2_497_280_256
MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
DEFAULT_MODEL = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362/model/Qwen3-4B-Q4_K_M.gguf"
)
DEFAULT_BASE = ROOT / "release/casulo-native-neural-port-system-pack-np10.cspk.manifest.json"
DEFAULT_OUTPUT = ROOT / "release/casulo-native-physical-creation-system-pack-v1.cspk"


def _sha(path: Path) -> str:
    return sha256_file(path).hex()


def _inside_repo(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if ROOT.resolve() not in resolved.parents or not resolved.is_file() or resolved.is_symlink():
        raise SystemExit(f"unsafe repository source: {path}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Build append-only physical Native creation pack")
    parser.add_argument("--base-pack-manifest", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    base_manifest_path = _inside_repo(args.base_pack_manifest)
    base = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    if base.get("schema") != "casulo-native-creation-system-pack/1.0":
        raise SystemExit("base creation pack schema mismatch")
    base_pack = _inside_repo(ROOT / str(base["file"]))
    if _sha(base_pack) != base.get("sha256"):
        raise SystemExit("base creation pack hash mismatch")

    model = args.model.expanduser().resolve(strict=True)
    if not model.is_file() or model.is_symlink() or model.stat().st_size != MODEL_BYTES:
        raise SystemExit("adopted owner model identity/size mismatch")
    if _sha(model) != MODEL_SHA256:
        raise SystemExit("adopted owner model SHA-256 mismatch")

    sources: list[tuple[str, Path]] = []
    for entry in base.get("entries", []):
        name = str(entry["name"])
        source = _inside_repo(ROOT / str(entry["source"]))
        if KINDS.get(name) != int(entry["kind"]) or _sha(source) != entry.get("source_sha256"):
            raise SystemExit(f"base entry identity mismatch: {name}")
        sources.append((name, source))
    if [name for name, _ in sources] != [
        "BOOTSTRAP_TCAP", "UX_CONTRACT", "GUIDE_T_SOURCE", "MODEL_GGUF_PROBE",
        "NATIVE_SAMPLING_POLICY", "NATIVE_CREATION_PROMPT",
        "NATIVE_CREATION_ARTIFACT", "NATIVE_CREATION_ACCEPTANCE",
    ]:
        raise SystemExit("base creation pack entry order mismatch")
    sources.append(("NATIVE_MODEL_GGUF", model))

    output = args.output.resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    records = build_from_paths(output, [(KINDS[name], path) for name, path in sources])
    if parse_file(output) != records:
        raise SystemExit("streaming pack verification mismatch")
    pack_sha = _sha(output)
    record = {
        "schema": "casulo-native-physical-creation-system-pack/1.0",
        "file": output.relative_to(ROOT).as_posix(),
        "bytes": output.stat().st_size,
        "sha256": pack_sha,
        "base_pack_manifest": base_manifest_path.relative_to(ROOT).as_posix(),
        "base_pack_sha256": base["sha256"],
        "entries": [
            {
                "name": name,
                "kind": KINDS[name],
                "source": (
                    "<owner-cache>/qwen3-4b-q4km-llamacpp-b10362/Qwen3-4B-Q4_K_M.gguf"
                    if name == "NATIVE_MODEL_GGUF"
                    else path.relative_to(ROOT).as_posix()
                ),
                "source_sha256": _sha(path),
                **records[index],
            }
            for index, (name, path) in enumerate(sources)
        ],
        "model_embedded": True,
        "model_bytes": MODEL_BYTES,
        "model_sha256": MODEL_SHA256,
        "transport": "uefi-ramdisk-content-addressed/1.0",
        "full_model_second_copy": False,
        "network": False,
        "external_api": False,
        "physical_device_written": False,
        "fat32_single_file_limit_pass": output.stat().st_size < 4 * 1024**3 - 1,
    }
    manifest = output.with_suffix(output.suffix + ".manifest.json")
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{pack_sha}  {output.name}\n", encoding="ascii"
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
