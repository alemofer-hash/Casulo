from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class ControlStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_APPLIED = "not_applied"


@dataclass(frozen=True, slots=True)
class ControlReport:
    control: str
    status: ControlStatus
    reason_code: str
    evidence: Mapping[str, object]


class UClampController:
    """Capability interface only; applying uclamp requires a host adapter.

    The research preview deliberately does not pretend Python's process API can
    set uclamp. A future Linux adapter can implement ``apply`` behind this
    interface after a read-back check.
    """

    def probe(self, *, system: str | None = None, root: Path = Path("/")) -> ControlReport:
        current = (system or platform.system()).lower()
        if current != "linux":
            return ControlReport("uclamp", ControlStatus.UNAVAILABLE, f"unsupported_os:{current}", {})
        path = root / "proc/sys/kernel/sched_util_clamp_min"
        if not path.exists():
            return ControlReport("uclamp", ControlStatus.UNAVAILABLE, "kernel_interface_missing", {"path": str(path)})
        return ControlReport("uclamp", ControlStatus.NOT_APPLIED, "host_adapter_not_configured", {"path": str(path)})


class PerfCollector:
    def probe(self, *, system: str | None = None) -> ControlReport:
        current = (system or platform.system()).lower()
        if current != "linux":
            return ControlReport("perf", ControlStatus.UNAVAILABLE, f"unsupported_os:{current}", {})
        executable = shutil.which("perf")
        if executable is None:
            return ControlReport("perf", ControlStatus.UNAVAILABLE, "executable_missing", {})
        return ControlReport("perf", ControlStatus.NOT_APPLIED, "collector_not_started", {"executable": executable})


class SchedExtController:
    def probe(self, *, system: str | None = None, root: Path = Path("/")) -> ControlReport:
        current = (system or platform.system()).lower()
        if current != "linux":
            return ControlReport("sched_ext", ControlStatus.UNAVAILABLE, f"unsupported_os:{current}", {})
        path = root / "sys/kernel/sched_ext"
        if not path.exists():
            return ControlReport("sched_ext", ControlStatus.UNAVAILABLE, "kernel_interface_missing", {"path": str(path)})
        return ControlReport("sched_ext", ControlStatus.NOT_APPLIED, "scheduler_program_not_configured", {"path": str(path)})
