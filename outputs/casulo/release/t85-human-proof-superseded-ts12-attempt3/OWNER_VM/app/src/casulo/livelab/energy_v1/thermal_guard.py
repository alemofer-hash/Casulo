from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class ThermalSnapshot:
    monotonic_ns: int
    temperatures_c: tuple[float, ...]
    maximum_c: float | None
    throttling_detected: bool | None
    throttle_counters: tuple[int, ...]
    source: str
    advancing: bool

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["temperatures_c"] = list(self.temperatures_c)
        value["throttle_counters"] = list(self.throttle_counters)
        return value


@dataclass(frozen=True, slots=True)
class ThermalAssessment:
    accepted: bool
    reason_code: str
    maximum_c: float | None
    drift_c: float | None
    throttling_detected: bool | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def probe_linux_thermal(
    *,
    thermal_root: Path = Path("/sys/class/thermal"),
    cpu_root: Path = Path("/sys/devices/system/cpu"),
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> ThermalSnapshot:
    temperatures = []
    root = Path(thermal_root)
    if root.is_dir():
        for path in sorted(root.glob("thermal_zone*/temp")):
            try:
                raw = float(path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                continue
            value = raw / 1000.0 if raw > 1000 else raw
            if math.isfinite(value) and -20 <= value <= 150:
                temperatures.append(value)
    counters = []
    for pattern in ("cpu*/thermal_throttle/core_throttle_count", "cpu*/thermal_throttle/package_throttle_count"):
        for path in sorted(Path(cpu_root).glob(pattern)):
            try:
                value = int(path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                continue
            if value >= 0:
                counters.append(value)
    return ThermalSnapshot(
        clock_ns(), tuple(temperatures), max(temperatures) if temperatures else None,
        False if counters else None, tuple(counters),
        "linux_sysfs" if temperatures else "unavailable", False,
    )


def assess_thermal_window(
    samples: tuple[ThermalSnapshot, ...],
    *,
    maximum_temperature_c: float = 55.0,
    maximum_drift_c: float = 3.0,
) -> ThermalAssessment:
    if len(samples) < 2:
        return ThermalAssessment(False, "thermal_samples_insufficient", None, None, None)
    if any(item.maximum_c is None for item in samples):
        return ThermalAssessment(False, "thermal_metric_unavailable", None, None, None)
    if any(right.monotonic_ns <= left.monotonic_ns for left, right in zip(samples, samples[1:])):
        return ThermalAssessment(False, "thermal_timestamp_not_advancing", None, None, None)
    values = tuple(float(item.maximum_c) for item in samples if item.maximum_c is not None)
    maximum = max(values)
    drift = max(values) - min(values)
    throttling = any(item.throttling_detected is True for item in samples)
    for left, right in zip(samples, samples[1:]):
        if left.throttle_counters and right.throttle_counters:
            if len(left.throttle_counters) != len(right.throttle_counters):
                return ThermalAssessment(False, "throttle_counter_topology_changed", maximum, drift, None)
            throttling = throttling or any(b > a for a, b in zip(left.throttle_counters, right.throttle_counters))
    if throttling:
        return ThermalAssessment(False, "throttling_detected", maximum, drift, True)
    if maximum > maximum_temperature_c:
        return ThermalAssessment(False, "temperature_limit_exceeded", maximum, drift, False)
    if drift > maximum_drift_c:
        return ThermalAssessment(False, "thermal_drift_exceeded", maximum, drift, False)
    return ThermalAssessment(True, "thermal_window_stable", maximum, drift, False)
