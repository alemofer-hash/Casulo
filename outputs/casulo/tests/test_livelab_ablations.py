from __future__ import annotations

import pytest

from casulo.livelab.ablations import (
    PREREGISTERED_ABLATION_PLAN,
    canonical_plan_bytes,
    profiling_record,
)


EXPECTED_AXES = {
    "buffer-reuse",
    "vectorization",
    "optimization-level",
    "workers",
    "autograd-specialization",
    "fusion",
    "shape-mode",
    "compiler-route",
    "scheduler-policy",
}


def test_ablation_plan_preregisters_every_required_axis() -> None:
    plan = PREREGISTERED_ABLATION_PLAN

    assert {item.axis_id for item in plan.axes} == EXPECTED_AXES
    assert plan.minimum_pairs == 21
    assert plan.warmups == 3
    assert plan.sha256 == "1b2eed200792a874b4e76cd9d023233702526aee3493d3db3a8662f604457a60"
    assert canonical_plan_bytes() == canonical_plan_bytes(plan)
    assert plan.to_dict()["scientific_invariants"]["unfavorable_results_preserved"]


def test_unavailable_profile_is_explicit_null_not_zero() -> None:
    record = profiling_record({}, status="unavailable", reason="perf absent")

    assert record["status"] == "unavailable"
    assert all(value is None for value in record["counters"].values())


def test_profile_rejects_partial_measured_or_invented_unavailable_values() -> None:
    with pytest.raises(ValueError, match="complete and nonnegative"):
        profiling_record({"cycles": 10}, status="measured", reason=None)
    with pytest.raises(ValueError, match="must be null"):
        profiling_record({"cycles": 0}, status="unavailable", reason="absent")
    with pytest.raises(ValueError, match="unknown profiling"):
        profiling_record({"temperature_as_energy": 1}, status="measured", reason=None)
