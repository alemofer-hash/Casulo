from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from build_native_gguf_probe import (  # noqa: E402
    GGML_TYPE_Q4_K,
    GGML_TYPE_Q6_K,
    MODEL,
    Q4_K_BLOCK_BYTES,
    Q6_K_BLOCK_BYTES,
    inspect_mapping,
    sha256_file,
)


TOKEN_IDS = (49_242, 8_763)
BLOCK_PREFIX = "blk.0."
EXPECTED = {
    "embedding_length": 2_560,
    "feed_forward_length": 9_728,
    "head_count": 32,
    "head_count_kv": 8,
    "key_length": 128,
    "value_length": 128,
}


def _sha256_bytes(payload: bytes | memoryview) -> str:
    return hashlib.sha256(payload).hexdigest()


def _f32_summary(values: np.ndarray) -> dict[str, object]:
    normalized = np.asarray(values, dtype="<f4")
    return {
        "shape": list(normalized.shape),
        "sha256_f32_le": _sha256_bytes(normalized.tobytes(order="C")),
        "first_bits": [f"{int(value):08x}" for value in normalized.view("<u4").ravel()[:8]],
        "sum_f64": float(np.sum(normalized, dtype=np.float64)),
        "l2_f64": float(np.sqrt(np.sum(normalized.astype(np.float64) ** 2))),
        "min": float(np.min(normalized)),
        "max": float(np.max(normalized)),
    }


def _f16_from(raw: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(raw)
    return contiguous.view("<f2").reshape(raw.shape[:-1]).astype(np.float32)


def _decode_q4_blocks(blocks: np.ndarray) -> np.ndarray:
    if blocks.shape[-1] != Q4_K_BLOCK_BYTES:
        raise ValueError("invalid Q4_K block width")
    d = _f16_from(blocks[..., 0:2])
    dmin = _f16_from(blocks[..., 2:4])
    scales = blocks[..., 4:16]
    qs = blocks[..., 16:144]
    output = np.empty(blocks.shape[:-1] + (256,), dtype=np.float32)
    for group in range(4):
        pairs: list[tuple[np.ndarray, np.ndarray]] = []
        for index in (group * 2, group * 2 + 1):
            if index < 4:
                scale = scales[..., index] & 0x3F
                minimum = scales[..., index + 4] & 0x3F
            else:
                scale = (scales[..., index + 4] & 0x0F) | ((scales[..., index - 4] >> 6) << 4)
                minimum = (scales[..., index + 4] >> 4) | ((scales[..., index] >> 6) << 4)
            pairs.append((scale.astype(np.float32), minimum.astype(np.float32)))
        base = group * 64
        qbase = group * 32
        low = qs[..., qbase : qbase + 32] & 0x0F
        high = qs[..., qbase : qbase + 32] >> 4
        output[..., base : base + 32] = (
            d[..., None] * pairs[0][0][..., None] * low.astype(np.float32)
            - dmin[..., None] * pairs[0][1][..., None]
        )
        output[..., base + 32 : base + 64] = (
            d[..., None] * pairs[1][0][..., None] * high.astype(np.float32)
            - dmin[..., None] * pairs[1][1][..., None]
        )
    return output


def _decode_q6_blocks(blocks: np.ndarray) -> np.ndarray:
    if blocks.shape[-1] != Q6_K_BLOCK_BYTES:
        raise ValueError("invalid Q6_K block width")
    ql = blocks[..., :128]
    qh = blocks[..., 128:192]
    scales = blocks[..., 192:208].view(np.int8)
    d = _f16_from(blocks[..., 208:210])
    output = np.empty(blocks.shape[:-1] + (256,), dtype=np.float32)
    for half in range(2):
        ql_base = half * 64
        qh_base = half * 32
        scale_base = half * 8
        out_base = half * 128
        high = qh[..., qh_base : qh_base + 32]
        low_a = ql[..., ql_base : ql_base + 32]
        low_b = ql[..., ql_base + 32 : ql_base + 64]
        quantized = (
            ((low_a & 0x0F) | ((high & 0x03) << 4)).astype(np.int16) - 32,
            ((low_b & 0x0F) | (((high >> 2) & 0x03) << 4)).astype(np.int16) - 32,
            ((low_a >> 4) | (((high >> 4) & 0x03) << 4)).astype(np.int16) - 32,
            ((low_b >> 4) | (((high >> 6) & 0x03) << 4)).astype(np.int16) - 32,
        )
        lane_scale = np.arange(32) // 16
        for quarter, quant in enumerate(quantized):
            scale = scales[..., scale_base + lane_scale + quarter * 2]
            output[..., out_base + quarter * 32 : out_base + (quarter + 1) * 32] = (
                d[..., None] * scale.astype(np.float32) * quant.astype(np.float32)
            )
    return output


class Oracle:
    def __init__(self, mapping: mmap.mmap, inspection) -> None:
        self.mapping = mapping
        self.inspection = inspection
        self.tensors = {tensor.name: tensor for tensor in inspection.tensors}

    def f32(self, name: str) -> np.ndarray:
        tensor = self.tensors[name]
        count = int(np.prod(tensor.dimensions))
        return np.frombuffer(self.mapping, dtype="<f4", count=count, offset=tensor.absolute_offset).copy()

    def matvec(self, name: str, vector: np.ndarray, *, rows_per_batch: int = 64) -> np.ndarray:
        tensor = self.tensors[name]
        if len(tensor.dimensions) != 2:
            raise ValueError(f"{name} is not a matrix")
        input_width, output_width = map(int, tensor.dimensions)
        x = np.asarray(vector, dtype=np.float32)
        if x.shape != (input_width,) or input_width % 256:
            raise ValueError(f"{name} input mismatch")
        if tensor.ggml_type == GGML_TYPE_Q4_K:
            block_bytes, decoder = Q4_K_BLOCK_BYTES, _decode_q4_blocks
        elif tensor.ggml_type == GGML_TYPE_Q6_K:
            block_bytes, decoder = Q6_K_BLOCK_BYTES, _decode_q6_blocks
        else:
            raise ValueError(f"unsupported matrix type {tensor.ggml_type} for {name}")
        blocks_per_row = input_width // 256
        output = np.empty(output_width, dtype=np.float32)
        for first in range(0, output_width, rows_per_batch):
            count = min(rows_per_batch, output_width - first)
            byte_offset = tensor.absolute_offset + first * blocks_per_row * block_bytes
            byte_count = count * blocks_per_row * block_bytes
            raw = np.frombuffer(self.mapping, dtype=np.uint8, count=byte_count, offset=byte_offset)
            blocks = raw.reshape(count, blocks_per_row, block_bytes)
            decoded = decoder(blocks)
            # NumPy is deliberately an independent host oracle. Native uses a
            # scalar accumulation order, so comparison uses frozen tolerances,
            # not bit identity for matvec outputs.
            output[first : first + count] = np.sum(
                decoded * x.reshape(1, blocks_per_row, 256), axis=(1, 2), dtype=np.float32
            )
        return output

    def embedding(self, token_id: int) -> np.ndarray:
        tensor = self.tensors["token_embd.weight"]
        width, rows = map(int, tensor.dimensions)
        if not 0 <= token_id < rows or tensor.ggml_type != GGML_TYPE_Q6_K:
            raise ValueError("embedding selection mismatch")
        blocks_per_row = width // 256
        byte_count = blocks_per_row * Q6_K_BLOCK_BYTES
        offset = tensor.absolute_offset + token_id * byte_count
        raw = np.frombuffer(self.mapping, dtype=np.uint8, count=byte_count, offset=offset)
        return _decode_q6_blocks(raw.reshape(blocks_per_row, Q6_K_BLOCK_BYTES)).reshape(width)


def rms_norm(vector: np.ndarray, weight: np.ndarray, epsilon: float) -> np.ndarray:
    x = np.asarray(vector, dtype=np.float32)
    w = np.asarray(weight, dtype=np.float32)
    if x.shape != w.shape:
        raise ValueError("RMSNorm shape mismatch")
    scale = np.float32(1.0 / np.sqrt(np.mean(x * x, dtype=np.float32) + np.float32(epsilon)))
    return (x * scale * w).astype(np.float32)


def head_rms_norm(vector: np.ndarray, weight: np.ndarray, heads: int, epsilon: float) -> np.ndarray:
    head_dim = len(weight)
    shaped = np.asarray(vector, dtype=np.float32).reshape(heads, head_dim)
    return np.stack([rms_norm(head, weight, epsilon) for head in shaped]).reshape(-1)


def rope(vector: np.ndarray, heads: int, position: int, frequency_base: float) -> np.ndarray:
    shaped = np.asarray(vector, dtype=np.float32).reshape(heads, -1).copy()
    head_dim = shaped.shape[1]
    # GGML normal RoPE consumes adjacent pairs. The GGUF conversion permutes
    # Q/K rows from the Hugging Face rotate-half layout into this runtime
    # layout; using rotate-half directly here would validate the wrong ABI.
    half = head_dim // 2
    dimensions = np.arange(half, dtype=np.float32)
    theta = np.float32(position) / np.power(np.float32(frequency_base), dimensions / np.float32(half))
    cosine, sine = np.cos(theta).astype(np.float32), np.sin(theta).astype(np.float32)
    pairs = shaped.reshape(heads, half, 2)
    first, second = pairs[..., 0].copy(), pairs[..., 1].copy()
    pairs[..., 0] = first * cosine - second * sine
    pairs[..., 1] = first * sine + second * cosine
    return shaped.reshape(-1)


def attention(
    query: np.ndarray,
    keys: list[np.ndarray],
    values: list[np.ndarray],
    *,
    q_heads: int,
    kv_heads: int,
    head_dim: int,
) -> tuple[np.ndarray, np.ndarray]:
    q = query.reshape(q_heads, head_dim)
    k = np.stack(keys).reshape(len(keys), kv_heads, head_dim)
    v = np.stack(values).reshape(len(values), kv_heads, head_dim)
    groups = q_heads // kv_heads
    output = np.empty((q_heads, head_dim), dtype=np.float32)
    scores_out = np.empty((q_heads, len(keys)), dtype=np.float32)
    inverse_sqrt = np.float32(1.0 / np.sqrt(np.float32(head_dim)))
    for q_head in range(q_heads):
        kv_head = q_head // groups
        scores = np.sum(k[:, kv_head, :] * q[q_head], axis=1, dtype=np.float32) * inverse_sqrt
        scores -= np.max(scores)
        weights = np.exp(scores).astype(np.float32)
        weights /= np.sum(weights, dtype=np.float32)
        scores_out[q_head] = weights
        output[q_head] = np.sum(v[:, kv_head, :] * weights[:, None], axis=0, dtype=np.float32)
    return output.reshape(-1), scores_out


def silu(vector: np.ndarray) -> np.ndarray:
    x = np.asarray(vector, dtype=np.float32)
    return (x / (np.float32(1.0) + np.exp(-x).astype(np.float32))).astype(np.float32)


def _tensor_sizes(inspection, source_len: int) -> dict[str, int]:
    ordered = sorted(inspection.tensors, key=lambda tensor: tensor.absolute_offset)
    return {
        tensor.name: (
            ordered[index + 1].absolute_offset - tensor.absolute_offset
            if index + 1 < len(ordered)
            else source_len - tensor.absolute_offset
        )
        for index, tensor in enumerate(ordered)
    }


def run(model: Path) -> dict[str, object]:
    with model.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
        inspection = inspect_mapping(mapping)
        oracle = Oracle(mapping, inspection)
        sizes = _tensor_sizes(inspection, len(mapping))
        config = inspection.metadata
        epsilon = float(config["qwen3.attention.layer_norm_rms_epsilon"])
        frequency_base = float(config["qwen3.rope.freq_base"])
        q_heads, kv_heads, head_dim = 32, 8, 128
        if (
            int(config["qwen3.embedding_length"]) != EXPECTED["embedding_length"]
            or int(config["qwen3.feed_forward_length"]) != EXPECTED["feed_forward_length"]
            or int(config["qwen3.attention.head_count"]) != q_heads
            or int(config["qwen3.attention.head_count_kv"]) != kv_heads
        ):
            raise ValueError("adopted model architecture changed")

        tensor_receipts = []
        for tensor in sorted(
            (item for item in inspection.tensors if item.name.startswith(BLOCK_PREFIX)),
            key=lambda item: item.name,
        ):
            raw = memoryview(mapping)[tensor.absolute_offset : tensor.absolute_offset + sizes[tensor.name]]
            tensor_receipts.append(
                {
                    "name": tensor.name,
                    "dimensions": list(tensor.dimensions),
                    "ggml_type": tensor.ggml_type,
                    "absolute_offset": tensor.absolute_offset,
                    "byte_len": sizes[tensor.name],
                    "sha256_raw": _sha256_bytes(raw),
                }
            )
            raw.release()

        intermediates: dict[str, dict[str, object]] = {}
        keys: list[np.ndarray] = []
        values: list[np.ndarray] = []
        token_outputs: list[np.ndarray] = []
        operation_counts = {
            "tokens": len(TOKEN_IDS),
            "quantized_matvec_rows": 0,
            "quantized_dot_products": 0,
            "attention_score_products": 0,
        }
        attn_norm_weight = oracle.f32("blk.0.attn_norm.weight")
        q_norm_weight = oracle.f32("blk.0.attn_q_norm.weight")
        k_norm_weight = oracle.f32("blk.0.attn_k_norm.weight")
        ffn_norm_weight = oracle.f32("blk.0.ffn_norm.weight")

        for position, token_id in enumerate(TOKEN_IDS):
            prefix = f"token_{position}"
            x = oracle.embedding(token_id)
            intermediates[f"{prefix}.embedding"] = _f32_summary(x)
            norm = rms_norm(x, attn_norm_weight, epsilon)
            intermediates[f"{prefix}.attn_norm"] = _f32_summary(norm)
            q = oracle.matvec("blk.0.attn_q.weight", norm)
            k = oracle.matvec("blk.0.attn_k.weight", norm)
            v = oracle.matvec("blk.0.attn_v.weight", norm)
            intermediates[f"{prefix}.query_projection"] = _f32_summary(q)
            intermediates[f"{prefix}.key_projection"] = _f32_summary(k)
            intermediates[f"{prefix}.value_projection"] = _f32_summary(v)
            operation_counts["quantized_matvec_rows"] += len(q) + len(k) + len(v)
            operation_counts["quantized_dot_products"] += len(q) + len(k) + len(v)
            q = head_rms_norm(q, q_norm_weight, q_heads, epsilon)
            k = head_rms_norm(k, k_norm_weight, kv_heads, epsilon)
            intermediates[f"{prefix}.q_norm"] = _f32_summary(q)
            intermediates[f"{prefix}.k_norm"] = _f32_summary(k)
            q = rope(q, q_heads, position, frequency_base)
            k = rope(k, kv_heads, position, frequency_base)
            intermediates[f"{prefix}.q_rope"] = _f32_summary(q)
            intermediates[f"{prefix}.k_rope"] = _f32_summary(k)
            keys.append(k)
            values.append(v)
            context, weights = attention(
                q,
                keys,
                values,
                q_heads=q_heads,
                kv_heads=kv_heads,
                head_dim=head_dim,
            )
            operation_counts["attention_score_products"] += q_heads * len(keys)
            intermediates[f"{prefix}.attention_weights"] = _f32_summary(weights)
            intermediates[f"{prefix}.attention_context"] = _f32_summary(context)
            projected = oracle.matvec("blk.0.attn_output.weight", context)
            operation_counts["quantized_matvec_rows"] += len(projected)
            operation_counts["quantized_dot_products"] += len(projected)
            intermediates[f"{prefix}.attention_projection"] = _f32_summary(projected)
            residual = (x + projected).astype(np.float32)
            intermediates[f"{prefix}.attention_residual"] = _f32_summary(residual)
            ffn_norm = rms_norm(residual, ffn_norm_weight, epsilon)
            intermediates[f"{prefix}.ffn_norm"] = _f32_summary(ffn_norm)
            gate = oracle.matvec("blk.0.ffn_gate.weight", ffn_norm)
            up = oracle.matvec("blk.0.ffn_up.weight", ffn_norm)
            intermediates[f"{prefix}.ffn_gate"] = _f32_summary(gate)
            intermediates[f"{prefix}.ffn_up"] = _f32_summary(up)
            operation_counts["quantized_matvec_rows"] += len(gate) + len(up)
            operation_counts["quantized_dot_products"] += len(gate) + len(up)
            activated = (silu(gate) * up).astype(np.float32)
            intermediates[f"{prefix}.ffn_activated"] = _f32_summary(activated)
            down = oracle.matvec("blk.0.ffn_down.weight", activated)
            operation_counts["quantized_matvec_rows"] += len(down)
            operation_counts["quantized_dot_products"] += len(down)
            intermediates[f"{prefix}.ffn_down"] = _f32_summary(down)
            x = (residual + down).astype(np.float32)
            intermediates[f"{prefix}.block_output"] = _f32_summary(x)
            token_outputs.append(x)

        all_output = np.stack(token_outputs)
        return {
            "schema": "casulo-native-qwen-block0-oracle/0.1",
            "claim": "two authentic tokens through Qwen3 block 0; no later block, logits, sampling, or output token",
            "model": {
                "path": str(model),
                "bytes": len(mapping),
                "sha256": sha256_file(model),
                "gguf_version": inspection.version,
                "architecture": config["general.architecture"],
            },
            "context": {
                "token_ids": list(TOKEN_IDS),
                "positions": [0, 1],
                "head_dimension": head_dim,
                "attention_context_lengths": [1, 2],
                "rms_epsilon": epsilon,
                "rope_frequency_base": frequency_base,
            },
            "tensor_receipts": tensor_receipts,
            "operation_counts": operation_counts,
            "intermediates": intermediates,
            "final_output": _f32_summary(all_output),
            "oracle": {
                "implementation": "independent Python/NumPy GGUF decoder and Qwen3 block",
                "numpy_version": np.__version__,
                "comparison": "frozen tolerances; matvec bit identity is not required across accumulation orders",
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and independently execute Qwen3 block 0")
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = args.model.expanduser().resolve(strict=True)
    result = run(model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "final_output": result["final_output"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
