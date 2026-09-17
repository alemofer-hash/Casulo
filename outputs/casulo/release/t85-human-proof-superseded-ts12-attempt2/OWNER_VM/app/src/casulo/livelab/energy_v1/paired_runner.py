from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from casulo.livelab.energy import RaplCounter, RaplSample

from .battery_guard import BatterySnapshot, assess_battery_window, probe_battery
from .protocol import EnergyProtocol, deterministic_schedule
from .schemas import SAMPLE_SCHEMA, canonical_bytes, iter_jsonl, sha256_bytes, sha256_file, validate_sample
from .thermal_guard import ThermalSnapshot, assess_thermal_window, probe_linux_thermal


UNIT_RESULT_SCHEMA = "casulo-energy-unit-result/1.0"
COMMANDS_SCHEMA = "casulo-energy-commands/1.0"


@dataclass(frozen=True, slots=True)
class UnitCommand:
    implementation: str
    argv: tuple[str, ...]
    cwd: str
    environment: Mapping[str, str]
    timeout_seconds: float
    workload: str
    seed: int
    executable_sha256: str | None
    tcap_sha256: str | None
    dataset_sha256: str
    configuration_sha256: str
    compilation_included: bool

    def __post_init__(self) -> None:
        if not self.implementation or not self.argv or any(not item for item in self.argv):
            raise ValueError("unit command is empty")
        if not 0.1 <= self.timeout_seconds <= 3600:
            raise ValueError("unit timeout outside safety bounds")
        for value in (self.executable_sha256, self.tcap_sha256, self.dataset_sha256, self.configuration_sha256):
            if value is not None and (len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)):
                raise ValueError("unit command has an invalid SHA-256")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["argv"] = list(self.argv)
        value["environment"] = dict(self.environment)
        return value


@dataclass(frozen=True, slots=True)
class EnergyReading:
    domain: str
    cumulative_joules: float
    monotonic_ns: int
    physical: bool
    source_kind: str
    raw: Mapping[str, Any]


class PhysicalEnergySource(Protocol):
    domain: str
    source_kind: str
    physical: bool

    def read(self) -> EnergyReading: ...
    def delta(self, before: EnergyReading, after: EnergyReading) -> float: ...


class RaplPackageSource:
    domain = "CPU_PACKAGE_RAPL"
    source_kind = "linux_powercap"
    physical = True

    def __init__(self, energy_uj: Path, max_energy_range_uj: Path) -> None:
        self.counter = RaplCounter(Path(energy_uj), max_range_path=Path(max_energy_range_uj))

    def read(self) -> EnergyReading:
        item = self.counter.sample()
        return EnergyReading(
            self.domain, item.energy_uj / 1_000_000.0, item.observed_ns, True,
            self.source_kind,
            {"energy_uj": item.energy_uj, "max_energy_range_uj": item.max_energy_range_uj, "path": item.domain},
        )

    def delta(self, before: EnergyReading, after: EnergyReading) -> float:
        first = RaplSample(
            str(before.raw["path"]), int(before.raw["energy_uj"]), before.monotonic_ns,
            int(before.raw["max_energy_range_uj"]),
        )
        second = RaplSample(
            str(after.raw["path"]), int(after.raw["energy_uj"]), after.monotonic_ns,
            int(after.raw["max_energy_range_uj"]),
        )
        return self.counter.delta(first, second).joules

    def start_window(self, *, poll_seconds: float = 0.05) -> "RaplWindowMonitor":
        return RaplWindowMonitor(self.counter, poll_seconds=poll_seconds)


class RaplWindowMonitor:
    """Accumulate adjacent RAPL deltas so multiple window wraps are observed."""

    def __init__(self, counter: RaplCounter, *, poll_seconds: float) -> None:
        if not 0.005 <= poll_seconds <= 0.5:
            raise ValueError("RAPL monitor interval outside bounds")
        self.counter = counter
        self.poll_seconds = poll_seconds
        self.samples = [counter.sample()]
        self.error: BaseException | None = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample_loop, name="casulo-rapl-readonly", daemon=True)
        self.thread.start()

    @property
    def before(self) -> EnergyReading:
        return _rapl_reading(self.samples[0], sample_count=1, rollovers=0, maximum_interval_ns=0)

    def finish(self) -> tuple[EnergyReading, float]:
        self.stop_event.set()
        self.thread.join(timeout=max(1.0, self.poll_seconds * 4))
        if self.thread.is_alive():
            raise RuntimeError("RAPL monitor did not stop")
        if self.error is not None:
            raise RuntimeError(f"RAPL monitor failed: {self.error}") from self.error
        final = self.counter.sample()
        if final.observed_ns > self.samples[-1].observed_ns:
            self.samples.append(final)
        energy_uj, rollovers, maximum_interval = accumulate_rapl_samples(tuple(self.samples))
        after = _rapl_reading(
            self.samples[-1], sample_count=len(self.samples), rollovers=rollovers,
            maximum_interval_ns=maximum_interval,
        )
        return after, energy_uj / 1_000_000.0

    def _sample_loop(self) -> None:
        try:
            while not self.stop_event.wait(self.poll_seconds):
                sample = self.counter.sample()
                if sample.observed_ns <= self.samples[-1].observed_ns:
                    raise RuntimeError("RAPL monitor timestamp did not advance")
                self.samples.append(sample)
        except BaseException as exc:
            self.error = exc
            self.stop_event.set()


def accumulate_rapl_samples(samples: tuple[RaplSample, ...]) -> tuple[int, int, int]:
    if len(samples) < 2:
        raise ValueError("RAPL window requires at least two samples")
    total_uj = 0
    rollovers = 0
    maximum_interval_ns = 0
    for left, right in zip(samples, samples[1:]):
        delta = RaplCounter.delta(left, right)
        total_uj += delta.energy_uj
        rollovers += delta.rollovers
        maximum_interval_ns = max(maximum_interval_ns, delta.elapsed_ns)
    return total_uj, rollovers, maximum_interval_ns


def _rapl_reading(sample: RaplSample, *, sample_count: int, rollovers: int, maximum_interval_ns: int) -> EnergyReading:
    return EnergyReading(
        "CPU_PACKAGE_RAPL", sample.energy_uj / 1_000_000.0, sample.observed_ns,
        True, "linux_powercap",
        {
            "energy_uj": sample.energy_uj,
            "max_energy_range_uj": sample.max_energy_range_uj,
            "path": sample.domain,
            "monitor_sample_count": sample_count,
            "observed_rollovers": rollovers,
            "maximum_sample_interval_ns": maximum_interval_ns,
        },
    )


class CallbackWallSource:
    """A validated local device API callback; never used for mock exports."""

    domain = "TOTAL_SYSTEM_WALL"
    source_kind = "physical_local_api"
    physical = True

    def __init__(self, callback: Callable[[], tuple[float, float, str]]) -> None:
        self.callback = callback

    def read(self) -> EnergyReading:
        joules, epoch_seconds, device_id = self.callback()
        if not device_id or not math.isfinite(joules) or joules < 0 or not math.isfinite(epoch_seconds):
            raise ValueError("invalid local physical meter reading")
        return EnergyReading(self.domain, joules, time.monotonic_ns(), True, self.source_kind, {"device_id": device_id, "epoch_seconds": epoch_seconds})

    def delta(self, before: EnergyReading, after: EnergyReading) -> float:
        if before.raw.get("device_id") != after.raw.get("device_id"):
            raise ValueError("wall meter identity changed")
        if after.raw.get("epoch_seconds", 0) <= before.raw.get("epoch_seconds", 0):
            raise ValueError("wall meter timestamp did not advance")
        delta = after.cumulative_joules - before.cumulative_joules
        if delta < 0:
            raise ValueError("wall meter energy regressed")
        return delta


class CampaignInterrupted(RuntimeError):
    pass


def load_commands(path: Path) -> dict[str, UnitCommand]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != COMMANDS_SCHEMA or not isinstance(value.get("commands"), list):
        raise ValueError("invalid command manifest")
    commands = {}
    for raw in value["commands"]:
        item = dict(raw)
        repository = Path(__file__).resolve().parents[4]
        item["argv"] = tuple(
            str(value).replace("{python}", __import__("sys").executable).replace("{repo}", str(repository))
            for value in item["argv"]
        )
        item["cwd"] = str(item["cwd"]).replace("{repo}", str(repository))
        if item.get("executable_sha256") is None:
            item["executable_sha256"] = sha256_file(Path(item["argv"][0]))
        command = UnitCommand(**item)
        if command.implementation in commands:
            raise ValueError("duplicate implementation command")
        commands[command.implementation] = command
    return commands


def equivalence_gate(
    commands: Mapping[str, UnitCommand],
    candidate: str,
    baseline: str,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    results = {}
    for name in (baseline, candidate):
        results[name] = _execute_unit(commands[name])
    left = results[baseline]
    right = results[candidate]
    if left["dataset_sha256"] != right["dataset_sha256"] or left["semantic_scope"] != right["semantic_scope"]:
        return {"status": "FAIL", "reason": "dataset_or_semantic_scope_mismatch", "results": results}
    a = tuple(float(item) for item in left["numeric_output"])
    b = tuple(float(item) for item in right["numeric_output"])
    if len(a) != len(b) or not a:
        return {"status": "FAIL", "reason": "numeric_output_cardinality_mismatch", "results": results}
    maximum_absolute = 0.0
    maximum_relative = 0.0
    for expected, observed in zip(a, b):
        if not math.isfinite(expected) or not math.isfinite(observed):
            return {"status": "FAIL", "reason": "nonfinite_numeric_output", "results": results}
        delta = abs(expected - observed)
        maximum_absolute = max(maximum_absolute, delta)
        maximum_relative = max(maximum_relative, delta / max(abs(expected), abs(observed), 1e-30))
    passed = maximum_absolute <= absolute_tolerance or maximum_relative <= relative_tolerance
    return {
        "status": "PASS" if passed else "FAIL",
        "reason": "within_frozen_tolerance" if passed else "outside_frozen_tolerance",
        "maximum_absolute_error": maximum_absolute,
        "maximum_relative_error": maximum_relative,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "results": results,
    }


def calibrate_k(
    command: UnitCommand,
    *,
    target_seconds: float,
    maximum_k: int = 1_000_000,
) -> dict[str, Any]:
    if not 1.0 <= target_seconds <= 120.0:
        raise ValueError("target calibration window outside bounds")
    durations = []
    for _ in range(3):
        started = time.monotonic_ns()
        _execute_unit(command)
        durations.append((time.monotonic_ns() - started) / 1_000_000_000.0)
    median = sorted(durations)[1]
    if median <= 0:
        raise ValueError("unit duration did not advance")
    k = max(1, math.ceil(target_seconds / median))
    if k > maximum_k:
        raise ValueError("calibrated K exceeds bounded maximum")
    return {
        "implementation": command.implementation,
        "warmups": 3,
        "warmup_seconds": durations,
        "median_unit_seconds": median,
        "target_window_seconds": target_seconds,
        "K": k,
        "frozen_before_campaign": True,
    }


def run_paired_campaign(
    directory: Path,
    protocol: EnergyProtocol,
    commands: Mapping[str, UnitCommand],
    energy_source: PhysicalEnergySource,
    equivalence: Mapping[str, Any],
    *,
    thermal_sampler: Callable[[], ThermalSnapshot] = probe_linux_thermal,
    battery_sampler: Callable[[], BatterySnapshot] = probe_battery,
    interrupt_after_samples: int | None = None,
) -> dict[str, Any]:
    if energy_source.domain != protocol.energy_domain or not energy_source.physical:
        raise ValueError("physical energy source differs from frozen protocol")
    if energy_source.source_kind not in {"linux_powercap", "physical_local_api"}:
        raise ValueError("simulated energy sources cannot execute a scientific campaign")
    if equivalence.get("status") != "PASS":
        raise ValueError("equivalence gate must pass before energy execution")
    if set(commands) < {protocol.candidate, protocol.baseline}:
        raise ValueError("candidate or baseline command is absent")
    if set(protocol.K) < {protocol.candidate, protocol.baseline}:
        raise ValueError("K must be frozen for both implementations")
    root = Path(directory)
    raw_dir = root / "raw"
    rejected_dir = root / "rejected"
    raw_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "samples.jsonl"
    completed = _completed_keys(raw_path)
    schedule = deterministic_schedule(protocol)
    warmup_marker = raw_dir / "warmups.json"
    if not warmup_marker.exists():
        warmups = []
        for implementation in (protocol.baseline, protocol.candidate):
            for index in range(protocol.warmups):
                started = time.monotonic_ns()
                result = _execute_unit(commands[implementation])
                warmups.append({"implementation": implementation, "index": index + 1, "elapsed_seconds": (time.monotonic_ns() - started) / 1e9, "output_sha256": result["output_sha256"]})
        _exclusive_json(warmup_marker, {"warmups": warmups, "outside_scientific_samples": True})
    written = 0
    for session in schedule["sessions"]:
        for pair in session["pairs"]:
            for order_index, implementation in enumerate(pair["order"], 1):
                key = (session["session_id"], pair["pair_id"], implementation)
                if key in completed:
                    continue
                sample = _measure_window(
                    protocol, commands[implementation], energy_source, equivalence,
                    session["session_id"], pair["pair_id"], order_index,
                    thermal_sampler, battery_sampler,
                )
                destination = raw_path if sample["accepted"] else rejected_dir / "samples.jsonl"
                _append_jsonl(destination, sample)
                written += 1
                if interrupt_after_samples is not None and written >= interrupt_after_samples:
                    raise CampaignInterrupted("campaign interrupted by registered test hook")
    return {"status": "COMPLETE", "new_samples": written, "resumed_samples": len(completed), "raw": str(raw_path)}


def _measure_window(
    protocol: EnergyProtocol,
    command: UnitCommand,
    source: PhysicalEnergySource,
    equivalence: Mapping[str, Any],
    session_id: str,
    pair_id: str,
    order_index: int,
    thermal_sampler: Callable[[], ThermalSnapshot],
    battery_sampler: Callable[[], BatterySnapshot],
) -> dict[str, Any]:
    thermal_before = thermal_sampler()
    battery_before = battery_sampler()
    frequency_before = _probe_frequency_mhz()
    rapl_monitor = source.start_window() if isinstance(source, RaplPackageSource) else None
    energy_before = rapl_monitor.before if rapl_monitor is not None else source.read()
    civil_start = datetime.now(timezone.utc).isoformat()
    started = time.monotonic_ns()
    results = []
    phases = {"initialization": 0.0, "compilation": 0.0, "warmup": 0.0, "stationary_execution": 0.0, "shutdown": 0.0}
    failure = None
    try:
        for _ in range(protocol.K[command.implementation]):
            result = _execute_unit(command)
            results.append(result)
            for key, value in result.get("phases_seconds", {}).items():
                if key in phases:
                    phases[key] += float(value)
    except Exception as exc:
        failure = f"workload_error:{type(exc).__name__}:{exc}"
    ended = time.monotonic_ns()
    civil_end = datetime.now(timezone.utc).isoformat()
    if rapl_monitor is not None:
        energy_after, delta = rapl_monitor.finish()
    else:
        energy_after = source.read()
        delta = source.delta(energy_before, energy_after)
    battery_after = battery_sampler()
    thermal_after = thermal_sampler()
    frequency_after = _probe_frequency_mhz()
    thermal = assess_thermal_window((thermal_before, thermal_after), maximum_temperature_c=protocol.maximum_temperature_c, maximum_drift_c=protocol.maximum_thermal_drift_c)
    battery = assess_battery_window(battery_before, battery_after, wall_energy_joules=delta) if source.domain == "TOTAL_SYSTEM_WALL" else None
    ac_stable = (
        battery_before.ac_connected is True
        and battery_after.ac_connected is True
        and battery_before.ac_connected == battery_after.ac_connected
    )
    accepted = failure is None and delta > 0 and thermal.accepted and ac_stable and (battery is None or battery.accepted)
    if failure:
        reason = failure
    elif delta <= 0:
        reason = "energy_counter_not_advancing"
    elif not thermal.accepted:
        reason = thermal.reason_code
    elif not ac_stable:
        reason = "ac_not_continuously_connected"
    elif battery is not None and not battery.accepted:
        reason = battery.reason_code
    else:
        reason = "accepted"
    output_hashes = {item["output_sha256"] for item in results}
    if accepted and len(output_hashes) != 1:
        accepted = False
        reason = "independent_unit_outputs_differ"
    # RAPL may wrap; scientific cumulative endpoints are normalized to a
    # monotonic local interval while raw hardware values remain in provenance.
    normalized_end = energy_before.cumulative_joules + delta
    sample = {
        "schema": SAMPLE_SCHEMA,
        "campaign_id": protocol.campaign_id,
        "session_id": session_id,
        "pair_id": pair_id,
        "order_in_pair": order_index,
        "implementation": command.implementation,
        "workload": command.workload,
        "seed": command.seed,
        "K": protocol.K[command.implementation],
        "timestamp_utc_start": civil_start,
        "timestamp_utc_end": civil_end,
        "monotonic_ns_start": started,
        "monotonic_ns_end": ended,
        "energy_domain": source.domain,
        "energy_start_joules": energy_before.cumulative_joules,
        "energy_end_joules": normalized_end,
        "energy_delta_joules": delta,
        "elapsed_seconds": (ended - started) / 1e9,
        "battery_before": battery_before.to_dict(),
        "battery_after": battery_after.to_dict(),
        "battery_assessment": battery.to_dict() if battery else None,
        "temperature": thermal.to_dict(),
        "frequency": {
            "before_mhz": frequency_before,
            "after_mhz": frequency_after,
            "status": "observed" if frequency_before is not None and frequency_after is not None else "unavailable",
        },
        "throttling": thermal.throttling_detected,
        "equivalence": dict(equivalence),
        "accepted": accepted,
        "reason_code": reason,
        "hashes": {
            "executable": command.executable_sha256,
            "tcap": command.tcap_sha256,
            "dataset": command.dataset_sha256,
            "configuration": command.configuration_sha256,
        },
        "physical_measurement": True,
        "source_provenance": {"kind": source.source_kind, "before": dict(energy_before.raw), "after": dict(energy_after.raw)},
        "phases_seconds": phases,
        "compilation_included": command.compilation_included,
        "output_sha256": next(iter(output_hashes)) if len(output_hashes) == 1 else None,
    }
    validate_sample(sample)
    return sample


def _execute_unit(command: UnitCommand) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update(command.environment)
    completed = subprocess.run(
        command.argv, cwd=command.cwd, env=environment, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=command.timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"unit exited {completed.returncode}: {completed.stderr[-1000:]}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("unit did not emit one JSON document") from exc
    if value.get("schema") != UNIT_RESULT_SCHEMA or value.get("status") != "PASS":
        raise RuntimeError("unit result failed its contract")
    if value.get("implementation") != command.implementation or value.get("dataset_sha256") != command.dataset_sha256:
        raise RuntimeError("unit identity or dataset differs from command manifest")
    if not isinstance(value.get("numeric_output"), list) or not value["numeric_output"]:
        raise RuntimeError("unit numeric output is absent")
    expected_digest = sha256_bytes(canonical_bytes(value["numeric_output"]))
    if value.get("output_sha256") != expected_digest:
        raise RuntimeError("unit output digest differs")
    return value


def _completed_keys(path: Path) -> set[tuple[str, str, str]]:
    if not Path(path).is_file():
        return set()
    completed = set()
    for sample in iter_jsonl(path):
        validate_sample(sample)
        key = (sample["session_id"], sample["pair_id"], sample["implementation"])
        if key in completed:
            raise ValueError("raw sample log already contains a duplicate")
        completed.add(key)
    return completed


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_bytes(value) + b"\n"
    with destination.open("ab") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)


def _probe_frequency_mhz() -> float | None:
    try:
        import psutil

        value = psutil.cpu_freq()
        if value is None or not math.isfinite(float(value.current)) or value.current <= 0:
            return None
        return float(value.current)
    except Exception:
        return None
