from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def load_tool():
    path = ROOT / "research/interlocution/tools/run_holdouts.py"
    spec = importlib.util.spec_from_file_location("interlocution_holdouts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_holdouts_are_distinct_and_frozen_in_source() -> None:
    definitions = load_tool().definitions()
    assert len(definitions) == 2
    assert {item["kind"] for item in definitions} == {"linear_regression", "logistic_binary"}
    assert {item["loss"] for item in definitions} == {"mae", "bce_logits"}
    assert len({item["seed"] for item in definitions}) == 2
    assert definitions[1]["working_set_count"] < definitions[1]["records"]


def test_independent_verifier_has_no_trainer_import() -> None:
    source = (ROOT / "research/interlocution/independent_holdout_verifier.py").read_text(encoding="utf-8")
    assert "interlocution.worker" not in source
    assert "run_holdouts" not in source
    assert "torch" not in source
