from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from casulo.livelab.campaign import (
    CampaignPolicy, CampaignSpec, CampaignStatus, IsolationEvidence,
    PowerStateEvidence, ThermalEvidence, TrialMeasurement, evaluate_preflight,
    execute_paired_campaign, sha256_output,
)
from casulo.livelab.capabilities import Capability, CapabilityStatus
from casulo.livelab.controls import ControlStatus, PerfCollector, SchedExtController, UClampController
from casulo.livelab.energy import ExternalMeterSample
from casulo.livelab.executor import (
    BoundedExecutorConfig, BoundedProcessExecutor, ProcessWorkload, ThermalPoint,
)
from casulo.livelab.isolation import CgroupChildPlan


def _ready():
    required = CampaignPolicy().required_capabilities + ("external_power_meter",)
    capabilities = {name: Capability(name, CapabilityStatus.AVAILABLE, True, "fixture", "now") for name in required}
    return evaluate_preflight(
        capabilities,
        thermal=ThermalEvidence("sensor", (1, 2, 3), (40.0, 40.0, 40.0), False, True),
        power=PowerStateEvidence("fixture", True, "fixed", "fixed", True),
        isolation=IsolationEvidence(True, (0,), 1, "/fixture", {}),
    )


class FakeExecutor:
    def __init__(self, measurements):
        self.measurements = iter(measurements)

    def safety_check(self):
        return _ready()

    def run_trial(self, label, workload, *, maximum_seconds):
        workload()
        return next(self.measurements)


def test_strict_statistics_use_paired_ratios_seeded_bootstrap_and_exact_sign_test() -> None:
    digest = sha256_output("equivalent")
    measurements = []
    for index in range(21):
        by_label = {
            "base": TrialMeasurement(200 + index, 2.0 + index / 100, 42.0, digest, 50 if index == 0 else 0, {"execute": 200 + index}, "fixed"),
            "candidate": TrialMeasurement(100 + index, 1.0 + index / 100, 42.0, digest, 80 if index == 0 else 0, {"execute": 100 + index}, "fixed"),
        }
        order = ("base", "candidate") if index % 2 == 0 else ("candidate", "base")
        measurements.extend(by_label[label] for label in order)
    spec = CampaignSpec(
        "strict", "base", "candidate", 21, strict_statistics=True,
        bootstrap_seed=7, bootstrap_resamples=1000, compile_amortization_runs=100,
        require_power_parity=True,
    )
    result = execute_paired_campaign(spec, _ready(), {"base": lambda: None, "candidate": lambda: None}, FakeExecutor(measurements))
    aggregate = result.to_dict()["aggregates"]
    ratios = [(200 + index) / (100 + index) for index in range(21)]
    assert result.status is CampaignStatus.COMPLETE
    assert aggregate["estimator"] == "median_of_paired_ratios"
    assert aggregate["speedup_baseline_over_candidate"] == pytest.approx(sorted(ratios)[10])
    assert aggregate["paired_ratio_ci95"]["seed"] == 7
    assert aggregate["paired_exact_sign_test"] == {
        "method": "two_sided_exact_sign_test", "wins": 21, "losses": 0,
        "ties": 0, "p_value": pytest.approx(2 / 2**21),
    }
    assert aggregate["compile_elapsed_ns_total"] == {"base": 50, "candidate": 80}
    assert aggregate["median_phase_timings_ns"]["candidate"]["execute"] == 110.0


def test_strict_campaign_rejects_fewer_than_21_pairs() -> None:
    with pytest.raises(ValueError, match="at least"):
        CampaignSpec("short", "a", "b", 20, strict_statistics=True)


def test_only_preregistered_exclusions_are_accepted() -> None:
    digest = sha256_output("same")
    bad = TrialMeasurement(1, None, 40, digest, exclusion_reason="thermal_noise")
    result = execute_paired_campaign(
        CampaignSpec("unregistered", "a", "b", 3), _ready(),
        {"a": lambda: None, "b": lambda: None}, FakeExecutor([bad]),
    )
    assert result.status is CampaignStatus.ABORTED
    assert result.abort_reason == "unregistered_exclusion"


def test_power_parity_is_global_not_only_within_each_pair() -> None:
    digest = sha256_output("same")
    measurements = [
        TrialMeasurement(2, None, 40, digest, power_state_signature="fixed-a"),
        TrialMeasurement(1, None, 40, digest, power_state_signature="fixed-a"),
        TrialMeasurement(1, None, 40, digest, power_state_signature="fixed-b"),
    ]
    result = execute_paired_campaign(
        CampaignSpec("power-drift", "a", "b", 3, require_power_parity=True), _ready(),
        {"a": lambda: None, "b": lambda: None}, FakeExecutor(measurements),
    )
    assert result.status is CampaignStatus.ABORTED
    assert result.abort_reason == "power_state_parity_failed"


def test_strict_campaign_aborts_when_preregistered_exclusion_drops_below_21() -> None:
    digest = sha256_output("same")
    measurements = []
    for pair_index in range(21):
        reason = "thermal_noise" if pair_index == 0 else None
        pair = {
            "a": TrialMeasurement(2, None, 40, digest, exclusion_reason=reason),
            "b": TrialMeasurement(1, None, 40, digest, exclusion_reason=reason),
        }
        order = ("a", "b") if pair_index % 2 == 0 else ("b", "a")
        measurements.extend(pair[label] for label in order)
    result = execute_paired_campaign(
        CampaignSpec("excluded", "a", "b", 21, strict_statistics=True, preregistered_exclusions=("thermal_noise",)),
        _ready(), {"a": lambda: None, "b": lambda: None}, FakeExecutor(measurements),
    )
    assert result.status is CampaignStatus.ABORTED
    assert result.abort_reason == "insufficient_valid_pairs"
    assert result.to_dict()["aggregates"] is None


@pytest.mark.parametrize("controller", [UClampController(), PerfCollector(), SchedExtController()])
def test_linux_only_controller_interfaces_are_explicitly_unavailable_on_windows(controller) -> None:
    report = controller.probe(system="Windows")
    assert report.status is ControlStatus.UNAVAILABLE
    assert report.reason_code == "unsupported_os:windows"


class Thermal:
    def __init__(self, values=(40.0,)):
        self.values = iter(values)
        self.last = 40.0

    def sample(self):
        self.last = next(self.values, self.last)
        return ThermalPoint(time.monotonic_ns(), self.last, False)


class Power:
    def sample_signature(self):
        return "ac:fixed"


class Energy:
    def __init__(self):
        self.joules = 10.0

    def read_sample(self):
        self.joules += 0.5
        return ExternalMeterSample("fake", time.monotonic_ns(), self.joules)


def _current_cpu() -> int:
    try:
        import psutil
        return psutil.Process().cpu_affinity()[0]
    except Exception:
        return 0


def test_bounded_executor_runs_real_child_and_proves_teardown(tmp_path: Path) -> None:
    executor = BoundedProcessExecutor(
        preflight_sampler=_ready, thermal_sampler=Thermal(), power_sampler=Power(),
        energy_adapter=Energy(),
        config=BoundedExecutorConfig((_current_cpu(),), 1, 55.0, poll_interval_seconds=0.01),
    )
    workload = ProcessWorkload((sys.executable, "-c", "print('canonical')"), tmp_path)
    measurement = executor.run_trial("candidate", lambda: workload, maximum_seconds=2.0)
    assert measurement.elapsed_ns > 0
    assert measurement.energy_joules == pytest.approx(0.5)
    assert measurement.power_state_signature == "ac:fixed"
    assert executor.live_child_pids == set()


def test_bounded_executor_terminates_process_tree_on_dynamic_thermal_gate(tmp_path: Path) -> None:
    executor = BoundedProcessExecutor(
        preflight_sampler=_ready, thermal_sampler=Thermal((40.0, 40.0, 70.0)),
        power_sampler=Power(), energy_adapter=Energy(),
        config=BoundedExecutorConfig((_current_cpu(),), 1, 55.0, poll_interval_seconds=0.01),
    )
    workload = ProcessWorkload((sys.executable, "-c", "import time; time.sleep(2)"), tmp_path)
    with pytest.raises(Exception, match="dynamic_thermal_gate_failed"):
        executor.run_trial("candidate", lambda: workload, maximum_seconds=1.0)
    assert executor.live_child_pids == set()


def test_bounded_executor_enforces_wall_timeout_and_cleans_child(tmp_path: Path) -> None:
    executor = BoundedProcessExecutor(
        preflight_sampler=_ready, thermal_sampler=Thermal(), power_sampler=Power(),
        energy_adapter=Energy(),
        config=BoundedExecutorConfig((_current_cpu(),), 1, 55.0, poll_interval_seconds=0.01),
    )
    workload = ProcessWorkload((sys.executable, "-c", "import time; time.sleep(2)"), tmp_path)
    with pytest.raises(Exception, match="trial_timeout"):
        executor.run_trial("candidate", lambda: workload, maximum_seconds=0.03)
    assert executor.live_child_pids == set()


def test_bounded_executor_applies_transactional_cgroup_hook_before_release(tmp_path: Path) -> None:
    parent = tmp_path / "fake-cgroup"
    parent.mkdir()
    (parent / "cgroup.controllers").write_text("cpu cpuset\n", encoding="ascii")
    (parent / "cgroup.subtree_control").write_text("cpu cpuset\n", encoding="ascii")
    executor = BoundedProcessExecutor(
        preflight_sampler=_ready, thermal_sampler=Thermal(), power_sampler=Power(),
        energy_adapter=Energy(),
        config=BoundedExecutorConfig((_current_cpu(),), 1, 55.0, poll_interval_seconds=0.01),
        cgroup_plan_factory=lambda name: CgroupChildPlan(parent, name, cpu_weight=100),
    )
    workload = ProcessWorkload((sys.executable, "-c", "print('canonical')"), tmp_path)
    executor.run_trial("candidate", lambda: workload, maximum_seconds=2.0)
    assert not any(path.is_dir() for path in parent.iterdir())
    assert executor.live_child_pids == set()
