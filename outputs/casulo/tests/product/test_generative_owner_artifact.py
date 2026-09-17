from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "build_generative_owner_artifact",
        ROOT / "tools/build_generative_owner_artifact.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_artifact_is_exact_allowlist_and_excludes_reference_engine(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "casulo-owner-generative.zip"
    result = module.build(
        output,
        ROOT / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json",
    )
    assert result["audit"]["pass"] is True
    assert result["audit"]["generative_adapter_present"] is True
    assert result["audit"]["reference_engine_absent"] is True
    with zipfile.ZipFile(output) as archive:
        manifest = archive.read("OWNER_ARTIFACT.json")
        names = archive.namelist()
    assert b'"fake_engine_included": false' in manifest
    assert b'"model_weights_embedded": false' in manifest
    assert not any(name.endswith(("motor.py", "adapter.py", "alpha_demo.py")) for name in names)


def test_artifact_never_overwrites_existing_destination(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "preserve.zip"
    output.write_bytes(b"user-data")
    with pytest.raises(RuntimeError, match="overwrite denied"):
        module.build(
            output,
            ROOT / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json",
        )
    assert output.read_bytes() == b"user-data"


def test_semantic_multiverse_owner_artifact_adds_only_private_adapter(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "casulo-owner-semantic.zip"
    result = module.build(
        output,
        ROOT / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json",
        semantic_multiverse=True,
    )
    assert result["audit"]["pass"] is True
    assert "casulo_owner/semantic_multiverse.py" in result["audit"]["files"]
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("OWNER_ARTIFACT.json"))
        semantic = archive.read("casulo_owner/semantic_multiverse.py")
    assert manifest["semantic_multiverse"] is True
    assert b"CloudEngineClient" not in semantic
