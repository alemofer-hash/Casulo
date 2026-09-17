from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("LOCALAPPDATA", "")) / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362"
EXPECTED_MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def binary_format(path: Path) -> str:
    if not path.is_file():
        return "MISSING"
    with path.open("rb") as handle:
        magic = handle.read(4)
    if magic[:2] == b"MZ":
        return "PE_COFF_WINDOWS"
    if magic == b"\x7fELF":
        return "ELF"
    return "UNKNOWN"


def inspect(cache: Path = CACHE, verify_model_hash: bool = True) -> dict[str, object]:
    adoption = cache / "ADOPTION.json"
    model = cache / "model/Qwen3-4B-Q4_K_M.gguf"
    runtime = cache / "runtime/llama-server.exe"
    adoption_payload = json.loads(adoption.read_text(encoding="utf-8")) if adoption.is_file() else {}
    source_patterns = ("ggml.c", "ggml.h", "llama.cpp", "llama.h", "CMakeLists.txt")
    source_files = sorted(
        path.relative_to(cache).as_posix()
        for pattern in source_patterns
        for path in cache.rglob(pattern)
        if path.is_file()
    ) if cache.is_dir() else []
    model_hash = sha256(model) if verify_model_hash and model.is_file() else adoption_payload.get("model_sha256")
    run_qemu = (ROOT / "os/tools/run_qemu.py").read_text(encoding="utf-8")
    qemu_memory = re.search(r'"-m",\s*"([0-9]+[MG])"', run_qemu)
    memory_source = (ROOT / "os/kernel/src/memory.rs").read_text(encoding="utf-8")
    heap = re.search(r"HEAP_SIZE:\s*usize\s*=\s*([^;]+);", memory_source)
    blockers = [
        {
            "id": "NATIVE_RUNTIME_TARGET",
            "observed": binary_format(runtime),
            "required": "freestanding x86_64 Casulo ABI object/library",
            "causal": True,
        },
        {
            "id": "NATIVE_RUNTIME_SOURCE",
            "observed_files": source_files,
            "required": "audited llama.cpp/ggml source or a first-party compatible decoder implementation",
            "causal": not bool(source_files),
        },
        {
            "id": "MODEL_ADDRESS_SPACE",
            "observed": "single small TCAP ramdisk; no GGUF mapping into ring 3",
            "required": "content-addressed model pack, bounded mapping and read-only tensor views",
            "causal": True,
        },
        {
            "id": "MEMORY_ENVELOPE",
            "observed_qemu_ram": qemu_memory.group(1) if qemu_memory else "UNKNOWN",
            "observed_kernel_heap_expression": heap.group(1).strip() if heap else "UNKNOWN",
            "model_bytes": model.stat().st_size if model.is_file() else 0,
            "required": "model plus KV/graph workspace admitted before execution",
            "causal": True,
        },
        {
            "id": "MODEL_GRAPH_RUNTIME",
            "observed": "MODEL_ASSERT + bounded DOT_I16X4 + TOKEN_EMIT only",
            "required": "GGUF metadata/tensor loader, Q4_K kernels, RMSNorm, RoPE, attention, FFN, KV cache, tokenizer and sampler",
            "causal": True,
        },
        {
            "id": "FREESTANDING_SERVICES",
            "observed": "no libc/libc++, file/mmap API, production threadpool or AVX process-state contract",
            "required": "narrow equivalents or runtime adaptation behind manifest-listed primitives",
            "causal": True,
        },
    ]
    passed = (
        adoption.is_file()
        and model.is_file()
        and model_hash == EXPECTED_MODEL_SHA256
        and binary_format(runtime) == "PE_COFF_WINDOWS"
        and not source_files
    )
    return {
        "schema": "casulo-native-inference-doctor/0.1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "cache": str(cache),
        "adoption_present": adoption.is_file(),
        "model": {
            "present": model.is_file(),
            "bytes": model.stat().st_size if model.is_file() else 0,
            "sha256": model_hash,
            "expected_sha256": EXPECTED_MODEL_SHA256,
            "hash_valid": model_hash == EXPECTED_MODEL_SHA256,
            "license": adoption_payload.get("model_license"),
        },
        "adopted_runtime": {
            "path": str(runtime),
            "format": binary_format(runtime),
            "license": adoption_payload.get("runtime_license"),
            "source_files_in_cache": source_files,
        },
        "nf3": {
            "abi": "ring3-capability-primitives/0.1",
            "model_bytes_consumed": 0,
            "neural_inference_executed": False,
        },
        "blockers": blockers,
        "classification_gate_passed": passed,
        "nf4_state": "BLOCKED_NATIVE_QWEN_RUNTIME_PORT" if passed else "BLOCKED_ENVIRONMENT_INTEGRITY",
        "first_model_derived_token": False,
        "forbidden_interpretation": "The NF3 token event is not a neural token and Windows llama.cpp cannot be executed as Casulo Native evidence.",
        "next_engineering_action": "adopt or implement an audited freestanding GGUF/Qwen decoder behind the NF3 ABI, then raise the bounded memory envelope before attaching model bytes read-only",
        "network_used": False,
        "external_api_used": False,
        "physical_device_written": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Casulo Native inference feasibility doctor")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-model-hash", action="store_true")
    args = parser.parse_args()
    report = inspect(args.cache.expanduser().resolve(), not args.skip_model_hash)
    output = args.output.expanduser().resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
