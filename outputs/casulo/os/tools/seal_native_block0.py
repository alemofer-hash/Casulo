from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / "outputs/casulo/native-neural-port/2026-08-21-np6"
IMAGE = ROOT / "release/casulo-native-neural-port-np6-attempt-4.img"
IMAGE_MANIFEST = IMAGE.with_suffix(".manifest.json")
MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
SOURCE_FILES = (
    "os/native-model/Cargo.toml",
    "os/native-model/src/lib.rs",
    "os/native-model/examples/block0_host.rs",
    "os/kernel/src/model_block0_oracle.rs",
    "os/kernel/src/model_block0_probe.rs",
    "os/kernel/src/fw_cfg.rs",
    "os/kernel/src/memory.rs",
    "os/kernel/src/main.rs",
    "os/tools/inventory_native_block0.py",
    "os/tools/verify_native_block0.py",
    "os/tools/build_native_neural_port_image.py",
    "os/tools/run_native_block0_qemu.py",
    "tests/product/test_native_block0_runner.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest_path = CAMPAIGN / "MANIFEST.json"
    sums_path = CAMPAIGN / "SHA256SUMS"
    if manifest_path.exists() or sums_path.exists():
        raise SystemExit("append-only NP6 seal already exists")
    definitive_path = CAMPAIGN / "qemu-definitive-3boots-attempt-2.json"
    oracle_path = CAMPAIGN / "block0-oracle-attempt-3.json"
    host_comparison_path = CAMPAIGN / "host-verification/block0-comparison.json"
    definitive = json.loads(definitive_path.read_text(encoding="utf-8"))
    host_comparison = json.loads(host_comparison_path.read_text(encoding="utf-8"))
    image_manifest = json.loads(IMAGE_MANIFEST.read_text(encoding="utf-8"))
    if (
        not definitive["passed"]
        or len(definitive["boots"]) != 3
        or not all(boot["validation"]["passed"] for boot in definitive["boots"])
        or host_comparison["status"] != "PASS"
        or image_manifest["sha256"] != sha256(IMAGE)
        or definitive["model"]["sha256_after"] != MODEL_SHA256
    ):
        raise SystemExit("NP6 evidence does not satisfy the seal contract")
    failures = [
        ("block0-oracle.json", "incorrect rotate-half assumption for GGML RoPE ABI"),
        ("block0-oracle-attempt-2.json", "correct RoPE but incomplete intermediate-stage inventory"),
        ("qemu-smoke-whpx.json", "two-token WHPX scope timed out"),
        ("qemu-smoke-tcg.json", "two-token TCG scope timed out"),
        ("qemu-smoke-tcg-prefetch.json", "two-token TCG scope remained outside bounded window"),
        ("qemu-smoke-tcg-one-token.json", "strict one-token TCG scope timed out"),
        ("qemu-smoke-whpx-one-token.json", "block passed but inherited validator required superseded marker"),
        ("qemu-definitive-3boots.json", "three technical passes retained stale validator boolean"),
    ]
    manifest = {
        "schema": "casulo-native-neural-port-evidence/0.1",
        "campaign_id": "2026-08-21-np6",
        "closed_date": "2026-08-21",
        "state": "NATIVE_ONE_COMPLETE_QWEN3_BLOCK_VALIDATED_36_BLOCKS_PENDING",
        "source_model": {
            "file_name": "Qwen3-4B-Q4_K_M.gguf",
            "bytes": 2_497_280_256,
            "sha256": MODEL_SHA256,
            "copied_into_repository": False,
            "unchanged": definitive["model"]["unchanged"],
        },
        "authoritative_image": {
            "path": IMAGE.relative_to(ROOT).as_posix(),
            "bytes": IMAGE.stat().st_size,
            "sha256": sha256(IMAGE),
            "manifest_sha256": sha256(IMAGE_MANIFEST),
            "system_pack": image_manifest["system_pack"],
            "system_pack_sha256": image_manifest["system_pack_sha256"],
        },
        "native_work": {
            "tokens": 1,
            "contexts": [1],
            "matvec_calls": 7,
            "quantized_blocks": 394_240,
            "weight_bytes_read": 63_866_880,
            "multiply_accumulates": 100_925_440,
            "attention_scores": 32,
            "arena_bytes": 259_328,
            "oracle_stages": 19,
            "output_sha256": "487179f486f1df8a132b66f7ef1f542a4f1a8768278dfe67d8e5bcaab77b0b51",
        },
        "host_work": {
            "tokens": 2,
            "contexts": [1, 2],
            "oracle_stages": 38,
            "comparison_status": host_comparison["status"],
            "scope": "supplementary host execution; Native claim remains one complete token position",
        },
        "validation": {
            "python_tests_passed": 31,
            "rust_tests_passed": 14,
            "qemu_boots_passed": 3,
            "qemu_boots_total": 3,
            "unique_output_hashes": len(
                {boot["metrics"]["CASULO_NATIVE_BLOCK0_OUTPUT_SHA256"] for boot in definitive["boots"]}
            ),
            "missing_model_rejected": definitive["negative_controls"][0]["passed"],
            "truncated_model_rejected": definitive["negative_controls"][1]["passed"],
            "shape_mutation_rejected": True,
            "wider_rope_rejected": True,
            "wider_context_rejected": True,
            "later_blocks_executed": False,
            "logits_executed": False,
            "first_model_derived_output_token": False,
        },
        "preserved_failures": [
            {"artifact": f"outputs/casulo/native-neural-port/2026-08-21-np6/{name}", "sha256": sha256(CAMPAIGN / name), "cause": cause}
            for name, cause in failures
        ],
        "evidence": {
            "oracle_sha256": sha256(oracle_path),
            "host_comparison_sha256": sha256(host_comparison_path),
            "definitive_three_boots_sha256": sha256(definitive_path),
        },
        "source_hashes": {name: sha256(ROOT / name) for name in SOURCE_FILES},
        "claims_not_authorized": [
            "all 36 transformer blocks executed",
            "logits or model-derived output token",
            "complete Qwen decoder inference",
            "performance, compression or energy advantage",
            "general RoPE or full 40960-token context support",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sealed = sorted(path for path in CAMPAIGN.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    sums_path.write_text(
        "".join(f"{sha256(path)}  {path.relative_to(CAMPAIGN).as_posix()}\n" for path in sealed),
        encoding="ascii",
        newline="\n",
    )
    print(json.dumps({"manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "sha256sums_sha256": sha256(sums_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
