from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .battery_guard import probe_battery
from .rapl import discover_rapl_zones, validate_rapl_zones
from .schemas import CAPABILITIES_SCHEMA, ENVIRONMENT_SCHEMA
from .thermal_guard import assess_thermal_window, probe_linux_thermal
from .wall_meter import fetch_local_api, import_meter_file, validate_meter_samples


def build_environment_report(*, root: Path = Path("/"), system: str | None = None) -> dict[str, Any]:
    current = (system or platform.system()).lower()
    report: dict[str, Any] = {
        "schema": ENVIRONMENT_SCHEMA,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution": {
            "python": sys.version,
            "executable": sys.executable,
            "cwd": str(Path.cwd()),
            "process_affinity": _affinity(),
            "threads_environment": {
                name: os.environ.get(name)
                for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
            },
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "kernel": platform.uname().release,
        },
        "host": {
            "execution_class": "unknown",
            "manufacturer": None,
            "model": None,
            "firmware": None,
            "microcode": None,
            "cpu": platform.processor() or None,
            "physical_cores": None,
            "logical_cpus": os.cpu_count(),
            "hypervisor_present": None,
        },
        "power_policy": {"governor": None, "profile": None},
        "frequency": {"current_mhz": None, "maximum_mhz": None, "source": "unavailable"},
        "tooling": {
            "perf": shutil.which("perf"),
            "systemd_detect_virt": shutil.which("systemd-detect-virt"),
        },
    }
    if current == "windows":
        _augment_windows(report)
    elif current == "linux":
        _augment_linux(report, Path(root))
    battery = probe_battery(power_supply_root=Path(root) / "sys/class/power_supply" if Path(root) != Path("/") else Path("/sys/class/power_supply"))
    report["battery"] = battery.to_dict()
    return report


def preflight_energy(
    *,
    root: Path = Path("/"),
    system: str | None = None,
    wall_meter_path: Path | None = None,
    wall_meter_url: str | None = None,
    thermal_limit_c: float = 55.0,
) -> dict[str, Any]:
    current = (system or platform.system()).lower()
    environment = build_environment_report(root=root, system=current)
    zones = discover_rapl_zones(Path(root) / "sys/class/powercap" if Path(root) != Path("/") else Path("/sys/class/powercap")) if current == "linux" else ()
    thermal_samples = ()
    thermal = None
    if current == "linux":
        thermal_root = Path(root) / "sys/class/thermal" if Path(root) != Path("/") else Path("/sys/class/thermal")
        cpu_root = Path(root) / "sys/devices/system/cpu" if Path(root) != Path("/") else Path("/sys/devices/system/cpu")
        first = probe_linux_thermal(thermal_root=thermal_root, cpu_root=cpu_root)
        import time

        time.sleep(0.02)
        second = probe_linux_thermal(thermal_root=thermal_root, cpu_root=cpu_root)
        thermal_samples = (first, second)
        thermal = assess_thermal_window(thermal_samples, maximum_temperature_c=thermal_limit_c)
    rapl = []
    if current == "linux" and thermal is not None and thermal.accepted:
        rapl = [item.to_dict() for item in validate_rapl_zones(zones)]
    elif current == "linux":
        rapl = [{
            "valid": False,
            "reason_code": "thermal_guard_unavailable_before_controlled_rapl_load",
            "domain": None,
            "zone_id": None,
            "samples": [],
            "delta_uj": None,
            "rollovers": None,
            "controlled_load_iterations": 0,
            "physical": False,
        }]
    else:
        rapl = [{
            "valid": False,
            "reason_code": f"rapl_powercap_unsupported_os:{current}",
            "domain": None,
            "zone_id": None,
            "samples": [],
            "delta_uj": None,
            "rollovers": None,
            "controlled_load_iterations": 0,
            "physical": False,
        }]
    meter_validation = None
    meter_error = None
    if wall_meter_path is not None and wall_meter_url is not None:
        raise ValueError("configure either a meter export or a local API, not both")
    if wall_meter_path is not None:
        try:
            meter_validation = validate_meter_samples(import_meter_file(wall_meter_path))
        except Exception as exc:
            meter_error = f"{type(exc).__name__}:{exc}"
    elif wall_meter_url is not None:
        try:
            meter_validation = validate_meter_samples(fetch_local_api(wall_meter_url))
        except Exception as exc:
            meter_error = f"{type(exc).__name__}:{exc}"
    battery = environment["battery"]
    battery_observable = battery.get("energy_now_joules") is not None and battery.get("energy_resolution_joules") is not None
    rapl_ready = any(item["valid"] and item["domain"] == "CPU_PACKAGE_RAPL" for item in rapl)
    wall_ready = bool(meter_validation and meter_validation.valid and battery_observable and battery.get("ac_connected") is True)
    reasons = []
    if not rapl_ready:
        reasons.append("CPU_PACKAGE_RAPL_UNAVAILABLE")
    if not wall_ready:
        if meter_validation is None:
            reasons.append("TOTAL_SYSTEM_WALL_METER_NOT_CONFIGURED")
        elif not meter_validation.valid:
            reasons.append(f"TOTAL_SYSTEM_WALL_METER_INVALID:{meter_validation.reason_code}")
        elif not battery_observable:
            reasons.append("WALL_UNCONTROLLED_BATTERY")
        else:
            reasons.append("TOTAL_SYSTEM_WALL_NOT_READY")
    physical_domains = []
    if rapl_ready:
        physical_domains.append("CPU_PACKAGE_RAPL")
    if wall_ready:
        physical_domains.append("TOTAL_SYSTEM_WALL")
    return {
        "schema": CAPABILITIES_SCHEMA,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": environment,
        "rapl": {
            "zones": [zone.to_dict() for zone in zones],
            "validations": rapl,
            "hierarchical_zones_never_summed": True,
        },
        "wall_meter": {
            "configured": wall_meter_path is not None or wall_meter_url is not None,
            "path": str(Path(wall_meter_path).resolve()) if wall_meter_path else None,
            "url": wall_meter_url,
            "validation": meter_validation.to_dict() if meter_validation else None,
            "error": meter_error,
        },
        "battery": battery,
        "thermal": {
            "samples": [item.to_dict() for item in thermal_samples],
            "assessment": thermal.to_dict() if thermal else {
                "accepted": False,
                "reason_code": "trusted_thermal_stream_unavailable",
                "maximum_c": None,
                "drift_c": None,
                "throttling_detected": None,
            },
        },
        "sources": {
            "CPU_PACKAGE_RAPL": "ready" if rapl_ready else "unavailable",
            "TOTAL_SYSTEM_WALL": "ready" if wall_ready else "unavailable",
            "BATTERY_DELTA": "observable" if battery_observable else "unavailable",
            "LOGICAL_TELEMETRY": "not_energy",
        },
        "ready": bool(physical_domains),
        "physical_domains": physical_domains,
        "reason_codes": reasons,
        "writes_performed": False,
        "controlled_workload_started": any(item.get("controlled_load_iterations", 0) > 0 for item in rapl),
    }


def _affinity() -> list[int] | None:
    try:
        if hasattr(os, "sched_getaffinity"):
            return sorted(os.sched_getaffinity(0))
        import psutil

        return sorted(psutil.Process().cpu_affinity())
    except Exception:
        return None


def _augment_windows(report: dict[str, Any]) -> None:
    script = r"""
$ErrorActionPreference='Stop'
$cs=Get-CimInstance Win32_ComputerSystem
$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1
$bios=Get-CimInstance Win32_BIOS
$product=Get-CimInstance Win32_ComputerSystemProduct
$reg=Get-ItemProperty -LiteralPath 'Registry::HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\CentralProcessor\0'
$scheme=(powercfg /GETACTIVESCHEME) -join ' '
[PSCustomObject]@{
 manufacturer=$cs.Manufacturer; model=$product.Name; version=$product.Version
 hypervisor_present=[bool]$cs.HypervisorPresent; cpu=$cpu.Name
 physical_cores=[int]$cpu.NumberOfCores; logical_cpus=[int]$cpu.NumberOfLogicalProcessors
 maximum_mhz=[double]$cpu.MaxClockSpeed; current_mhz=[double]$cpu.CurrentClockSpeed
 firmware=($bios.SMBIOSBIOSVersion -join ','); microcode=([BitConverter]::ToString($reg.'Update Revision'))
 power_profile=$scheme
} | ConvertTo-Json -Compress
"""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=10, check=False,
        )
        value = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except Exception:
        value = {}
    virtual_tokens = ("virtual", "vmware", "qemu", "kvm", "hyper-v")
    identity = f"{value.get('manufacturer', '')} {value.get('model', '')}".lower()
    virtual_machine = any(token in identity for token in virtual_tokens)
    report["host"].update({
        "execution_class": "virtual_machine" if virtual_machine else "bare_metal_with_hypervisor_enabled" if value.get("hypervisor_present") else "bare_metal",
        "manufacturer": value.get("manufacturer"), "model": value.get("model"),
        "firmware": value.get("firmware"), "microcode": value.get("microcode"),
        "cpu": value.get("cpu"), "physical_cores": value.get("physical_cores"),
        "logical_cpus": value.get("logical_cpus"), "hypervisor_present": value.get("hypervisor_present"),
    })
    report["frequency"] = {"current_mhz": value.get("current_mhz"), "maximum_mhz": value.get("maximum_mhz"), "source": "Win32_Processor"}
    report["power_policy"] = {"governor": None, "profile": value.get("power_profile")}


def _augment_linux(report: dict[str, Any], root: Path) -> None:
    proc_cpuinfo = root / "proc/cpuinfo" if root != Path("/") else Path("/proc/cpuinfo")
    dmi = root / "sys/class/dmi/id" if root != Path("/") else Path("/sys/class/dmi/id")
    report["host"].update({
        "manufacturer": _read(dmi / "sys_vendor"), "model": _read(dmi / "product_name"),
        "firmware": _read(dmi / "bios_version"), "microcode": _cpuinfo_field(proc_cpuinfo, "microcode"),
        "cpu": _cpuinfo_field(proc_cpuinfo, "model name"), "physical_cores": _physical_cores_linux(proc_cpuinfo),
        "execution_class": _linux_execution_class(), "hypervisor_present": "hypervisor" in (_read(proc_cpuinfo) or ""),
    })
    governors = []
    for path in sorted((root / "sys/devices/system/cpu" if root != Path("/") else Path("/sys/devices/system/cpu")).glob("cpu*/cpufreq/scaling_governor")):
        value = _read(path)
        if value:
            governors.append(value)
    report["power_policy"] = {"governor": sorted(set(governors)) or None, "profile": None}


def _linux_execution_class() -> str:
    executable = shutil.which("systemd-detect-virt")
    if not executable:
        return "unknown"
    completed = subprocess.run([executable], capture_output=True, text=True, timeout=2, check=False)
    return "bare_metal" if completed.stdout.strip() == "none" else f"virtual:{completed.stdout.strip()}"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _cpuinfo_field(path: Path, key: str) -> str | None:
    text = _read(path)
    if text is None:
        return None
    for line in text.splitlines():
        left, separator, right = line.partition(":")
        if separator and left.strip() == key:
            return right.strip()
    return None


def _physical_cores_linux(path: Path) -> int | None:
    text = _read(path)
    if text is None:
        return None
    current: dict[str, str] = {}
    cores = set()
    for line in [*text.splitlines(), ""]:
        if not line.strip():
            if "physical id" in current and "core id" in current:
                cores.add((current["physical id"], current["core id"]))
            current = {}
            continue
        left, separator, right = line.partition(":")
        if separator:
            current[left.strip()] = right.strip()
    return len(cores) or None
