from __future__ import annotations

from pathlib import Path

from casulo.livelab.capabilities import CapabilityStatus, probe_capabilities
from casulo.livelab.energy import ExternalMeterValidation


def test_windows_never_claims_linux_controls() -> None:
    reports = probe_capabilities(system="Windows")
    for name in ("cgroups_v2", "cgroup_cpuset", "cpu_weight", "cpu_max", "uclamp", "rapl_powercap", "perf_events", "sched_ext"):
        assert reports[name].status is CapabilityStatus.UNAVAILABLE
        assert reports[name].value is None


def test_fake_linux_sysfs_distinguishes_support_from_permission(tmp_path: Path) -> None:
    controllers = tmp_path / "sys/fs/cgroup/cgroup.controllers"
    controllers.parent.mkdir(parents=True)
    controllers.write_text("cpu cpuset\n", encoding="utf-8")
    reports = probe_capabilities(system="Linux", root=tmp_path)
    assert reports["cgroups_v2"].status is CapabilityStatus.AVAILABLE
    assert reports["rapl_powercap"].value is None


def test_unavailable_values_are_null() -> None:
    reports = probe_capabilities(system="Windows")
    assert all(item.value is None for item in reports.values() if item.status is not CapabilityStatus.AVAILABLE)


def test_external_meter_is_available_only_after_validation() -> None:
    validated = ExternalMeterValidation(True, "validated_advancing_counter", 3, 2, 1.5)
    report = probe_capabilities(system="Windows", external_meter_validation=validated)["external_power_meter"]
    assert report.status is CapabilityStatus.AVAILABLE
    assert report.value["sample_count"] == 3
    rejected = ExternalMeterValidation(False, "energy_counter_not_advancing", 3, 0, None)
    report = probe_capabilities(system="Windows", external_meter_validation=rejected)["external_power_meter"]
    assert report.status is CapabilityStatus.ERROR
    assert report.value is None
