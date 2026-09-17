from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .resource import ResourceContract
from .effects import KNOWN_CAPABILITY_EFFECTS


TCAP_MAGIC = b"TCAP"
TCAP_MAJOR = 1
TCAP_MINOR = 0
TCAP_VNEXT_MINOR = 1
TCAP_HEADER = struct.Struct("<4sHHIIQQ")
TCAP_MAX_FILE = 64 * 1024 * 1024
TCAP_MAX_MANIFEST = 1024 * 1024
TCAP_MAX_SEGMENTS = 64
TCAP_ALIGNMENT = 8


class TcapError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TcapSegment:
    name: str
    data: bytes
    flags: str
    alignment: int = TCAP_ALIGNMENT

    def __post_init__(self) -> None:
        if not self.name or len(self.name.encode("utf-8")) > 128:
            raise TcapError("segment name is empty or too long")
        if not self.data:
            raise TcapError("empty segments are not permitted")
        if any(flag not in "rwx" for flag in self.flags) or len(set(self.flags)) != len(self.flags):
            raise TcapError("segment flags are invalid")
        if "w" in self.flags and "x" in self.flags:
            raise TcapError("W+X segments are forbidden")
        if self.alignment < 1 or self.alignment > 4096 or self.alignment & (self.alignment - 1):
            raise TcapError("alignment must be a power of two up to 4096")


@dataclass(frozen=True, slots=True)
class TcapPackage:
    manifest: dict[str, Any]
    segments: tuple[TcapSegment, ...]
    raw: bytes


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_tcap(
    *,
    segments: Iterable[TcapSegment],
    target: str,
    abi: str,
    entry_segment: str,
    entry_offset: int,
    compiler: dict[str, str],
    resource_contract: ResourceContract,
    capability_requirements: Iterable[str] | None = None,
) -> bytes:
    segment_list = tuple(segments)
    if not 1 <= len(segment_list) <= TCAP_MAX_SEGMENTS:
        raise TcapError("segment count outside supported bounds")
    if len({item.name for item in segment_list}) != len(segment_list):
        raise TcapError("duplicate segment name")
    offset = 0
    descriptors: list[dict[str, Any]] = []
    payload = bytearray()
    for segment in segment_list:
        aligned = _align(offset, segment.alignment)
        payload.extend(b"\0" * (aligned - offset))
        payload.extend(segment.data)
        descriptors.append(
            {
                "name": segment.name,
                "offset": aligned,
                "length": len(segment.data),
                "flags": segment.flags,
                "alignment": segment.alignment,
                "sha256": hashlib.sha256(segment.data).hexdigest(),
            }
        )
        offset = aligned + len(segment.data)
    requirements = (
        None
        if capability_requirements is None
        else _validate_capability_requirements(tuple(capability_requirements))
    )
    manifest = {
        "schema": "tcap-manifest/1.1" if requirements is not None else "tcap-manifest/1.0",
        "target": _required_text(target, "target"),
        "abi": _required_text(abi, "abi"),
        "entry_point": {"segment": entry_segment, "offset": entry_offset},
        "compiler": _validate_compiler(compiler),
        "resource_contract": resource_contract.to_dict(),
        "segments": descriptors,
        "content_sha256": _content_hash(segment_list),
        "energy": {"status": "unavailable", "joules": None},
    }
    if requirements is not None:
        manifest["capability_requirements"] = list(requirements)
    _validate_manifest(manifest, segment_list)
    manifest_bytes = canonical_json(manifest)
    if len(manifest_bytes) > TCAP_MAX_MANIFEST:
        raise TcapError("manifest too large")
    payload_offset = _align(TCAP_HEADER.size + len(manifest_bytes), TCAP_ALIGNMENT)
    file_length = payload_offset + len(payload)
    if file_length > TCAP_MAX_FILE:
        raise TcapError("TCAP file too large")
    header = TCAP_HEADER.pack(
        TCAP_MAGIC,
        TCAP_MAJOR,
        TCAP_VNEXT_MINOR if requirements is not None else TCAP_MINOR,
        len(manifest_bytes), len(segment_list),
        payload_offset, file_length,
    )
    return header + manifest_bytes + b"\0" * (payload_offset - len(header) - len(manifest_bytes)) + payload


def parse_tcap(raw: bytes) -> TcapPackage:
    if not TCAP_HEADER.size <= len(raw) <= TCAP_MAX_FILE:
        raise TcapError("file length outside supported bounds")
    magic, major, minor, manifest_len, segment_count, payload_offset, file_len = TCAP_HEADER.unpack_from(raw)
    if magic != TCAP_MAGIC or major != TCAP_MAJOR or minor not in {TCAP_MINOR, TCAP_VNEXT_MINOR}:
        raise TcapError("unsupported TCAP magic or version")
    if not 1 <= manifest_len <= TCAP_MAX_MANIFEST or not 1 <= segment_count <= TCAP_MAX_SEGMENTS:
        raise TcapError("header bounds invalid")
    if file_len != len(raw) or payload_offset < TCAP_HEADER.size + manifest_len or payload_offset > len(raw):
        raise TcapError("header offsets invalid")
    if payload_offset % TCAP_ALIGNMENT:
        raise TcapError("payload is not aligned")
    manifest_raw = raw[TCAP_HEADER.size : TCAP_HEADER.size + manifest_len]
    padding = raw[TCAP_HEADER.size + manifest_len : payload_offset]
    if any(padding):
        raise TcapError("non-zero manifest padding")
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, TcapError) as exc:
        raise TcapError(f"invalid manifest: {exc}") from exc
    if canonical_json(manifest) != manifest_raw:
        raise TcapError("manifest is not canonical JSON")
    expected_schema = "tcap-manifest/1.1" if minor == TCAP_VNEXT_MINOR else "tcap-manifest/1.0"
    if manifest.get("schema") != expected_schema:
        raise TcapError("header and manifest versions differ")
    descriptors = manifest.get("segments")
    if type(descriptors) is not list or len(descriptors) != segment_count:
        raise TcapError("segment count differs from manifest")
    segments: list[TcapSegment] = []
    occupied: list[tuple[int, int]] = []
    for descriptor in descriptors:
        if type(descriptor) is not dict:
            raise TcapError("segment descriptor must be an object")
        expected = {"name", "offset", "length", "flags", "alignment", "sha256"}
        if set(descriptor) != expected:
            raise TcapError("segment descriptor keys differ")
        offset = _strict_nonnegative_int(descriptor["offset"], "offset")
        length = _strict_positive_int(descriptor["length"], "length")
        alignment = _strict_positive_int(descriptor["alignment"], "alignment")
        if alignment > 4096 or alignment & (alignment - 1) or offset % alignment:
            raise TcapError("segment alignment invalid")
        end = offset + length
        if end > len(raw) - payload_offset:
            raise TcapError("segment exceeds payload")
        if any(offset < existing_end and start < end for start, existing_end in occupied):
            raise TcapError("overlapping segments")
        occupied.append((offset, end))
        data = raw[payload_offset + offset : payload_offset + end]
        if hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
            raise TcapError("segment hash mismatch")
        segments.append(TcapSegment(descriptor["name"], data, descriptor["flags"], alignment))
    package_segments = tuple(segments)
    _validate_manifest(manifest, package_segments)
    if manifest["content_sha256"] != _content_hash(package_segments):
        raise TcapError("content hash mismatch")
    return TcapPackage(manifest=manifest, segments=package_segments, raw=raw)


def load_tcap(path: str | Path) -> TcapPackage:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file() or source.is_symlink():
        raise TcapError("TCAP path must be a regular file")
    return parse_tcap(source.read_bytes())


def _validate_manifest(manifest: dict[str, Any], segments: tuple[TcapSegment, ...]) -> None:
    schema = manifest.get("schema")
    expected = {"schema", "target", "abi", "entry_point", "compiler", "resource_contract", "segments", "content_sha256", "energy"}
    if schema == "tcap-manifest/1.1":
        expected.add("capability_requirements")
    if set(manifest) != expected or schema not in {"tcap-manifest/1.0", "tcap-manifest/1.1"}:
        raise TcapError("manifest keys or schema invalid")
    if schema == "tcap-manifest/1.1":
        value = manifest["capability_requirements"]
        if type(value) is not list:
            raise TcapError("capability requirements must be an array")
        _validate_capability_requirements(tuple(value))
    _required_text(manifest["target"], "target")
    _required_text(manifest["abi"], "abi")
    _validate_compiler(manifest["compiler"])
    if type(manifest["resource_contract"]) is not dict:
        raise TcapError("resource contract must be an object")
    ResourceContract.from_dict(manifest["resource_contract"])
    energy = manifest["energy"]
    if energy != {"status": "unavailable", "joules": None}:
        raise TcapError("unmeasured energy must remain unavailable/null")
    entry = manifest["entry_point"]
    if type(entry) is not dict or set(entry) != {"segment", "offset"}:
        raise TcapError("entry point invalid")
    entry_name = _required_text(entry["segment"], "entry segment")
    entry_offset = _strict_nonnegative_int(entry["offset"], "entry offset")
    matching = [item for item in segments if item.name == entry_name]
    if len(matching) != 1 or "x" not in matching[0].flags or entry_offset >= len(matching[0].data):
        raise TcapError("entry point must fall inside one executable segment")
    content_hash = manifest["content_sha256"]
    if type(content_hash) is not str or len(content_hash) != 64:
        raise TcapError("content hash invalid")


def _validate_compiler(value: Any) -> dict[str, str]:
    if type(value) is not dict or set(value) != {"name", "version", "commit"}:
        raise TcapError("compiler provenance invalid")
    return {key: _required_text(value[key], f"compiler {key}") for key in ("name", "version", "commit")}


def _validate_capability_requirements(values: tuple[Any, ...]) -> tuple[str, ...]:
    if len(values) > 64 or len(set(values)) != len(values):
        raise TcapError("capability requirements must be unique and bounded")
    for value in values:
        if type(value) is not str or value not in KNOWN_CAPABILITY_EFFECTS:
            raise TcapError(f"unknown capability requirement: {value!r}")
    return tuple(values)


def _content_hash(segments: tuple[TcapSegment, ...]) -> str:
    digest = hashlib.sha256()
    for segment in segments:
        name = segment.name.encode("utf-8")
        digest.update(len(name).to_bytes(4, "little"))
        digest.update(name)
        digest.update(len(segment.data).to_bytes(8, "little"))
        digest.update(segment.data)
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TcapError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _required_text(value: Any, name: str) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise TcapError(f"{name} must be a bounded non-empty string")
    return value


def _strict_nonnegative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise TcapError(f"{name} must be a non-negative integer")
    return value


def _strict_positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise TcapError(f"{name} must be a positive integer")
    return value
