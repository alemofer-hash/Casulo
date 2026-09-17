from __future__ import annotations

import glob
import os
import platform
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from .energy import ExternalMeterValidation


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    BLOCKED_PERMISSION = "blocked_permission"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Capability:
    id: str
    status: CapabilityStatus
    value: Any
    reason_code: str
    observed_at_utc: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is not CapabilityStatus.AVAILABLE and self.value is not None:
            raise ValueError("unavailable capability values must be null")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["evidence"] = list(self.evidence)
        return result


def probe_capabilities(
    *,
    system: str | None = None,
    root: Path = Path("/"),
    external_meter_validation: ExternalMeterValidation | None = None,
) -> dict[str, Capability]:
    observed = datetime.now(timezone.utc).isoformat()
    current = (system or platform.system()).lower()
    reports: dict[str, Capability] = {}

    affinity = hasattr(os, "sched_getaffinity") or _psutil_affinity_available()
    reports["process_affinity"] = _cap(
        "process_affinity", affinity, True if affinity else None,
        "probe_supported" if affinity else f"unsupported_os:{current}", observed,
    )
    reports["thread_environment"] = _cap(
        "thread_environment", True, True, "environment_contract", observed,
        ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"),
    )

    linux_only = ("cgroups_v2", "cgroup_cpuset", "cpu_weight", "cpu_max", "uclamp", "rapl_powercap", "perf_events", "sched_ext")
    if current != "linux":
        for name in linux_only:
            reports[name] = Capability(name, CapabilityStatus.UNAVAILABLE, None, f"unsupported_os:{current}", observed)
    else:
        cgroup = root / "sys/fs/cgroup"
        controllers = cgroup / "cgroup.controllers"
        delegated = controllers.is_file() and os.access(cgroup, os.W_OK)
        reports["cgroups_v2"] = _path_cap("cgroups_v2", controllers, observed)
        for name, controller in (("cgroup_cpuset", "cpuset"), ("cpu_weight", "cpu"), ("cpu_max", "cpu")):
            reports[name] = _controller_cap(name, controllers, controller, delegated, observed)
        reports["uclamp"] = _path_cap("uclamp", root / "proc/sys/kernel/sched_util_clamp_min", observed)
        rapl_paths = tuple(glob.glob(str(root / "sys/class/powercap/intel-rapl*/energy_uj")))
        reports["rapl_powercap"] = _list_cap("rapl_powercap", rapl_paths, observed)
        perf = shutil.which("perf")
        reports["perf_events"] = _cap("perf_events", perf is not None, perf, "executable_found" if perf else "missing_executable", observed)
        reports["sched_ext"] = _path_cap("sched_ext", root / "sys/kernel/sched_ext", observed)

    if external_meter_validation is None:
        reports["external_power_meter"] = Capability(
            "external_power_meter", CapabilityStatus.UNAVAILABLE, None, "adapter_not_configured", observed
        )
    elif external_meter_validation.valid:
        reports["external_power_meter"] = Capability(
            "external_power_meter",
            CapabilityStatus.AVAILABLE,
            {
                "validation": external_meter_validation.reason_code,
                "sample_count": external_meter_validation.sample_count,
                "advancing_intervals": external_meter_validation.advancing_intervals,
            },
            "validated_external_meter",
            observed,
        )
    else:
        reports["external_power_meter"] = Capability(
            "external_power_meter",
            CapabilityStatus.ERROR,
            None,
            external_meter_validation.reason_code,
            observed,
        )
    reports["trusted_thermal_stream"] = Capability(
        "trusted_thermal_stream", CapabilityStatus.UNAVAILABLE, None, "advancing_sensor_not_configured", observed
    )
    return reports


def _cap(identifier: str, available: bool, value: Any, reason: str, observed: str, evidence: tuple[str, ...] = ()) -> Capability:
    return Capability(identifier, CapabilityStatus.AVAILABLE if available else CapabilityStatus.UNAVAILABLE, value if available else None, reason, observed, evidence)


def _path_cap(identifier: str, path: Path, observed: str) -> Capability:
    exists = path.exists()
    return _cap(identifier, exists, str(path) if exists else None, "path_found" if exists else "path_missing", observed, (str(path),))


def _list_cap(identifier: str, paths: tuple[str, ...], observed: str) -> Capability:
    return _cap(identifier, bool(paths), list(paths) if paths else None, "paths_found" if paths else "paths_missing", observed, paths)


def _controller_cap(identifier: str, controllers: Path, required: str, delegated: bool, observed: str) -> Capability:
    if not controllers.is_file():
        return Capability(identifier, CapabilityStatus.UNAVAILABLE, None, "cgroups_v2_missing", observed)
    available = required in controllers.read_text(encoding="utf-8").split()
    if not available:
        return Capability(identifier, CapabilityStatus.UNAVAILABLE, None, f"controller_missing:{required}", observed)
    if not delegated:
        return Capability(identifier, CapabilityStatus.BLOCKED_PERMISSION, None, "cgroup_not_delegated", observed, (str(controllers),))
    return Capability(identifier, CapabilityStatus.AVAILABLE, {"controller": required}, "controller_delegated", observed, (str(controllers),))


def _psutil_affinity_available() -> bool:
    try:
        import psutil

        return hasattr(psutil.Process(), "cpu_affinity")
    except Exception:
        return False
