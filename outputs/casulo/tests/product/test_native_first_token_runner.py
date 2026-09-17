from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "os/tools/run_native_first_token_qemu.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_np8_requires_t_authority_before_model_token_publication() -> None:
    runner = load(RUNNER, "native_first_token")
    markers = set(runner.NP8_MARKERS)
    assert "CASULO_NATIVE_SAMPLING_AUTHORITY=T/2.0" in markers
    assert "CASULO_NATIVE_OUTPUT_TOKEN_MODEL_DERIVED=YES" in markers
    assert "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=PASS" in markers
    assert "CASULO_NATIVE_SAMPLING_GATE=PASS" in markers
    source = RUNNER.read_text(encoding="utf-8")
    assert '"guest_network": False' in source
    assert '"external_api": False' in source
    assert '"physical_device_written": False' in source
    assert "shell=True" not in source
    ast.parse(source)


def test_np8_preserves_unrelated_product_gate_failures() -> None:
    runner = load(RUNNER, "native_first_token_validation")
    validation = {
        "missing_markers": ["CASULO_NATIVE_NEURAL_INFERENCE=NOT_EXECUTED", "HEAP_ALLOC=PASS"],
        "forbidden_markers": [],
        "passed": False,
    }
    observed = runner.finalize_np8_validation(
        {"returncode": 33, "timed_out": False}, validation, [], []
    )
    assert observed["passed"] is False
    assert observed["missing_markers"] == ["HEAP_ALLOC=PASS"]


def test_sampling_policy_is_real_t_source_and_causally_checked() -> None:
    policy = (ROOT / "private/casulo-owner/t-v2/native-sampling-policy.t").read_text(encoding="utf-8")
    kernel = (ROOT / "os/kernel/src/main.rs").read_text(encoding="utf-8")
    decoder = (ROOT / "os/kernel/src/model_decoder_probe.rs").read_text(encoding="utf-8")
    runtime = (ROOT / "os/kernel/src/tcap_v2.rs").read_text(encoding="utf-8")
    assert "language T/2.0" in policy
    assert policy.count('return ok "PUBLISH_TOKEN"') == 2
    assert 'input.token_index == 0' in policy
    assert 'input.token_index == 1' in policy
    assert "execute_with_payload" in decoder
    assert "previous_policy_receipt" in decoder
    assert "runtime_payload" in runtime
    assert "sampling_policy_matches" not in kernel
    assert "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=PASS" in kernel
    assert "decoder.sampling_tokens_authorized == decoder.incremental_tokens_completed" in kernel


def test_incremental_runner_streams_and_can_cancel_without_shell() -> None:
    path = ROOT / "os/tools/run_native_incremental_qemu.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "CASULO_NATIVE_STREAM_CANCEL_WINDOW=OPEN" in source
    assert "CASULO_NATIVE_STREAM_TOKEN_1_PUBLICATION=PASS" in source
    assert 'process.stdin.write("\\x03")' in source
    assert "shell=True" not in source
    assert tree is not None
