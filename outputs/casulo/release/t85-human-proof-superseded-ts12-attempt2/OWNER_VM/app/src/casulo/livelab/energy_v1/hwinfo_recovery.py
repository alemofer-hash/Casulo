from __future__ import annotations

import json
import math
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import exact_sign_test, paired_bootstrap_ci
from .hwinfo import extract_interval_csv, inspect_file, integrate_window, read_shared_snapshot
from .hwinfo_campaign import (
    AFFINITY,
    EAGER_IMPLEMENTATION,
    PersistentWorker,
    TCAP_IMPLEMENTATION,
    _complete_native_result,
    _live_guard,
    _normalize,
    _wait_for_bracketing_sample,
    prepare_workers,
)
from .schemas import canonical_bytes, read_json, sha256_bytes, sha256_file, write_json
from .hwinfo_workers import validate_scientific_training_unit


RECOVERY_CAMPAIGN_ID = "2026-08-07-g5-hwinfo-thermal-recovery"
RECOVERY_SCHEMA = "casulo-hwinfo-thermal-recovery/1.0"
POLLING_MEDIAN_LIMIT_SECONDS = 0.550
POLLING_P95_LIMIT_SECONDS = 0.750
BOOTSTRAP_SEED = 20260807
BOOTSTRAP_RESAMPLES = 20_000
DEFAULT_THERMAL_ABORT_C = 74.5
MAXIMUM_USER_EXCEPTION_ABORT_C = 90.0


class ThermalRecoveryBlocked(RuntimeError):
    def __init__(self, state: str, detail: dict[str, Any]):
        super().__init__(state)
        self.state = state
        self.detail = detail


def initialize_recovery_campaign(
    root: Path,
    csv_path: Path,
    tcap_path: Path,
    campaign_id: str = RECOVERY_CAMPAIGN_ID,
    *,
    polling_mode_ms: int = 500,
    thermal_abort_c: float = DEFAULT_THERMAL_ABORT_C,
    start_threshold_override_c: float | None = None,
    _allow_bounded_canary_for_nonperformance_test: bool = False,
) -> Path:
    if polling_mode_ms not in {250, 500}:
        raise ValueError("recovery polling mode must be 250 or 500 ms")
    if not DEFAULT_THERMAL_ABORT_C <= thermal_abort_c <= MAXIMUM_USER_EXCEPTION_ABORT_C:
        raise ValueError("thermal abort must remain between 74.5 C and 90.0 C")
    if start_threshold_override_c not in {None, 60.0, 70.0}:
        raise ValueError("the authorized start-threshold overrides are 60.0 C and 70.0 C")
    if not _allow_bounded_canary_for_nonperformance_test:
        validate_scientific_training_unit(tcap_path)
    preabort_c = thermal_abort_c - 0.5
    root = Path(root).resolve()
    campaign_id = _allocate_new_id(root, campaign_id)
    directory = root / campaign_id
    directory.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "rejected", "equivalence"):
        (directory / name).mkdir()
    snapshot, parsed, inspection = inspect_file(csv_path)
    sensor = parsed.selected_energy_sensor
    if sensor is None or sensor.literal_name != "Potência total da CPU [W]" or sensor.unit != "w":
        # Some consoles display replacement characters although the normalized
        # UTF-8 header is unambiguous. Preserve the literal and require its
        # normalized Portuguese identity as the compatibility path.
        if sensor is None or sensor.normalized_name != "potencia total da cpu w" or sensor.unit != "w":
            raise RuntimeError("recovery requires literal Potência total da CPU [W]")
    formal_start = datetime.now(timezone.utc)
    protocol = {
        "schema": RECOVERY_SCHEMA,
        "campaign_id": campaign_id,
        "created_at_utc": formal_start.isoformat(),
        "source_csv": str(Path(csv_path).resolve()),
        "source_sensor": sensor.to_dict(),
        "claim_scope": "HWiNFO-reported CPU package energy on bare-metal Windows",
        "candidate": TCAP_IMPLEMENTATION,
        "baseline": EAGER_IMPLEMENTATION,
        "workload": "FloodSurrogate",
        "epochs": 400,
        "precision": "float64",
        "threads": 1,
        "affinity": list(AFFINITY),
        "equivalence_absolute_tolerance": 1e-9,
        "polling_mode_ms": polling_mode_ms,
        "polling_gate": {
            "median_interval_max_seconds": (
                0.300 if polling_mode_ms == 250 else POLLING_MEDIAN_LIMIT_SECONDS
            ),
            "p95_interval_max_seconds": (
                None if polling_mode_ms == 250 else POLLING_P95_LIMIT_SECONDS
            ),
            "required_before_any_workload": True,
        },
        "target_window_formula": (
            "max(20 seconds, 70 * median_sampling_interval)"
            if polling_mode_ms == 250
            else "max(30 seconds, 70 * median_sampling_interval)"
        ),
        "minimum_samples_per_window": 60,
        "target_samples_per_window": 70,
        "minimum_coverage": 0.98,
        "maximum_gap_factor": 5.0,
        "integration": "trapezoidal_real_timestamps_with_boundary_interpolation",
        "physical_watchdog_reader": {
            "implementation": "bounded-live-tail-v1",
            "maximum_bytes_per_poll": 262144,
            "guard_poll_seconds": 0.25,
            "full_csv_reparse_per_guard_poll": False,
            "scientific_integration_uses_full_immutable_snapshot": True,
        },
        "thermal": {
            "start_threshold_formula": "min(idle_temperature_median + 3 C, 60 C)",
            "start_threshold_override_c": start_threshold_override_c,
            "preabort_c": preabort_c,
            "abort_c": thermal_abort_c,
            "hard_claim_limit_c": thermal_abort_c,
            "instantaneous_throttling_allowed": False,
            "stable_start_seconds": 30,
            "maximum_median_temperature_asymmetry_c": 3.0,
            "experiment_local_exception": (
                {
                    "enabled": True,
                    "authorized_at_utc": formal_start.isoformat(),
                    "scope": "this campaign only",
                    "default_abort_c_preserved": DEFAULT_THERMAL_ABORT_C,
                    "maximum_exception_abort_c": MAXIMUM_USER_EXCEPTION_ABORT_C,
                }
                if thermal_abort_c > DEFAULT_THERMAL_ABORT_C
                else {"enabled": False}
            ),
            "start_threshold_exception": (
                {
                    "enabled": True,
                    "authorized_at_utc": formal_start.isoformat(),
                    "scope": "this campaign only",
                    "override_c": start_threshold_override_c,
                    "derived_formula_preserved_for_audit": (
                        "min(idle_temperature_median + 3 C, 60 C)"
                    ),
                }
                if start_threshold_override_c is not None
                else {"enabled": False}
            ),
        },
        "probe_sequence_seconds": (
            [10, 20] if polling_mode_ms == 250 else [10, 20, 30]
        ),
        "fallback_250ms": {
            "separate_campaign_required": True,
            "median_interval_max_seconds": 0.300,
            "minimum_samples": 60,
            "minimum_coverage": 0.98,
            "minimum_window_seconds": 20,
        },
        "pairs_required": 21,
        "warmups": 3,
        "schedule": "deterministic alternating AB/BA with preregistered replacements",
        "outlier_removal_after_observation": False,
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
    }
    write_json(directory / "protocol.json", protocol)
    write_json(directory / "schedule.json", _recovery_schedule())
    capture = {
        "captured_at_utc": formal_start.isoformat(),
        "byte_offset": snapshot.bytes_read,
        "sha256": snapshot.sha256,
        "last_timestamp_before_campaign_utc": parsed.last_timestamp_utc,
        "snapshot": snapshot.metadata(),
        "inspection": inspection,
    }
    write_json(directory / "source_initial.json", capture)
    (directory / "source_csv_initial.sha256").write_text(
        f"{snapshot.sha256}  {Path(csv_path).name} bytes=0:{snapshot.bytes_read}\n",
        encoding="ascii",
        newline="\n",
    )
    write_json(directory / "input_hashes.json", {
        "tcap_sha256": sha256_file(tcap_path),
        "configuration_sha256": sha256_bytes(canonical_bytes(protocol)),
    })
    _append_marker(directory, "campaign_formal_start", formal_start, {"byte_offset": snapshot.bytes_read})
    return directory


def validate_recovery_polling(
    directory: Path,
    csv_path: Path,
    *,
    minimum_new_samples: int = 15,
    timeout_seconds: float = 40.0,
) -> dict[str, Any]:
    directory = Path(directory)
    protocol = read_json(directory / "protocol.json")
    initial = json.loads((directory / "source_initial.json").read_text(encoding="utf-8"))
    baseline = datetime.fromisoformat(initial["last_timestamp_before_campaign_utc"])
    started = datetime.now(timezone.utc)
    _append_marker(directory, "polling_validation_start", started, {})
    observer_before = _observer_snapshot()
    host_cpu = []
    deadline = time.monotonic() + timeout_seconds
    snapshot = None
    parsed = None
    new_rows = []
    initial_size = int(initial["byte_offset"])
    observed_sizes = [Path(csv_path).stat().st_size]
    # Observe append activity with stat() only. Repeated full reparses of a
    # multi-MB live CSV would itself perturb the thermal/energy preflight.
    parse_delay = min(
        max(0.5, timeout_seconds * 0.50),
        max(4.0, minimum_new_samples * 0.30),
    )
    earliest_parse = time.monotonic() + parse_delay
    while time.monotonic() < deadline:
        observed_sizes.append(Path(csv_path).stat().st_size)
        host_cpu.append(_host_cpu_percent())
        if time.monotonic() >= earliest_parse and observed_sizes[-1] > initial_size:
            snapshot, parsed, _ = inspect_file(csv_path)
            new_rows = [row for row in parsed.rows if row.timestamp_utc > baseline]
            if len(new_rows) >= minimum_new_samples:
                break
            earliest_parse = time.monotonic() + 1.0
        time.sleep(0.25)
    ended = datetime.now(timezone.utc)
    observer_after = _observer_snapshot()
    _append_marker(directory, "polling_validation_end", ended, {"new_samples": len(new_rows)})
    if snapshot is None or parsed is None:
        raise RuntimeError("HWiNFO source could not be sampled")
    intervals = [
        (right.timestamp_utc - left.timestamp_utc).total_seconds()
        for left, right in zip(new_rows, new_rows[1:])
    ]
    strict = all(value > 0 for value in intervals)
    median = statistics.median(intervals) if intervals else None
    p95 = _percentile(intervals, 0.95) if intervals else None
    maximum = max(intervals) if intervals else None
    sensor = parsed.selected_energy_sensor
    sensor_values = []
    if sensor is not None:
        for row in new_rows:
            try:
                sensor_values.append(float(row.values[sensor.index].replace(",", ".")) * sensor.si_scale)
            except (ValueError, IndexError):
                sensor_values.append(float("nan"))
    finite_nonnegative = bool(sensor_values) and all(value >= 0 and value == value and value != float("inf") for value in sensor_values)
    median_limit = float(protocol["polling_gate"]["median_interval_max_seconds"])
    p95_limit_raw = protocol["polling_gate"].get("p95_interval_max_seconds")
    p95_limit = float(p95_limit_raw) if p95_limit_raw is not None else None
    passed = bool(
        len(new_rows) >= minimum_new_samples
        and strict
        and finite_nonnegative
        and median is not None
        and p95 is not None
        and median <= median_limit
        and (p95_limit is None or p95 <= p95_limit)
    )
    state = "PASS" if passed else "BLOCKED_HWINFO_POLLING_NOT_CHANGED"
    validation = {
        "schema": "casulo-hwinfo-polling-validation/1.0",
        "status": state,
        "formal_baseline_timestamp_utc": baseline.isoformat(),
        "validation_start_utc": started.isoformat(),
        "validation_end_utc": ended.isoformat(),
        "new_samples": len(new_rows),
        "interval_count": len(intervals),
        "median_interval_seconds": median,
        "p95_interval_seconds": p95,
        "minimum_interval_seconds": min(intervals) if intervals else None,
        "maximum_interval_seconds": maximum,
        "strictly_increasing": strict,
        "finite_nonnegative_package_power": finite_nonnegative,
        "limits": {
            "median_seconds": median_limit,
            "p95_seconds": p95_limit,
        },
        "workload_executed": False,
        "preflight_reader": "stat-growth-plus-single-bounded-snapshot",
        "observed_file_growth_events": sum(
            right > left for left, right in zip(observed_sizes, observed_sizes[1:])
        ),
        "decision": (
            "polling gate passed; observer validation may continue"
            if passed
            else "Global Polling Period must still be configured to 500 ms; no workload authorized"
        ),
    }
    write_json(directory / "polling_validation.json", validation)
    valid_host_cpu = [value for value in host_cpu if value is not None]
    observer = {
        "schema": "casulo-hwinfo-observer-overhead/1.0",
        "status": "PASSIVE_BASELINE_ONLY" if not passed else "PREFLIGHT_PASSIVE_COMPLETE",
        "window_seconds": (ended - started).total_seconds(),
        "hwinfo_process_before": observer_before,
        "hwinfo_process_after": observer_after,
        "hwinfo_cpu_seconds_delta": _cpu_seconds_delta(observer_before, observer_after),
        "host_cpu_percent_samples": host_cpu,
        "host_cpu_percent_median": statistics.median(valid_host_cpu) if valid_host_cpu else None,
        "selective_subtraction_allowed": False,
        "workload_probe_executed": False,
        "limitation": "active observer overhead probes require polling gate PASS",
    }
    write_json(directory / "observer_overhead.json", observer)
    if new_rows:
        text = extract_interval_csv(snapshot, new_rows[0].timestamp_utc, new_rows[-1].timestamp_utc)
        (directory / "source_segment.csv").write_text(text, encoding="utf-8", newline="")
    else:
        (directory / "source_segment.csv").write_text("", encoding="utf-8")
    return validation


def finalize_polling_block(
    directory: Path,
    csv_path: Path,
    validation: dict[str, Any],
) -> dict[str, Any]:
    if validation["status"] != "BLOCKED_HWINFO_POLLING_NOT_CHANGED":
        raise ValueError("polling block finalizer requires failed R1")
    placeholders = {
        "thermal_calibration.json": {
            "status": "NOT_RUN",
            "reason_code": validation["status"],
            "workload_executed": False,
        },
        "frozen_k.json": {
            "status": "NOT_FROZEN",
            "K_TCAP": None,
            "K_Eager": None,
            "reason_code": validation["status"],
        },
    }
    for name, value in placeholders.items():
        write_json(Path(directory) / name, value)
    analysis = {
        "schema": "casulo-hwinfo-thermal-recovery-analysis/1.0",
        "campaign_id": Path(directory).name,
        "terminal_state": "BLOCKED_HWINFO_POLLING_NOT_CHANGED",
        "polling": validation,
        "valid_pairs": 0,
        "rejected_pairs": 0,
        "joules_per_training": {TCAP_IMPLEMENTATION: None, EAGER_IMPLEMENTATION: None},
        "ratio_tcap_over_eager": None,
        "paired_bootstrap_ci95": None,
        "equivalence": "NOT_RUN_IN_NEW_CAMPAIGN",
        "workload_executions": 0,
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
        "single_human_action": "Set HWiNFO Global Polling Period to 500 ms and keep logging to the same CSV, then start a new recovery campaign.",
    }
    write_json(Path(directory) / "analysis.json", analysis)
    report = _blocked_report(analysis)
    (Path(directory) / "report.md").write_text(report, encoding="utf-8", newline="\n")
    snapshot = read_shared_snapshot(csv_path)
    (Path(directory) / "source_csv_final.sha256").write_text(
        f"{snapshot.sha256}  {Path(csv_path).name} bytes=0:{snapshot.bytes_read}\n",
        encoding="ascii",
        newline="\n",
    )
    return seal_recovery_campaign(Path(directory))


def finalize_observer_contamination(
    directory: Path,
    csv_path: Path,
    *,
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    """Seal a calibration-only attempt invalidated before candidate workload."""

    directory = Path(directory).resolve()
    calibration_path = directory / "thermal_calibration.json"
    calibration = read_json(calibration_path) if calibration_path.exists() else {}
    calibration.update(
        {
            "status": "REJECTED_OBSERVER_OVERHEAD_IMPLEMENTATION",
            "reason_code": "FULL_CSV_REPARSE_IN_PHYSICAL_GUARD",
            "candidate_workload_executed": False,
            "definitive_pair_count": 0,
            "replacement": "bounded-live-tail-v1",
        }
    )
    write_json(calibration_path, calibration)
    write_json(
        directory / "frozen_k.json",
        {
            "status": "NOT_FROZEN",
            "K_TCAP": None,
            "K_Eager": None,
            "reason_code": "REJECTED_OBSERVER_OVERHEAD_IMPLEMENTATION",
        },
    )
    observer_path = directory / "observer_overhead.json"
    observer = read_json(observer_path)
    observer.update(
        {
            "status": "REJECTED_AND_CORRECTED_BEFORE_WORKLOAD",
            "watchdog_microbenchmark": benchmark,
            "rejected_reader": "full-csv-reparse-per-guard-poll",
            "replacement_reader": "bounded-live-tail-v1",
            "candidate_workload_executed": False,
        }
    )
    write_json(observer_path, observer)
    analysis = {
        "schema": "casulo-hwinfo-thermal-recovery-analysis/1.0",
        "campaign_id": directory.name,
        "terminal_state": "CALIBRATION_REJECTED_OBSERVER_CONTAMINATION",
        "scientific_judgment": "NOT_A_DEFINITIVE_ENERGY_CAMPAIGN",
        "valid_pairs": 0,
        "rejected_pairs": 0,
        "candidate_workload_executed": False,
        "reason_code": "FULL_CSV_REPARSE_IN_PHYSICAL_GUARD",
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
    }
    write_json(directory / "analysis.json", analysis)
    (directory / "report.md").write_text(
        "# Calibração rejeitada por contaminação do observador\n\n"
        "Esta tentativa foi interrompida antes de qualquer workload TCAP ou Eager e antes de pares definitivos. "
        "A guarda física relia todo o CSV em cada poll, elevando o próprio overhead do runner. "
        "Os dados permanecem preservados, mas não autorizam conclusão energética.\n\n"
        "A implementação substituta `bounded-live-tail-v1` lê no máximo 256 KiB por poll; "
        "a integração científica continua usando o snapshot completo imutável.\n\n"
        "`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`\n\n"
        "`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`\n",
        encoding="utf-8",
        newline="\n",
    )
    snapshot = read_shared_snapshot(csv_path)
    (directory / "source_csv_final.sha256").write_text(
        f"{snapshot.sha256}  {Path(csv_path).name} bytes=0:{snapshot.bytes_read}\n",
        encoding="ascii",
        newline="\n",
    )
    return seal_recovery_campaign(directory)


def finalize_500ms_thermal_block(directory: Path, csv_path: Path) -> dict[str, Any]:
    """Seal the 500 ms branch while explicitly routing to the 250 ms fallback."""

    directory = Path(directory).resolve()
    calibration = read_json(directory / "thermal_calibration.json")
    if calibration.get("status") != "BLOCKED_ACTIVE_COOLING_REQUIRED":
        raise ValueError("500 ms thermal finalizer requires a recorded guard block")
    analysis = {
        "schema": "casulo-hwinfo-thermal-recovery-analysis/1.0",
        "campaign_id": directory.name,
        "terminal_state": "BLOCKED_HWINFO_FALLBACK_250MS_CONFIGURATION_REQUIRED",
        "scientific_judgment": "500MS_BRANCH_REJECTED_BEFORE_WORKLOAD",
        "valid_pairs": 0,
        "rejected_pairs": 0,
        "workload_executions": 0,
        "idle": calibration.get("idle"),
        "thermal_blocker": calibration.get("blocker"),
        "equivalence": "NOT_RUN_IN_THIS_BRANCH",
        "fallback_required": {
            "global_polling_period_ms": 250,
            "new_campaign_required": True,
            "median_interval_max_seconds": 0.300,
            "minimum_window_seconds": 20,
            "minimum_samples": 60,
        },
        "single_human_action": "Set HWiNFO Global Polling Period to 250 ms while keeping the same logger active, then resume the prepared fallback campaign.",
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
    }
    write_json(directory / "analysis.json", analysis)
    (directory / "report.md").write_text(
        "# Ramo térmico de 500 ms encerrado\n\n"
        "O polling de 500 ms passou e o idle foi medido, mas a guarda registrou 75 °C antes de qualquer "
        "treinamento. Não houve throttling, equivalência, probe ou par definitivo neste ramo.\n\n"
        "O protocolo exige agora uma campanha separada a 250 ms, com janela mínima de 20 s e pelo menos "
        "60 amostras. Este ramo não autoriza conclusão sobre vantagem energética nem a declaração final "
        "de cooling ativo necessário.\n\n"
        "`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`\n\n"
        "`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`\n",
        encoding="utf-8",
        newline="\n",
    )
    snapshot = read_shared_snapshot(csv_path)
    (directory / "source_csv_final.sha256").write_text(
        f"{snapshot.sha256}  {Path(csv_path).name} bytes=0:{snapshot.bytes_read}\n",
        encoding="ascii",
        newline="\n",
    )
    return seal_recovery_campaign(directory)


def finalize_active_cooling_block(directory: Path, csv_path: Path) -> dict[str, Any]:
    """Seal the final 250 ms branch after its physical thermal guard fires."""

    directory = Path(directory).resolve()
    calibration = read_json(directory / "thermal_calibration.json")
    protocol = read_json(directory / "protocol.json")
    if int(protocol.get("polling_mode_ms", 0)) != 250:
        raise ValueError("active-cooling finalizer is reserved for the 250 ms branch")
    if calibration.get("status") != "BLOCKED_ACTIVE_COOLING_REQUIRED":
        raise ValueError("active-cooling finalizer requires a recorded thermal block")
    analysis = {
        "schema": "casulo-hwinfo-thermal-recovery-analysis/1.0",
        "campaign_id": directory.name,
        "terminal_state": "BLOCKED_ACTIVE_COOLING_REQUIRED",
        "scientific_judgment": "NO_ENERGY_RESULT",
        "polling": read_json(directory / "polling_validation.json"),
        "idle": calibration.get("idle"),
        "thermal_blocker": calibration.get("blocker"),
        "valid_pairs": 0,
        "rejected_pairs": 0,
        "workload_executions": 0,
        "equivalence": "NOT_RUN",
        "frozen_k": "NOT_FROZEN",
        "joules_per_training": {
            TCAP_IMPLEMENTATION: None,
            EAGER_IMPLEMENTATION: None,
        },
        "ratio_tcap_over_eager": None,
        "paired_bootstrap_ci95": None,
        "single_human_action": (
            "Install a powered cooling pad or equivalent active airflow under "
            "the notebook, allow the host to return below the frozen start "
            "threshold, keep HWiNFO at 250 ms, and start a new campaign."
        ),
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
    }
    write_json(directory / "analysis.json", analysis)
    blocker = calibration.get("blocker", {})
    state = blocker.get("state", {})
    if analysis.get("idle") is None:
        analysis["idle"] = {
            "sample_count": None,
            "idle_average_watts": None,
        }
    marker_path = directory / "benchmark_markers.jsonl"
    marker_text = marker_path.read_text(encoding="utf-8")
    if (
        '"event":"thermal_abort"' not in marker_text
        and state.get("hwinfo_timestamp_utc")
    ):
        blocker_utc = datetime.fromisoformat(state["hwinfo_timestamp_utc"])
        _append_marker(
            directory,
            "thermal_abort",
            blocker_utc,
            {
                "temperature_c": state.get("temperature_c"),
                "throttling": state.get("throttling"),
                "stage": blocker.get("stage"),
            },
        )
    (directory / "report.md").write_text(
        "# HWiNFO 250 ms — bloqueio térmico físico\n\n"
        "**Estado científico:** `BLOCKED_ACTIVE_COOLING_REQUIRED`\n\n"
        f"O polling passou com mediana `{analysis['polling']['median_interval_seconds']} s`. "
        f"O idle válido teve `{analysis['idle']['sample_count']}` amostras, "
        f"`{analysis['idle']['idle_average_watts']} W` e mediana térmica "
        f"`{calibration.get('idle_temperature_median_c')} C`. Durante a espera "
        f"pré-equivalência, a guarda registrou `{state.get('temperature_c')} C` "
        "e abortou antes de qualquer workload.\n\n"
        "Equivalência: não executada. K: não congelado. Pares: 0/21. "
        "Joules por treinamento, razão e IC95: indisponíveis. Nenhuma vantagem "
        "energética é alegada.\n\n"
        "Ação física única: instalar cooling pad alimentado ou fluxo de ar ativo "
        "equivalente sob o notebook; depois iniciar uma campanha nova mantendo "
        "o HWiNFO em 250 ms e os mesmos limites.\n\n"
        "`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`\n\n"
        "`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`\n",
        encoding="utf-8",
        newline="\n",
    )
    return finalize_recovery_evidence(directory, csv_path)


def finalize_protocol_superseded(
    directory: Path,
    csv_path: Path,
    *,
    reason: str,
) -> dict[str, Any]:
    """Preserve an interrupted calibration when a new user policy supersedes it."""

    directory = Path(directory).resolve()
    marker_path = directory / "benchmark_markers.jsonl"
    markers = [
        json.loads(line)
        for line in marker_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    calibration_windows = sum(
        item.get("event") == "window_start" for item in markers
    )
    equivalence_gates = len(list((directory / "equivalence").glob("*.json")))
    calibration_path = directory / "thermal_calibration.json"
    calibration = read_json(calibration_path) if calibration_path.exists() else {}
    calibration.update(
        {
            "status": "SUPERSEDED_BEFORE_DEFINITIVE_CAMPAIGN",
            "superseded_reason": reason,
            "calibration_windows": calibration_windows,
            "definitive_pairs": 0,
        }
    )
    write_json(calibration_path, calibration)
    write_json(
        directory / "frozen_k.json",
        {
            "status": "NOT_FROZEN",
            "K_TCAP": None,
            "K_Eager": None,
            "reason_code": "SUPERSEDED_BEFORE_DEFINITIVE_CAMPAIGN",
        },
    )
    _append_marker(
        directory,
        "protocol_superseded",
        datetime.now(timezone.utc),
        {"reason": reason},
    )
    analysis = {
        "schema": "casulo-hwinfo-thermal-recovery-analysis/1.0",
        "campaign_id": directory.name,
        "terminal_state": "SUPERSEDED_BEFORE_DEFINITIVE_CAMPAIGN",
        "scientific_judgment": "NO_ENERGY_RESULT",
        "valid_pairs": 0,
        "calibration_windows": calibration_windows,
        "equivalence_gates": equivalence_gates,
        "reason": reason,
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
    }
    write_json(directory / "analysis.json", analysis)
    (directory / "report.md").write_text(
        "# Campanha substituída antes do workload\n\n"
        f"Motivo: {reason}.\n\n"
        "Nenhuma equivalência, probe, janela TCAP/Eager ou par definitivo foi "
        "aceito nesta campanha. Ela é preservada somente como trilha de auditoria "
        "e não autoriza conclusão energética.\n",
        encoding="utf-8",
        newline="\n",
    )
    (directory / "report.md").write_text(
        "# Superseded calibration campaign\n\n"
        f"Reason: {reason}.\n\n"
        f"Preserved calibration windows: {calibration_windows}. "
        f"Preserved equivalence gates: {equivalence_gates}. "
        "No definitive pair was started or promoted, and this campaign "
        "authorizes no energy conclusion.\n",
        encoding="utf-8",
        newline="\n",
    )
    return finalize_recovery_evidence(directory, csv_path)


def run_thermal_recovery_calibration(
    directory: Path,
    csv_path: Path,
    tcap_path: Path,
) -> dict[str, Any]:
    directory = Path(directory).resolve()
    polling = read_json(directory / "polling_validation.json")
    if polling.get("status") != "PASS":
        raise ValueError("polling gate must pass before thermal recovery")
    protocol = read_json(directory / "protocol.json")
    polling_mode_ms = int(protocol.get("polling_mode_ms", 500))
    preabort_c = float(protocol["thermal"]["preabort_c"])
    abort_c = float(protocol["thermal"]["abort_c"])
    median_interval = float(polling["median_interval_seconds"])
    minimum_window = 20.0 if polling_mode_ms == 250 else 30.0
    target_window = max(minimum_window, 70.0 * median_interval)
    probe_sequence = (10.0, 20.0) if polling_mode_ms == 250 else (10.0, 20.0, 30.0)
    native, eager, build = prepare_workers(directory, tcap_path)
    write_json(directory / "worker_build.json", build)
    calibration: dict[str, Any] = {
        "schema": "casulo-hwinfo-thermal-calibration/1.0",
        "status": "RUNNING",
        "target_window_seconds": target_window,
        "polling_median_seconds": median_interval,
        "polling_mode_ms": polling_mode_ms,
        "probe_sequence_seconds": list(probe_sequence),
        "probes": [],
        "frozen_k": None,
    }
    write_json(directory / "thermal_calibration.json", calibration)
    try:
        initial_threshold = float(
            protocol["thermal"].get("start_threshold_override_c") or 60.0
        )
        initial_stability = _wait_recovery_stable(
            csv_path,
            threshold_c=initial_threshold,
            stable_seconds=30.0,
            preabort_c=preabort_c,
            abort_c=abort_c,
        )
        idle = None
        idle_rejections = []
        for attempt in range(1, 4):
            try:
                idle = _measure_recovery_idle(
                    directory,
                    csv_path,
                    seconds=60.0,
                    preabort_c=preabort_c,
                    abort_c=abort_c,
                )
                break
            except ThermalRecoveryBlocked as exc:
                state = exc.detail.get("state", {})
                temperature = state.get("temperature_c")
                transient_throttle = bool(
                    exc.detail.get("stage") == "idle"
                    and state.get("throttling") is True
                    and isinstance(temperature, (int, float))
                    and float(temperature) < abort_c
                )
                if not transient_throttle or attempt == 3:
                    raise
                rejection = {
                    "attempt": attempt,
                    "reason": "transient_throttling_inside_idle",
                    "state": state,
                }
                idle_rejections.append(rejection)
                write_json(
                    directory / "rejected" / f"idle-attempt-{attempt:02d}.json",
                    rejection,
                )
                _append_marker(
                    directory,
                    "idle_rejected",
                    datetime.now(timezone.utc),
                    {"attempt": attempt, "reason": rejection["reason"]},
                )
                _wait_recovery_stable(
                    csv_path,
                    threshold_c=initial_threshold,
                    stable_seconds=30.0,
                    preabort_c=preabort_c,
                    abort_c=abort_c,
                )
        if idle is None:
            raise RuntimeError("idle retry loop ended without a valid window")
        idle_median_temperature = idle["thermal"].get("median_temperature_c")
        if not isinstance(idle_median_temperature, (int, float)):
            raise ThermalRecoveryBlocked(
                "BLOCKED_TRUSTED_THERMAL_SENSOR_REQUIRED",
                {"reason": "unique HWiNFO idle temperature samples absent"},
            )
        idle_median_temperature = float(idle_median_temperature)
        derived_start_threshold = min(idle_median_temperature + 3.0, 60.0)
        override = protocol["thermal"].get("start_threshold_override_c")
        start_threshold = float(override) if override is not None else derived_start_threshold
        calibration.update(
            {
                "initial_stability": initial_stability,
                "idle": idle,
                "idle_rejections": idle_rejections,
                "idle_temperature_median_c": idle_median_temperature,
                "derived_start_threshold_c": derived_start_threshold,
                "start_threshold_c": start_threshold,
            }
        )
        write_json(directory / "thermal_calibration.json", calibration)

        equivalence = _recovery_equivalence_gate(
            directory,
            csv_path,
            tcap_path,
            (native, eager),
            start_threshold,
            preabort_c,
            abort_c,
            label="pre-calibration",
        )
        calibration["equivalence"] = equivalence
        write_json(directory / "thermal_calibration.json", calibration)

        seconds_per_training = float(
            equivalence["implementations"][EAGER_IMPLEMENTATION][
                "seconds_per_training"
            ]
        )
        calibrated_seconds_per_training = {
            implementation: float(value["seconds_per_training"])
            for implementation, value in equivalence["implementations"].items()
        }
        _augment_observer_overhead(
            directory,
            equivalence["implementations"],
            idle,
        )
        for target in probe_sequence:
            stability = _wait_recovery_stable(
                csv_path,
                threshold_c=start_threshold,
                stable_seconds=30.0,
                preabort_c=preabort_c,
                abort_c=abort_c,
            )
            # Keep the probe close to its declared duration and never select K
            # from an energy outcome.
            count = max(1, math.ceil(target / seconds_per_training))
            probe = _run_recovery_window_with_retries(
                directory,
                csv_path,
                eager,
                count,
                stage=f"probe-eager-{int(target)}s",
                required_samples=(60 if target == probe_sequence[-1] else 2),
                minimum_expected_seconds=(
                    minimum_window if target == probe_sequence[-1] else 0.0
                ),
                maximum_expected_seconds=target + max(3.0, 0.20 * target),
                tcap_path=tcap_path,
                preabort_c=preabort_c,
                abort_c=abort_c,
                start_threshold_c=start_threshold,
            )
            probe["declared_target_seconds"] = target
            probe["pre_window_stability"] = stability
            calibration["probes"].append(probe)
            write_json(directory / "thermal_calibration.json", calibration)
            seconds_per_training = probe["elapsed_seconds"] / probe["K"]
            calibrated_seconds_per_training[EAGER_IMPLEMENTATION] = (
                seconds_per_training
            )
            _wait_recovery_stable(
                csv_path,
                threshold_c=start_threshold,
                stable_seconds=30.0,
                preabort_c=preabort_c,
                abort_c=abort_c,
            )

        # A single TCAP training is too short for a stable extrapolation to a
        # 20-second HWiNFO window. Measure a dedicated runtime-only probe before
        # qualification, just as Eager was refined above. Energy from this
        # probe is preserved but never used to choose K.
        tcap_probe_target = 10.0
        tcap_probe_count = max(
            1,
            math.ceil(
                tcap_probe_target
                / calibrated_seconds_per_training[TCAP_IMPLEMENTATION]
            ),
        )
        tcap_stability = _wait_recovery_stable(
            csv_path,
            threshold_c=start_threshold,
            stable_seconds=30.0,
            preabort_c=preabort_c,
            abort_c=abort_c,
        )
        tcap_runtime_probe = _run_recovery_window_with_retries(
            directory,
            csv_path,
            native,
            tcap_probe_count,
            stage="probe-tcap-10s",
            required_samples=2,
            minimum_expected_seconds=0.0,
            maximum_expected_seconds=15.0,
            tcap_path=tcap_path,
            preabort_c=preabort_c,
            abort_c=abort_c,
            start_threshold_c=start_threshold,
        )
        tcap_runtime_probe["declared_target_seconds"] = tcap_probe_target
        tcap_runtime_probe["pre_window_stability"] = tcap_stability
        calibration["tcap_runtime_probe"] = tcap_runtime_probe
        calibrated_seconds_per_training[TCAP_IMPLEMENTATION] = (
            tcap_runtime_probe["elapsed_seconds"] / tcap_runtime_probe["K"]
        )
        write_json(directory / "thermal_calibration.json", calibration)
        _wait_recovery_stable(
            csv_path,
            threshold_c=start_threshold,
            stable_seconds=30.0,
            preabort_c=preabort_c,
            abort_c=abort_c,
        )

        qualifications = {}
        frozen = {}
        for worker in (native, eager):
            implementation = worker.implementation
            estimate = calibrated_seconds_per_training[implementation]
            count = max(1, math.ceil(target_window / estimate))
            stability = _wait_recovery_stable(
                csv_path,
                threshold_c=start_threshold,
                stable_seconds=30.0,
                preabort_c=preabort_c,
                abort_c=abort_c,
            )
            qualification = _run_recovery_window_with_retries(
                directory,
                csv_path,
                worker,
                count,
                stage=f"qualification-{implementation}",
                required_samples=60,
                minimum_expected_seconds=minimum_window,
                maximum_expected_seconds=target_window * 1.35 + 3.0,
                tcap_path=tcap_path,
                preabort_c=preabort_c,
                abort_c=abort_c,
                start_threshold_c=start_threshold,
            )
            qualification["pre_window_stability"] = stability
            qualifications[implementation] = qualification
            # ``_run_recovery_window_with_retries`` may increase K when the
            # first qualification attempt is shorter than the preregistered
            # minimum.  Freeze the K that actually produced the accepted
            # qualification, not the stale initial estimate.  Freezing
            # ``count`` here made definitive windows systematically shorter
            # than the window that passed calibration.
            frozen[implementation] = _qualified_k(qualification)
            _wait_recovery_stable(
                csv_path,
                threshold_c=start_threshold,
                stable_seconds=30.0,
                preabort_c=preabort_c,
                abort_c=abort_c,
            )

        frozen_k = {
            "status": "FROZEN",
            "frozen_before_definitive_pairs": True,
            "polling_mode_ms": polling_mode_ms,
            "target_window_seconds": target_window,
            "minimum_window_seconds": minimum_window,
            "K_TCAP": frozen[TCAP_IMPLEMENTATION],
            "K_Eager": frozen[EAGER_IMPLEMENTATION],
            "selection_basis": (
                "latest runtime calibration per implementation only; "
                "no energy outcome inspected"
            ),
            "qualifications": qualifications,
        }
        write_json(directory / "frozen_k.json", frozen_k)
        calibration["status"] = "QUALIFICATION_PASS_K_FROZEN"
        calibration["qualifications"] = qualifications
        calibration["frozen_k"] = frozen_k
        calibration["largest_approved_probe_seconds"] = calibration["probes"][-1][
            "elapsed_seconds"
        ]
        calibration["target_window_seconds"] = target_window
        write_json(directory / "thermal_calibration.json", calibration)
        return calibration
    except ThermalRecoveryBlocked as exc:
        calibration["status"] = exc.state
        calibration["blocker"] = exc.detail
        calibration["frozen_k"] = None
        write_json(directory / "thermal_calibration.json", calibration)
        write_json(
            directory / "frozen_k.json",
            {
                "status": "NOT_FROZEN",
                "reason_code": exc.state,
                "K_TCAP": None,
                "K_Eager": None,
            },
        )
        raise
    finally:
        native.stop()
        eager.stop()


def _qualified_k(qualification: dict[str, Any]) -> int:
    """Return the K of the accepted qualification window itself."""
    if qualification.get("accepted") is not True:
        raise ValueError("cannot freeze K from an unaccepted qualification")
    value = int(qualification["K"])
    if value < 1:
        raise ValueError("qualification K must be positive")
    return value


def _measure_recovery_idle(
    directory: Path,
    csv_path: Path,
    *,
    seconds: float,
    preabort_c: float,
    abort_c: float,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc)
    _append_marker(directory, "idle_start", start, {"seconds": seconds})
    observations = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = _recovery_guard(
            csv_path,
            preabort_c=preabort_c,
            abort_c=abort_c,
        )
        observations.append(state)
        if not state["safe_during_load"]:
            raise ThermalRecoveryBlocked(
                "BLOCKED_ACTIVE_COOLING_REQUIRED",
                {"stage": "idle", "state": state},
            )
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    end = datetime.now(timezone.utc)
    _append_marker(directory, "idle_end", end, {})
    _wait_for_bracketing_sample(csv_path, end)
    _, parsed, _ = inspect_file(csv_path)
    window = integrate_window(parsed, start, end, minimum_samples=60)
    if window.status != "PASS":
        raise ThermalRecoveryBlocked(
            "BLOCKED_HWINFO_IDLE_WINDOW_INVALID",
            {"stage": "idle", "window": window.to_dict()},
        )
    telemetry = _window_thermal_telemetry(parsed, start, end)
    return {
        **window.to_dict(),
        "guard_observations": observations,
        "thermal": telemetry,
        "idle_energy_joules": window.energy_joules,
        "idle_average_watts": window.average_watts,
    }


def _wait_recovery_stable(
    csv_path: Path,
    *,
    threshold_c: float,
    stable_seconds: float,
    preabort_c: float,
    abort_c: float,
    timeout_seconds: float = 900.0,
) -> dict[str, Any]:
    started = time.monotonic()
    stable_started: float | None = None
    observations = []
    last_timestamp = None
    while time.monotonic() - started < timeout_seconds:
        state = _recovery_guard(
            csv_path,
            preabort_c=preabort_c,
            abort_c=abort_c,
        )
        timestamp = state.get("hwinfo_timestamp_utc")
        if timestamp != last_timestamp:
            observations.append(state)
            last_timestamp = timestamp
        ready = bool(
            state.get("logger_live")
            and state.get("ac_connected") is True
            and state.get("throttling") is False
            and isinstance(state.get("temperature_c"), (int, float))
            and float(state["temperature_c"]) < threshold_c
        )
        if ready:
            if stable_started is None:
                stable_started = time.monotonic()
            if time.monotonic() - stable_started >= stable_seconds:
                return {
                    "status": "PASS",
                    "threshold_c": threshold_c,
                    "stable_seconds": time.monotonic() - stable_started,
                    "samples": len(observations),
                    "first": observations[0] if observations else None,
                    "last": observations[-1] if observations else None,
                }
        else:
            stable_started = None
        # A transient throttle while waiting is outside every scientific
        # window. It resets the required clean stability interval; throttling
        # inside a measured or equivalence window remains a rejection.
        if isinstance(state.get("temperature_c"), (int, float)) and float(
            state["temperature_c"]
        ) >= abort_c:
            raise ThermalRecoveryBlocked(
                "BLOCKED_ACTIVE_COOLING_REQUIRED",
                {"stage": "cooldown_or_stability", "state": state},
            )
        time.sleep(0.25)
    raise ThermalRecoveryBlocked(
        "BLOCKED_ACTIVE_COOLING_REQUIRED",
        {
            "stage": "cooldown_or_stability",
            "reason": "stable_start_timeout",
            "threshold_c": threshold_c,
            "observations": observations[-20:],
        },
    )


def _recovery_equivalence_gate(
    directory: Path,
    csv_path: Path,
    tcap_path: Path,
    workers: tuple[PersistentWorker, PersistentWorker],
    start_threshold_c: float,
    preabort_c: float,
    abort_c: float,
    *,
    label: str,
) -> dict[str, Any]:
    results = {}
    for worker in workers:
        stability = _wait_recovery_stable(
            csv_path,
            threshold_c=start_threshold_c,
            stable_seconds=30.0,
            preabort_c=preabort_c,
            abort_c=abort_c,
        )
        result, observations = worker.run(
            1,
            timeout_seconds=30.0,
            guard=_make_recovery_execution_guard(
                csv_path,
                preabort_c=preabort_c,
                abort_c=abort_c,
            ),
        )
        result = _complete_native_result(result, tcap_path)
        results[worker.implementation] = {
            **result,
            "pre_execution_stability": stability,
            "thermal_observations": observations,
        }
    candidate = results[TCAP_IMPLEMENTATION]
    baseline = results[EAGER_IMPLEMENTATION]
    differences = {
        "initial_loss": abs(candidate["loss"]["initial"] - baseline["loss"]["initial"]),
        "final_loss": abs(candidate["loss"]["final"] - baseline["loss"]["final"]),
        "parameters_max_abs": max(
            abs(left - right)
            for left, right in zip(
                candidate["parameters"], baseline["parameters"], strict=True
            )
        ),
        "predictions_max_abs": max(
            abs(left - right)
            for left, right in zip(
                candidate["predictions"], baseline["predictions"], strict=True
            )
        ),
    }
    passed = (
        candidate["dataset_sha256"] == baseline["dataset_sha256"]
        and all(value <= 1e-9 for value in differences.values())
    )
    gate = {
        "schema": "casulo-hwinfo-recovery-equivalence/1.0",
        "label": label,
        "status": "PASS" if passed else "FAIL",
        "tolerance": 1e-9,
        "epochs": 400,
        "threads": 1,
        "affinity": list(AFFINITY),
        "differences": differences,
        "implementations": results,
    }
    write_json(directory / "equivalence" / f"{label}.json", gate)
    if not passed:
        raise ThermalRecoveryBlocked(
            "FAIL_EQUIVALENCE",
            {"stage": label, "gate": gate},
        )
    return gate


def _run_recovery_window(
    directory: Path,
    csv_path: Path,
    worker: PersistentWorker,
    count: int,
    *,
    stage: str,
    required_samples: int,
    maximum_expected_seconds: float,
    tcap_path: Path,
    minimum_expected_seconds: float = 0.0,
    preabort_c: float = 74.0,
    abort_c: float = 74.5,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc)
    _append_marker(
        directory,
        "window_start",
        start,
        {"stage": stage, "implementation": worker.implementation, "K": count},
    )
    try:
        result, guard_observations = worker.run(
            count,
            timeout_seconds=maximum_expected_seconds + 5.0,
            guard=_make_recovery_execution_guard(
                csv_path,
                preabort_c=preabort_c,
                abort_c=abort_c,
            ),
        )
    except Exception as exc:
        rejection = {
            "schema": "casulo-hwinfo-recovery-rejection/1.0",
            "stage": stage,
            "implementation": worker.implementation,
            "K": count,
            "reason": f"{type(exc).__name__}:{exc}",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(directory / "rejected" / f"{stage}.json", rejection)
        raise ThermalRecoveryBlocked(
            "BLOCKED_ACTIVE_COOLING_REQUIRED",
            rejection,
        ) from exc
    end = datetime.now(timezone.utc)
    _append_marker(
        directory,
        "window_end",
        end,
        {"stage": stage, "implementation": worker.implementation, "K": count},
    )
    result = _complete_native_result(result, tcap_path)
    _wait_for_bracketing_sample(csv_path, end)
    _, parsed, _ = inspect_file(csv_path)
    window = integrate_window(
        parsed,
        start,
        end,
        minimum_samples=required_samples,
        minimum_coverage=0.98,
        maximum_gap_factor=5.0,
    )
    thermal = _window_thermal_telemetry(parsed, start, end)
    after = _recovery_guard(
        csv_path,
        preabort_c=preabort_c,
        abort_c=abort_c,
    )
    preabort = bool(
        thermal["maximum_temperature_c"] is not None
        and thermal["maximum_temperature_c"] >= preabort_c
    )
    accepted = bool(
        window.status == "PASS"
        and result["elapsed_seconds"] >= minimum_expected_seconds
        and result["elapsed_seconds"] <= maximum_expected_seconds
        and thermal["maximum_temperature_c"] is not None
        and thermal["maximum_temperature_c"] < abort_c
        and not thermal["throttling_detected"]
        and result["status"] == "PASS"
    )
    value = {
        "schema": "casulo-hwinfo-recovery-window/1.0",
        "stage": stage,
        "implementation": worker.implementation,
        "K": count,
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "elapsed_seconds": result["elapsed_seconds"],
        "maximum_expected_seconds": maximum_expected_seconds,
        "minimum_expected_seconds": minimum_expected_seconds,
        "window": window.to_dict(),
        "thermal": thermal,
        "preabort_entered": preabort,
        "guard_observations": guard_observations,
        "guard_after": after,
        "numeric_result": result,
        "accepted": accepted,
        "reason_code": (
            "accepted"
            if accepted
            else _window_rejection_reason(
                window.status,
                thermal,
                elapsed_seconds=result["elapsed_seconds"],
                minimum_expected_seconds=minimum_expected_seconds,
                maximum_expected_seconds=maximum_expected_seconds,
                abort_c=abort_c,
            )
        ),
    }
    destination = directory / ("raw" if accepted else "rejected") / f"{stage}.json"
    write_json(destination, value)
    if not accepted:
        raise ThermalRecoveryBlocked(
            "BLOCKED_ACTIVE_COOLING_REQUIRED",
            {"stage": stage, "window": value},
        )
    return value


def _run_recovery_window_with_retries(
    directory: Path,
    csv_path: Path,
    worker: PersistentWorker,
    count: int,
    *,
    stage: str,
    required_samples: int,
    maximum_expected_seconds: float,
    tcap_path: Path,
    start_threshold_c: float,
    minimum_expected_seconds: float = 0.0,
    preabort_c: float = 74.0,
    abort_c: float = 74.5,
    maximum_attempts: int = 3,
) -> dict[str, Any]:
    current_count = count
    for attempt in range(1, maximum_attempts + 1):
        actual_stage = stage if attempt == 1 else f"{stage}-replacement-{attempt:02d}"
        try:
            value = _run_recovery_window(
                directory,
                csv_path,
                worker,
                current_count,
                stage=actual_stage,
                required_samples=required_samples,
                maximum_expected_seconds=maximum_expected_seconds,
                tcap_path=tcap_path,
                minimum_expected_seconds=minimum_expected_seconds,
                preabort_c=preabort_c,
                abort_c=abort_c,
            )
            value["logical_stage"] = stage
            value["attempt"] = attempt
            return value
        except ThermalRecoveryBlocked as exc:
            window = exc.detail.get("window", {})
            thermal = window.get("thermal", {})
            transient_throttle = bool(
                thermal.get("throttling_detected") is True
                and isinstance(thermal.get("maximum_temperature_c"), (int, float))
                and float(thermal["maximum_temperature_c"]) < abort_c
            )
            short_runtime = bool(
                window.get("reason_code")
                == "preregistered_minimum_duration_not_met"
                and isinstance(window.get("elapsed_seconds"), (int, float))
                and float(window["elapsed_seconds"]) > 0
                and minimum_expected_seconds > 0
            )
            if not (transient_throttle or short_runtime) or attempt == maximum_attempts:
                raise
            if short_runtime:
                current_count = max(
                    current_count + 1,
                    math.ceil(
                        current_count
                        * minimum_expected_seconds
                        / float(window["elapsed_seconds"])
                        * 1.05
                    ),
                )
            _wait_recovery_stable(
                csv_path,
                threshold_c=start_threshold_c,
                stable_seconds=30.0,
                preabort_c=preabort_c,
                abort_c=abort_c,
            )
    raise RuntimeError("recovery replacement loop ended without a valid window")


def _recovery_execution_guard(
    csv_path: Path,
    *,
    preabort_c: float,
    abort_c: float,
) -> dict[str, Any]:
    state = _recovery_guard(
        csv_path,
        preabort_c=preabort_c,
        abort_c=abort_c,
    )
    temperature = state.get("temperature_c")
    supervised_envelope = bool(
        state.get("logger_live")
        and state.get("ac_connected") is not False
        and isinstance(temperature, (int, float))
        and float(temperature) < abort_c
    )
    if supervised_envelope and not state.get("safe_during_load"):
        return {
            **state,
            "safe_during_load": True,
            "reason_code": "supervised_envelope_record_and_validate_after_completion",
        }
    return state


def _make_recovery_execution_guard(
    csv_path: Path,
    *,
    preabort_c: float,
    abort_c: float,
    transient_grace_samples: int = 4,
):
    consecutive_observer_failures = 0

    def guard() -> dict[str, Any]:
        nonlocal consecutive_observer_failures
        state = _recovery_execution_guard(
            csv_path,
            preabort_c=preabort_c,
            abort_c=abort_c,
        )
        temperature = state.get("temperature_c")
        hard_temperature_abort = bool(
            isinstance(temperature, (int, float))
            and float(temperature) >= abort_c
        )
        if state.get("safe_during_load") or hard_temperature_abort:
            consecutive_observer_failures = 0
            return state
        consecutive_observer_failures += 1
        if consecutive_observer_failures < transient_grace_samples:
            return {
                **state,
                "safe_during_load": True,
                "observer_failure_grace_sample": consecutive_observer_failures,
                "observer_failure_grace_limit": transient_grace_samples,
                "reason_code": "transient_observer_failure_grace",
            }
        return {
            **state,
            "observer_failure_grace_sample": consecutive_observer_failures,
            "observer_failure_grace_limit": transient_grace_samples,
        }

    return guard


def _recovery_guard(
    csv_path: Path,
    *,
    preabort_c: float = 74.0,
    abort_c: float = 74.5,
) -> dict[str, Any]:
    state = _live_guard(csv_path, during_load=True)
    temperature = state.get("temperature_c")
    safe = bool(
        state.get("logger_live")
        and state.get("ac_connected") is True
        and state.get("throttling") is False
        and isinstance(temperature, (int, float))
        and float(temperature) < abort_c
    )
    return {
        **state,
        "preabort": bool(
            isinstance(temperature, (int, float))
            and float(temperature) >= preabort_c
        ),
        "preabort_c": preabort_c,
        "abort_c": abort_c,
        "safe_during_load": safe,
        "reason_code": (
            "recovery_safe"
            if safe
            else "recovery_abort_thermal_or_observer_guard"
        ),
    }


def _window_thermal_telemetry(parsed, start: datetime, end: datetime) -> dict[str, Any]:
    if not parsed.headers:
        return {
            "initial_temperature_c": None,
            "maximum_temperature_c": None,
            "final_temperature_c": None,
            "throttling_detected": None,
            "samples": 0,
        }
    rows = [row for row in parsed.rows if start <= row.timestamp_utc <= end]
    if not rows:
        return {
            "initial_temperature_c": None,
            "maximum_temperature_c": None,
            "final_temperature_c": None,
            "throttling_detected": None,
            "samples": 0,
        }
    header = parsed.headers[min(rows[-1].session_id, len(parsed.headers) - 1)]
    normalized = [_normalize(value) for value in header]
    temperature_indices = [
        index
        for index, value in enumerate(normalized)
        if "temperaturas centrais" in value
        or ("cpu package" in value and "c" in value and "power" not in value)
    ]
    throttle_indices = [
        index
        for index, value in enumerate(normalized)
        if ("estrangulamento termico" in value or "thermal throttling" in value)
        and "maximum" not in value
        and "maximo" not in value
    ]
    samples = []
    throttling = False
    for row in rows:
        values = []
        for index in temperature_indices:
            try:
                value = float(row.values[index].replace(",", "."))
            except (ValueError, IndexError):
                continue
            if math.isfinite(value):
                values.append(value)
        if values:
            samples.append(max(values))
        for index in throttle_indices:
            if index < len(row.values) and _normalize(row.values[index]) in {
                "yes",
                "sim",
                "true",
                "1",
            }:
                throttling = True
    return {
        "initial_temperature_c": samples[0] if samples else None,
        "maximum_temperature_c": max(samples) if samples else None,
        "final_temperature_c": samples[-1] if samples else None,
        "median_temperature_c": statistics.median(samples) if samples else None,
        "throttling_detected": throttling,
        "samples": len(rows),
    }


def _augment_observer_overhead(
    directory: Path,
    implementations: dict[str, Any],
    idle: dict[str, Any],
) -> None:
    path = directory / "observer_overhead.json"
    observer = read_json(path)
    observer.update(
        {
            "status": "PASS_LIGHT_PROBES",
            "light_probe_runtime_seconds": {
                name: value["elapsed_seconds"]
                for name, value in implementations.items()
            },
            "idle_average_watts": idle["idle_average_watts"],
            "idle_sampling_median_seconds": idle["median_interval_seconds"],
            "selective_subtraction_allowed": False,
            "observer_present_for_both_implementations": True,
        }
    )
    write_json(path, observer)


def _window_rejection_reason(
    status: str,
    thermal: dict[str, Any],
    *,
    elapsed_seconds: float | None = None,
    minimum_expected_seconds: float | None = None,
    maximum_expected_seconds: float | None = None,
    abort_c: float = 74.5,
) -> str:
    if thermal.get("throttling_detected"):
        return "instantaneous_thermal_throttling"
    maximum = thermal.get("maximum_temperature_c")
    if isinstance(maximum, (int, float)) and maximum >= abort_c:
        return "temperature_abort_threshold"
    if (
        elapsed_seconds is not None
        and minimum_expected_seconds is not None
        and elapsed_seconds < minimum_expected_seconds
    ):
        return "preregistered_minimum_duration_not_met"
    if (
        elapsed_seconds is not None
        and maximum_expected_seconds is not None
        and elapsed_seconds > maximum_expected_seconds
    ):
        return "preregistered_duration_exceeded"
    if status != "PASS":
        return "energy_window_invalid"
    return "unknown_rejection"


def run_definitive_recovery_campaign(
    directory: Path,
    csv_path: Path,
    tcap_path: Path,
) -> dict[str, Any]:
    """Run the frozen AB/BA design transactionally after calibration passes."""

    directory = Path(directory).resolve()
    frozen = read_json(directory / "frozen_k.json")
    if frozen.get("status") != "FROZEN":
        raise ValueError("K must be frozen before definitive recovery campaign")
    calibration = read_json(directory / "thermal_calibration.json")
    if calibration.get("status") != "QUALIFICATION_PASS_K_FROZEN":
        raise ValueError("thermal qualification must pass before definitive pairs")
    protocol = read_json(directory / "protocol.json")
    schedule = read_json(directory / "schedule.json")
    start_threshold = float(calibration["start_threshold_c"])
    preabort_c = float(protocol["thermal"]["preabort_c"])
    abort_c = float(protocol["thermal"]["abort_c"])
    minimum_window = float(frozen["minimum_window_seconds"])
    target_window = float(frozen["target_window_seconds"])
    k_by_implementation = {
        TCAP_IMPLEMENTATION: int(frozen["K_TCAP"]),
        EAGER_IMPLEMENTATION: int(frozen["K_Eager"]),
    }
    native, eager, build = prepare_workers(directory, tcap_path)
    workers = {
        TCAP_IMPLEMENTATION: native,
        EAGER_IMPLEMENTATION: eager,
    }
    write_json(directory / "definitive_worker_build.json", build)
    try:
        warmups_path = directory / "warmups.json"
        if not warmups_path.exists():
            warmups = []
            for index in range(1, 4):
                for implementation in (TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION):
                    stability = _wait_recovery_stable(
                        csv_path,
                        threshold_c=start_threshold,
                        stable_seconds=30.0,
                        preabort_c=preabort_c,
                        abort_c=abort_c,
                    )
                    result, observations = workers[implementation].run(
                        1,
                        timeout_seconds=30.0,
                        guard=_make_recovery_execution_guard(
                            csv_path,
                            preabort_c=preabort_c,
                            abort_c=abort_c,
                        ),
                    )
                    result = _complete_native_result(result, tcap_path)
                    warmups.append(
                        {
                            "warmup": index,
                            "implementation": implementation,
                            "stability": stability,
                            "guard_observations": observations,
                            "numeric_result": result,
                        }
                    )
            write_json(
                warmups_path,
                {
                    "status": "PASS",
                    "outside_energy_samples": True,
                    "count_per_implementation": 3,
                    "items": warmups,
                },
            )
        else:
            # A resumed CLI invocation creates fresh worker processes. Run one
            # symmetric, unmeasured unit per implementation so process-local
            # lazy initialization cannot leak into the next energy window.
            resume_items = []
            for implementation in (TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION):
                stability = _wait_recovery_stable(
                    csv_path,
                    threshold_c=start_threshold,
                    stable_seconds=30.0,
                    preabort_c=preabort_c,
                    abort_c=abort_c,
                )
                result, observations = workers[implementation].run(
                    1,
                    timeout_seconds=30.0,
                    guard=_make_recovery_execution_guard(
                        csv_path,
                        preabort_c=preabort_c,
                        abort_c=abort_c,
                    ),
                )
                resume_items.append(
                    {
                        "implementation": implementation,
                        "stability": stability,
                        "guard_observations": observations,
                        "numeric_result": _complete_native_result(result, tcap_path),
                    }
                )
            resume_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            write_json(
                directory / f"resume-warmups-{resume_id}.json",
                {
                    "status": "PASS",
                    "outside_energy_samples": True,
                    "reason": "fresh worker processes on transactional resume",
                    "items": resume_items,
                },
            )

        completed = {
            read_json(path)["pair_id"]
            for path in (directory / "raw").glob("*-pair-result.json")
            if read_json(path).get("accepted") is True
        }
        attempted = completed | {
            read_json(path)["pair_id"]
            for path in (directory / "rejected").glob("*-pair-result.json")
            if read_json(path).get("accepted") is False
        }
        agenda = [*schedule["primary"], *schedule["replacement_queue"]]
        for item in agenda:
            if len(completed) >= int(schedule["valid_pairs_required"]):
                break
            pair_id = item["pair_id"]
            if pair_id in attempted:
                continue
            pre = _recovery_equivalence_gate(
                directory,
                csv_path,
                tcap_path,
                (native, eager),
                start_threshold,
                preabort_c,
                abort_c,
                label=f"{pair_id}-pre",
            )
            windows = {}
            pair_rejection = None
            for order, implementation in enumerate(item["order"], 1):
                stability = _wait_recovery_stable(
                    csv_path,
                    threshold_c=start_threshold,
                    stable_seconds=30.0,
                    preabort_c=preabort_c,
                    abort_c=abort_c,
                )
                try:
                    window = _run_recovery_window(
                        directory,
                        csv_path,
                        workers[implementation],
                        k_by_implementation[implementation],
                        stage=f"{pair_id}-{implementation}",
                        required_samples=60,
                        minimum_expected_seconds=minimum_window,
                        maximum_expected_seconds=target_window * 1.50 + 5.0,
                        tcap_path=tcap_path,
                        preabort_c=preabort_c,
                        abort_c=abort_c,
                    )
                except ThermalRecoveryBlocked as exc:
                    rejected_window = exc.detail.get("window")
                    if not isinstance(rejected_window, dict):
                        raise
                    pair_rejection = {
                        "schema": "casulo-hwinfo-recovery-pair-rejection/1.0",
                        "pair_id": pair_id,
                        "order": item["order"],
                        "accepted": False,
                        "pre_equivalence": pre["status"],
                        "failed_implementation": implementation,
                        "reason_code": rejected_window.get("reason_code"),
                        "window": rejected_window,
                    }
                    write_json(
                        directory / "rejected" / f"{pair_id}-pair-result.json",
                        pair_rejection,
                    )
                    attempted.add(pair_id)
                    break
                window.update(
                    {
                        "pair_id": pair_id,
                        "order_in_pair": order,
                        "pre_window_stability": stability,
                        "joules_per_training": (
                            window["window"]["energy_joules"] / window["K"]
                        ),
                        "seconds_per_training": (
                            window["elapsed_seconds"] / window["K"]
                        ),
                    }
                )
                write_json(
                    directory / "raw" / f"{pair_id}-{implementation}.json",
                    window,
                )
                windows[implementation] = window
            if pair_rejection is not None:
                continue
            post = _recovery_equivalence_gate(
                directory,
                csv_path,
                tcap_path,
                (native, eager),
                start_threshold,
                preabort_c,
                abort_c,
                label=f"{pair_id}-post",
            )
            pair = {
                "schema": "casulo-hwinfo-recovery-pair/1.0",
                "pair_id": pair_id,
                "order": item["order"],
                "accepted": True,
                "pre_equivalence": pre["status"],
                "post_equivalence": post["status"],
                "windows": windows,
            }
            write_json(directory / "raw" / f"{pair_id}-pair-result.json", pair)
            completed.add(pair_id)
        state = {
            "status": (
                "COLLECTION_COMPLETE"
                if len(completed) == int(schedule["valid_pairs_required"])
                else "COLLECTION_INCOMPLETE"
            ),
            "valid_pairs": len(completed),
            "required_pairs": int(schedule["valid_pairs_required"]),
            "completed_pair_ids": sorted(completed),
        }
        write_json(directory / "collection_state.json", state)
        return state
    finally:
        native.stop()
        eager.stop()


def analyze_recovery_campaign(directory: Path) -> dict[str, Any]:
    directory = Path(directory).resolve()
    protocol = read_json(directory / "protocol.json")
    pairs = [
        read_json(path)
        for path in sorted((directory / "raw").glob("*-pair-result.json"))
        if read_json(path).get("accepted") is True
    ]
    details = []
    for pair in pairs:
        candidate = pair["windows"][TCAP_IMPLEMENTATION]
        baseline = pair["windows"][EAGER_IMPLEMENTATION]
        candidate_j = float(candidate["joules_per_training"])
        baseline_j = float(baseline["joules_per_training"])
        details.append(
            {
                "pair_id": pair["pair_id"],
                "order": pair["order"],
                "tcap_joules_per_training": candidate_j,
                "eager_joules_per_training": baseline_j,
                "ratio_tcap_over_eager": candidate_j / baseline_j,
                "tcap_seconds_per_training": candidate["seconds_per_training"],
                "eager_seconds_per_training": baseline["seconds_per_training"],
                "tcap_average_watts": candidate["window"]["average_watts"],
                "eager_average_watts": baseline["window"]["average_watts"],
                "tcap_maximum_temperature_c": candidate["thermal"]["maximum_temperature_c"],
                "eager_maximum_temperature_c": baseline["thermal"]["maximum_temperature_c"],
            }
        )
    ratios = tuple(item["ratio_tcap_over_eager"] for item in details)
    candidate_values = [item["tcap_joules_per_training"] for item in details]
    baseline_values = [item["eager_joules_per_training"] for item in details]
    median_ratio = statistics.median(ratios) if ratios else None
    low = high = None
    if len(ratios) >= 2:
        low, high = paired_bootstrap_ci(
            ratios,
            seed=BOOTSTRAP_SEED,
            resamples=BOOTSTRAP_RESAMPLES,
        )
    complete = len(details) == int(protocol["pairs_required"])
    t_temperatures = [item["tcap_maximum_temperature_c"] for item in details]
    e_temperatures = [item["eager_maximum_temperature_c"] for item in details]
    asymmetry = (
        abs(statistics.median(t_temperatures) - statistics.median(e_temperatures))
        if details
        else None
    )
    thermal_parity = bool(
        asymmetry is not None
        and asymmetry
        <= float(protocol["thermal"]["maximum_median_temperature_asymmetry_c"])
        and all(
            value < float(protocol["thermal"]["abort_c"])
            for value in [*t_temperatures, *e_temperatures]
        )
    )
    if not complete:
        terminal = "BLOCKED_PHYSICAL_INSTRUMENT"
    elif median_ratio is not None and high is not None and median_ratio < 1 and high < 1 and thermal_parity:
        terminal = "PASS_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS"
    elif low is not None and median_ratio is not None and median_ratio >= 1 and low >= 1:
        terminal = "FAIL_NO_CPU_PACKAGE_ENERGY_ADVANTAGE_HWINFO_WINDOWS"
    else:
        terminal = "INCONCLUSIVE_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS"
    analysis = {
        "schema": "casulo-hwinfo-thermal-recovery-analysis/1.0",
        "campaign_id": directory.name,
        "terminal_state": terminal,
        "scientific_scope": "HWiNFO-reported CPU package energy on bare-metal Windows",
        "sensor": protocol["source_sensor"],
        "sampling": read_json(directory / "polling_validation.json"),
        "valid_pairs": len(details),
        "rejected_artifacts": len(list((directory / "rejected").glob("*.json"))),
        "pairs": details,
        "median_joules_per_training": {
            TCAP_IMPLEMENTATION: statistics.median(candidate_values) if candidate_values else None,
            EAGER_IMPLEMENTATION: statistics.median(baseline_values) if baseline_values else None,
        },
        "median_ratio_tcap_over_eager": median_ratio,
        "paired_bootstrap_ci95": (
            {
                "lower": low,
                "upper": high,
                "seed": BOOTSTRAP_SEED,
                "resamples": BOOTSTRAP_RESAMPLES,
            }
            if low is not None
            else None
        ),
        "exact_sign_test": (
            exact_sign_test(candidate_values, baseline_values) if details else None
        ),
        "material_improvement_at_least_10_percent": bool(
            median_ratio is not None and 1.0 - median_ratio >= 0.10
        ),
        "thermal_parity": {
            "passed": thermal_parity,
            "median_maximum_temperature_asymmetry_c": asymmetry,
            "limit_c": protocol["thermal"]["maximum_median_temperature_asymmetry_c"],
        },
        "equivalence": "PASS_PER_PAIR_PRE_AND_POST" if complete else "INCOMPLETE",
        "outliers_removed": False,
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
    }
    write_json(directory / "analysis.json", analysis)
    return analysis


def render_recovery_report(directory: Path, analysis: dict[str, Any]) -> Path:
    directory = Path(directory).resolve()
    ci = analysis.get("paired_bootstrap_ci95") or {}
    medians = analysis["median_joules_per_training"]
    report = f"""# Campanha energética HWiNFO: TCAP × PyTorch Eager

**Estado científico:** `{analysis['terminal_state']}`

Escopo: HWiNFO-reported CPU package energy on bare-metal Windows.

- Sensor: `{analysis['sensor']['literal_name']}` ({analysis['sensor']['unit']})
- Intervalo mediano: {analysis['sampling']['median_interval_seconds']} s
- Pares válidos: {analysis['valid_pairs']}/21
- TCAP: {medians[TCAP_IMPLEMENTATION]} J/treinamento
- PyTorch Eager: {medians[EAGER_IMPLEMENTATION]} J/treinamento
- Razão TCAP/Eager: {analysis['median_ratio_tcap_over_eager']}
- IC bootstrap pareado 95%: [{ci.get('lower')}, {ci.get('upper')}]
- Equivalência: {analysis['equivalence']}
- Assimetria térmica mediana: {analysis['thermal_parity']['median_maximum_temperature_asymmetry_c']} °C
- Outliers removidos: não

`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`

`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`

Nenhuma extrapolação para Inductor, GPU/TPU, datacenter, outros hosts ou energia total.
"""
    path = directory / "report.md"
    path.write_text(report, encoding="utf-8", newline="\n")
    return path


def finalize_recovery_evidence(directory: Path, csv_path: Path) -> dict[str, Any]:
    directory = Path(directory).resolve()
    snapshot = read_shared_snapshot(csv_path)
    (directory / "source_csv_final.sha256").write_text(
        f"{snapshot.sha256}  {Path(csv_path).name} bytes=0:{snapshot.bytes_read}\n",
        encoding="ascii",
        newline="\n",
    )
    markers = [
        json.loads(line)
        for line in (directory / "benchmark_markers.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    bounds = [datetime.fromisoformat(item["utc"]) for item in markers]
    if bounds:
        segment = extract_interval_csv(snapshot, min(bounds), max(bounds))
        (directory / "source_segment.csv").write_text(
            segment,
            encoding="utf-8",
            newline="",
        )
    return seal_recovery_campaign(directory)


def seal_recovery_campaign(directory: Path) -> dict[str, Any]:
    directory = Path(directory).resolve()
    files = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}
    ]
    entries = [
        {
            "path": path.relative_to(directory).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(files)
    ]
    manifest = {
        "schema": "casulo-hwinfo-thermal-recovery-manifest/1.0",
        "campaign_id": directory.name,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }
    write_json(directory / "MANIFEST.json", manifest)
    checksum_files = [*files, directory / "MANIFEST.json"]
    (directory / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(directory).as_posix()}\n"
            for path in sorted(checksum_files)
        ),
        encoding="ascii",
        newline="\n",
    )
    return {
        "manifest_sha256": sha256_file(directory / "MANIFEST.json"),
        "sha256s_sha256": sha256_file(directory / "SHA256SUMS"),
        "files": len(entries),
    }


def _recovery_schedule() -> dict[str, Any]:
    primary = []
    replacements = []
    for index in range(1, 22):
        order = [TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION] if index % 2 else [EAGER_IMPLEMENTATION, TCAP_IMPLEMENTATION]
        primary.append({"pair_id": f"pair-{index:02d}", "order": order})
    for index in range(22, 64):
        order = [TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION] if index % 2 else [EAGER_IMPLEMENTATION, TCAP_IMPLEMENTATION]
        replacements.append({"pair_id": f"replacement-{index:02d}", "order": order})
    return {
        "schema": "casulo-hwinfo-recovery-schedule/1.0",
        "frozen_before_results": True,
        "valid_pairs_required": 21,
        "primary": primary,
        "replacement_queue": replacements,
    }


def _allocate_new_id(root: Path, requested: str) -> str:
    if not (Path(root) / requested).exists():
        return requested
    index = 2
    while (Path(root) / f"{requested}-{index:02d}").exists():
        index += 1
    return f"{requested}-{index:02d}"


def _append_marker(directory: Path, event: str, utc: datetime, extra: dict[str, Any]) -> None:
    value = {
        "event": event,
        "utc": utc.astimezone(timezone.utc).isoformat(),
        "local": utc.astimezone().isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        **extra,
    }
    with (Path(directory) / "benchmark_markers.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _observer_snapshot() -> list[dict[str, Any]]:
    try:
        import psutil
    except ImportError:
        return []
    result = []
    for process in psutil.process_iter(("pid", "name", "cpu_times")):
        name = str(process.info.get("name") or "")
        if "hwinfo" not in name.lower():
            continue
        times = process.info.get("cpu_times")
        result.append({
            "pid": process.info["pid"],
            "name": name,
            "user_cpu_seconds": float(times.user) if times else None,
            "system_cpu_seconds": float(times.system) if times else None,
        })
    return result


def _cpu_seconds_delta(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> float | None:
    old = {item["pid"]: item for item in before}
    deltas = []
    for item in after:
        previous = old.get(item["pid"])
        if previous is None:
            continue
        deltas.append(
            item["user_cpu_seconds"] + item["system_cpu_seconds"]
            - previous["user_cpu_seconds"] - previous["system_cpu_seconds"]
        )
    return sum(deltas) if deltas else None


def _host_cpu_percent() -> float | None:
    try:
        import psutil
        return float(psutil.cpu_percent(interval=None))
    except Exception:
        return None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _blocked_report(analysis: dict[str, Any]) -> str:
    polling = analysis["polling"]
    return f"""# HWiNFO thermal recovery campaign

Scientific state: `BLOCKED_HWINFO_POLLING_NOT_CHANGED`

## R1 result

- Median interval: `{polling['median_interval_seconds']:.6f} s`
- P95 interval: `{polling['p95_interval_seconds']:.6f} s`
- Required median: `<= {POLLING_MEDIAN_LIMIT_SECONDS:.3f} s`
- Required P95: `<= {POLLING_P95_LIMIT_SECONDS:.3f} s`
- New samples: `{polling['new_samples']}`
- Workload executions: `0`

The active logger is still near its previous polling period. `Global Polling
Period` must be configured to `500 ms` before any thermal probe or definitive
window. The prior blocked campaign and the source CSV remain unchanged.

No joules per training, paired ratio, confidence interval, or energy advantage
is reported. `TOTAL_SYSTEM_WALL` and `CASULO_NATIVE_ENERGY` remain
`BLOCKED_PHYSICAL_INSTRUMENT`.
"""
