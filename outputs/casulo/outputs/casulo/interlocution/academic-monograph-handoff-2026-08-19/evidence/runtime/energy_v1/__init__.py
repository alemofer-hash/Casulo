"""Casulo LiveLab Energy Protocol v1.

This package is deliberately separate from the legacy ``energy.py`` adapter.
It adds scientific provenance, physical-source capability checks, battery and
thermal guards, resumable paired campaigns, and confirmatory analysis without
changing the frozen T compiler/TCAP source tree.
"""

from .analysis import analyze_campaign, paired_bootstrap_ci, exact_sign_test
from .battery_guard import BatterySnapshot, assess_battery_window, probe_battery
from .capabilities import build_environment_report, preflight_energy
from .protocol import EnergyProtocol, freeze_protocol, load_protocol
from .rapl import RaplZone, discover_rapl_zones, validate_rapl_zones
from .wall_meter import import_meter_file, validate_meter_samples
from .hwinfo import inspect_file as inspect_hwinfo_file, integrate_window as integrate_hwinfo_window, watch_file as watch_hwinfo_file

__all__ = [
    "BatterySnapshot",
    "EnergyProtocol",
    "RaplZone",
    "analyze_campaign",
    "assess_battery_window",
    "build_environment_report",
    "discover_rapl_zones",
    "exact_sign_test",
    "freeze_protocol",
    "import_meter_file",
    "inspect_hwinfo_file",
    "integrate_hwinfo_window",
    "load_protocol",
    "paired_bootstrap_ci",
    "preflight_energy",
    "probe_battery",
    "validate_meter_samples",
    "validate_rapl_zones",
    "watch_hwinfo_file",
]
