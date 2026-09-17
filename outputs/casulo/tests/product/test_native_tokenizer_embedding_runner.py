from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "os/tools/run_native_tokenizer_embedding_qemu.py"
INVENTORY = ROOT / "os/tools/inventory_native_tokenizer.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("native_tokenizer_embedding_runner", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_np5_runner_preserves_scope_and_safety_boundary() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert '"first_model_derived_output_token": False' in source
    assert '"chat_template_executed": False' in source
    assert '"transformer_executed": False' in source
    assert '"guest_network": False' in source
    assert '"physical_device_written": False' in source
    assert "shell=True" not in source
    ast.parse(source)


def test_np5_markers_require_real_oracle_cases_and_embedding() -> None:
    runner = load_runner()
    markers = set(runner.NP5_MARKERS)
    assert "CASULO_NATIVE_TOKENIZER_CASE_CASULO=49242,8763" in markers
    assert "CASULO_NATIVE_TOKENIZER_CASE_OLA_CASULO=42719,1953,11,11054,8763,13" in markers
    assert "CASULO_NATIVE_EMBEDDING_ROW_OFFSET=109374792" in markers
    assert "CASULO_NATIVE_TOKENIZER_FIRST_OUTPUT_TOKEN=NO" in markers


def test_np5_metrics_and_gate_trace_are_content_bounded() -> None:
    runner = load_runner()
    serial = (
        "private-user-text=do-not-collect\n"
        "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=PASS\n"
        "CASULO_NATIVE_EMBEDDING_TOKEN_ID=49242\n"
        "G7_DEMO_COMPLETE=PASS\n"
    )
    assert runner.native_metrics(serial) == {
        "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE": "PASS",
        "CASULO_NATIVE_EMBEDDING_TOKEN_ID": "49242",
    }
    assert runner.gate_trace(serial) == [
        "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=PASS",
        "G7_DEMO_COMPLETE=PASS",
    ]


def test_tokenizer_inventory_is_offline_append_only_and_console_safe() -> None:
    source = INVENTORY.read_text(encoding="utf-8")
    assert '"--offline"' in source
    assert "shell=False" in source
    assert "ensure_ascii=True" in source
    assert "if output.exists():" in source
    assert "append-only output exists" in source
    ast.parse(source)
