from __future__ import annotations

import hashlib
import time
import zlib
from dataclasses import dataclass


class TransformError(ValueError):
    pass


TRANSFORM_ORDER = (
    "raw",
    "zlib",
    "delta8-zlib",
    "xor-prev-zlib",
    "shuffle4-zlib",
)


@dataclass(frozen=True, slots=True)
class TransformCandidate:
    name: str
    payload: bytes
    source_sha256: str
    payload_sha256: str
    roundtrip: bool
    logical_operations: int
    primitive: str
    encode_ns: int
    inverse_verify_ns: int

    @property
    def payload_bytes(self) -> int:
        return len(self.payload)


def _delta8(data: bytes) -> bytes:
    output = bytearray(len(data))
    previous = 0
    for index, value in enumerate(data):
        output[index] = (value - previous) & 0xFF
        previous = value
    return bytes(output)


def _undelta8(data: bytes) -> bytes:
    output = bytearray(len(data))
    previous = 0
    for index, value in enumerate(data):
        previous = (previous + value) & 0xFF
        output[index] = previous
    return bytes(output)


def _xor_previous(data: bytes) -> bytes:
    output = bytearray(len(data))
    previous = 0
    for index, value in enumerate(data):
        output[index] = value ^ previous
        previous = value
    return bytes(output)


def _unxor_previous(data: bytes) -> bytes:
    output = bytearray(len(data))
    previous = 0
    for index, value in enumerate(data):
        decoded = value ^ previous
        output[index] = decoded
        previous = decoded
    return bytes(output)


def _shuffle4(data: bytes) -> bytes:
    full = len(data) - (len(data) % 4)
    body = data[:full]
    return b"".join(body[lane::4] for lane in range(4)) + data[full:]


def _unshuffle4(data: bytes, expected_size: int) -> bytes:
    full = expected_size - (expected_size % 4)
    lane_size = full // 4
    shuffled = data[:full]
    output = bytearray(full)
    for lane in range(4):
        values = shuffled[lane * lane_size : (lane + 1) * lane_size]
        output[lane:full:4] = values
    return bytes(output) + data[full:]


def encode_transform(name: str, data: bytes) -> tuple[bytes, int, str]:
    if name == "raw":
        return data, 0, "python.bytes/raw"
    if name == "zlib":
        return zlib.compress(data, 9), len(data), f"zlib/{zlib.ZLIB_RUNTIME_VERSION}"
    if name == "delta8-zlib":
        return (
            zlib.compress(_delta8(data), 9),
            len(data),
            f"casulo.delta8-v1+zlib/{zlib.ZLIB_RUNTIME_VERSION}",
        )
    if name == "xor-prev-zlib":
        return (
            zlib.compress(_xor_previous(data), 9),
            len(data),
            f"casulo.xor-prev-v1+zlib/{zlib.ZLIB_RUNTIME_VERSION}",
        )
    if name == "shuffle4-zlib":
        return (
            zlib.compress(_shuffle4(data), 9),
            len(data),
            f"casulo.shuffle4-v1+zlib/{zlib.ZLIB_RUNTIME_VERSION}",
        )
    raise TransformError(f"transform desconhecido: {name}")


def decode_transform(name: str, payload: bytes, expected_size: int) -> bytes:
    if expected_size < 0:
        raise TransformError("expected_size negativo")
    try:
        if name == "raw":
            decoded = payload
        elif name == "zlib":
            decoded = zlib.decompress(payload)
        elif name == "delta8-zlib":
            decoded = _undelta8(zlib.decompress(payload))
        elif name == "xor-prev-zlib":
            decoded = _unxor_previous(zlib.decompress(payload))
        elif name == "shuffle4-zlib":
            decoded = _unshuffle4(zlib.decompress(payload), expected_size)
        else:
            raise TransformError(f"transform desconhecido: {name}")
    except zlib.error as exc:
        raise TransformError(f"payload {name} inválido") from exc
    if len(decoded) != expected_size:
        raise TransformError(
            f"tamanho inverso divergente: esperado {expected_size}, obtido {len(decoded)}"
        )
    return decoded


def candidate_set(
    data: bytes,
    *,
    kind: str,
    names: tuple[str, ...] | None = None,
) -> dict[str, TransformCandidate]:
    selected_names = ("raw",) if kind == "box_header" else (names or TRANSFORM_ORDER)
    if not selected_names or "raw" not in selected_names or len(set(selected_names)) != len(selected_names):
        raise TransformError("candidate family must contain raw exactly once")
    if any(name not in TRANSFORM_ORDER for name in selected_names):
        raise TransformError("candidate family contains an unknown transform")
    source_hash = hashlib.sha256(data).hexdigest()
    result: dict[str, TransformCandidate] = {}
    for name in selected_names:
        encode_started = time.perf_counter_ns()
        payload, operations, primitive = encode_transform(name, data)
        encode_ns = time.perf_counter_ns() - encode_started
        inverse_started = time.perf_counter_ns()
        restored = decode_transform(name, payload, len(data))
        inverse_ns = time.perf_counter_ns() - inverse_started
        candidate = TransformCandidate(
            name=name,
            payload=payload,
            source_sha256=source_hash,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            roundtrip=restored == data,
            logical_operations=operations,
            primitive=primitive,
            encode_ns=encode_ns,
            inverse_verify_ns=inverse_ns,
        )
        if not candidate.roundtrip:
            raise TransformError(f"inversa local falhou para {name}")
        result[name] = candidate
    return result


def primitive_manifest() -> list[dict[str, object]]:
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
            "name": "delta8-v1",
            "implementation": "Casulo reversible byte delta",
            "version": "1",
            "abi": "bytes -> bytes",
            "decision_owner": "T",
            "effects": ["cpu", "memory"],
        },
        {
            "name": "xor-prev-v1",
            "implementation": "Casulo reversible previous-byte XOR",
            "version": "1",
            "abi": "bytes -> bytes",
            "decision_owner": "T",
            "effects": ["cpu", "memory"],
        },
        {
            "name": "shuffle4-v1",
            "implementation": "Casulo reversible four-byte lane shuffle",
            "version": "1",
            "abi": "bytes -> bytes",
            "decision_owner": "T",
            "effects": ["cpu", "memory"],
        },
    ]
