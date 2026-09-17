from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import numpy as np

from tools.build_native_gguf_probe import dequantize_q4_k, dequantize_q6_k


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "os/tools/run_native_block0_qemu.py"
ORACLE = ROOT / "os/tools/inventory_native_block0.py"
VERIFIER = ROOT / "os/tools/verify_native_block0.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_np6_runner_preserves_scope_and_requires_complete_receipts() -> None:
    runner = load(RUNNER, "native_block0_runner")
    markers = set(runner.NP6_MARKERS)
    assert "CASULO_NATIVE_BLOCK0_TOKENS_COMPLETED=1" in markers
    assert "CASULO_NATIVE_BLOCK0_ORACLE_STAGES=19" in markers
    assert "CASULO_NATIVE_BLOCK0_ORACLE_MISMATCH_MASK=0000000000000000" in markers
    assert "CASULO_NATIVE_BLOCK0_LOGITS=NOT_EXECUTED" in markers
    assert "CASULO_NATIVE_BLOCK0_OUTPUT_TOKEN=NO" in markers
    source = RUNNER.read_text(encoding="utf-8")
    assert '"guest_network": False' in source
    assert '"physical_device_written": False' in source
    assert '"performance_measured": False' in source
    assert '"energy_measured": False' in source
    assert "shell=True" not in source
    ast.parse(source)


def test_np6_supersedes_only_the_historical_no_inference_marker() -> None:
    runner = load(RUNNER, "native_block0_runner_validation")
    validation = {
        "missing_markers": ["CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED"],
        "forbidden_markers": [],
        "passed": False,
    }
    observed = runner.finalize_np6_validation(
        {"returncode": 33, "timed_out": False}, validation, [], []
    )
    assert observed["passed"] is True
    assert observed["missing_markers"] == []
    validation = {
        "missing_markers": ["CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED", "HEAP_ALLOC=PASS"],
        "forbidden_markers": [],
        "passed": False,
    }
    observed = runner.finalize_np6_validation(
        {"returncode": 33, "timed_out": False}, validation, [], []
    )
    assert observed["passed"] is False
    assert observed["missing_markers"] == ["HEAP_ALLOC=PASS"]


def test_vectorized_oracle_q4_and_q6_match_scalar_reference() -> None:
    oracle = load(ORACLE, "native_block0_oracle")
    q4 = np.arange(144, dtype=np.uint8)
    # Keep both half values finite and modest.
    q4[:4] = np.frombuffer(np.array([0.5, 0.125], dtype="<f2").tobytes(), dtype=np.uint8)
    expected_q4 = np.asarray(dequantize_q4_k(q4.tobytes()), dtype=np.float32)
    observed_q4 = oracle._decode_q4_blocks(q4.reshape(1, 144)).reshape(256)
    np.testing.assert_array_equal(observed_q4, expected_q4)

    q6 = (np.arange(210, dtype=np.uint8) * 7).astype(np.uint8)
    q6[208:210] = np.frombuffer(np.array([0.25], dtype="<f2").tobytes(), dtype=np.uint8)
    expected_q6 = np.asarray(dequantize_q6_k(q6.tobytes()), dtype=np.float32)
    observed_q6 = oracle._decode_q6_blocks(q6.reshape(1, 210)).reshape(256)
    np.testing.assert_array_equal(observed_q6, expected_q6)


def test_host_receipt_parser_rejects_duplicate_or_truncated_stages() -> None:
    verifier = load(VERIFIER, "native_block0_verifier")
    line = "STAGE|token_0.embedding|2560|1.0|2.0|-0.5|0.5"
    counters, stages = verifier.parse_stdout("TOKENS_COMPLETED=1\n" + line)
    assert counters == {"TOKENS_COMPLETED": "1"}
    assert stages["token_0.embedding"]["square_sum_f64"] == 2.0
    try:
        verifier.parse_stdout(line + "\n" + line)
    except ValueError as error:
        assert "duplicate stage" in str(error)
    else:
        raise AssertionError("duplicate receipt was accepted")
    try:
        verifier.parse_stdout("STAGE|truncated|1|2")
    except ValueError as error:
        assert "invalid stage receipt" in str(error)
    else:
        raise AssertionError("truncated receipt was accepted")


def test_np6_builder_and_verifier_keep_output_token_forbidden() -> None:
    builder = (ROOT / "os/tools/build_native_neural_port_image.py").read_text(encoding="utf-8")
    verifier = VERIFIER.read_text(encoding="utf-8")
    assert '"np6": "NP6_ONE_COMPLETE_QWEN3_TRANSFORMER_BLOCK"' in builder
    assert '"first_model_derived_token": args.stage in ("np8", "np9", "np10")' in builder
    assert '"np6": "one authentic token position executed through complete Qwen3 block zero' in builder
    assert "no later block/logits/output token" in builder
    assert "model identity diverges from oracle" in verifier
    assert "timeout=120" in verifier
    ast.parse(verifier)
