from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


class EnergyMeasurementError(RuntimeError):
    """Raised when an energy source cannot support an honest delta."""


@dataclass(frozen=True, slots=True)
class RaplSample:
    domain: str
    energy_uj: int
    observed_ns: int
    max_energy_range_uj: int


@dataclass(frozen=True, slots=True)
class EnergyDelta:
    domain: str
    energy_uj: int
    elapsed_ns: int
    rollovers: int

    @property
    def joules(self) -> float:
        return self.energy_uj / 1_000_000.0

    @property
    def average_watts(self) -> float:
        if self.elapsed_ns <= 0:
            raise EnergyMeasurementError("elapsed time must advance")
        return self.joules / (self.elapsed_ns / 1_000_000_000.0)


class RaplCounter:
    """Linux powercap counter with explicit, single-wrap accounting.

    The kernel exposes a cumulative microjoule counter that wraps at
    ``max_energy_range_uj``. Sampling intervals must therefore be short enough
    to guarantee at most one wrap. LiveLab never guesses multiple rollovers.
    """

    def __init__(
        self,
        energy_path: Path,
        *,
        max_range_path: Path | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.energy_path = Path(energy_path)
        self.max_range_path = Path(max_range_path) if max_range_path else self.energy_path.with_name("max_energy_range_uj")
        self.clock_ns = clock_ns

    def sample(self) -> RaplSample:
        maximum = _read_positive_integer(self.max_range_path, "RAPL maximum range")
        energy = _read_nonnegative_integer(self.energy_path, "RAPL energy")
        if energy >= maximum:
            raise EnergyMeasurementError("RAPL energy is outside its declared range")
        return RaplSample(str(self.energy_path), energy, self.clock_ns(), maximum)

    @staticmethod
    def delta(before: RaplSample, after: RaplSample) -> EnergyDelta:
        if before.domain != after.domain:
            raise EnergyMeasurementError("RAPL samples belong to different domains")
        if before.max_energy_range_uj != after.max_energy_range_uj:
            raise EnergyMeasurementError("RAPL maximum range changed between samples")
        elapsed = after.observed_ns - before.observed_ns
        if elapsed <= 0:
            raise EnergyMeasurementError("RAPL timestamps did not advance")
        if after.energy_uj >= before.energy_uj:
            consumed = after.energy_uj - before.energy_uj
            rollovers = 0
        else:
            consumed = before.max_energy_range_uj - before.energy_uj + after.energy_uj
            rollovers = 1
        return EnergyDelta(before.domain, consumed, elapsed, rollovers)


@dataclass(frozen=True, slots=True)
class ExternalMeterSample:
    device_id: str
    observed_ns: int
    cumulative_joules: float
    watts: float | None = None


@dataclass(frozen=True, slots=True)
class ExternalMeterValidation:
    valid: bool
    reason_code: str
    sample_count: int
    advancing_intervals: int
    energy_delta_joules: float | None


class ExternalPowerMeterAdapter(Protocol):
    """Configured hardware adapter; discovery alone is not validation."""

    def read_sample(self) -> ExternalMeterSample:
        ...


def collect_external_meter_validation(
    adapter: ExternalPowerMeterAdapter,
    *,
    sample_count: int = 3,
) -> tuple[tuple[ExternalMeterSample, ...], ExternalMeterValidation]:
    if not 2 <= sample_count <= 10_000:
        raise ValueError("sample_count outside supported bounds")
    samples: list[ExternalMeterSample] = []
    try:
        for _ in range(sample_count):
            sample = adapter.read_sample()
            if not isinstance(sample, ExternalMeterSample):
                raise TypeError("adapter returned an invalid sample type")
            samples.append(sample)
    except Exception:
        return (
            tuple(samples),
            ExternalMeterValidation(False, "adapter_read_error", len(samples), 0, None),
        )
    frozen = tuple(samples)
    return frozen, validate_external_meter(frozen, minimum_samples=sample_count)


def validate_external_meter(
    samples: tuple[ExternalMeterSample, ...] | list[ExternalMeterSample],
    *,
    minimum_samples: int = 3,
) -> ExternalMeterValidation:
    """Validate identity, finite values and advancing time/energy.

    A valid adapter must expose a cumulative joule reading. Instantaneous watts
    are diagnostic only and are never integrated into an invented energy value.
    """

    if minimum_samples < 2:
        raise ValueError("minimum_samples must be at least two")
    count = len(samples)
    if count < minimum_samples:
        return ExternalMeterValidation(False, "insufficient_samples", count, 0, None)
    device = samples[0].device_id
    if not device or any(item.device_id != device for item in samples):
        return ExternalMeterValidation(False, "device_identity_changed", count, 0, None)
    for item in samples:
        if not math.isfinite(item.cumulative_joules) or item.cumulative_joules < 0:
            return ExternalMeterValidation(False, "invalid_cumulative_energy", count, 0, None)
        if item.watts is not None and (not math.isfinite(item.watts) or item.watts < 0):
            return ExternalMeterValidation(False, "invalid_instantaneous_power", count, 0, None)
    advancing = 0
    for left, right in zip(samples, samples[1:]):
        if right.observed_ns <= left.observed_ns:
            return ExternalMeterValidation(False, "timestamp_not_monotonic", count, advancing, None)
        if right.cumulative_joules < left.cumulative_joules:
            return ExternalMeterValidation(False, "energy_counter_regressed", count, advancing, None)
        if right.cumulative_joules > left.cumulative_joules:
            advancing += 1
    if advancing == 0:
        return ExternalMeterValidation(False, "energy_counter_not_advancing", count, 0, None)
    delta = samples[-1].cumulative_joules - samples[0].cumulative_joules
    return ExternalMeterValidation(True, "validated_advancing_counter", count, advancing, delta)


def _read_positive_integer(path: Path, label: str) -> int:
    value = _read_nonnegative_integer(path, label)
    if value <= 0:
        raise EnergyMeasurementError(f"{label} must be positive")
    return value


def _read_nonnegative_integer(path: Path, label: str) -> int:
    try:
        text = path.read_text(encoding="ascii").strip()
        value = int(text)
    except (OSError, ValueError) as exc:
        raise EnergyMeasurementError(f"cannot read {label}: {path}") from exc
    if value < 0:
        raise EnergyMeasurementError(f"{label} must be nonnegative")
    return value
