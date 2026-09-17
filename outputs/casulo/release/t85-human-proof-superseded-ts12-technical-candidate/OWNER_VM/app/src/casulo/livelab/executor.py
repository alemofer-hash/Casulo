from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .campaign import PreflightReport, TrialMeasurement, sha256_output
from .energy import ExternalMeterSample, ExternalPowerMeterAdapter
from .isolation import CgroupChildPlan, CgroupV2Child


class ProcessExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessWorkload:
    argv: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str] = field(default_factory=dict)
    compile_elapsed_ns: int = 0
    phase_timings_ns: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.argv or any(not value for value in self.argv):
            raise ValueError("workload argv must be non-empty")
        if self.compile_elapsed_ns < 0:
            raise ValueError("compile time must be nonnegative")


@dataclass(frozen=True, slots=True)
class ThermalPoint:
    observed_ns: int
    temperature_c: float
    throttling_detected: bool = False


class ThermalSampler(Protocol):
    def sample(self) -> ThermalPoint: ...


class PowerSignatureSampler(Protocol):
    def sample_signature(self) -> str: ...


@dataclass(frozen=True, slots=True)
class BoundedExecutorConfig:
    cpu_affinity: tuple[int, ...]
    threads: int
    maximum_temperature_c: float
    poll_interval_seconds: float = 0.05
    startup_timeout_seconds: float = 5.0
    maximum_output_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.cpu_affinity or min(self.cpu_affinity) < 0:
            raise ValueError("at least one nonnegative CPU is required")
        if not 1 <= self.threads <= 1024:
            raise ValueError("threads outside supported bounds")
        if not 20 <= self.maximum_temperature_c <= 100:
            raise ValueError("thermal limit outside supported bounds")
        if not 0.005 <= self.poll_interval_seconds <= 1.0:
            raise ValueError("poll interval outside supported bounds")


class BoundedProcessExecutor:
    """Runs one workload below a waiting supervisor, then proves teardown.

    The supervisor waits before launching the actual command. Affinity and an
    optional cgroup transaction are therefore applied before workload code can
    execute and are inherited by its descendants.
    """

    def __init__(
        self,
        *,
        preflight_sampler: Callable[[], PreflightReport],
        thermal_sampler: ThermalSampler,
        power_sampler: PowerSignatureSampler,
        energy_adapter: ExternalPowerMeterAdapter,
        config: BoundedExecutorConfig,
        cgroup_plan_factory: Callable[[str], CgroupChildPlan] | None = None,
    ) -> None:
        self.preflight_sampler = preflight_sampler
        self.thermal_sampler = thermal_sampler
        self.power_sampler = power_sampler
        self.energy_adapter = energy_adapter
        self.config = config
        self.cgroup_plan_factory = cgroup_plan_factory
        self.live_child_pids: set[int] = set()

    def safety_check(self) -> PreflightReport:
        return self.preflight_sampler()

    def run_trial(self, label: str, workload: Callable[[], object], *, maximum_seconds: float) -> TrialMeasurement:
        spec = workload()
        if not isinstance(spec, ProcessWorkload):
            raise ProcessExecutionError("bounded executor requires ProcessWorkload")
        initial_thermal = self.thermal_sampler.sample()
        if initial_thermal.throttling_detected or initial_thermal.temperature_c > self.config.maximum_temperature_c:
            raise ProcessExecutionError("thermal gate failed before child creation")
        power_before = self.power_sampler.sample_signature()
        if not power_before:
            raise ProcessExecutionError("power signature unavailable")
        with tempfile.TemporaryDirectory(prefix="casulo-livelab-") as directory:
            control = Path(directory)
            (control / "config.json").write_text(json.dumps({
                "argv": list(spec.argv),
                "cwd": str(spec.cwd),
                "environment": {**_thread_environment(self.config.threads), **dict(spec.environment)},
                "maximum_output_bytes": self.config.maximum_output_bytes,
            }, sort_keys=True), encoding="utf-8")
            child = subprocess.Popen(
                (sys.executable, "-m", "casulo.livelab.child_runner", str(control)),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self.live_child_pids.add(child.pid)
            cgroup: CgroupV2Child | None = None
            try:
                _wait_path(control / "ready", child, self.config.startup_timeout_seconds)
                _set_affinity(child.pid, self.config.cpu_affinity)
                if self.cgroup_plan_factory is not None:
                    cgroup = CgroupV2Child(self.cgroup_plan_factory(f"{label}-{child.pid}"))
                    cgroup.apply(child.pid)
                energy_before = self.energy_adapter.read_sample()
                started_ns = time.monotonic_ns()
                (control / "start").write_text("start", encoding="ascii")
                maximum_temperature = initial_thermal.temperature_c
                failure: str | None = None
                while child.poll() is None:
                    elapsed = (time.monotonic_ns() - started_ns) / 1_000_000_000
                    point = self.thermal_sampler.sample()
                    maximum_temperature = max(maximum_temperature, point.temperature_c)
                    if point.throttling_detected or point.temperature_c > self.config.maximum_temperature_c:
                        failure = "dynamic_thermal_gate_failed"
                        break
                    if elapsed > maximum_seconds:
                        failure = "trial_timeout"
                        break
                    time.sleep(self.config.poll_interval_seconds)
                if failure is not None:
                    _terminate_tree(child)
                    raise ProcessExecutionError(failure)
                child.wait(timeout=1.0)
                ended_ns = time.monotonic_ns()
                if child.returncode != 0:
                    raise ProcessExecutionError(f"workload supervisor failed:{child.returncode}")
                result = json.loads((control / "result.json").read_text(encoding="utf-8"))
                if result["returncode"] != 0 or result["stdout_truncated"] or result["stderr_truncated"]:
                    raise ProcessExecutionError("workload failed or output exceeded bound")
                energy_after = self.energy_adapter.read_sample()
                power_after = self.power_sampler.sample_signature()
                if power_after != power_before:
                    raise ProcessExecutionError("power state changed during trial")
                energy_joules = _external_energy_delta(energy_before, energy_after)
                output = (control / "stdout.bin").read_bytes()
                return TrialMeasurement(
                    ended_ns - started_ns,
                    energy_joules,
                    maximum_temperature,
                    sha256_output(output),
                    spec.compile_elapsed_ns,
                    dict(spec.phase_timings_ns),
                    power_before,
                )
            finally:
                if child.poll() is None:
                    (control / "cancel").write_text("cancel", encoding="ascii")
                    _terminate_tree(child)
                cleanup_error: Exception | None = None
                if cgroup is not None:
                    try:
                        cgroup.cleanup()
                    except Exception as exc:
                        cleanup_error = exc
                self.live_child_pids.discard(child.pid)
                _assert_zero_descendants(child.pid)
                if cleanup_error is not None:
                    raise ProcessExecutionError(f"cgroup teardown failed: {cleanup_error}") from cleanup_error


def _thread_environment(threads: int) -> dict[str, str]:
    return {name: str(threads) for name in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS",
    )}


def _wait_path(path: Path, process: subprocess.Popen[bytes], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise ProcessExecutionError("supervisor exited before ready")
        time.sleep(0.005)
    raise ProcessExecutionError("supervisor startup timeout")


def _set_affinity(pid: int, cpus: tuple[int, ...]) -> None:
    try:
        import psutil
        process = psutil.Process(pid)
        process.cpu_affinity(list(cpus))
        if tuple(sorted(process.cpu_affinity())) != tuple(sorted(cpus)):
            raise ProcessExecutionError("CPU affinity read-back mismatch")
    except ProcessExecutionError:
        raise
    except Exception as exc:
        raise ProcessExecutionError(f"cannot apply CPU affinity: {exc}") from exc


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        import psutil
        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
        for item in descendants:
            item.terminate()
        parent.terminate()
        _, alive = psutil.wait_procs([*descendants, parent], timeout=1.0)
        for item in alive:
            item.kill()
        psutil.wait_procs(alive, timeout=1.0)
    except Exception:
        process.kill()
        process.wait(timeout=1.0)


def _assert_zero_descendants(pid: int) -> None:
    try:
        import psutil
    except ImportError as exc:
        raise ProcessExecutionError("psutil is required to prove child teardown") from exc
    try:
        if not psutil.pid_exists(pid):
            return
        process = psutil.Process(pid)
        if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
            raise ProcessExecutionError("supervisor process remained alive after teardown")
    except psutil.NoSuchProcess:
        return


def _external_energy_delta(before: ExternalMeterSample, after: ExternalMeterSample) -> float:
    if before.device_id != after.device_id or not before.device_id:
        raise ProcessExecutionError("energy meter identity changed")
    if after.observed_ns <= before.observed_ns:
        raise ProcessExecutionError("energy timestamps did not advance")
    delta = after.cumulative_joules - before.cumulative_joules
    if delta < 0:
        raise ProcessExecutionError("energy counter regressed")
    return delta
