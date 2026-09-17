from __future__ import annotations

import pytest

from tools.generative_vm_handoff_probe import STEP_IDS, checked_bridge_line, judge_steps, one_line


def test_g10_judge_requires_all_sixteen_named_steps() -> None:
    passing = {step: {"passed": True} for step in STEP_IDS}
    assert len(passing) == 16
    assert judge_steps(passing)

    missing = dict(passing)
    missing.pop("export_feedback")
    assert not judge_steps(missing)

    failed = {**passing, "interrupt_and_correct": {"passed": False}}
    assert not judge_steps(failed)


def test_g10_judge_rejects_unknown_or_truthy_non_boolean_step() -> None:
    passing = {step: {"passed": True} for step in STEP_IDS}
    assert not judge_steps({**passing, "decorative_claim": {"passed": True}})
    non_boolean = dict(passing)
    non_boolean["simulate"] = {"passed": "yes"}
    assert not judge_steps(non_boolean)


def test_bridge_line_limit_is_measured_in_utf8_bytes() -> None:
    value = one_line(("ação çã õ " * 1000) + "\x00")
    assert 0 < len(value.encode("utf-8")) <= 4000
    assert "\x00" not in value
    assert checked_bridge_line(value, label="test") == value
    with pytest.raises(RuntimeError, match="vazia"):
        checked_bridge_line(" \n\t", label="empty")
