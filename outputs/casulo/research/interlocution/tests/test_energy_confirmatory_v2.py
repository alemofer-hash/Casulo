from __future__ import annotations

from energy_confirmatory.analysis import analyze_confirmatory_campaign, validate_arm_sample
from energy_confirmatory.metrology import (
    InstrumentManifest,
    MeterSample,
    integrate_energy_window,
    qualify_power_path,
    validate_instrument,
)
from energy_confirmatory.same_kernel import run_static_policy_same_kernel


ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]


def _sample(implementation: str, energy: float, *, host: str = "h1", pair: str = "p1") -> dict:
    return {
        "sample_id": f"{host}-{pair}-{implementation}",
        "host_id": host,
        "cpu_family": "f1",
        "lab_id": "l1",
        "workload_id": "flood",
        "session_id": "s1",
        "pair_id": pair,
        "implementation": implementation,
        "K_requested": 2,
        "K_frozen": 2,
        "K_dispatched": 2,
        "K_started": 2,
        "K_completed": 2,
        "receipt_count": 2,
        "epochs_completed": 800,
        "optimizer_steps": 800,
        "records_visited": 819_200,
        "energy_joules": energy,
        "elapsed_seconds": 1.0,
        "equivalence": "PASS",
        "accepted": True,
    }


def test_power_only_meter_is_integrated_with_boundary_interpolation() -> None:
    samples = (
        MeterSample("1970-01-01T00:00:00+00:00", 0.0, watts=10.0),
        MeterSample("1970-01-01T00:00:02+00:00", 2.0, watts=20.0),
        MeterSample("1970-01-01T00:00:04+00:00", 4.0, watts=10.0),
    )
    window = integrate_energy_window(samples, start_epoch_seconds=1.0, end_epoch_seconds=3.0)
    assert window.status == "PASS"
    assert window.integrated_joules == 35.0
    assert window.average_watts == 17.5


def test_cumulative_meter_is_integrated_at_exact_boundaries() -> None:
    samples = (
        MeterSample("1970-01-01T00:00:00+00:00", 0.0, cumulative_joules=100.0),
        MeterSample("1970-01-01T00:00:02+00:00", 2.0, cumulative_joules=120.0),
        MeterSample("1970-01-01T00:00:04+00:00", 4.0, cumulative_joules=160.0),
    )
    window = integrate_energy_window(samples, start_epoch_seconds=1.0, end_epoch_seconds=3.0)
    assert window.status == "PASS"
    assert window.integrated_joules == 30.0


def test_mock_and_uncalibrated_wall_meter_cannot_be_confirmatory() -> None:
    mock = InstrumentManifest("m", "TOTAL_SYSTEM_WALL", "x", "y", "s", None, None, None, None, False, True)
    assert validate_instrument(mock, confirmatory=True)[0] is False
    uncalibrated = InstrumentManifest("w", "TOTAL_SYSTEM_WALL", "x", "y", "s", None, None, None, None, True)
    assert validate_instrument(uncalibrated, confirmatory=True) == (False, "wall_meter_calibration_incomplete")


def test_calibrated_wall_meter_requires_runtime_range_firmware_and_clock() -> None:
    incomplete = InstrumentManifest(
        "w", "TOTAL_SYSTEM_WALL", "x", "y", "serial", "cal", "2026-01-01T00:00:00+00:00", "lab", 0.005, True
    )
    assert validate_instrument(incomplete, confirmatory=True) == (False, "wall_meter_runtime_configuration_incomplete")
    complete = InstrumentManifest(
        "w", "TOTAL_SYSTEM_WALL", "x", "y", "serial", "cal", "2026-01-01T00:00:00+00:00", "lab", 0.005, True,
        firmware="1.0", configured_range="0-100W", clock_uncertainty_seconds=0.01,
    )
    assert validate_instrument(complete, confirmatory=True)[0] is True


def test_hwinfo_is_explicitly_exploratory() -> None:
    manifest = InstrumentManifest("hw", "EXPLORATORY_HWINFO", "HWiNFO", "reported package", "host", None, None, None, None, True)
    assert validate_instrument(manifest, confirmatory=False)[0] is True
    assert validate_instrument(manifest, confirmatory=True) == (False, "exploratory_source_not_confirmatory")


def test_completed_work_is_the_only_normalization_divisor() -> None:
    invalid = _sample("D", 1.0)
    invalid["K_requested"] = 100
    try:
        validate_arm_sample(invalid)
    except ValueError as error:
        assert "work differs" in str(error)
    else:
        raise AssertionError("mismatched requested/completed work was accepted")


def test_gap_reset_partial_and_range_change_are_rejected() -> None:
    gap = (
        MeterSample("a", 0.0, watts=10.0),
        MeterSample("b", 1.0, watts=10.0),
        MeterSample("bb", 2.0, watts=10.0),
        MeterSample("c", 20.0, watts=10.0),
    )
    assert integrate_energy_window(gap, start_epoch_seconds=0.0, end_epoch_seconds=20.0).reason_code == "sampling_gap_exceeded"
    reset = (
        MeterSample("a", 0.0, cumulative_joules=100.0),
        MeterSample("b", 1.0, cumulative_joules=90.0),
    )
    assert integrate_energy_window(reset, start_epoch_seconds=0.0, end_epoch_seconds=1.0).reason_code == "cumulative_counter_reset_or_wrap_unknown"
    partial = (
        MeterSample("a", 0.0, watts=10.0),
        MeterSample("b", 1.0),
    )
    assert integrate_energy_window(partial, start_epoch_seconds=0.0, end_epoch_seconds=1.0).reason_code == "mixed_or_ambiguous_meter_signal"
    range_change = (
        MeterSample("a", 0.0, watts=10.0, range_id="low"),
        MeterSample("b", 1.0, watts=10.0, range_id="high"),
    )
    assert integrate_energy_window(range_change, start_epoch_seconds=0.0, end_epoch_seconds=1.0).reason_code == "meter_range_changed_inside_source"


def test_power_path_accepts_batteryless_desktop_but_not_unstable_laptop() -> None:
    assert qualify_power_path(has_battery=False, battery_observable=False, battery_stable=False, ac_continuous=True)[0] is True
    assert qualify_power_path(has_battery=True, battery_observable=True, battery_stable=False, ac_continuous=True) == (False, "laptop_battery_not_stable")


def test_analysis_reports_external_scale_blocker_without_promoting_local_data() -> None:
    samples = [_sample("D", 1.0, pair="p1"), _sample("E", 2.0, pair="p1")]
    analysis = analyze_confirmatory_campaign(
        samples,
        candidate="D",
        baseline="E",
        expected_hosts=6,
        expected_cpu_families=3,
        expected_labs=2,
        expected_workloads=3,
        expected_pairs_per_host_workload=24,
        bootstrap_seed=7,
        bootstrap_resamples=100,
    )
    assert analysis["valid_pairs"] == 1
    assert analysis["terminal_state"] == "BLOCKED_INSUFFICIENT_EXTERNAL_SCALE"
    assert analysis["claim_authorized"] is False


def test_same_kernel_arm_proves_one_full_work_unit(tmp_path) -> None:
    full = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
    result = run_static_policy_same_kernel(
        executable=full / "worker/tcap_full_worker.exe",
        tcap=full / "artifact/FloodSurrogate.full.tcap",
        dataset=full / "artifact/FloodSurrogate.dataset.bin",
        initializations=full / "artifact/FloodSurrogate.initializations.bin",
        start=0,
        count=1,
        output_directory=tmp_path / "arm-e",
    )
    assert result.K_completed == 1
    assert result.epochs_completed == 400
    assert result.optimizer_steps == 400
    assert result.records_visited == 409_600
    assert result.receipt_count == 1
    assert result.receipt_provenance.startswith("SUPERVISOR_DERIVED")
