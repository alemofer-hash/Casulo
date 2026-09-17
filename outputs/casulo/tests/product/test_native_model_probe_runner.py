from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_model_probe_runner_is_read_only_and_networkless() -> None:
    source = (ROOT / "os/tools/run_native_model_probe_qemu.py").read_text(encoding="utf-8")
    assert "image_read_only" in source
    assert '"guest_network": False' in source
    assert '"physical_device_written": False' in source
    assert "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=NO" in source
    assert "shell=True" not in source
    ast.parse(source)


def test_neural_port_builder_scopes_token_claim_to_token_capable_stages() -> None:
    source = (ROOT / "os/tools/build_native_neural_port_image.py").read_text(encoding="utf-8")
    assert '"first_model_derived_token": args.stage in ("np8", "np9", "np10")' in source
    assert '"np1": "authentic adopted-model Q4_K block parsed and executed in Native; not decoder inference"' in source
    assert '"physical_device_written": False' in source
    assert "--offline" in source
    ast.parse(source)
