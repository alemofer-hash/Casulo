from __future__ import annotations

import math
import platform
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BatterySnapshot:
    observed_at_utc: str
    monotonic_ns: int
    present: bool
    ac_connected: bool | None
    status: str | None
    percent: float | None
    energy_now_joules: float | None
    energy_resolution_joules: float | None
    charge_now_coulombs: float | None
    charge_resolution_coulombs: float | None
    power_now_watts: float | None
    current_now_amperes: float | None
    voltage_now_volts: float | None
    source: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BatteryAssessment:
    accepted: bool
    reason_code: str
    controlled: bool
    energy_delta_joules: float | None
    allowed_delta_joules: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def probe_battery(
    *,
    power_supply_root: Path = Path("/sys/class/power_supply"),
    monotonic_ns=None,
) -> BatterySnapshot:
    import time

    clock = monotonic_ns or time.monotonic_ns
    observed = datetime.now(timezone.utc).isoformat()
    root = Path(power_supply_root)
    batteries = []
    mains = []
    if root.is_dir():
        for item in sorted(root.iterdir()):
            kind = _read(item / "type")
            if kind == "Battery":
                batteries.append(item)
            elif kind in {"Mains", "USB", "USB_C"}:
                mains.append(item)
    if batteries:
        battery = batteries[0]
        energy_uj = _read_float(battery / "energy_now")
        charge_uah = _read_float(battery / "charge_now")
        power_uw = _read_float(battery / "power_now")
        current_ua = _read_float(battery / "current_now")
        voltage_uv = _read_float(battery / "voltage_now")
        ac = any(_read(item / "online") == "1" for item in mains) if mains else None
        return BatterySnapshot(
            observed, clock(), True, ac, _read(battery / "status"),
            _read_float(battery / "capacity"),
            None if energy_uj is None else energy_uj * 0.0036,
            None if energy_uj is None else 0.0036,
            None if charge_uah is None else charge_uah * 0.0036,
            None if charge_uah is None else 0.0036,
            None if power_uw is None else power_uw / 1_000_000.0,
            None if current_ua is None else current_ua / 1_000_000.0,
            None if voltage_uv is None else voltage_uv / 1_000_000.0,
            "linux_power_supply",
        )
    if platform.system().lower() == "windows":
        try:
            import psutil

            item = psutil.sensors_battery()
        except Exception:
            item = None
        if item is not None:
            status = "Full" if item.percent >= 99.5 and item.power_plugged else (
                "Charging" if item.power_plugged else "Discharging"
            )
            return BatterySnapshot(
                observed, clock(), True, bool(item.power_plugged), status,
                float(item.percent), None, None, None, None, None, None, None,
                "windows_psutil_status_only",
            )
    return BatterySnapshot(
        observed, clock(), False, None, None, None, None, None, None, None,
        None, None, None, "unavailable",
    )


def assess_battery_window(
    before: BatterySnapshot,
    after: BatterySnapshot,
    *,
    wall_energy_joules: float,
) -> BatteryAssessment:
    if not math.isfinite(wall_energy_joules) or wall_energy_joules < 0:
        raise ValueError("wall energy must be finite and nonnegative")
    if before.present != after.present:
        return BatteryAssessment(False, "battery_presence_changed", False, None, None)
    if not before.present:
        return BatteryAssessment(False, "battery_not_observable", False, None, None)
    if before.ac_connected is not True or after.ac_connected is not True:
        return BatteryAssessment(False, "ac_not_continuously_connected", False, None, None)
    if before.status != after.status:
        return BatteryAssessment(False, "battery_status_transition", False, None, None)
    if before.status and before.status.lower() in {"charging", "discharging"}:
        return BatteryAssessment(False, f"battery_state_{before.status.lower()}", False, None, None)
    if before.energy_now_joules is None or after.energy_now_joules is None:
        return BatteryAssessment(False, "wall_uncontrolled_battery", False, None, None)
    resolution = max(
        before.energy_resolution_joules or 0.0,
        after.energy_resolution_joules or 0.0,
    )
    allowed = max(2.0 * resolution, 0.01 * wall_energy_joules)
    delta = after.energy_now_joules - before.energy_now_joules
    if abs(delta) > allowed:
        return BatteryAssessment(False, "battery_energy_delta_exceeded", True, delta, allowed)
    return BatteryAssessment(True, "battery_stable", True, delta, allowed)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError:
        return None


def _read_float(path: Path) -> float | None:
    text = _read(path)
    if text is None:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None
