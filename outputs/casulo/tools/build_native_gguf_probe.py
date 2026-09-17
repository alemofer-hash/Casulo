from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import struct
from dataclasses import dataclass
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json"
CACHE = Path(os.environ.get("LOCALAPPDATA", "")) / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362"
MODEL = CACHE / "model/Qwen3-4B-Q4_K_M.gguf"
MAGIC = b"GGUF"
VERSION = 3
GGML_TYPE_Q4_K = 12
GGML_TYPE_Q6_K = 14
QK_K = 256
Q4_K_BLOCK_BYTES = 144
Q6_K_BLOCK_BYTES = 210
F32_PROBE_VALUES = 16
MAX_COUNT = 16_777_216
MAX_KEY = 4_096

U8, I8, U16, I16, U32, I32, F32, BOOL, STRING, ARRAY, U64, I64, F64 = range(13)
FIXED_WIDTH = {U8: 1, I8: 1, BOOL: 1, U16: 2, I16: 2, U32: 4, I32: 4, F32: 4, U64: 8, I64: 8, F64: 8}
WANTED = {
    "general.architecture",
    "general.alignment",
    "qwen3.context_length",
    "qwen3.embedding_length",
    "qwen3.feed_forward_length",
    "qwen3.block_count",
    "qwen3.attention.head_count",
    "qwen3.attention.head_count_kv",
    "qwen3.rope.freq_base",
    "qwen3.attention.layer_norm_rms_epsilon",
}


class GgufError(ValueError):
    pass


class Cursor:
    def __init__(self, data: mmap.mmap | bytes):
        self.data = data
        self.offset = 0

    def take(self, length: int) -> bytes:
        if length < 0 or self.offset + length > len(self.data):
            raise GgufError("truncated GGUF")
        start = self.offset
        self.offset += length
        return self.data[start : self.offset]

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self, *, key: bool = False) -> str:
        length = self.unpack("<Q")
        if length > len(self.data) or (key and length > MAX_KEY):
            raise GgufError("GGUF string length outside bound")
        try:
            return self.take(length).decode("utf-8")
        except UnicodeDecodeError as error:
            raise GgufError("GGUF string is not UTF-8") from error


@dataclass(frozen=True)
class Tensor:
    name: str
    dimensions: tuple[int, ...]
    ggml_type: int
    relative_offset: int
    absolute_offset: int


@dataclass(frozen=True)
class Inspection:
    version: int
    tensor_count: int
    metadata_count: int
    alignment: int
    data_offset: int
    metadata: dict[str, object]
    tensors: tuple[Tensor, ...]


def _skip_value(cursor: Cursor, value_type: int, depth: int = 0) -> None:
    if value_type in FIXED_WIDTH:
        cursor.take(FIXED_WIDTH[value_type])
        return
    if value_type == STRING:
        length = cursor.unpack("<Q")
        cursor.take(length)
        return
    if value_type != ARRAY or depth >= 3:
        raise GgufError(f"unsupported GGUF metadata type {value_type}")
    element_type = cursor.unpack("<I")
    count = cursor.unpack("<Q")
    if count > MAX_COUNT:
        raise GgufError("GGUF array exceeds safety bound")
    if element_type in FIXED_WIDTH:
        cursor.take(count * FIXED_WIDTH[element_type])
        return
    for _ in range(count):
        _skip_value(cursor, element_type, depth + 1)


def _read_scalar(cursor: Cursor, value_type: int) -> object:
    formats = {
        U8: "<B", I8: "<b", U16: "<H", I16: "<h", U32: "<I", I32: "<i",
        F32: "<f", BOOL: "<?", U64: "<Q", I64: "<q", F64: "<d",
    }
    if value_type == STRING:
        return cursor.string()
    if value_type not in formats:
        raise GgufError("requested metadata is not scalar")
    return cursor.unpack(formats[value_type])


def inspect_mapping(data: mmap.mmap | bytes) -> Inspection:
    cursor = Cursor(data)
    if cursor.take(4) != MAGIC:
        raise GgufError("invalid GGUF magic")
    version = cursor.unpack("<I")
    if version != VERSION:
        raise GgufError(f"unsupported GGUF version {version}")
    tensor_count = cursor.unpack("<Q")
    metadata_count = cursor.unpack("<Q")
    if not 1 <= tensor_count <= 65_536 or not 1 <= metadata_count <= 65_536:
        raise GgufError("GGUF header count outside bound")
    metadata: dict[str, object] = {}
    alignment = 32
    for _ in range(metadata_count):
        key = cursor.string(key=True)
        value_type = cursor.unpack("<I")
        if key in WANTED:
            value = _read_scalar(cursor, value_type)
            metadata[key] = value
            if key == "general.alignment":
                alignment = int(value)
        else:
            _skip_value(cursor, value_type)
    # GGUF defines 32-byte tensor alignment when general.alignment is absent.
    # Preserve the resolved value in the inspection so downstream policy never
    # has to guess whether an absent key means zero or the format default.
    metadata.setdefault("general.alignment", alignment)
    if alignment <= 0 or alignment > 4096 or alignment & (alignment - 1):
        raise GgufError("invalid GGUF alignment")
    pending: list[tuple[str, tuple[int, ...], int, int]] = []
    for _ in range(tensor_count):
        name = cursor.string(key=True)
        dimension_count = cursor.unpack("<I")
        if not 1 <= dimension_count <= 4:
            raise GgufError("tensor dimension count outside bound")
        dimensions = tuple(cursor.unpack("<Q") for _ in range(dimension_count))
        if any(dimension <= 0 for dimension in dimensions):
            raise GgufError("zero tensor dimension")
        ggml_type = cursor.unpack("<I")
        relative_offset = cursor.unpack("<Q")
        pending.append((name, dimensions, ggml_type, relative_offset))
    data_offset = (cursor.offset + alignment - 1) & ~(alignment - 1)
    if data_offset > len(data):
        raise GgufError("GGUF tensor data offset is truncated")
    tensors = tuple(
        Tensor(name, dimensions, ggml_type, relative_offset, data_offset + relative_offset)
        for name, dimensions, ggml_type, relative_offset in pending
    )
    return Inspection(version, tensor_count, metadata_count, alignment, data_offset, metadata, tensors)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _half(value: bytes) -> float:
    return struct.unpack("<e", value)[0]


def dequantize_q4_k(block: bytes) -> list[float]:
    if len(block) != Q4_K_BLOCK_BYTES:
        raise GgufError("Q4_K block must contain exactly 144 bytes")
    d, dmin = _half(block[:2]), _half(block[2:4])
    scales, qs = block[4:16], block[16:144]
    output = [0.0] * QK_K
    for group in range(4):
        pairs: list[tuple[int, int]] = []
        for index in (group * 2, group * 2 + 1):
            if index < 4:
                scale = scales[index] & 0x3F
                minimum = scales[index + 4] & 0x3F
            else:
                scale = (scales[index + 4] & 0x0F) | ((scales[index - 4] >> 6) << 4)
                minimum = (scales[index + 4] >> 4) | ((scales[index] >> 6) << 4)
            pairs.append((scale, minimum))
        base, qbase = group * 64, group * 32
        for lane in range(32):
            low_scale = _f32(d * pairs[0][0])
            low_minimum = _f32(dmin * pairs[0][1])
            high_scale = _f32(d * pairs[1][0])
            high_minimum = _f32(dmin * pairs[1][1])
            output[base + lane] = _f32(_f32(low_scale * (qs[qbase + lane] & 0x0F)) - low_minimum)
            output[base + 32 + lane] = _f32(_f32(high_scale * (qs[qbase + lane] >> 4)) - high_minimum)
    return output


def probe_dot(block: bytes) -> float:
    decoded = dequantize_q4_k(block)
    total = 0.0
    for index, value in enumerate(decoded):
        input_value = _f32(((index % 17) - 8) / 8.0)
        total = _f32(total + _f32(value * input_value))
    return total


def dequantize_q6_k(block: bytes) -> list[float]:
    if len(block) != Q6_K_BLOCK_BYTES:
        raise GgufError("Q6_K block must contain exactly 210 bytes")
    ql, qh, scales = block[:128], block[128:192], block[192:208]
    d = _half(block[208:210])
    output = [0.0] * QK_K
    for half_index in range(2):
        ql_base = half_index * 64
        qh_base = half_index * 32
        scale_base = half_index * 8
        output_base = half_index * 128
        for lane in range(32):
            scale_lane = lane // 16
            high = qh[qh_base + lane]
            quantized = (
                ((ql[ql_base + lane] & 0x0F) | ((high & 0x03) << 4)) - 32,
                ((ql[ql_base + lane + 32] & 0x0F) | (((high >> 2) & 0x03) << 4)) - 32,
                ((ql[ql_base + lane] >> 4) | (((high >> 4) & 0x03) << 4)) - 32,
                ((ql[ql_base + lane + 32] >> 4) | (((high >> 6) & 0x03) << 4)) - 32,
            )
            signed_scales = tuple(
                struct.unpack("<b", bytes([scales[scale_base + scale_lane + offset]]))[0]
                for offset in (0, 2, 4, 6)
            )
            for quarter, (quant, scale) in enumerate(zip(quantized, signed_scales, strict=True)):
                output[output_base + lane + quarter * 32] = _f32(_f32(d * scale) * quant)
    return output


def probe_dot_q6(block: bytes) -> float:
    decoded = dequantize_q6_k(block)
    total = 0.0
    for index, value in enumerate(decoded):
        input_value = _f32(((index % 17) - 8) / 8.0)
        total = _f32(total + _f32(value * input_value))
    return total


def _gguf_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<Q", len(encoded)) + encoded


def _metadata(key: str, value_type: int, value: object) -> bytes:
    encoded = bytearray(_gguf_string(key) + struct.pack("<I", value_type))
    if value_type == STRING:
        encoded.extend(_gguf_string(str(value)))
    elif value_type == U32:
        encoded.extend(struct.pack("<I", int(value)))
    elif value_type == U64:
        encoded.extend(struct.pack("<Q", int(value)))
    elif value_type == F32:
        encoded.extend(struct.pack("<f", float(value)))
    else:
        raise GgufError("probe builder supports only scalar metadata")
    return bytes(encoded)


def build_projection(inspection: Inspection, source: Path, source_sha256: str) -> tuple[bytes, dict[str, object]]:
    missing = sorted(WANTED - inspection.metadata.keys())
    if missing:
        raise GgufError(f"required Qwen metadata missing: {missing}")
    if inspection.metadata["general.architecture"] != "qwen3":
        raise GgufError("model architecture is not qwen3")
    selected_q4 = next((tensor for tensor in inspection.tensors if tensor.ggml_type == GGML_TYPE_Q4_K), None)
    selected_q6 = next((tensor for tensor in inspection.tensors if tensor.ggml_type == GGML_TYPE_Q6_K), None)
    selected_f32 = next((tensor for tensor in inspection.tensors if tensor.ggml_type == 0), None)
    if selected_q4 is None or selected_q6 is None or selected_f32 is None:
        raise GgufError("model does not expose all required F32/Q4_K/Q6_K formats")
    with source.open("rb") as handle:
        handle.seek(selected_q4.absolute_offset)
        block_q4 = handle.read(Q4_K_BLOCK_BYTES)
        handle.seek(selected_q6.absolute_offset)
        block_q6 = handle.read(Q6_K_BLOCK_BYTES)
        handle.seek(selected_f32.absolute_offset)
        prefix_f32 = handle.read(F32_PROBE_VALUES * 4)
    if len(block_q4) != Q4_K_BLOCK_BYTES or len(block_q6) != Q6_K_BLOCK_BYTES or len(prefix_f32) != F32_PROBE_VALUES * 4:
        raise GgufError("selected tensor probe is truncated")

    q4_hash = hashlib.sha256(block_q4).hexdigest()
    q6_hash = hashlib.sha256(block_q6).hexdigest()
    f32_hash = hashlib.sha256(prefix_f32).hexdigest()
    q4_dot = probe_dot(block_q4)
    q6_dot = probe_dot_q6(block_q6)
    q4_bits = f"{struct.unpack('<I', struct.pack('<f', q4_dot))[0]:08x}"
    q6_bits = f"{struct.unpack('<I', struct.pack('<f', q6_dot))[0]:08x}"

    values: list[tuple[str, int, object]] = []
    for key in sorted(WANTED):
        value = inspection.metadata[key]
        value_type = STRING if isinstance(value, str) else F32 if isinstance(value, float) else U32
        values.append((key, value_type, value))
    values.extend(
        [
            ("casulo.source_model_sha256", STRING, source_sha256),
            ("casulo.source_model_bytes", U64, source.stat().st_size),
            ("casulo.source_tensor_name", STRING, selected_q4.name),
            ("casulo.source_tensor_offset", U64, selected_q4.absolute_offset),
            ("casulo.source_tensor_dimensions", STRING, "x".join(str(item) for item in selected_q4.dimensions)),
            ("casulo.source_block_sha256", STRING, q4_hash),
            ("casulo.probe_dot_f32", F32, q4_dot),
            ("casulo.probe_dot_f32_bits", STRING, q4_bits),
            ("casulo.source_q6_tensor_name", STRING, selected_q6.name),
            ("casulo.source_q6_tensor_offset", U64, selected_q6.absolute_offset),
            ("casulo.source_q6_block_sha256", STRING, q6_hash),
            ("casulo.probe_q6_dot_f32", F32, q6_dot),
            ("casulo.probe_q6_dot_f32_bits", STRING, q6_bits),
            ("casulo.source_f32_tensor_name", STRING, selected_f32.name),
            ("casulo.source_f32_tensor_offset", U64, selected_f32.absolute_offset),
            ("casulo.source_f32_prefix_sha256", STRING, f32_hash),
        ]
    )
    tensors = [
        ("casulo.probe.q4_k", (QK_K,), GGML_TYPE_Q4_K, block_q4),
        ("casulo.probe.q6_k", (QK_K,), GGML_TYPE_Q6_K, block_q6),
        ("casulo.probe.f32", (F32_PROBE_VALUES,), 0, prefix_f32),
    ]
    alignment = int(inspection.metadata["general.alignment"])
    tensor_data = bytearray()
    relative_offsets: list[int] = []
    for _name, _dimensions, _kind, payload in tensors:
        tensor_data.extend(b"\0" * ((-len(tensor_data)) % alignment))
        relative_offsets.append(len(tensor_data))
        tensor_data.extend(payload)

    blob = bytearray(MAGIC)
    blob.extend(struct.pack("<IQQ", VERSION, len(tensors), len(values)))
    for key, value_type, value in values:
        blob.extend(_metadata(key, value_type, value))
    for (name, dimensions, kind, _payload), relative_offset in zip(tensors, relative_offsets, strict=True):
        blob.extend(_gguf_string(name))
        blob.extend(struct.pack("<I", len(dimensions)))
        for dimension in dimensions:
            blob.extend(struct.pack("<Q", dimension))
        blob.extend(struct.pack("<IQ", kind, relative_offset))
    blob.extend(b"\0" * ((-len(blob)) % alignment))
    blob.extend(tensor_data)

    manifest = {
        "schema": "casulo-native-gguf-probe/0.2",
        "claim": "authentic F32/Q4_K/Q6_K samples projected from the adopted model; not token inference",
        "source_model": {
            "bytes": source.stat().st_size,
            "sha256": source_sha256,
            "gguf_version": inspection.version,
            "architecture": inspection.metadata["general.architecture"],
            "tensor_count": inspection.tensor_count,
            "metadata_count": inspection.metadata_count,
            "data_offset": inspection.data_offset,
        },
        "source_tensor": {
            "name": selected_q4.name,
            "dimensions": selected_q4.dimensions,
            "ggml_type": selected_q4.ggml_type,
            "absolute_offset": selected_q4.absolute_offset,
            "block_bytes": len(block_q4),
            "block_sha256": q4_hash,
        },
        "source_tensors": {
            "q4_k": {"name": selected_q4.name, "dimensions": selected_q4.dimensions, "absolute_offset": selected_q4.absolute_offset, "sha256": q4_hash},
            "q6_k": {"name": selected_q6.name, "dimensions": selected_q6.dimensions, "absolute_offset": selected_q6.absolute_offset, "sha256": q6_hash},
            "f32": {"name": selected_f32.name, "dimensions": selected_f32.dimensions, "absolute_offset": selected_f32.absolute_offset, "sha256": f32_hash},
        },
        "projection": {
            "tensor_names": [item[0] for item in tensors],
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "q4_dot_f32": q4_dot,
            "q4_dot_f32_bits": q4_bits,
            "dot_f32": q4_dot,
            "dot_f32_bits": q4_bits,
            "q6_dot_f32": q6_dot,
            "q6_dot_f32_bits": q6_bits,
            "f32_prefix_sha256": f32_hash,
        },
        "full_model_mapped": False,
        "first_model_derived_token": False,
        "network": False,
        "physical_device_written": False,
    }
    return bytes(blob), manifest


def inspect_file(path: Path) -> Inspection:
    with path.open("rb") as handle:
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
            return inspect_mapping(mapping)


def write_append_only(path: Path, payload: bytes) -> None:
    resolved = path.expanduser().resolve()
    if ROOT.resolve() not in resolved.parents:
        raise SystemExit("output must remain inside repository")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists():
        if resolved.read_bytes() != payload:
            raise SystemExit(f"append-only collision: {resolved}")
        return
    resolved.write_bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a bounded GGUF/Q4_K probe from the adopted owner model")
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--output", type=Path, default=ROOT / "release/casulo-native-qwen3-q4k-probe.gguf")
    args = parser.parse_args()
    model = args.model.expanduser().resolve(strict=True)
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    expected_bytes = int(candidate["model"]["bytes"])
    expected_sha256 = str(candidate["model"]["sha256"])
    if model.stat().st_size != expected_bytes:
        raise SystemExit("adopted model size mismatch")
    observed_sha256 = sha256_file(model)
    if observed_sha256 != expected_sha256:
        raise SystemExit("adopted model SHA-256 mismatch")
    inspection = inspect_file(model)
    blob, manifest = build_projection(inspection, model, observed_sha256)
    output = args.output.expanduser().resolve()
    write_append_only(output, blob)
    manifest["projection"]["file"] = output.relative_to(ROOT).as_posix()
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_append_only(manifest_path, manifest_bytes)
    checksum = output.with_suffix(output.suffix + ".sha256")
    write_append_only(checksum, f"{manifest['projection']['sha256']}  {output.name}\n".encode("ascii"))
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
