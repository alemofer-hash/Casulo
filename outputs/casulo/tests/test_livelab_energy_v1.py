from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from casulo.livelab.energy_v1.analysis import analyze_campaign, exact_sign_test, paired_bootstrap_ci
from casulo.livelab.energy_v1.artifacts import seal_campaign, verify_campaign
from casulo.livelab.energy_v1.battery_guard import BatterySnapshot, assess_battery_window
from casulo.livelab.energy_v1.capabilities import preflight_energy
from casulo.livelab.energy_v1.paired_runner import (
    CampaignInterrupted,
    EnergyReading,
    UnitCommand,
    accumulate_rapl_samples,
    run_paired_campaign,
)
from casulo.livelab.energy_v1.protocol import EnergyProtocol, deterministic_schedule, freeze_protocol
from casulo.livelab.energy_v1.rapl import discover_rapl_zones, package_zones, validate_rapl_zones
from casulo.livelab.energy import RaplSample
from casulo.livelab.energy_v1.schemas import SAMPLE_SCHEMA, canonical_bytes, iter_jsonl, sha256_bytes, validate_sample, write_json
from casulo.livelab.energy_v1.thermal_guard import ThermalSnapshot, assess_thermal_window
from casulo.livelab.energy_v1.wall_meter import align_window, import_meter_file, mock_samples, validate_meter_samples


def _zone(root: Path, relative: str, name: str, energy: str = "100", maximum: str = "1000") -> Path:
    zone = root / relative
    zone.mkdir(parents=True)
    (zone / "name").write_text(name, encoding="ascii")
    (zone / "energy_uj").write_text(energy, encoding="ascii")
    (zone / "max_energy_range_uj").write_text(maximum, encoding="ascii")
    return zone


def test_rapl_wraparound_advancing_and_hierarchy(tmp_path: Path) -> None:
    # NTFS rejects ':'; the Linux identity is represented by the zone name.
    package = _zone(tmp_path, "intel-rapl_0", "package-0", "950", "1000")
    _zone(package, "intel-rapl_0_0", "core", "200", "1000")
    zones = discover_rapl_zones(tmp_path)
    assert len(zones) == 2
    assert len(package_zones(zones)) == 1

    def load(_: float) -> int:
        (package / "energy_uj").write_text("25", encoding="ascii")
        return 7

    validation = validate_rapl_zones(zones, load=load)[0]
    assert validation.valid
    assert validation.delta_uj == 75
    assert validation.rollovers == 1
    assert validation.controlled_load_iterations == 7


@pytest.mark.parametrize("energy,maximum", [("truncated", "1000"), ("5", "0"), ("-1", "1000")])
def test_rapl_invalid_or_truncated_is_not_zero(tmp_path: Path, energy: str, maximum: str) -> None:
    _zone(tmp_path, "intel-rapl_0", "package-0", energy, maximum)
    result = validate_rapl_zones(discover_rapl_zones(tmp_path), load=lambda _: 1)[0]
    assert not result.valid
    assert result.delta_uj is None
    assert result.reason_code.startswith("rapl_invalid:")


def test_rapl_stationary_and_missing_metric_fail_closed(tmp_path: Path) -> None:
    _zone(tmp_path, "intel-rapl_0", "package-0")
    stationary = validate_rapl_zones(discover_rapl_zones(tmp_path), load=lambda _: 3)[0]
    assert stationary.reason_code == "rapl_counter_not_advancing"
    absent = validate_rapl_zones(())[0]
    assert absent.reason_code == "cpu_package_rapl_zone_absent"
    assert absent.delta_uj is None


def test_rapl_window_accumulates_multiple_observed_wraps() -> None:
    samples = (
        RaplSample("package", 950, 1, 1000),
        RaplSample("package", 25, 2, 1000),
        RaplSample("package", 900, 3, 1000),
        RaplSample("package", 10, 4, 1000),
    )
    energy_uj, rollovers, maximum_interval = accumulate_rapl_samples(samples)
    assert energy_uj == 1060
    assert rollovers == 2
    assert maximum_interval == 1


def test_wall_meter_csv_jsonl_and_mock_rejection(tmp_path: Path) -> None:
    csv_path = tmp_path / "meter.csv"
    csv_path.write_text(
        "device_id,timestamp_utc,cumulative_joules,watts\n"
        "meter-1,2026-08-07T12:00:00+00:00,10.0,20\n"
        "meter-1,2026-08-07T12:00:01+00:00,30.5,20.5\n",
        encoding="utf-8",
    )
    samples = import_meter_file(csv_path)
    accepted = validate_meter_samples(samples)
    assert accepted.valid and accepted.delta_joules == pytest.approx(20.5)
    before, after = align_window(
        samples,
        samples[0].epoch_seconds + 0.1,
        samples[-1].epoch_seconds - 0.1,
    )
    assert before.sequence == 0 and after.sequence == 1
    jsonl = tmp_path / "meter.jsonl"
    jsonl.write_text(
        json.dumps({"device_id": "meter-2", "epoch_seconds": 1, "cumulative_joules": 4}) + "\n"
        + json.dumps({"device_id": "meter-2", "epoch_seconds": 2, "cumulative_joules": 5}) + "\n",
        encoding="utf-8",
    )
    assert validate_meter_samples(import_meter_file(jsonl)).valid
    rejected = validate_meter_samples(mock_samples(((1, 1), (2, 2))))
    assert rejected.reason_code == "simulated_or_mock_source_rejected"
    assert not rejected.physical


def _battery(*, status: str = "Full", energy: float | None = 1000, resolution: float | None = 1, ac: bool = True, t: int = 1) -> BatterySnapshot:
    return BatterySnapshot("2026-08-07T00:00:00+00:00", t, True, ac, status, 100, energy, resolution, None, None, 0, 0, 12, "test")


def test_battery_transitions_charge_discharge_and_threshold() -> None:
    assert assess_battery_window(_battery(status="Full"), _battery(status="Charging", t=2), wall_energy_joules=100).reason_code == "battery_status_transition"
    assert assess_battery_window(_battery(status="Charging"), _battery(status="Charging", t=2), wall_energy_joules=100).reason_code == "battery_state_charging"
    assert assess_battery_window(_battery(status="Discharging"), _battery(status="Discharging", t=2), wall_energy_joules=100).reason_code == "battery_state_discharging"
    accepted = assess_battery_window(_battery(energy=1000), _battery(energy=1001.5, t=2), wall_energy_joules=100)
    assert accepted.accepted and accepted.allowed_delta_joules == 2
    rejected = assess_battery_window(_battery(energy=1000), _battery(energy=1003, t=2), wall_energy_joules=100)
    assert rejected.reason_code == "battery_energy_delta_exceeded"
    uncontrolled = assess_battery_window(_battery(energy=None, resolution=None), _battery(energy=None, resolution=None, t=2), wall_energy_joules=100)
    assert uncontrolled.reason_code == "wall_uncontrolled_battery"


def _thermal(value: float, t: int, throttling: bool = False) -> ThermalSnapshot:
    return ThermalSnapshot(t, (value,), value, throttling, (0,), "test", True)


def test_thermal_drift_limit_and_throttling() -> None:
    assert assess_thermal_window((_thermal(40, 1), _thermal(42, 2))).accepted
    assert assess_thermal_window((_thermal(40, 1), _thermal(44, 2))).reason_code == "thermal_drift_exceeded"
    assert assess_thermal_window((_thermal(54, 1), _thermal(56, 2))).reason_code == "temperature_limit_exceeded"
    assert assess_thermal_window((_thermal(40, 1), _thermal(40, 2, True))).reason_code == "throttling_detected"


def test_windows_preflight_starts_no_controlled_load() -> None:
    result = preflight_energy(system="Windows")
    assert not result["ready"]
    assert result["controlled_workload_started"] is False
    assert result["sources"]["CPU_PACKAGE_RAPL"] == "unavailable"
    assert "CPU_PACKAGE_RAPL_UNAVAILABLE" in result["reason_codes"]


def _sample(session: int, pair: int, implementation: str, joules: float, *, candidate: str = "candidate", baseline: str = "baseline") -> dict:
    start = 1000 + session * 100 + pair * 2 + (implementation == candidate)
    value = {
        "schema": SAMPLE_SCHEMA,
        "campaign_id": "campaign",
        "session_id": f"S{session:02d}",
        "pair_id": f"S{session:02d}-P{pair:03d}",
        "order_in_pair": 1 if implementation == baseline else 2,
        "implementation": implementation,
        "workload": "unit",
        "seed": 1,
        "K": 2,
        "timestamp_utc_start": "2026-08-07T00:00:00+00:00",
        "timestamp_utc_end": "2026-08-07T00:00:10+00:00",
        "monotonic_ns_start": start,
        "monotonic_ns_end": start + 10,
        "energy_domain": "CPU_PACKAGE_RAPL",
        "energy_start_joules": 10.0,
        "energy_end_joules": 10.0 + joules,
        "energy_delta_joules": joules,
        "elapsed_seconds": 10.0,
        "battery_before": {},
        "battery_after": {},
        "temperature": {},
        "frequency": {},
        "throttling": False,
        "equivalence": {"status": "PASS"},
        "accepted": True,
        "reason_code": "accepted",
        "hashes": {"executable": None, "tcap": "a" * 64, "dataset": "b" * 64, "configuration": "c" * 64},
        "physical_measurement": True,
        "source_provenance": {"kind": "linux_powercap"},
        "phases_seconds": {},
        "compilation_included": False,
    }
    validate_sample(value)
    return value


def test_confirmatory_analysis_gate_and_statistics() -> None:
    samples = []
    for session in range(1, 4):
        for pair in range(1, 22):
            samples.extend((_sample(session, pair, "baseline", 20.0), _sample(session, pair, "candidate", 10.0)))
    result = analyze_campaign(
        tuple(samples), campaign_id="campaign", candidate="candidate", baseline="baseline",
        energy_domain="CPU_PACKAGE_RAPL", expected_sessions=3, expected_pairs_per_session=21,
        bootstrap_seed=7, bootstrap_resamples=200,
    )
    assert result["terminal_state"] == "PASS_CPU_PACKAGE_ENERGY"
    assert result["median_ratio_candidate_over_baseline"] == 0.5
    assert result["paired_bootstrap_ci95"]["upper"] < 1
    assert result["material_improvement_at_least_10_percent"]
    assert paired_bootstrap_ci((0.4, 0.5, 0.6), seed=1, resamples=100)[1] <= 0.6
    assert exact_sign_test((1, 1), (2, 2))["wins"] == 2


def test_incomplete_campaign_is_blocked_not_zero() -> None:
    result = analyze_campaign((), campaign_id="campaign", candidate="candidate", baseline="baseline", energy_domain="TOTAL_SYSTEM_WALL", expected_sessions=3, expected_pairs_per_session=21, bootstrap_seed=1, bootstrap_resamples=100)
    assert result["terminal_state"] == "BLOCKED_PHYSICAL_INSTRUMENT"
    assert result["median_ratio_candidate_over_baseline"] is None


class _PhysicalCounter:
    domain = "CPU_PACKAGE_RAPL"
    source_kind = "linux_powercap"
    physical = True

    def __init__(self) -> None:
        self.value = 0.0

    def read(self) -> EnergyReading:
        self.value += 1.0
        return EnergyReading(self.domain, self.value, int(self.value * 1000), True, self.source_kind, {"counter": self.value})

    def delta(self, before: EnergyReading, after: EnergyReading) -> float:
        return after.cumulative_joules - before.cumulative_joules


def test_interrupted_campaign_resumes_without_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = "b" * 64
    numeric = [1.0, 2.0]
    output = sha256_bytes(canonical_bytes(numeric))
    payload = {
        "schema": "casulo-energy-unit-result/1.0", "status": "PASS",
        "implementation": "", "dataset_sha256": dataset,
        "semantic_scope": ["forward", "loss", "backward", "optimizer"],
        "numeric_output": numeric, "output_sha256": output, "phases_seconds": {},
    }
    commands = {}
    for name in ("baseline", "candidate"):
        value = dict(payload, implementation=name)
        argv = (sys.executable, "-c", f"import json;print(json.dumps({value!r}))")
        commands[name] = UnitCommand(name, argv, str(tmp_path), {}, 10, "unit", 1, None, None, dataset, "c" * 64, False)
    protocol = EnergyProtocol("resume", "candidate", "baseline", "unit", "CPU_PACKAGE_RAPL", K={"candidate": 1, "baseline": 1})
    short_schedule = {
        "schema": "casulo-energy-schedule/1.0", "campaign_id": "resume", "protocol_sha256": protocol.sha256,
        "seed": protocol.seed, "frozen_before_results": True,
        "sessions": [{"session_id": "S01", "pairs": [{"pair_id": "S01-P001", "order": ["baseline", "candidate"]}]}],
    }
    monkeypatch.setattr("casulo.livelab.energy_v1.paired_runner.deterministic_schedule", lambda _: short_schedule)
    tick = iter(range(1, 100))
    def thermal() -> ThermalSnapshot:
        return _thermal(40, next(tick))
    def battery() -> BatterySnapshot:
        return _battery(t=next(tick))
    with pytest.raises(CampaignInterrupted):
        run_paired_campaign(
            tmp_path,
            protocol,
            commands,
            _PhysicalCounter(),
            {"status": "PASS"},
            thermal_sampler=thermal,
            battery_sampler=battery,
            interrupt_after_samples=1,
        )
    result = run_paired_campaign(
        tmp_path,
        protocol,
        commands,
        _PhysicalCounter(),
        {"status": "PASS"},
        thermal_sampler=thermal,
        battery_sampler=battery,
    )
    assert result["new_samples"] == 1
    rows = tuple(iter_jsonl(tmp_path / "raw" / "samples.jsonl"))
    assert len(rows) == 2
    assert len({(row["pair_id"], row["implementation"]) for row in rows}) == 2


def test_protocol_schedule_hash_manifest_and_rejection_log(tmp_path: Path) -> None:
    protocol = EnergyProtocol("sealed", "candidate", "baseline", "unit", "CPU_PACKAGE_RAPL")
    freeze_protocol(tmp_path, protocol)
    assert deterministic_schedule(protocol)["protocol_sha256"] == protocol.sha256
    (tmp_path / "raw").mkdir()
    (tmp_path / "rejected").mkdir()
    write_json(tmp_path / "analysis.json", {"status": "BLOCKED_PHYSICAL_INSTRUMENT"})
    manifest = seal_campaign(tmp_path)
    assert manifest["simulated_measurement_accepted"] is False
    assert verify_campaign(tmp_path)["status"] == "PASS"
    (tmp_path / "analysis.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        verify_campaign(tmp_path)
