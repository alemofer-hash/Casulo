from __future__ import annotations

import hashlib
import struct

import pytest

from tools.build_native_gguf_probe import (
    F32,
    GGML_TYPE_Q4_K,
    Q6_K_BLOCK_BYTES,
    Q4_K_BLOCK_BYTES,
    STRING,
    U32,
    U64,
    GgufError,
    _gguf_string,
    _metadata,
    dequantize_q4_k,
    dequantize_q6_k,
    inspect_mapping,
    probe_dot,
    probe_dot_q6,
)


def fixture(*, architecture: str = "qwen3") -> bytes:
    block = bytearray(Q4_K_BLOCK_BYTES)
    block[:2] = struct.pack("<e", 1.0)
    block[2:4] = struct.pack("<e", 0.5)
    block[4:16] = bytes([3]) * 12
    block[16:] = bytes([0x21]) * 128
    values = [
        ("general.architecture", STRING, architecture),
        ("general.alignment", U32, 32),
        ("qwen3.context_length", U32, 32768),
        ("qwen3.embedding_length", U32, 2560),
        ("qwen3.feed_forward_length", U32, 9728),
        ("qwen3.block_count", U32, 36),
        ("qwen3.attention.head_count", U32, 32),
        ("qwen3.attention.head_count_kv", U32, 8),
        ("qwen3.rope.freq_base", F32, 1_000_000.0),
        ("qwen3.attention.layer_norm_rms_epsilon", F32, 1e-6),
        ("casulo.source_model_bytes", U64, 2_497_280_256),
    ]
    data = bytearray(b"GGUF" + struct.pack("<IQQ", 3, 1, len(values)))
    for item in values:
        data.extend(_metadata(*item))
    data.extend(_gguf_string("casulo.probe.q4_k"))
    data.extend(struct.pack("<IQIQ", 1, 256, GGML_TYPE_Q4_K, 0))
    data.extend(b"\0" * ((-len(data)) % 32))
    data.extend(block)
    return bytes(data)


def fixture_without_alignment() -> bytes:
    data = bytearray(fixture())
    # Rebuild instead of byte-splicing variable-length metadata.
    block = data[-Q4_K_BLOCK_BYTES:]
    values = [
        ("general.architecture", STRING, "qwen3"),
        ("qwen3.context_length", U32, 32768),
        ("qwen3.embedding_length", U32, 2560),
        ("qwen3.feed_forward_length", U32, 9728),
        ("qwen3.block_count", U32, 36),
        ("qwen3.attention.head_count", U32, 32),
        ("qwen3.attention.head_count_kv", U32, 8),
        ("qwen3.rope.freq_base", F32, 1_000_000.0),
        ("qwen3.attention.layer_norm_rms_epsilon", F32, 1e-6),
    ]
    rebuilt = bytearray(b"GGUF" + struct.pack("<IQQ", 3, 1, len(values)))
    for item in values:
        rebuilt.extend(_metadata(*item))
    rebuilt.extend(_gguf_string("casulo.probe.q4_k"))
    rebuilt.extend(struct.pack("<IQIQ", 1, 256, GGML_TYPE_Q4_K, 0))
    rebuilt.extend(b"\0" * ((-len(rebuilt)) % 32))
    rebuilt.extend(block)
    return bytes(rebuilt)


def test_probe_parser_recovers_qwen_metadata_and_q4k_tensor() -> None:
    data = fixture()
    inspection = inspect_mapping(data)
    assert inspection.metadata["general.architecture"] == "qwen3"
    assert inspection.metadata["qwen3.block_count"] == 36
    tensor = inspection.tensors[0]
    assert tensor.ggml_type == GGML_TYPE_Q4_K
    assert hashlib.sha256(data[tensor.absolute_offset : tensor.absolute_offset + 144]).digest()


def test_probe_parser_applies_normative_alignment_default() -> None:
    inspection = inspect_mapping(fixture_without_alignment())
    assert inspection.alignment == 32
    assert inspection.metadata["general.alignment"] == 32


def test_q4k_reference_is_causal() -> None:
    inspection = inspect_mapping(fixture())
    start = inspection.tensors[0].absolute_offset
    a = bytearray(fixture()[start : start + Q4_K_BLOCK_BYTES])
    b = bytearray(a)
    b[16] ^= 3
    assert len(dequantize_q4_k(a)) == 256
    assert probe_dot(a) != probe_dot(b)


def test_q4k_reference_uses_eight_scale_groups() -> None:
    block = bytearray(Q4_K_BLOCK_BYTES)
    block[:2] = struct.pack("<e", 1.0)
    block[2:4] = struct.pack("<e", 0.0)
    block[4:16] = bytes([1, 2, 3, 4, 0, 0, 0, 0, 5, 6, 7, 8])
    block[16:] = bytes([0x11]) * 128
    decoded = dequantize_q4_k(block)
    for group in range(8):
        assert decoded[group * 32 : group * 32 + 32] == [float(group + 1)] * 32


def test_q6k_reference_is_causal() -> None:
    a = bytearray(Q6_K_BLOCK_BYTES)
    a[:128] = bytes((index * 13) & 0xFF for index in range(128))
    a[128:192] = bytes((index * 7) & 0xFF for index in range(64))
    a[192:208] = bytes([2]) * 16
    a[208:210] = struct.pack("<e", 1.0)
    b = bytearray(a)
    b[0] ^= 1
    assert len(dequantize_q6_k(a)) == 256
    assert probe_dot_q6(a) != probe_dot_q6(b)


@pytest.mark.parametrize("mutation", [b"BAD!", b"GGUF\x02\0\0\0"])
def test_probe_parser_rejects_invalid_header(mutation: bytes) -> None:
    data = bytearray(fixture())
    data[: len(mutation)] = mutation
    with pytest.raises(GgufError):
        inspect_mapping(data)
