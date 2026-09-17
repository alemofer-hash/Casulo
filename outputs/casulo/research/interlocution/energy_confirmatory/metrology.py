from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal


SourceKind = Literal["TOTAL_SYSTEM_WALL", "CPU_PACKAGE_RAPL", "EXPLORATORY_HWINFO"]


@dataclass(frozen=True, slots=True)
class InstrumentManifest:
    instrument_id: str
    source_kind: SourceKind
    manufacturer: str
    model: str
    serial_number: str
    calibration_id: str | None
    calibration_utc: str | None
    calibration_authority: str | None
    stated_relative_uncertainty: float | None
    physical: bool
    mock: bool = False
    firmware: str | None = None
    configured_range: str | None = None
    clock_uncertainty_seconds: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MeterSample:
    timestamp_utc: str
    epoch_seconds: float
    watts: float | None = None
    cumulative_joules: float | None = None
    range_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EnergyWindow:
    status: str
    reason_code: str
    start_epoch_seconds: float
    end_epoch_seconds: float
    duration_seconds: float
    samples: int
    median_interval_seconds: float | None
    maximum_gap_seconds: float | None
    coverage: float
    integrated_joules: float | None
    average_watts: float | None
    measurement_mode: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_instrument(
    manifest: InstrumentManifest,
    *,
    confirmatory: bool,
) -> tuple[bool, str]:
    if not manifest.instrument_id.strip() or not manifest.manufacturer.strip() or not manifest.model.strip():
        return False, "instrument_identity_incomplete"
    if manifest.mock or not manifest.physical:
        return False, "mock_or_nonphysical_instrument"
    if manifest.source_kind == "EXPLORATORY_HWINFO":
        return (False, "exploratory_source_not_confirmatory") if confirmatory else (True, "exploratory_physical_telemetry")
    if manifest.source_kind == "TOTAL_SYSTEM_WALL":
        if not manifest.serial_number.strip():
            return False, "wall_meter_serial_missing"
        if confirmatory and (
            not manifest.calibration_id
            or not manifest.calibration_utc
            or not manifest.calibration_authority
            or manifest.stated_relative_uncertainty is None
        ):
            return False, "wall_meter_calibration_incomplete"
        if confirmatory and (
            not manifest.firmware
            or not manifest.configured_range
            or manifest.clock_uncertainty_seconds is None
        ):
            return False, "wall_meter_runtime_configuration_incomplete"
    if manifest.stated_relative_uncertainty is not None and (
        not math.isfinite(manifest.stated_relative_uncertainty)
        or not 0 <= manifest.stated_relative_uncertainty < 1
    ):
        return False, "instrument_uncertainty_invalid"
    if manifest.clock_uncertainty_seconds is not None and (
        not math.isfinite(manifest.clock_uncertainty_seconds)
        or manifest.clock_uncertainty_seconds < 0
    ):
        return False, "instrument_clock_uncertainty_invalid"
    return True, "confirmatory_physical_instrument" if confirmatory else "physical_instrument"


def integrate_energy_window(
    samples: Iterable[MeterSample],
    *,
    start_epoch_seconds: float,
    end_epoch_seconds: float,
    minimum_samples: int = 2,
    minimum_coverage: float = 0.98,
    maximum_gap_factor: float = 5.0,
) -> EnergyWindow:
    if not math.isfinite(start_epoch_seconds) or not math.isfinite(end_epoch_seconds) or end_epoch_seconds <= start_epoch_seconds:
        raise ValueError("energy window must be finite and advancing")
    ordered = tuple(sorted(samples, key=lambda item: item.epoch_seconds))
    duration = end_epoch_seconds - start_epoch_seconds
    if len(ordered) < 2:
        return _rejected("insufficient_source_samples", start_epoch_seconds, end_epoch_seconds)
    for left, right in zip(ordered, ordered[1:]):
        if right.epoch_seconds <= left.epoch_seconds:
            return _rejected("duplicate_or_regressing_timestamp", start_epoch_seconds, end_epoch_seconds)
    modes = {
        "power" if item.watts is not None and item.cumulative_joules is None else
        "cumulative" if item.cumulative_joules is not None and item.watts is None else
        "invalid"
        for item in ordered
    }
    if modes == {"invalid"} or "invalid" in modes or len(modes) != 1:
        return _rejected("mixed_or_ambiguous_meter_signal", start_epoch_seconds, end_epoch_seconds)
    ranges = {item.range_id for item in ordered if item.range_id is not None}
    if len(ranges) > 1:
        return _rejected("meter_range_changed_inside_source", start_epoch_seconds, end_epoch_seconds)
    mode = next(iter(modes))
    values = tuple(
        float(item.watts if mode == "power" else item.cumulative_joules)
        for item in ordered
    )
    if any(not math.isfinite(value) or value < 0 for value in values):
        return _rejected("negative_or_nonfinite_meter_value", start_epoch_seconds, end_epoch_seconds)
    before_start = [index for index, item in enumerate(ordered) if item.epoch_seconds <= start_epoch_seconds]
    after_start = [index for index, item in enumerate(ordered) if item.epoch_seconds >= start_epoch_seconds]
    before_end = [index for index, item in enumerate(ordered) if item.epoch_seconds <= end_epoch_seconds]
    after_end = [index for index, item in enumerate(ordered) if item.epoch_seconds >= end_epoch_seconds]
    if not before_start or not after_start or not before_end or not after_end:
        return _rejected("benchmark_window_not_bracketed", start_epoch_seconds, end_epoch_seconds)
    start_value = _interpolate(
        ordered[before_start[-1]].epoch_seconds,
        values[before_start[-1]],
        ordered[after_start[0]].epoch_seconds,
        values[after_start[0]],
        start_epoch_seconds,
    )
    end_value = _interpolate(
        ordered[before_end[-1]].epoch_seconds,
        values[before_end[-1]],
        ordered[after_end[0]].epoch_seconds,
        values[after_end[0]],
        end_epoch_seconds,
    )
    internal = [
        (item.epoch_seconds, value)
        for item, value in zip(ordered, values, strict=True)
        if start_epoch_seconds < item.epoch_seconds < end_epoch_seconds
    ]
    window = [(start_epoch_seconds, start_value), *internal, (end_epoch_seconds, end_value)]
    intervals = [right[0] - left[0] for left, right in zip(window, window[1:])]
    median_interval = statistics.median(intervals) if intervals else None
    maximum_gap = max(intervals) if intervals else None
    coverage = (window[-1][0] - window[0][0]) / duration
    if len(window) < minimum_samples:
        return _rejected("insufficient_window_samples", start_epoch_seconds, end_epoch_seconds, len(window), median_interval, maximum_gap, coverage, mode)
    if coverage < minimum_coverage:
        return _rejected("coverage_below_threshold", start_epoch_seconds, end_epoch_seconds, len(window), median_interval, maximum_gap, coverage, mode)
    if median_interval is None or maximum_gap is None or maximum_gap > maximum_gap_factor * median_interval:
        return _rejected("sampling_gap_exceeded", start_epoch_seconds, end_epoch_seconds, len(window), median_interval, maximum_gap, coverage, mode)
    if mode == "power":
        joules = sum(
            ((left[1] + right[1]) / 2.0) * (right[0] - left[0])
            for left, right in zip(window, window[1:])
        )
    else:
        if any(right[1] < left[1] for left, right in zip(window, window[1:])):
            return _rejected("cumulative_counter_reset_or_wrap_unknown", start_epoch_seconds, end_epoch_seconds, len(window), median_interval, maximum_gap, coverage, mode)
        joules = end_value - start_value
    return EnergyWindow(
        "PASS",
        "integrated_with_exact_boundary_interpolation",
        start_epoch_seconds,
        end_epoch_seconds,
        duration,
        len(window),
        median_interval,
        maximum_gap,
        coverage,
        joules,
        joules / duration,
        mode,
    )


def sample_from_iso(timestamp_utc: str, *, watts: float | None = None, cumulative_joules: float | None = None, range_id: str | None = None) -> MeterSample:
    parsed = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("meter timestamp must include a timezone")
    normalized = parsed.astimezone(timezone.utc)
    return MeterSample(normalized.isoformat(), normalized.timestamp(), watts, cumulative_joules, range_id)


def qualify_power_path(
    *,
    has_battery: bool,
    battery_observable: bool,
    battery_stable: bool,
    ac_continuous: bool,
) -> tuple[bool, str]:
    if not ac_continuous:
        return False, "ac_not_continuous"
    if not has_battery:
        return True, "batteryless_desktop_power_path"
    if not battery_observable:
        return False, "laptop_battery_unobservable"
    if not battery_stable:
        return False, "laptop_battery_not_stable"
    return True, "laptop_battery_observed_stable"


def _interpolate(t0: float, v0: float, t1: float, v1: float, target: float) -> float:
    if t0 == t1:
        if target != t0:
            raise ValueError("cannot interpolate duplicate timestamps")
        return v0
    return v0 + ((target - t0) / (t1 - t0)) * (v1 - v0)


def _rejected(
    reason: str,
    start: float,
    end: float,
    samples: int = 0,
    median: float | None = None,
    maximum_gap: float | None = None,
    coverage: float = 0.0,
    mode: str | None = None,
) -> EnergyWindow:
    return EnergyWindow("REJECTED", reason, start, end, end - start, samples, median, maximum_gap, coverage, None, None, mode)
