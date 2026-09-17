from __future__ import annotations

import hashlib
import struct
import time
import zlib
from dataclasses import dataclass


class GOPTransformError(ValueError):
    pass


TRANSFORM_ORDER = ("raw", "zlib", "xor-reference-prefix-zlib")
XOR_PREFIX_LIMIT = 1024 * 1024


@dataclass(frozen=True, slots=True)
class GOPTransformCandidate:
    name: str
    payload: bytes
    source_sha256: str
    payload_sha256: str
    roundtrip: bool
    primitive: str
    logical_operations: int
    encode_ns: int
    inverse_verify_ns: int
    reference_bytes: int

    @property
    def payload_bytes(self) -> int:
        return len(self.payload)


def _xor_prefix(data: bytes, reference: bytes, length: int) -> bytes:
    return bytes(left ^ right for left, right in zip(data[:length], reference[:length]))


def encode_gop_transform(
    name: str,
    data: bytes,
    *,
    reference: bytes | None = None,
) -> tuple[bytes, int, str, int]:
    if name == "raw":
        return data, 0, "python.bytes/raw", 0
    if name == "zlib":
        return (
            zlib.compress(data, 9),
            len(data),
            f"zlib/{zlib.ZLIB_RUNTIME_VERSION}",
            0,
        )
    if name == "xor-reference-prefix-zlib":
        if reference is None:
            raise GOPTransformError("xor-reference transform requires prior decoded bytes")
        prefix_bytes = min(len(data), len(reference), XOR_PREFIX_LIMIT)
        if prefix_bytes <= 0:
            raise GOPTransformError("xor-reference transform requires a non-empty reference")
        residual = _xor_prefix(data, reference, prefix_bytes)
        compressed = zlib.compress(residual, 9)
        payload = (
            struct.pack(">II", prefix_bytes, len(compressed))
            + compressed
            + data[prefix_bytes:]
        )
        return (
            payload,
            prefix_bytes * 2,
            f"casulo.xor-reference-prefix-v1+zlib/{zlib.ZLIB_RUNTIME_VERSION}",
            prefix_bytes,
        )
    raise GOPTransformError(f"unknown GOP transform: {name}")


def decode_gop_transform(
    name: str,
    payload: bytes,
    expected_size: int,
    *,
    reference: bytes | None = None,
) -> bytes:
    if expected_size < 0:
        raise GOPTransformError("negative expected size")
    try:
        if name == "raw":
            decoded = payload
        elif name == "zlib":
            decoded = zlib.decompress(payload)
        elif name == "xor-reference-prefix-zlib":
            if reference is None or len(payload) < 8:
                raise GOPTransformError("xor-reference payload lacks its reference or header")
            prefix_bytes, compressed_bytes = struct.unpack(">II", payload[:8])
            if (
                prefix_bytes <= 0
                or prefix_bytes > expected_size
                or prefix_bytes > len(reference)
                or prefix_bytes > XOR_PREFIX_LIMIT
                or 8 + compressed_bytes > len(payload)
            ):
                raise GOPTransformError("xor-reference payload header is invalid")
            residual = zlib.decompress(payload[8 : 8 + compressed_bytes])
            if len(residual) != prefix_bytes:
                raise GOPTransformError("xor-reference residual length differs")
            prefix = bytes(
                left ^ right
                for left, right in zip(residual, reference[:prefix_bytes])
            )
            decoded = prefix + payload[8 + compressed_bytes :]
        else:
            raise GOPTransformError(f"unknown GOP inverse: {name}")
    except zlib.error as exc:
        raise GOPTransformError(f"invalid {name} payload") from exc
    if len(decoded) != expected_size:
        raise GOPTransformError(
            f"GOP inverse length differs: expected {expected_size}, got {len(decoded)}"
        )
    return decoded


def gop_candidate_set(
    data: bytes,
    *,
    names: tuple[str, ...],
    reference: bytes | None,
) -> dict[str, GOPTransformCandidate]:
    if not names or names[0] != "raw" or len(set(names)) != len(names):
        raise GOPTransformError("candidate family must start with raw and contain no duplicates")
    if any(name not in TRANSFORM_ORDER for name in names):
        raise GOPTransformError("candidate family contains an unknown transform")
    if "xor-reference-prefix-zlib" in names and reference is None:
        raise GOPTransformError("candidate family requests an unavailable reference")
    source_hash = hashlib.sha256(data).hexdigest()
    candidates: dict[str, GOPTransformCandidate] = {}
    for name in names:
        started = time.perf_counter_ns()
        payload, operations, primitive, reference_bytes = encode_gop_transform(
            name, data, reference=reference
        )
        encode_ns = time.perf_counter_ns() - started
        inverse_started = time.perf_counter_ns()
        restored = decode_gop_transform(
            name,
            payload,
            expected_size=len(data),
            reference=reference,
        )
        inverse_ns = time.perf_counter_ns() - inverse_started
        candidate = GOPTransformCandidate(
            name=name,
            payload=payload,
            source_sha256=source_hash,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            roundtrip=restored == data,
            primitive=primitive,
            logical_operations=operations,
            encode_ns=encode_ns,
            inverse_verify_ns=inverse_ns,
            reference_bytes=reference_bytes,
        )
        if not candidate.roundtrip:
            raise GOPTransformError(f"local inverse failed for {name}")
        candidates[name] = candidate
    return candidates


def gop_primitive_manifest() -> list[dict[str, object]]:
    return [
        {
            "name": "raw",
            "implementation": "Python bytes",
            "version": "runtime",
            "abi": "bytes -> bytes",
            "decision_owner": "T",
            "effects": [],
        },
        {
            "name": "zlib",
            "implementation": "CPython zlib binding",
            "version": zlib.ZLIB_RUNTIME_VERSION,
            "abi": "bytes -> RFC1950 bytes",
            "decision_owner": "T",
            "effects": ["cpu", "memory"],
        },
        {
            "name": "xor-reference-prefix-v1",
            "implementation": "Casulo bounded prior-NAL predictor",
            "version": "1",
            "abi": "current bytes + prior decoded bytes -> reversible residual bytes",
            "decision_owner": "T",
            "effects": ["cpu", "memory"],
            "maximum_reference_prefix_bytes": XOR_PREFIX_LIMIT,
        },
    ]


__all__ = [
    "GOPTransformCandidate",
    "GOPTransformError",
    "TRANSFORM_ORDER",
    "XOR_PREFIX_LIMIT",
    "decode_gop_transform",
    "gop_candidate_set",
    "gop_primitive_manifest",
]
