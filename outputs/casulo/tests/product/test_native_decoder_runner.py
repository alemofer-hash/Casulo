from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "os/tools/run_native_decoder_qemu.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_np7_runner_requires_complete_decoder_receipts_and_withholds_publication() -> None:
    runner = load(RUNNER, "native_decoder_runner")
    markers = set(runner.NP7_MARKERS)
    assert "CASULO_NATIVE_DECODER_BLOCKS_COMPLETED=36" in markers
    assert "CASULO_NATIVE_DECODER_MATVEC_CALLS=253" in markers
    assert "CASULO_NATIVE_DECODER_MULTIPLY_ACCUMULATES=4022272000" in markers
    assert "CASULO_NATIVE_DECODER_GREEDY_CANDIDATE_ID=6237" in markers
    assert "CASULO_NATIVE_DECODER_CANCELLATION_CONTROL=PASS" in markers
    assert "CASULO_NATIVE_DECODER_OUTPUT_TOKEN=NO_POLICY_GATE_PENDING" in markers
    source = RUNNER.read_text(encoding="utf-8")
    assert '"guest_network": False' in source
    assert '"physical_device_written": False' in source
    assert '"sampling_executed": False' in source
    assert "shell=True" not in source
    ast.parse(source)


def test_np7_supersedes_only_the_historical_no_inference_marker() -> None:
    runner = load(RUNNER, "native_decoder_runner_validation")
    validation = {
        "missing_markers": ["CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED"],
        "forbidden_markers": [],
        "passed": False,
    }
    observed = runner.finalize_np7_validation(
        {"returncode": 33, "timed_out": False}, validation, [], []
    )
    assert observed["passed"] is True
    assert observed["missing_markers"] == []

    validation = {
        "missing_markers": ["CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED", "HEAP_ALLOC=PASS"],
        "forbidden_markers": [],
        "passed": False,
    }
    observed = runner.finalize_np7_validation(
        {"returncode": 33, "timed_out": False}, validation, [], []
    )
    assert observed["passed"] is False
    assert observed["missing_markers"] == ["HEAP_ALLOC=PASS"]


def test_np7_builder_enables_decoder_without_reexecuting_np6_probe() -> None:
    builder = (ROOT / "os/tools/build_native_neural_port_image.py").read_text(encoding="utf-8")
    assert '"np7": "NP7_COMPLETE_QWEN3_DECODER_TO_LOGITS"' in builder
    assert 'environment["CASULO_NATIVE_MODEL_DECODER"] = "1" if args.stage in ("np7", "np8", "np9", "np10") else "0"' in builder
    assert 'environment["CASULO_NATIVE_MODEL_RESIDENT"] = "1" if args.stage in ("np9", "np10") else "0"' in builder
    assert 'environment["CASULO_NATIVE_MODEL_BLOCK0"] = "1" if args.stage == "np6" else "0"' in builder
    assert '"first_model_derived_token": args.stage in ("np8", "np9", "np10")' in builder
    assert 'environment["CASULO_NATIVE_CREATION"] = "1" if args.stage == "np10" else "0"' in builder
    ast.parse(builder)


def test_decoder_metrics_reject_duplicate_receipts() -> None:
    runner = load(RUNNER, "native_decoder_duplicate")
    line = "CASULO_NATIVE_DECODER_GATE=PASS"
    try:
        runner.decoder_metrics(line + "\n" + line)
    except ValueError as error:
        assert "duplicate decoder marker" in str(error)
    else:
        raise AssertionError("duplicate decoder receipt was accepted")
