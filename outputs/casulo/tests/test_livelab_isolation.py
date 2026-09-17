from __future__ import annotations

from pathlib import Path

import pytest

from casulo.livelab.isolation import (
    CgroupChildPlan,
    CgroupV2Child,
    IsolationError,
    seal_threads,
)


def _fake_cgroup(tmp_path: Path, controllers: str = "cpu cpuset") -> Path:
    parent = tmp_path / "cgroup"
    parent.mkdir()
    (parent / "cgroup.controllers").write_text(controllers + "\n", encoding="ascii")
    (parent / "cgroup.subtree_control").write_text("cpu cpuset\n", encoding="ascii")
    (parent / "cgroup.procs").write_text("\n", encoding="ascii")
    return parent


def test_cgroup_child_applies_controls_attaches_and_cleans_up(tmp_path: Path) -> None:
    parent = _fake_cgroup(tmp_path)
    plan = CgroupChildPlan(
        parent,
        "casulo-run-1",
        cpus="0-1",
        mems="0",
        cpu_weight=200,
        cpu_max_quota_us=50_000,
    )
    child = CgroupV2Child(plan)
    location = child.apply(4242)
    assert (location / "cpuset.cpus").read_text(encoding="ascii").strip() == "0-1"
    assert (location / "cpuset.mems").read_text(encoding="ascii").strip() == "0"
    assert (location / "cpu.weight").read_text(encoding="ascii").strip() == "200"
    assert (location / "cpu.max").read_text(encoding="ascii").strip() == "50000 100000"
    assert (location / "cgroup.procs").read_text(encoding="ascii").strip() == "4242"
    child.cleanup()
    assert not location.exists()
    assert (parent / "cgroup.procs").read_text(encoding="ascii").strip() == "4242"


def test_cgroup_setup_fails_closed_and_rolls_back(tmp_path: Path) -> None:
    parent = _fake_cgroup(tmp_path, controllers="cpuset")
    plan = CgroupChildPlan(parent, "run", cpu_weight=100)
    with pytest.raises(IsolationError, match="missing cgroup controllers"):
        CgroupV2Child(plan).apply(1)
    assert not plan.child.exists()


def test_cgroup_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="child name"):
        CgroupChildPlan(Path("/sys/fs/cgroup"), "../escape")


class _FakeTorch:
    def __init__(self) -> None:
        self.intra = 8
        self.inter = 8

    def set_num_threads(self, value: int) -> None:
        self.intra = value

    def get_num_threads(self) -> int:
        return self.intra

    def set_num_interop_threads(self, value: int) -> None:
        self.inter = value

    def get_num_interop_threads(self) -> int:
        return self.inter


def test_thread_seal_sets_environment_and_verifies_torch() -> None:
    environment: dict[str, str] = {"OMP_NUM_THREADS": "99"}
    torch = _FakeTorch()
    seal = seal_threads(2, environ=environment, torch_module=torch)
    assert set(seal.environment.values()) == {"2"}
    assert seal.torch_threads == 2
    assert seal.torch_interop_threads == 2
