from __future__ import annotations

import json
from pathlib import Path

import pytest

from casulo.livelab.campaign import (
    CampaignPolicy,
    CampaignSpec,
    CampaignStatus,
    IsolationEvidence,
    PowerStateEvidence,
    ThermalEvidence,
    TrialMeasurement,
    evaluate_preflight,
    execute_paired_campaign,
    sha256_output,
)
from casulo.livelab.capabilities import Capability, CapabilityStatus, probe_capabilities
from casulo.livelab.reporting import write_campaign_reports
from casulo.livelab.preflight import main as preflight_main


def _capabilities() -> dict[str, Capability]:
    required = CampaignPolicy().required_capabilities + ("external_power_meter",)
    return {
        name: Capability(name, CapabilityStatus.AVAILABLE, True, "fake_test_fixture", "2026-01-01T00:00:00Z")
        for name in required
    }


def _ready_preflight():
    return evaluate_preflight(
        _capabilities(),
        thermal=ThermalEvidence("fake-sensor", (1, 2, 3), (40.0, 41.0, 42.0), False, True),
        power=PowerStateEvidence("fake-source", True, "performance", "fixed", True),
        isolation=IsolationEvidence(True, (0, 1, 2, 3), 4, "/fake/cgroup/campaign", {"cpu.max": "400000 100000"}),
    )


class FakeExecutor:
    def __init__(self, preflight, measurements):
        self.preflight = preflight
        self.measurements = iter(measurements)
        self.labels: list[str] = []

    def safety_check(self):
        return self.preflight

    def run_trial(self, label, workload, *, maximum_seconds):
        self.labels.append(label)
        workload()
        return next(self.measurements)


def _measurement(elapsed: int, *, digest: str | None = None, temperature: float = 44.0):
    return TrialMeasurement(elapsed, elapsed / 1_000_000_000, temperature, digest or sha256_output("same-output"))


def test_windows_preflight_blocks_without_invoking_workloads() -> None:
    preflight = evaluate_preflight(probe_capabilities(system="Windows"), thermal=None, power=None, isolation=None)
    calls = []

    def workload():
        calls.append("called")

    result = execute_paired_campaign(
        CampaignSpec("blocked", "torch", "casulo", 3),
        preflight,
        {"torch": workload, "casulo": workload},
        FakeExecutor(preflight, []),
    )
    assert result.status is CampaignStatus.BLOCKED_BEFORE_START
    assert not result.workload_started
    assert result.trials == ()
    assert result.workload_invocations == 0
    assert calls == []
    assert result.to_dict()["aggregates"] is None


def test_blocked_result_writes_durable_zero_trial_reports(tmp_path: Path) -> None:
    preflight = evaluate_preflight(probe_capabilities(system="Windows"), thermal=None, power=None, isolation=None)
    result = execute_paired_campaign(
        CampaignSpec("durable-block", "torch", "casulo", 3),
        preflight,
        {"torch": lambda: (_ for _ in ()).throw(AssertionError()), "casulo": lambda: (_ for _ in ()).throw(AssertionError())},
        FakeExecutor(preflight, []),
    )
    paths = write_campaign_reports(result, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["status"] == "blocked_before_start"
    assert payload["workload_invocations"] == 0
    assert payload["trials"] == []
    assert paths["csv"].read_text(encoding="utf-8").count("\n") == 1
    assert "Missing or failed gates" in paths["markdown"].read_text(encoding="utf-8")


def test_preflight_command_persists_failure_without_child_work(tmp_path: Path, capsys) -> None:
    output = tmp_path / "preflight"
    assert preflight_main(["--output", str(output), "--campaign-id", "command-test"]) == 2
    message = json.loads(capsys.readouterr().out)
    payload = json.loads((output / "campaign.json").read_text(encoding="utf-8"))
    assert message["status"] == "blocked_before_start"
    assert message["workload_started"] is False
    assert payload["workload_invocations"] == 0
    assert payload["trials"] == []


def test_fake_campaign_alternates_pairs_and_reports_descriptive_ratios(tmp_path: Path) -> None:
    preflight = _ready_preflight()
    measurements = [
        _measurement(600), _measurement(100),
        _measurement(100), _measurement(600),
        _measurement(600), _measurement(100),
    ]
    executor = FakeExecutor(preflight, measurements)
    result = execute_paired_campaign(
        CampaignSpec("deterministic", "torch", "casulo", 3),
        preflight,
        {"torch": lambda: None, "casulo": lambda: None},
        executor,
    )
    assert result.status is CampaignStatus.COMPLETE
    assert executor.labels == ["torch", "casulo", "casulo", "torch", "torch", "casulo"]
    aggregates = result.to_dict()["aggregates"]
    assert aggregates["speedup_baseline_over_candidate"] == pytest.approx(6.0)
    assert aggregates["energy_ratio_baseline_over_candidate"] == pytest.approx(6.0)
    paths = write_campaign_reports(result, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["schema"] == "casulo-livelab-paired-campaign/1"
    assert len(paths["csv"].read_text(encoding="utf-8").splitlines()) == 7
    assert "descriptive only" in paths["markdown"].read_text(encoding="utf-8")


def test_output_mismatch_aborts_without_claim() -> None:
    preflight = _ready_preflight()
    executor = FakeExecutor(preflight, [_measurement(10, digest=sha256_output("a")), _measurement(9, digest=sha256_output("b"))])
    result = execute_paired_campaign(
        CampaignSpec("mismatch", "torch", "casulo", 3), preflight,
        {"torch": lambda: None, "casulo": lambda: None}, executor,
    )
    assert result.status is CampaignStatus.ABORTED
    assert result.abort_reason == "output_digest_mismatch"
    assert result.to_dict()["aggregates"] is None


def test_thermal_limit_aborts_at_first_hot_trial() -> None:
    preflight = _ready_preflight()
    executor = FakeExecutor(preflight, [_measurement(10, temperature=56.0)])
    result = execute_paired_campaign(
        CampaignSpec("hot", "torch", "casulo", 3), preflight,
        {"torch": lambda: None, "casulo": lambda: None}, executor,
    )
    assert result.status is CampaignStatus.ABORTED
    assert result.abort_reason == "thermal_limit_exceeded"
    assert len(result.trials) == 1


@pytest.mark.parametrize(
    ("thermal", "power", "isolation", "reason"),
    [
        (ThermalEvidence("sensor", (1, 1, 2), (40.0, 40.0, 40.0), False, True), PowerStateEvidence("x", True, "fixed", "fixed", True), IsolationEvidence(True, (0,), 1, "/cg", {}), "thermal_stream_not_advancing"),
        (ThermalEvidence("sensor", (1, 2, 3), (40.0, 40.0, 40.0), False, True), None, IsolationEvidence(True, (0,), 1, "/cg", {}), "power_state_evidence_missing"),
        (ThermalEvidence("sensor", (1, 2, 3), (40.0, 40.0, 40.0), False, True), PowerStateEvidence("x", True, "fixed", "fixed", True), None, "isolation_evidence_missing"),
    ],
)
def test_each_missing_safety_evidence_blocks(thermal, power, isolation, reason) -> None:
    report = evaluate_preflight(_capabilities(), thermal=thermal, power=power, isolation=isolation)
    assert report.status is CampaignStatus.BLOCKED_BEFORE_START
    assert reason in {gate.reason_code for gate in report.gates}
