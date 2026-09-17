from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import casulo.livelab.energy_v1.hwinfo_recovery as recovery_module
from casulo.livelab.energy_v1.hwinfo_campaign import verify_hwinfo_seal
from casulo.livelab.energy_v1.hwinfo_recovery import (
    _allocate_new_id,
    _qualified_k,
    _recovery_execution_guard,
    _run_recovery_window_with_retries,
    _wait_recovery_stable,
    ThermalRecoveryBlocked,
    analyze_recovery_campaign,
    finalize_polling_block,
    initialize_recovery_campaign,
    validate_recovery_polling,
)
from casulo.livelab.energy_v1.hwinfo_campaign import _truthy


@pytest.mark.parametrize("value", ["Sim", "Yes", "1", "verdadeiro", "true", "ativo"])
def test_localized_boolean_true_values(value: str) -> None:
    assert _truthy(value)


@pytest.mark.parametrize("value", ["Não", "Nao", "No", "0", "falso", "false", "inativo", ""])
def test_localized_boolean_false_values(value: str) -> None:
    assert not _truthy(value)
from casulo.livelab.energy_v1.hwinfo_workers import (
    EAGER_IMPLEMENTATION,
    TCAP_IMPLEMENTATION,
)
from casulo.livelab.energy_v1.schemas import write_json


ROOT = Path(__file__).resolve().parents[1]
TCAP = ROOT / "release" / "FloodSurrogate.tcap"


def test_recovery_always_allocates_new_identity(tmp_path: Path) -> None:
    assert _allocate_new_id(tmp_path, "recovery") == "recovery"
    (tmp_path / "recovery").mkdir()
    assert _allocate_new_id(tmp_path, "recovery") == "recovery-02"
    (tmp_path / "recovery-02").mkdir()
    assert _allocate_new_id(tmp_path, "recovery") == "recovery-03"


def test_pre_window_throttle_resets_stability_instead_of_blocking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    states = iter(
        [
            {
                "hwinfo_timestamp_utc": "2026-08-07T21:00:00+00:00",
                "logger_live": True,
                "ac_connected": True,
                "throttling": True,
                "temperature_c": 63.0,
            },
            {
                "hwinfo_timestamp_utc": "2026-08-07T21:00:00.250000+00:00",
                "logger_live": True,
                "ac_connected": True,
                "throttling": False,
                "temperature_c": 59.0,
            },
        ]
    )
    monkeypatch.setattr(recovery_module, "_recovery_guard", lambda *a, **k: next(states))
    monkeypatch.setattr(recovery_module.time, "sleep", lambda _seconds: None)
    result = _wait_recovery_stable(
        tmp_path / "unused.csv",
        threshold_c=60.0,
        stable_seconds=0.0,
        preabort_c=79.5,
        abort_c=90.0,
        timeout_seconds=1.0,
    )
    assert result["status"] == "PASS"
    assert result["last"]["throttling"] is False


def test_execution_guard_records_throttle_without_killing_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        recovery_module,
        "_recovery_guard",
        lambda *a, **k: {
            "logger_live": True,
            "ac_connected": True,
            "throttling": True,
            "temperature_c": 67.0,
            "safe_during_load": False,
            "reason_code": "recovery_abort_thermal_or_observer_guard",
        },
    )
    result = _recovery_execution_guard(
        tmp_path / "unused.csv",
        preabort_c=89.5,
        abort_c=90.0,
    )
    assert result["safe_during_load"] is True
    assert result["throttling"] is True
    assert result["reason_code"] == (
        "supervised_envelope_record_and_validate_after_completion"
    )


def test_short_runtime_recalibrates_k_without_energy_feedback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed_counts: list[int] = []

    def fake_window(*_args, **kwargs):
        observed_counts.append(_args[3])
        if len(observed_counts) == 1:
            raise ThermalRecoveryBlocked(
                "BLOCKED_ACTIVE_COOLING_REQUIRED",
                {
                    "window": {
                        "reason_code": "preregistered_minimum_duration_not_met",
                        "elapsed_seconds": 10.0,
                        "thermal": {
                            "throttling_detected": False,
                            "maximum_temperature_c": 60.0,
                        },
                    }
                },
            )
        return {"K": _args[3], "accepted": True}

    monkeypatch.setattr(recovery_module, "_run_recovery_window", fake_window)
    monkeypatch.setattr(
        recovery_module,
        "_wait_recovery_stable",
        lambda *a, **k: {"status": "PASS"},
    )
    result = _run_recovery_window_with_retries(
        tmp_path,
        tmp_path / "unused.csv",
        object(),
        10,
        stage="qualification",
        required_samples=60,
        maximum_expected_seconds=30.0,
        tcap_path=tmp_path / "unused.tcap",
        start_threshold_c=70.0,
        minimum_expected_seconds=20.0,
        preabort_c=89.5,
        abort_c=90.0,
    )
    assert observed_counts == [10, 21]
    assert result["K"] == 21
    assert result["attempt"] == 2


def test_freeze_uses_k_from_accepted_retried_qualification() -> None:
    assert _qualified_k({"accepted": True, "K": 102, "attempt": 3}) == 102
    with pytest.raises(ValueError, match="unaccepted"):
        _qualified_k({"accepted": False, "K": 93})


@pytest.mark.skipif(not TCAP.is_file(), reason="real FloodSurrogate TCAP required")
def test_two_second_polling_blocks_before_workload_and_seals(tmp_path: Path) -> None:
    csv_path = tmp_path / "live.csv"
    csv_path.write_text(
        "Date,Time,Potência total da CPU [W]\n"
        "07.08.2026,12:00:00.000,5.0\n",
        encoding="utf-8",
        newline="\n",
    )
    campaign = initialize_recovery_campaign(
        tmp_path / "energy",
        csv_path,
        TCAP,
        "recovery",
        _allow_bounded_canary_for_nonperformance_test=True,
    )

    def append_rows() -> None:
        time.sleep(0.05)
        with csv_path.open("a", encoding="utf-8", newline="\n") as handle:
            for index in range(1, 16):
                handle.write(f"07.08.2026,12:00:{index * 2:02d}.000,{5 + index / 10:.1f}\n")
                handle.flush()
                time.sleep(0.01)

    thread = threading.Thread(target=append_rows)
    thread.start()
    validation = validate_recovery_polling(campaign, csv_path, timeout_seconds=2)
    thread.join()
    assert validation["status"] == "BLOCKED_HWINFO_POLLING_NOT_CHANGED"
    assert validation["median_interval_seconds"] == 2.0
    assert validation["workload_executed"] is False
    finalize_polling_block(campaign, csv_path, validation)
    assert verify_hwinfo_seal(campaign)["status"] == "PASS"


@pytest.mark.skipif(not TCAP.is_file(), reason="real FloodSurrogate TCAP required")
def test_250ms_fallback_has_separate_protocol_and_polling_gate(tmp_path: Path) -> None:
    csv_path = tmp_path / "live.csv"
    csv_path.write_text(
        "Date,Time,Pot\u00eancia total da CPU [W]\n"
        "07.08.2026,12:00:00.000,5.0\n",
        encoding="utf-8",
        newline="\n",
    )
    campaign = initialize_recovery_campaign(
        tmp_path / "energy",
        csv_path,
        TCAP,
        "fallback-250ms",
        polling_mode_ms=250,
        _allow_bounded_canary_for_nonperformance_test=True,
    )

    def append_rows() -> None:
        time.sleep(0.05)
        with csv_path.open("a", encoding="utf-8", newline="\n") as handle:
            for index in range(1, 16):
                milliseconds = index * 250
                seconds, remainder = divmod(milliseconds, 1000)
                handle.write(
                    f"07.08.2026,12:00:{seconds:02d}.{remainder:03d},{5 + index / 10:.1f}\n"
                )
                handle.flush()
                time.sleep(0.01)

    thread = threading.Thread(target=append_rows)
    thread.start()
    validation = validate_recovery_polling(campaign, csv_path, timeout_seconds=2)
    thread.join()
    protocol = json.loads((campaign / "protocol.json").read_text(encoding="utf-8"))
    assert validation["status"] == "PASS"
    assert validation["median_interval_seconds"] == 0.25
    assert validation["limits"] == {"median_seconds": 0.3, "p95_seconds": None}
    assert protocol["polling_mode_ms"] == 250
    assert protocol["probe_sequence_seconds"] == [10, 20]
    assert protocol["target_window_formula"].startswith("max(20 seconds")


def test_recovery_analysis_requires_complete_ci_and_thermal_parity(tmp_path: Path) -> None:
    directory = tmp_path / "campaign"
    (directory / "raw").mkdir(parents=True)
    (directory / "rejected").mkdir()
    write_json(
        directory / "protocol.json",
        {
            "pairs_required": 21,
            "source_sensor": {"literal_name": "Potência total da CPU [W]", "unit": "w"},
            "thermal": {
                "maximum_median_temperature_asymmetry_c": 3.0,
                "abort_c": 74.5,
            },
        },
    )
    write_json(
        directory / "polling_validation.json",
        {"status": "PASS", "median_interval_seconds": 0.25},
    )
    for index in range(1, 22):
        candidate = {
            "joules_per_training": 8.0,
            "seconds_per_training": 1.0,
            "window": {"average_watts": 8.0},
            "thermal": {"maximum_temperature_c": 65.0},
        }
        baseline = {
            "joules_per_training": 10.0,
            "seconds_per_training": 1.0,
            "window": {"average_watts": 10.0},
            "thermal": {"maximum_temperature_c": 66.0},
        }
        write_json(
            directory / "raw" / f"pair-{index:02d}-pair-result.json",
            {
                "pair_id": f"pair-{index:02d}",
                "order": [TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION],
                "accepted": True,
                "windows": {
                    TCAP_IMPLEMENTATION: candidate,
                    EAGER_IMPLEMENTATION: baseline,
                },
            },
        )
    analysis = analyze_recovery_campaign(directory)
    assert analysis["terminal_state"] == "PASS_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS"
    assert analysis["valid_pairs"] == 21
    assert analysis["median_ratio_tcap_over_eager"] == pytest.approx(0.8)
    assert analysis["paired_bootstrap_ci95"]["upper"] < 1
    assert analysis["thermal_parity"]["passed"] is True


@pytest.mark.skipif(not TCAP.is_file(), reason="real FloodSurrogate TCAP required")
def test_90c_exception_is_campaign_local_and_default_stays_74_5(tmp_path: Path) -> None:
    csv_path = tmp_path / "live.csv"
    csv_path.write_text(
        "Date,Time,Pot\u00eancia total da CPU [W]\n"
        "07.08.2026,12:00:00.000,5.0\n",
        encoding="utf-8",
        newline="\n",
    )
    default = initialize_recovery_campaign(
        tmp_path / "default",
        csv_path,
        TCAP,
        "default",
        polling_mode_ms=250,
        _allow_bounded_canary_for_nonperformance_test=True,
    )
    exception = initialize_recovery_campaign(
        tmp_path / "exception",
        csv_path,
        TCAP,
        "exception",
        polling_mode_ms=250,
        thermal_abort_c=90.0,
        start_threshold_override_c=70.0,
        _allow_bounded_canary_for_nonperformance_test=True,
    )
    default_protocol = json.loads((default / "protocol.json").read_text(encoding="utf-8"))
    exception_protocol = json.loads(
        (exception / "protocol.json").read_text(encoding="utf-8")
    )
    assert default_protocol["thermal"]["abort_c"] == 74.5
    assert default_protocol["thermal"]["experiment_local_exception"] == {
        "enabled": False
    }
    assert exception_protocol["thermal"]["preabort_c"] == 89.5
    assert exception_protocol["thermal"]["abort_c"] == 90.0
    assert exception_protocol["thermal"]["start_threshold_override_c"] == 70.0
    assert exception_protocol["thermal"]["experiment_local_exception"]["scope"] == (
        "this campaign only"
    )
    assert exception_protocol["thermal"]["start_threshold_exception"] == {
        "enabled": True,
        "authorized_at_utc": exception_protocol["thermal"][
            "start_threshold_exception"
        ]["authorized_at_utc"],
        "scope": "this campaign only",
        "override_c": 70.0,
        "derived_formula_preserved_for_audit": (
            "min(idle_temperature_median + 3 C, 60 C)"
        ),
    }
    with pytest.raises(ValueError, match="between 74.5 C and 90.0 C"):
        initialize_recovery_campaign(
            tmp_path / "invalid",
            csv_path,
            TCAP,
            "invalid",
            polling_mode_ms=250,
            thermal_abort_c=90.1,
        )
    with pytest.raises(ValueError, match="authorized start-threshold overrides"):
        initialize_recovery_campaign(
            tmp_path / "invalid-start",
            csv_path,
            TCAP,
            "invalid-start",
            polling_mode_ms=250,
            start_threshold_override_c=59.0,
        )
