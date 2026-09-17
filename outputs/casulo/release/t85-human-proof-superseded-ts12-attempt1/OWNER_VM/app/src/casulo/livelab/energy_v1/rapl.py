from __future__ import annotations

import hashlib
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from casulo.livelab.energy import EnergyMeasurementError, RaplCounter, RaplSample


@dataclass(frozen=True, slots=True)
class RaplZone:
    zone_id: str
    name: str
    path: str
    parent_zone_id: str | None
    energy_uj_path: str
    max_energy_range_uj_path: str
    readable: bool
    resolution_uj: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RaplValidation:
    valid: bool
    reason_code: str
    domain: str | None
    zone_id: str | None
    samples: tuple[dict[str, int | str], ...]
    delta_uj: int | None
    rollovers: int | None
    controlled_load_iterations: int
    physical: bool

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["samples"] = list(self.samples)
        return value


def discover_rapl_zones(root: Path = Path("/sys/class/powercap")) -> tuple[RaplZone, ...]:
    base = Path(root)
    if not base.is_dir():
        return ()
    candidates = sorted(
        path for path in base.rglob("*") if path.is_dir() and (path / "energy_uj").exists()
    )
    zones: list[RaplZone] = []
    path_to_id: dict[Path, str] = {}
    for path in candidates:
        zone_id = path.name
        name_path = path / "name"
        try:
            name = name_path.read_text(encoding="ascii").strip()
        except OSError:
            name = zone_id
        energy = path / "energy_uj"
        maximum = path / "max_energy_range_uj"
        readable = energy.is_file() and maximum.is_file() and os.access(energy, os.R_OK) and os.access(maximum, os.R_OK)
        parent: str | None = None
        cursor = path.parent
        while cursor != base.parent:
            if cursor in path_to_id:
                parent = path_to_id[cursor]
                break
            if cursor == base:
                break
            cursor = cursor.parent
        zones.append(
            RaplZone(
                zone_id=zone_id,
                name=name or zone_id,
                path=str(path),
                parent_zone_id=parent,
                energy_uj_path=str(energy),
                max_energy_range_uj_path=str(maximum),
                readable=readable,
                resolution_uj=1,
            )
        )
        path_to_id[path] = zone_id
    return tuple(zones)


def package_zones(zones: tuple[RaplZone, ...]) -> tuple[RaplZone, ...]:
    """Select non-nested package domains; never aggregate hierarchical zones."""

    selected = []
    for zone in zones:
        normalized = zone.name.lower().replace("_", "-")
        if zone.parent_zone_id is None and (
            normalized in {"package-0", "package-1", "package"}
            or zone.zone_id.count(":") == 1
        ):
            selected.append(zone)
    return tuple(selected)


def _bounded_controlled_load(seconds: float, clock: Callable[[], float] = time.monotonic) -> int:
    if not 0.05 <= seconds <= 2.0:
        raise ValueError("controlled RAPL load must be between 0.05 and 2 seconds")
    deadline = clock() + seconds
    value = b"casulo-energy-rapl-preflight"
    iterations = 0
    while clock() < deadline:
        value = hashlib.sha256(value).digest()
        iterations += 1
    return iterations


def validate_rapl_zones(
    zones: tuple[RaplZone, ...],
    *,
    load_seconds: float = 0.10,
    load: Callable[[float], int] = _bounded_controlled_load,
) -> tuple[RaplValidation, ...]:
    results: list[RaplValidation] = []
    for zone in package_zones(zones):
        if not zone.readable:
            results.append(RaplValidation(False, "rapl_permission_denied", None, zone.zone_id, (), None, None, 0, True))
            continue
        counter = RaplCounter(Path(zone.energy_uj_path), max_range_path=Path(zone.max_energy_range_uj_path))
        try:
            before = counter.sample()
            iterations = load(load_seconds)
            after = counter.sample()
            delta = counter.delta(before, after)
            samples = (_sample_dict(before), _sample_dict(after))
            if delta.energy_uj <= 0:
                results.append(RaplValidation(False, "rapl_counter_not_advancing", None, zone.zone_id, samples, 0, delta.rollovers, iterations, True))
            else:
                results.append(RaplValidation(True, "validated_advancing_cpu_package_counter", "CPU_PACKAGE_RAPL", zone.zone_id, samples, delta.energy_uj, delta.rollovers, iterations, True))
        except EnergyMeasurementError as exc:
            results.append(RaplValidation(False, f"rapl_invalid:{exc}", None, zone.zone_id, (), None, None, 0, True))
    if not results:
        results.append(RaplValidation(False, "cpu_package_rapl_zone_absent", None, None, (), None, None, 0, False))
    return tuple(results)


def _sample_dict(sample: RaplSample) -> dict[str, int | str]:
    return {
        "domain": sample.domain,
        "energy_uj": sample.energy_uj,
        "observed_ns": sample.observed_ns,
        "max_energy_range_uj": sample.max_energy_range_uj,
    }
