from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Mapping


class IsolationError(RuntimeError):
    """Raised when an isolation contract cannot be applied completely."""


_CHILD_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_CPU_LIST = re.compile(r"[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*\Z")
_THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


@dataclass(frozen=True, slots=True)
class CgroupChildPlan:
    parent: Path
    child_name: str
    cpus: str | None = None
    mems: str | None = None
    cpu_weight: int | None = None
    cpu_max_quota_us: int | None = None
    cpu_max_period_us: int = 100_000

    def __post_init__(self) -> None:
        if not _CHILD_NAME.fullmatch(self.child_name) or self.child_name in {".", ".."}:
            raise ValueError("invalid cgroup child name")
        if self.cpus is not None and not _CPU_LIST.fullmatch(self.cpus):
            raise ValueError("invalid cpuset CPU list")
        if self.mems is not None and not _CPU_LIST.fullmatch(self.mems):
            raise ValueError("invalid cpuset memory list")
        if self.cpu_weight is not None and not 1 <= self.cpu_weight <= 10_000:
            raise ValueError("cpu_weight must be in [1, 10000]")
        if self.cpu_max_quota_us is not None and self.cpu_max_quota_us < 1_000:
            raise ValueError("cpu quota is below the supported bound")
        if not 1_000 <= self.cpu_max_period_us <= 1_000_000:
            raise ValueError("cpu period is outside cgroup v2 bounds")

    @property
    def child(self) -> Path:
        return self.parent / self.child_name

    def settings(self) -> tuple[tuple[str, str], ...]:
        values: list[tuple[str, str]] = []
        if self.mems is not None:
            values.append(("cpuset.mems", self.mems))
        if self.cpus is not None:
            values.append(("cpuset.cpus", self.cpus))
        if self.cpu_weight is not None:
            values.append(("cpu.weight", str(self.cpu_weight)))
        if self.cpu_max_quota_us is not None:
            values.append(("cpu.max", f"{self.cpu_max_quota_us} {self.cpu_max_period_us}"))
        return tuple(values)


class CgroupV2Child:
    """Own one cgroup v2 child and clean it up transactionally.

    Only the exact child in the immutable plan is ever created or removed. A
    failure during setup triggers best-effort rollback and is never downgraded
    to a successful unisolated run.
    """

    def __init__(self, plan: CgroupChildPlan) -> None:
        self.plan = plan
        self._created = False
        self._attached_pid: int | None = None

    def apply(self, pid: int) -> Path:
        if pid <= 0:
            raise ValueError("pid must be positive")
        _validate_cgroup_parent(self.plan)
        if self.plan.child.exists():
            raise IsolationError(f"cgroup child already exists: {self.plan.child}")
        try:
            self.plan.child.mkdir()
            self._created = True
            for name, value in self.plan.settings():
                _write_control(self.plan.child / name, value)
            _write_control(self.plan.child / "cgroup.procs", str(pid))
            self._attached_pid = pid
            return self.plan.child
        except Exception as exc:
            try:
                self.cleanup()
            except IsolationError:
                pass
            if isinstance(exc, IsolationError):
                raise
            raise IsolationError(f"failed to apply cgroup child: {exc}") from exc

    def cleanup(self) -> None:
        if not self._created:
            return
        errors: list[str] = []
        if self._attached_pid is not None:
            try:
                if not _looks_like_cgroupfs(self.plan.parent) or Path(f"/proc/{self._attached_pid}").exists():
                    _write_control(self.plan.parent / "cgroup.procs", str(self._attached_pid))
            except IsolationError as exc:
                errors.append(str(exc))
        # Fake sysfs tests use ordinary files; real cgroupfs exposes virtual
        # control files which disappear with rmdir and must not be unlinked.
        if not _looks_like_cgroupfs(self.plan.parent):
            for name, _ in reversed(self.plan.settings()):
                (self.plan.child / name).unlink(missing_ok=True)
            (self.plan.child / "cgroup.procs").unlink(missing_ok=True)
        try:
            self.plan.child.rmdir()
            self._created = False
            self._attached_pid = None
        except OSError as exc:
            errors.append(f"cannot remove cgroup child {self.plan.child}: {exc}")
        if errors:
            raise IsolationError("; ".join(errors))

    def __enter__(self) -> CgroupV2Child:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.cleanup()


@dataclass(frozen=True, slots=True)
class ThreadSeal:
    threads: int
    environment: Mapping[str, str]
    torch_threads: int | None
    torch_interop_threads: int | None


def seal_threads(
    threads: int,
    *,
    environ: dict[str, str] | None = None,
    torch_module: object | None = None,
) -> ThreadSeal:
    """Seal common CPU thread pools and verify the observable settings.

    Call this before importing numerical libraries. When a torch module is
    supplied, LiveLab also applies and reads back its intra-op setting. An
    inter-op setting that can no longer be changed fails closed.
    """

    if not 1 <= threads <= 1024:
        raise ValueError("threads outside supported bounds")
    target = environ if environ is not None else os.environ
    value = str(threads)
    for name in _THREAD_ENV:
        target[name] = value
    torch_threads: int | None = None
    torch_interop: int | None = None
    if torch_module is not None:
        try:
            torch_module.set_num_threads(threads)
            torch_threads = int(torch_module.get_num_threads())
            if torch_threads != threads:
                raise IsolationError("PyTorch intra-op thread seal did not hold")
            torch_module.set_num_interop_threads(threads)
            torch_interop = int(torch_module.get_num_interop_threads())
            if torch_interop != threads:
                raise IsolationError("PyTorch inter-op thread seal did not hold")
        except IsolationError:
            raise
        except Exception as exc:
            raise IsolationError(f"cannot seal PyTorch thread pools: {exc}") from exc
    return ThreadSeal(threads, {name: target[name] for name in _THREAD_ENV}, torch_threads, torch_interop)


def _validate_cgroup_parent(plan: CgroupChildPlan) -> None:
    controllers_path = plan.parent / "cgroup.controllers"
    if not controllers_path.is_file():
        raise IsolationError("cgroup v2 controllers file is missing")
    controllers = set(controllers_path.read_text(encoding="ascii").split())
    required: set[str] = set()
    if plan.cpus is not None or plan.mems is not None:
        required.add("cpuset")
    if plan.cpu_weight is not None or plan.cpu_max_quota_us is not None:
        required.add("cpu")
    missing = sorted(required - controllers)
    if missing:
        raise IsolationError("missing cgroup controllers: " + ", ".join(missing))
    subtree = plan.parent / "cgroup.subtree_control"
    if required and subtree.is_file():
        enabled = {item.lstrip("+") for item in subtree.read_text(encoding="ascii").split()}
        absent = sorted(required - enabled)
        if absent:
            raise IsolationError("controllers not delegated to children: " + ", ".join(absent))


def _write_control(path: Path, value: str) -> None:
    try:
        path.write_text(value + "\n", encoding="ascii")
    except OSError as exc:
        raise IsolationError(f"cannot write cgroup control {path}: {exc}") from exc


def _looks_like_cgroupfs(parent: Path) -> bool:
    try:
        return str(parent.resolve()).startswith("/sys/fs/cgroup")
    except OSError:
        return False
