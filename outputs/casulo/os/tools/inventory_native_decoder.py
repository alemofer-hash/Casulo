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


def _digest_f32(values: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(values, dtype="<f4").tobytes(order="C")).hexdigest()


def run(model: Path, logits_output: Path | None = None) -> dict[str, object]:
    with model.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
        inspection = inspect_mapping(mapping)
        oracle = Oracle(mapping, inspection)
        metadata = inspection.metadata
        blocks = int(metadata["qwen3.block_count"])
        epsilon = float(metadata["qwen3.attention.layer_norm_rms_epsilon"])
        frequency_base = float(metadata["qwen3.rope.freq_base"])
        q_heads, kv_heads, head_dim = 32, 8, 128
        hidden = oracle.embedding(INPUT_TOKEN_ID)
        block_receipts: list[dict[str, object]] = []
        hidden_chain = hashlib.sha256()
        operation_counts = {
            "blocks": 0,
            "matvec_calls": 0,
            "multiply_accumulates": 0,
        }
        for block in range(blocks):
            prefix = f"blk.{block}"
            attn_norm = rms_norm(hidden, oracle.f32(f"{prefix}.attn_norm.weight"), epsilon)
            query = oracle.matvec(f"{prefix}.attn_q.weight", attn_norm)
            key = oracle.matvec(f"{prefix}.attn_k.weight", attn_norm)
            value = oracle.matvec(f"{prefix}.attn_v.weight", attn_norm)
            query = head_rms_norm(query, oracle.f32(f"{prefix}.attn_q_norm.weight"), q_heads, epsilon)
            key = head_rms_norm(key, oracle.f32(f"{prefix}.attn_k_norm.weight"), kv_heads, epsilon)
            query = rope(query, q_heads, 0, frequency_base)
            key = rope(key, kv_heads, 0, frequency_base)
            context, weights = attention(
                query,
                [key],
                [value],
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
            summary = _f32_summary(hidden)
            block_receipts.append(
                {
                    "block": block,
                    "output": summary,
                    "attention_weights": _f32_summary(weights),
                }
            )
            hidden_chain.update(hidden.astype("<f4").tobytes())
            operation_counts["blocks"] += 1
            operation_counts["matvec_calls"] += 7
            operation_counts["multiply_accumulates"] += 100_925_440

        normalized = rms_norm(hidden, oracle.f32("output_norm.weight"), epsilon)
        logits = oracle.matvec("token_embd.weight", normalized, rows_per_batch=128)
        if logits_output is not None:
            logits_output.parent.mkdir(parents=True, exist_ok=True)
            if logits_output.exists():
                raise FileExistsError(f"append-only logits output exists: {logits_output}")
            logits_output.write_bytes(np.asarray(logits, dtype="<f4").tobytes(order="C"))
        greedy_id = int(np.argmax(logits))
        operation_counts["matvec_calls"] += 1
        operation_counts["multiply_accumulates"] += 2_560 * 151_936
        return {
            "schema": "casulo-native-qwen-decoder-oracle/0.1",
            "claim": "one authentic input token through 36 Qwen3 blocks, output norm and tied-embedding logits; no sampling publication",
            "model": {
                "path": str(model),
                "bytes": len(mapping),
                "sha256": sha256_file(model),
                "gguf_version": inspection.version,
                "architecture": metadata["general.architecture"],
            },
            "input_token_id": INPUT_TOKEN_ID,
            "block_receipts": block_receipts,
            "operation_counts": operation_counts,
            "hidden_chain_sha256": hidden_chain.hexdigest(),
            "normalized_output": _f32_summary(normalized),
            "logits": {
                "summary": _f32_summary(logits),
                "sha256_f32_le": _digest_f32(logits),
                "greedy_token_id": greedy_id,
                "greedy_token_logit": float(logits[greedy_id]),
            },
            "oracle": {
                "implementation": "independent Python/NumPy GGUF decoder",
                "numpy_version": np.__version__,
                "sampling_executed": False,
                "external_api": False,
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the independent 36-block Qwen3 oracle")
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--logits-output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    if output.exists():
        raise SystemExit(f"append-only output exists: {output}")
    logits_output = args.logits_output.resolve() if args.logits_output else None
    if logits_output is not None and ROOT.resolve() not in logits_output.parents:
        raise SystemExit("logits output must remain inside repository")
    result = run(args.model.expanduser().resolve(strict=True), logits_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "blocks": result["operation_counts"]["blocks"],
                "hidden_chain_sha256": result["hidden_chain_sha256"],
                "logits": result["logits"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
