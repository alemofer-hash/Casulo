from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAGIC = b"CSPK0001"
VERSION = 1
DESCRIPTOR = struct.Struct("<IIQQ32sQ")
KINDS = {
    "BOOTSTRAP_TCAP": 1,
    "UX_CONTRACT": 2,
    "GUIDE_T_SOURCE": 3,
    "MODEL_GGUF_PROBE": 4,
    "NATIVE_SAMPLING_POLICY": 5,
    "NATIVE_CREATION_PROMPT": 6,
    "NATIVE_CREATION_ARTIFACT": 7,
    "NATIVE_CREATION_ACCEPTANCE": 8,
    "NATIVE_MODEL_GGUF": 9,
}
MAX_ENTRIES = 9
COPY_CHUNK_BYTES = 4 * 1024 * 1024


def sha256_bytes(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def sha256_file(path: Path, *, offset: int = 0, length: int | None = None) -> bytes:
    digest = hashlib.sha256()
    remaining = length
    with path.open("rb") as handle:
        handle.seek(offset)
        while remaining is None or remaining > 0:
            requested = COPY_CHUNK_BYTES if remaining is None else min(COPY_CHUNK_BYTES, remaining)
            chunk = handle.read(requested)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    if remaining not in (None, 0):
        raise ValueError("truncated system-pack payload")
    return digest.digest()


def build(entries: list[tuple[int, bytes]]) -> bytes:
    if not 1 <= len(entries) <= MAX_ENTRIES or len({kind for kind, _ in entries}) != len(entries):
        raise ValueError("system pack requires one to nine unique entries")
    header_len = 16 + DESCRIPTOR.size * len(entries)
    offset = header_len
    descriptors = bytearray()
    payload = bytearray()
    for kind, data in entries:
        if kind not in KINDS.values() or not data:
            raise ValueError("invalid or empty system-pack entry")
        descriptors.extend(DESCRIPTOR.pack(kind, 1, offset, len(data), sha256_bytes(data), 0))
        payload.extend(data)
        offset += len(data)
    return MAGIC + struct.pack("<II", VERSION, len(entries)) + descriptors + payload


def build_from_paths(output: Path, entries: list[tuple[int, Path]]) -> list[dict[str, object]]:
    """Build a pack without materializing any payload in Python memory."""
    if output.exists():
        raise ValueError(f"append-only collision: {output}")
    if not 1 <= len(entries) <= MAX_ENTRIES or len({kind for kind, _ in entries}) != len(entries):
        raise ValueError("system pack requires one to nine unique entries")
    resolved: list[tuple[int, Path, int, bytes]] = []
    for kind, source in entries:
        path = source.resolve(strict=True)
        if kind not in KINDS.values() or not path.is_file() or path.is_symlink():
            raise ValueError("invalid system-pack source")
        size = path.stat().st_size
        if size <= 0:
            raise ValueError("invalid or empty system-pack entry")
        resolved.append((kind, path, size, sha256_file(path)))

    output.parent.mkdir(parents=True, exist_ok=True)
    header_len = 16 + DESCRIPTOR.size * len(resolved)
    cursor = header_len
    records: list[dict[str, object]] = []
    with output.open("xb") as target:
        target.write(MAGIC + struct.pack("<II", VERSION, len(resolved)))
        for kind, _path, size, digest in resolved:
            target.write(DESCRIPTOR.pack(kind, 1, cursor, size, digest, 0))
            records.append({"kind": kind, "offset": cursor, "bytes": size, "sha256": digest.hex()})
            cursor += size
        for _kind, path, _size, _digest in resolved:
            with path.open("rb") as source:
                shutil.copyfileobj(source, target, COPY_CHUNK_BYTES)
        target.flush()
    if output.stat().st_size != cursor:
        raise ValueError("system-pack output length mismatch")
    return records


def parse(blob: bytes) -> list[dict[str, object]]:
    if len(blob) < 16 or blob[:8] != MAGIC:
        raise ValueError("invalid system-pack magic")
    version, count = struct.unpack_from("<II", blob, 8)
    if version != VERSION or not 1 <= count <= MAX_ENTRIES:
        raise ValueError("unsupported system-pack header")
    header_len = 16 + DESCRIPTOR.size * count
    if len(blob) < header_len:
        raise ValueError("truncated system-pack descriptors")
    result: list[dict[str, object]] = []
    seen: set[int] = set()
    previous_end = header_len
    for index in range(count):
        kind, flags, offset, length, expected, reserved = DESCRIPTOR.unpack_from(
            blob, 16 + index * DESCRIPTOR.size
        )
        end = offset + length
        if (
            kind not in KINDS.values()
            or kind in seen
            or flags != 1
            or reserved != 0
            or length == 0
            or offset < previous_end
            or end > len(blob)
        ):
            raise ValueError("invalid system-pack entry")
        data = blob[offset:end]
        if sha256_bytes(data) != expected:
            raise ValueError("system-pack entry hash mismatch")
        seen.add(kind)
        previous_end = end
        result.append({"kind": kind, "offset": offset, "bytes": length, "sha256": expected.hex()})
    if previous_end != len(blob):
        raise ValueError("unreferenced system-pack bytes")
    return result


def parse_file(path: Path) -> list[dict[str, object]]:
    """Validate a potentially multi-gigabyte pack using bounded reads."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(16)
        if len(header) != 16 or header[:8] != MAGIC:
            raise ValueError("invalid system-pack magic")
        version, count = struct.unpack_from("<II", header, 8)
        if version != VERSION or not 1 <= count <= MAX_ENTRIES:
            raise ValueError("unsupported system-pack header")
        descriptor_bytes = handle.read(DESCRIPTOR.size * count)
    if len(descriptor_bytes) != DESCRIPTOR.size * count:
        raise ValueError("truncated system-pack descriptors")
    header_len = 16 + len(descriptor_bytes)
    result: list[dict[str, object]] = []
    seen: set[int] = set()
    previous_end = header_len
    for index in range(count):
        kind, flags, offset, length, expected, reserved = DESCRIPTOR.unpack_from(
            descriptor_bytes, index * DESCRIPTOR.size
        )
        end = offset + length
        if (
            kind not in KINDS.values()
            or kind in seen
            or flags != 1
            or reserved != 0
            or length == 0
            or offset < previous_end
            or end > size
        ):
            raise ValueError("invalid system-pack entry")
        if sha256_file(path, offset=offset, length=length) != expected:
            raise ValueError("system-pack entry hash mismatch")
        seen.add(kind)
        previous_end = end
        result.append({"kind": kind, "offset": offset, "bytes": length, "sha256": expected.hex()})
    if previous_end != size:
        raise ValueError("unreferenced system-pack bytes")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Casulo Native system pack")
    parser.add_argument("--output", type=Path, default=ROOT / "release/casulo-native-first-conversation-system-pack-v1.cspk")
    parser.add_argument("--model-probe", type=Path)
    parser.add_argument("--sampling-policy", type=Path)
    args = parser.parse_args()
    sources = [
        ("BOOTSTRAP_TCAP", ROOT / "release/FloodSurrogate.tcap"),
        ("UX_CONTRACT", ROOT / "schemas/product/hosted-native-ux-contract-v1.json"),
        ("GUIDE_T_SOURCE", ROOT / "examples/t/revolution/agent_logic.t"),
    ]
    if args.model_probe is not None:
        model_probe = args.model_probe.expanduser().resolve(strict=True)
        if ROOT.resolve() not in model_probe.parents:
            raise SystemExit("model probe must remain inside repository")
        sources.append(("MODEL_GGUF_PROBE", model_probe))
    if args.sampling_policy is not None:
        sampling_policy = args.sampling_policy.expanduser().resolve(strict=True)
        if ROOT.resolve() not in sampling_policy.parents:
            raise SystemExit("sampling policy must remain inside repository")
        sources.append(("NATIVE_SAMPLING_POLICY", sampling_policy))
    entries = [(KINDS[name], path.read_bytes()) for name, path in sources]
    blob = build(entries)
    parsed = parse(blob)
    output = args.output.expanduser().resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_bytes() != blob:
        raise SystemExit(f"append-only collision: {output}")
    output.write_bytes(blob)
    manifest = {
        "schema": "casulo-native-system-pack/1.0",
        "file": output.relative_to(ROOT).as_posix(),
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "entries": [
            {
                "name": name,
                "kind": KINDS[name],
                "source": path.relative_to(ROOT).as_posix(),
                **parsed[index],
            }
            for index, (name, path) in enumerate(sources)
        ],
        "t_execution": "BOOTSTRAP_TCAP_AND_NATIVE_SAMPLING_POLICY" if args.sampling_policy else "BOOTSTRAP_TCAP_ONLY",
        "guide_t_source_execution": "NOT_EXECUTED",
        "model_embedded": False,
        "model_probe_embedded": args.model_probe is not None,
        "model_probe_claim": (
            "content-addressed adopted-model weight-format projection; not full model or token inference"
            if args.model_probe is not None
            else "absent"
        ),
        "network": False,
        "physical_device_written": False,
    }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{manifest['sha256']}  {output.name}\n", encoding="ascii"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
