from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.native_inference_doctor import binary_format, inspect


def test_doctor_classifies_windows_runtime_without_source(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    (cache / "model").mkdir(parents=True)
    (cache / "runtime").mkdir()
    model = cache / "model/Qwen3-4B-Q4_K_M.gguf"
    model.write_bytes(b"GGUF-test")
    (cache / "runtime/llama-server.exe").write_bytes(b"MZ\x00\x00")
    (cache / "ADOPTION.json").write_text(
        json.dumps({
            "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
            "model_license": "Apache-2.0",
            "runtime_license": "MIT",
        }),
        encoding="utf-8",
    )
    report = inspect(cache, verify_model_hash=False)
    assert report["adopted_runtime"]["format"] == "PE_COFF_WINDOWS"
    assert report["adopted_runtime"]["source_files_in_cache"] == []
    assert report["first_model_derived_token"] is False
    assert report["nf4_state"] == "BLOCKED_ENVIRONMENT_INTEGRITY"


def test_binary_format_does_not_treat_arbitrary_bytes_as_native(tmp_path: Path) -> None:
    artifact = tmp_path / "runtime.bin"
    artifact.write_bytes(b"not-a-runtime")
    assert binary_format(artifact) == "UNKNOWN"
