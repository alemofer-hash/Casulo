from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_native_gguf_probe import (
    GGML_TYPE_Q4_K,
    GGML_TYPE_Q6_K,
    MODEL,
    Q4_K_BLOCK_BYTES,
    Q6_K_BLOCK_BYTES,
    QK_K,
    inspect_file,
    sha256_file,
    write_append_only,
)


NP3_REPORT = ROOT / "outputs/casulo/native-neural-port/2026-08-20-np3/qemu-3boots.json"
CANDIDATE = ROOT / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json"
DEFAULT_OUTPUT = ROOT / "outputs/casulo/native-neural-port/2026-08-20-np3/model-inventory.json"

TYPE_NAMES = {
    0: "F32",
    GGML_TYPE_Q4_K: "Q4_K",
    GGML_TYPE_Q6_K: "Q6_K",
}


def tensor_storage_bytes(ggml_type: int, dimensions: tuple[int, ...]) -> int:
    elements = 1
    for dimension in dimensions:
        elements *= dimension
    if ggml_type == 0:
        return elements * 4
    if ggml_type == GGML_TYPE_Q4_K:
        if elements % QK_K:
            raise ValueError("Q4_K tensor element count is not block aligned")
        return elements // QK_K * Q4_K_BLOCK_BYTES
    if ggml_type == GGML_TYPE_Q6_K:
        if elements % QK_K:
            raise ValueError("Q6_K tensor element count is not block aligned")
        return elements // QK_K * Q6_K_BLOCK_BYTES
    raise ValueError(f"unaccounted GGML tensor type {ggml_type}")


def build_inventory(model: Path, candidate: dict[str, object], np3: dict[str, object]) -> dict[str, object]:
    expected = candidate["model"]
    if model.stat().st_size != int(expected["bytes"]):
        raise ValueError("model size differs from frozen candidate")
    observed_hash = sha256_file(model)
    if observed_hash != str(expected["sha256"]):
        raise ValueError("model SHA-256 differs from frozen candidate")

    inspection = inspect_file(model)
    counts: collections.Counter[str] = collections.Counter()
    payload_bytes: collections.Counter[str] = collections.Counter()
    largest: list[dict[str, object]] = []
    for tensor in inspection.tensors:
        type_name = TYPE_NAMES.get(tensor.ggml_type)
        if type_name is None:
            raise ValueError(f"model exposes unsupported GGML type {tensor.ggml_type}")
        size = tensor_storage_bytes(tensor.ggml_type, tensor.dimensions)
        counts[type_name] += 1
        payload_bytes[type_name] += size
        largest.append({
            "name": tensor.name,
            "type": type_name,
            "dimensions": list(tensor.dimensions),
            "payload_bytes": size,
            "absolute_offset": tensor.absolute_offset,
        })
    largest.sort(key=lambda item: int(item["payload_bytes"]), reverse=True)
    accounted = sum(payload_bytes.values())
    tensor_region = model.stat().st_size - inspection.data_offset
    metadata = inspection.metadata
    return {
        "schema": "casulo-native-qwen-inventory/0.1",
        "classification": "MODEL_INVENTORY_NOT_FULL_NATIVE_INFERENCE",
        "source_model": {
            "file_name": model.name,
            "bytes": model.stat().st_size,
            "sha256": observed_hash,
            "license": expected["license"],
            "architecture": metadata["general.architecture"],
            "gguf_version": inspection.version,
            "metadata_count": inspection.metadata_count,
            "tensor_count": inspection.tensor_count,
            "data_offset": inspection.data_offset,
            "tensor_region_bytes": tensor_region,
            "accounted_tensor_payload_bytes": accounted,
            "alignment_or_trailing_bytes": tensor_region - accounted,
        },
        "qwen3_config": {
            "context_length": metadata["qwen3.context_length"],
            "embedding_length": metadata["qwen3.embedding_length"],
            "feed_forward_length": metadata["qwen3.feed_forward_length"],
            "block_count": metadata["qwen3.block_count"],
            "attention_head_count": metadata["qwen3.attention.head_count"],
            "attention_head_count_kv": metadata["qwen3.attention.head_count_kv"],
            "rope_frequency_base": metadata["qwen3.rope.freq_base"],
            "rms_epsilon": metadata["qwen3.attention.layer_norm_rms_epsilon"],
        },
        "tensor_formats": {
            name: {"tensor_count": counts[name], "payload_bytes": payload_bytes[name]}
            for name in sorted(counts)
        },
        "largest_tensors": largest[:12],
        "current_native_envelope": {
            "qemu_guest_memory_bytes": 256 * 1024 * 1024,
            "kernel_heap_bytes": 2 * 1024 * 1024,
            "full_model_fits_current_guest_memory": model.stat().st_size <= 256 * 1024 * 1024,
            "full_model_fits_current_kernel_heap": model.stat().st_size <= 2 * 1024 * 1024,
        },
        "np3_evidence": {
            "state": np3["state"],
            "passed": np3["passed"],
            "boots": len(np3["boots"]),
            "full_model_mapped": np3["full_model_mapped"],
            "first_model_derived_token": np3["first_model_derived_token"],
            "claim": np3["claim"],
            "image_sha256": np3["image_sha256_after"],
            "probe_manifest_sha256": np3["probe_manifest_sha256"],
        },
        "remaining_native_decoder_surfaces": [
            "read-only full-model mapping without duplicating the owner weights",
            "tokenizer and Qwen chat-template boundary",
            "Q6_K embedding row lookup",
            "RMSNorm and quantized matrix-vector kernels",
            "Q/K normalization, RoPE, grouped-query attention and KV cache",
            "SwiGLU feed-forward path across 36 transformer blocks",
            "output projection, sampling and token streaming",
            "bounded allocator, cancellation, watchdog and capability receipts",
        ],
        "claims": {
            "authorized": [
                "Native parsed GGUF v3 metadata from a content-addressed projection",
                "Native consumed authentic F32, Q4_K and Q6_K bytes from the adopted model",
                "corrected Q4_K and Q6_K arithmetic probes passed three read-only QEMU boots",
            ],
            "not_authorized": [
                "full Qwen model mapped by Casulo Native",
                "model-derived token emitted by Casulo Native",
                "native neural conversation",
                "performance, energy or superiority claim",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory the adopted Qwen GGUF for the Casulo Native port")
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--np3-report", type=Path, default=NP3_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    np3 = json.loads(args.np3_report.read_text(encoding="utf-8"))
    inventory = build_inventory(args.model.expanduser().resolve(strict=True), candidate, np3)
    payload = (json.dumps(inventory, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_append_only(args.output, payload)
    print(json.dumps(inventory, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
