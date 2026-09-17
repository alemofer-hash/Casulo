from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "os/tools/run_native_creation_qemu.py"
PACK_MANIFEST = ROOT / "release/casulo-native-neural-port-system-pack-np10.cspk.manifest.json"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_np10_runner_encodes_complete_autoregressive_accounting() -> None:
    runner = load(RUNNER, "native_creation_runner")
    manifest = json.loads(PACK_MANIFEST.read_text(encoding="utf-8"))
    markers = set(runner._expected_markers(manifest, False))
    assert runner.EXPECTED_POSITIONS == 50 + 34 - 1
    assert "CASULO_NATIVE_CREATION_BLOCKS_COMPLETED=2988" in markers
    assert "CASULO_NATIVE_CREATION_MATVEC_CALLS=20999" in markers
    assert "CASULO_NATIVE_CREATION_MULTIPLY_ACCUMULATES=333848576000" in markers
    assert "CASULO_NATIVE_CREATION_ARTIFACT_RESULT=18" in markers
    assert "CASULO_NATIVE_CREATION_SCENE_FORM=Materialized" in markers
    assert "CASULO_NATIVE_NEURAL_INFERENCE=BOOT_TO_CREATION_T_AUTHORIZED" in markers
    source = RUNNER.read_text(encoding="utf-8")
    assert '"network": False' in source
    assert '"physical_device": False' in source
    assert '"external_api": False' in source
    assert "shell=True" not in source
    ast.parse(source)


def test_np10_cancel_contract_forbids_late_materialization() -> None:
    runner = load(RUNNER, "native_creation_cancel_runner")
    manifest = json.loads(PACK_MANIFEST.read_text(encoding="utf-8"))
    markers = set(runner._expected_markers(manifest, True))
    assert "CASULO_NATIVE_CREATION_OUTPUT_TOKENS=1" in markers
    assert "CASULO_NATIVE_CREATION_ACCEPTANCE=NOT_PUBLISHED" in markers
    assert "CASULO_NATIVE_NEURAL_INFERENCE=NATIVE_CREATION_CANCELLED_CLEAN" in markers


def test_np10_t_policy_is_generic_and_artifact_is_content_addressed() -> None:
    token_source = ROOT / "private/casulo-owner/t-v2/native-creation-token-policy.t"
    artifact_source = ROOT / "private/casulo-owner/t-v2/native-creation-add.t"
    acceptance_source = ROOT / "private/casulo-owner/t-v2/native-creation-acceptance.t"
    prompt = json.loads((ROOT / "private/casulo-owner/native-creation-prompt.json").read_text(encoding="utf-8"))
    manifest = json.loads(PACK_MANIFEST.read_text(encoding="utf-8"))
    policy = token_source.read_text(encoding="utf-8")
    assert "greedy-creation-v1" in policy
    assert "NOME=SomeDoisNumeros" not in policy
    oracle_ids = prompt["frozen_llama_cpp_oracle"]["output_token_ids"]
    assert ",".join(str(value) for value in oracle_ids) not in policy
    assert manifest["policies"]["token"]["source_sha256"] == digest(token_source)
    assert manifest["policies"]["artifact"]["source_sha256"] == digest(artifact_source)
    assert manifest["policies"]["acceptance"]["source_sha256"] == digest(acceptance_source)
    assert manifest["model_embedded"] is False
    assert manifest["network"] is False
    assert manifest["external_api"] is False
    assert manifest["physical_device_written"] is False


def test_np10_pack_has_exact_complete_entry_set() -> None:
    manifest = json.loads(PACK_MANIFEST.read_text(encoding="utf-8"))
    assert [(entry["name"], entry["kind"]) for entry in manifest["entries"]] == [
        ("BOOTSTRAP_TCAP", 1),
        ("UX_CONTRACT", 2),
        ("GUIDE_T_SOURCE", 3),
        ("MODEL_GGUF_PROBE", 4),
        ("NATIVE_SAMPLING_POLICY", 5),
        ("NATIVE_CREATION_PROMPT", 6),
        ("NATIVE_CREATION_ARTIFACT", 7),
        ("NATIVE_CREATION_ACCEPTANCE", 8),
    ]
