from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_arm_and_campaign_scripts_are_importable() -> None:
    arm = _load("interlocution_run_arm", ROOT / "research/interlocution/tools/run_arm.py")
    campaign = _load("interlocution_campaign", ROOT / "research/interlocution/tools/run_ablation_campaign.py")
    assert arm.CAMPAIGN.name == "2026-08-18-interlocution-live-instance-attempt1"
    assert campaign.ARM_SCRIPT.name == "run_arm.py"
    assert "args.attempt[6:].isdigit()" in (ROOT / "research/interlocution/tools/run_ablation_campaign.py").read_text(encoding="utf-8")


def test_four_arm_semantics_are_frozen_in_source() -> None:
    source = (ROOT / "research/interlocution/tools/run_arm.py").read_text(encoding="utf-8")
    assert '"A": "FOREIGN_BASELINE"' in source
    assert '"B": "FOREIGN_POSTHOC_T_RESULT_IGNORED"' in source
    assert '"C": "T_ARCHITECTURE_FOREIGN_ACCEPTANCE"' in source
    assert '"D": "T_JUDGE_CONSUMED"' in source
    assert "NO_ENERGY_INSTRUMENT_USED_IN_TI9_TI10" in source
    assert "post-hoc auditing cannot" in source
