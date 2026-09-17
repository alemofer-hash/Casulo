from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path


MODEL_BYTES = 2_497_280_256
MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
ROOT = Path(__file__).resolve().parents[2]
CACHE = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362"
)
MODEL = CACHE / "model/Qwen3-4B-Q4_K_M.gguf"
ORACLE = CACHE / "runtime/llama-tokenize.exe"

TYPE_WIDTH = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
TYPE_STRING = 8
TYPE_ARRAY = 9
MAX_ARRAY = 16_777_216
MAX_STRING = 16_777_216

FROZEN_CASES = (
    "Casulo",
    "hello world",
    "Olá, Casulo.",
)

EMBEDDING_TOKEN_ID = 49_242
EMBEDDING_TENSOR_OFFSET = 5_966_592
EMBEDDING_WIDTH = 2_560
Q6_K_BLOCK_BYTES = 210
Q6_K_ELEMENTS = 256


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ArrayDescriptor:
    element_type: int
    count: int
    payload_offset: int
    end_offset: int
    string_offsets: tuple[tuple[int, int], ...]


class GgufReader:
    def __init__(self, path: Path):
        self.path = path
        self.handle = path.open("rb")
        self.size = path.stat().st_size

    def close(self) -> None:
        self.handle.close()

    def read(self, size: int) -> bytes:
        data = self.handle.read(size)
        if len(data) != size:
            raise ValueError("truncated GGUF metadata")
        return data

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def string_bytes(self) -> tuple[int, bytes]:
        length = self.u64()
        if length > MAX_STRING:
            raise ValueError("GGUF string exceeds bounded inventory limit")
        offset = self.handle.tell()
        return offset, self.read(length)

    def skip_value(self, value_type: int, depth: int = 0) -> ArrayDescriptor | None:
        width = TYPE_WIDTH.get(value_type)
        if width is not None:
            self.handle.seek(width, 1)
            return None
        if value_type == TYPE_STRING:
            self.string_bytes()
            return None
        if value_type != TYPE_ARRAY or depth >= 3:
            raise ValueError(f"unsupported GGUF value type {value_type}")
        element_type = self.u32()
        count = self.u64()
        if count > MAX_ARRAY:
            raise ValueError("GGUF array exceeds bounded inventory limit")
        payload_offset = self.handle.tell()
        offsets: list[tuple[int, int]] = []
        element_width = TYPE_WIDTH.get(element_type)
        if element_width is not None:
            self.handle.seek(element_width * count, 1)
        elif element_type == TYPE_STRING:
            for _ in range(count):
                offset, value = self.string_bytes()
                offsets.append((offset, len(value)))
        else:
            for _ in range(count):
                self.skip_value(element_type, depth + 1)
        return ArrayDescriptor(element_type, count, payload_offset, self.handle.tell(), tuple(offsets))

    def scalar(self, value_type: int):
        if value_type == 4:
            return self.u32()
        if value_type == 7:
            return bool(self.read(1)[0])
        if value_type == TYPE_STRING:
            _, raw = self.string_bytes()
            return raw.decode("utf-8")
        descriptor = self.skip_value(value_type)
        return descriptor

    def read_at(self, offset: int, size: int) -> bytes:
        current = self.handle.tell()
        self.handle.seek(offset)
        data = self.read(size)
        self.handle.seek(current)
        return data


def parse_metadata(path: Path) -> tuple[dict[str, object], dict[str, ArrayDescriptor]]:
    reader = GgufReader(path)
    try:
        if reader.read(4) != b"GGUF":
            raise ValueError("GGUF magic mismatch")
        version, tensors, metadata = reader.u32(), reader.u64(), reader.u64()
        if version != 3 or tensors != 398 or metadata != 28:
            raise ValueError("unexpected adopted-model header")
        values: dict[str, object] = {}
        arrays: dict[str, ArrayDescriptor] = {}
        for _ in range(metadata):
            _, key_bytes = reader.string_bytes()
            key = key_bytes.decode("utf-8")
            value_type = reader.u32()
            if value_type == TYPE_ARRAY:
                descriptor = reader.skip_value(value_type)
                assert descriptor is not None
                arrays[key] = descriptor
            else:
                values[key] = reader.scalar(value_type)
        return values, arrays
    finally:
        reader.close()


def token_text(path: Path, descriptor: ArrayDescriptor, token_id: int) -> str:
    if descriptor.element_type != TYPE_STRING or not 0 <= token_id < descriptor.count:
        raise ValueError("token ID outside vocabulary")
    offset, length = descriptor.string_offsets[token_id]
    with path.open("rb") as source:
        source.seek(offset)
        return source.read(length).decode("utf-8")


def raw_region_sha256(path: Path, start: int, end: int) -> str:
    digest = hashlib.sha256()
    remaining = end - start
    with path.open("rb") as source:
        source.seek(start)
        while remaining:
            block = source.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError("truncated raw metadata region")
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest()


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def dequantize_q6_block(block: bytes) -> list[float]:
    if len(block) != Q6_K_BLOCK_BYTES:
        raise ValueError("invalid Q6_K block")
    ql, qh = block[:128], block[128:192]
    scales = struct.unpack("<16b", block[192:208])
    d = struct.unpack("<e", block[208:210])[0]
    values = [0.0] * Q6_K_ELEMENTS
    for half in range(2):
        ql_base, qh_base = half * 64, half * 32
        scale_base, output_base = half * 8, half * 128
        for lane in range(32):
            scale_lane = lane // 16
            high = qh[qh_base + lane]
            quants = (
                (ql[ql_base + lane] & 0x0F) | ((high & 0x03) << 4),
                (ql[ql_base + lane + 32] & 0x0F) | (((high >> 2) & 0x03) << 4),
                (ql[ql_base + lane] >> 4) | (((high >> 4) & 0x03) << 4),
                (ql[ql_base + lane + 32] >> 4) | (((high >> 6) & 0x03) << 4),
            )
            for quarter, quant in enumerate(quants):
                product = f32(f32(d * scales[scale_base + scale_lane + quarter * 2]) * (quant - 32))
                values[output_base + lane + quarter * 32] = product
    return values


def embedding_receipt(path: Path) -> dict[str, object]:
    row_bytes = EMBEDDING_WIDTH // Q6_K_ELEMENTS * Q6_K_BLOCK_BYTES
    row_offset = EMBEDDING_TENSOR_OFFSET + EMBEDDING_TOKEN_ID * row_bytes
    with path.open("rb") as source:
        source.seek(row_offset)
        raw = source.read(row_bytes)
    if len(raw) != row_bytes:
        raise ValueError("truncated embedding row")
    values: list[float] = []
    for offset in range(0, row_bytes, Q6_K_BLOCK_BYTES):
        values.extend(dequantize_q6_block(raw[offset : offset + Q6_K_BLOCK_BYTES]))
    packed = b"".join(struct.pack("<f", value) for value in values)
    running_sum = 0.0
    for value in values:
        running_sum = f32(running_sum + value)
    return {
        "token_id": EMBEDDING_TOKEN_ID,
        "tensor": "token_embd.weight",
        "tensor_type": "Q6_K",
        "dimensions": [EMBEDDING_WIDTH, 151_936],
        "row_offset": row_offset,
        "row_bytes": row_bytes,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "decoded_f32_sha256": hashlib.sha256(packed).hexdigest(),
        "first_eight_f32_bits": [f"{struct.unpack('<I', packed[index:index + 4])[0]:08x}" for index in range(0, 32, 4)],
        "sum_f32_bits": f"{struct.unpack('<I', struct.pack('<f', running_sum))[0]:08x}",
    }


def oracle_tokens(executable: Path, model: Path, prompt: str) -> list[int]:
    completed = subprocess.run(
        [
            str(executable),
            "-m",
            str(model),
            "-p",
            prompt,
            "--ids",
            "--no-bos",
            "--offline",
            "--log-disable",
        ],
        shell=False,
        check=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    return [int(value) for value in json.loads(completed.stdout.strip())]


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory the adopted Qwen tokenizer boundary")
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--oracle", type=Path, default=ORACLE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = args.model.resolve(strict=True)
    oracle = args.oracle.resolve(strict=True)
    if model != MODEL.resolve(strict=True) or oracle != ORACLE.resolve(strict=True):
        raise SystemExit("only the exact adopted owner model/runtime are allowed")
    if model.stat().st_size != MODEL_BYTES or sha256(model) != MODEL_SHA256:
        raise SystemExit("adopted model identity mismatch")

    values, arrays = parse_metadata(model)
    tokens = arrays.get("tokenizer.ggml.tokens")
    merges = arrays.get("tokenizer.ggml.merges")
    token_types = arrays.get("tokenizer.ggml.token_type")
    if tokens is None or merges is None or token_types is None:
        raise SystemExit("required tokenizer arrays are missing")
    frozen = [{"text": text, "ids": oracle_tokens(oracle, model, text)} for text in FROZEN_CASES]
    selected_ids = sorted({token_id for case in frozen for token_id in case["ids"]})
    selected = {str(token_id): token_text(model, tokens, token_id) for token_id in selected_ids}
    relevant_values = {
        key: value
        for key, value in values.items()
        if key.startswith("tokenizer.") or key == "general.architecture"
    }
    chat_template = str(relevant_values.pop("tokenizer.chat_template"))
    chat_template_bytes = chat_template.encode("utf-8")
    relevant_values["tokenizer.chat_template"] = {
        "bytes": len(chat_template_bytes),
        "sha256": hashlib.sha256(chat_template_bytes).hexdigest(),
        "execution": "NOT_EXECUTED_IN_NP5",
    }
    report = {
        "schema": "casulo-native-tokenizer-inventory/0.1",
        "state": "NATIVE_TOKENIZER_SOURCE_INVENTORIED",
        "model": {"bytes": MODEL_BYTES, "sha256": MODEL_SHA256},
        "oracle": {
            "file": oracle.name,
            "sha256": sha256(oracle),
            "network": False,
            "shell": False,
        },
        "metadata": relevant_values,
        "arrays": {
            "tokens": {
                "element_type": tokens.element_type,
                "count": tokens.count,
                "payload_offset": tokens.payload_offset,
                "end_offset": tokens.end_offset,
                "raw_sha256": raw_region_sha256(model, tokens.payload_offset, tokens.end_offset),
            },
            "merges": {
                "element_type": merges.element_type,
                "count": merges.count,
                "payload_offset": merges.payload_offset,
                "end_offset": merges.end_offset,
                "raw_sha256": raw_region_sha256(model, merges.payload_offset, merges.end_offset),
            },
            "token_type": {
                "element_type": token_types.element_type,
                "count": token_types.count,
                "payload_offset": token_types.payload_offset,
                "end_offset": token_types.end_offset,
                "raw_sha256": raw_region_sha256(model, token_types.payload_offset, token_types.end_offset),
            },
        },
        "frozen_cases": frozen,
        "selected_token_text": selected,
        "embedding": embedding_receipt(model),
        "claim_boundary": "offline tokenizer oracle and GGUF metadata inventory; no Native tokenization or inference",
    }
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit(f"append-only output exists: {output}")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    # Windows terminals can still be configured as CP-1252. Keep the sealed
    # artifact human-readable UTF-8, but make stdout transport-independent.
    print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
