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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_native_gguf_probe import MODEL, inspect_mapping, sha256_file  # noqa: E402
from inventory_native_block0 import (  # noqa: E402
    Oracle,
    _f32_summary,
    attention,
    head_rms_norm,
    rms_norm,
    rope,
    silu,
)

INPUT_TOKEN_ID = 49_242
MAX_TOKENS = 4


def digest_f32(values: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(values, dtype="<f4").tobytes(order="C")).hexdigest()


def run(model: Path, token_count: int) -> dict[str, object]:
    if not 1 <= token_count <= MAX_TOKENS:
        raise ValueError("token_count outside bounded incremental context")
    with model.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
        inspection = inspect_mapping(mapping)
        oracle = Oracle(mapping, inspection)
        metadata = inspection.metadata
        blocks = int(metadata["qwen3.block_count"])
        epsilon = float(metadata["qwen3.attention.layer_norm_rms_epsilon"])
        frequency_base = float(metadata["qwen3.rope.freq_base"])
        q_heads, kv_heads, head_dim = 32, 8, 128
        keys: list[list[np.ndarray]] = [[] for _ in range(blocks)]
        values: list[list[np.ndarray]] = [[] for _ in range(blocks)]
        token_ids = [INPUT_TOKEN_ID]
        token_receipts: list[dict[str, object]] = []

        for position in range(token_count):
            input_token_id = token_ids[position]
            hidden = oracle.embedding(input_token_id)
            hidden_chain = hashlib.sha256()
            for block in range(blocks):
                prefix = f"blk.{block}"
                attn_norm = rms_norm(hidden, oracle.f32(f"{prefix}.attn_norm.weight"), epsilon)
                query = oracle.matvec(f"{prefix}.attn_q.weight", attn_norm)
                key = oracle.matvec(f"{prefix}.attn_k.weight", attn_norm)
                value = oracle.matvec(f"{prefix}.attn_v.weight", attn_norm)
                query = head_rms_norm(
                    query, oracle.f32(f"{prefix}.attn_q_norm.weight"), q_heads, epsilon
                )
                key = head_rms_norm(
                    key, oracle.f32(f"{prefix}.attn_k_norm.weight"), kv_heads, epsilon
                )
                query = rope(query, q_heads, position, frequency_base)
                key = rope(key, kv_heads, position, frequency_base)
                keys[block].append(key)
                values[block].append(value)
                context, weights = attention(
                    query,
                    keys[block],
                    values[block],
                    q_heads=q_heads,
                    kv_heads=kv_heads,
                    head_dim=head_dim,
                )
                projected = oracle.matvec(f"{prefix}.attn_output.weight", context)
                residual = (hidden + projected).astype(np.float32)
                ffn_norm = rms_norm(residual, oracle.f32(f"{prefix}.ffn_norm.weight"), epsilon)
                gate = oracle.matvec(f"{prefix}.ffn_gate.weight", ffn_norm)
                up = oracle.matvec(f"{prefix}.ffn_up.weight", ffn_norm)
                activated = (silu(gate) * up).astype(np.float32)
                down = oracle.matvec(f"{prefix}.ffn_down.weight", activated)
                hidden = (residual + down).astype(np.float32)
                hidden_chain.update(hidden.astype("<f4").tobytes())

            normalized = rms_norm(hidden, oracle.f32("output_norm.weight"), epsilon)
            logits = oracle.matvec("token_embd.weight", normalized, rows_per_batch=128)
            greedy_id = int(np.argmax(logits))
            token_receipts.append(
                {
                    "position": position,
                    "context": position + 1,
                    "input_token_id": input_token_id,
                    "hidden_chain_sha256": hidden_chain.hexdigest(),
                    "normalized_output": _f32_summary(normalized),
                    "logits_sha256_f32_le": digest_f32(logits),
                    "greedy_token_id": greedy_id,
                    "greedy_token_logit": float(logits[greedy_id]),
                    "attention_weight_count": blocks * q_heads * (position + 1),
                }
            )
            if position + 1 < token_count:
                token_ids.append(greedy_id)

        return {
            "schema": "casulo-native-qwen-incremental-oracle/0.1",
            "claim": "bounded greedy incremental decoding with persistent per-layer KV state",
            "model": {
                "path": str(model),
                "bytes": len(mapping),
                "sha256": sha256_file(model),
                "architecture": metadata["general.architecture"],
            },
            "token_count": token_count,
            "token_ids": token_ids,
            "tokens": token_receipts,
            "kv_state": {
                "layers": blocks,
                "positions": token_count,
                "values": blocks * token_count * kv_heads * head_dim * 2,
            },
            "oracle": {
                "implementation": "independent Python/NumPy incremental GGUF decoder",
                "numpy_version": np.__version__,
                "external_api": False,
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the independent incremental Qwen3 oracle")
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--tokens", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents or output.exists():
        raise SystemExit("output must be a new append-only repository path")
    result = run(args.model.expanduser().resolve(strict=True), args.tokens)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "tokens": result["tokens"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
