"""Fail-closed physical host qualification with no benchmark workload."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from casulo.livelab.energy_v1.hwinfo import (
    _is_header,
    _normalize,
    _parse_timestamp,
    inspect_file,
)
from casulo.livelab.energy_v1.hwinfo_campaign import (
    HWiNFOIncrementalWatcher,
    _truthy,
    incremental_guard,
)

DEFAULT_OUTPUT = ROOT / "outputs/casulo/preflight/2026-08-09-energy-host-qualification"
SEARCH_ROOTS = (ROOT / "benchmarks/results", ROOT / "outputs/casulo")
POLLING_MINIMUM_NEW_ROWS = 60
IDLE_SECONDS = 1200.0
POLLING_TIMEOUT_SECONDS = 45.0
OBSERVER_CPU_ONE_CORE_LIMIT = 2.0
OBSERVER_MAXIMUM_CHUNK_BYTES = 1024 * 1024


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def number(value: str) -> float | None:
    try:
        result = float(value.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None
    return result if math.isfinite(result) else None


def run_capture(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def discover_csvs() -> tuple[list[dict[str, Any]], list[Path]]:
    paths: set[Path] = set()
    for root in SEARCH_ROOTS:
        if root.is_dir():
            paths.update(path.resolve() for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".csv")
    initial = {
        path: {"size": path.stat().st_size, "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)}
        for path in sorted(paths)
    }
    time.sleep(3.0)
    now = utc_now()
    records = []
    active = []
    for path, before in initial.items():
        stat = path.stat()
        growth = stat.st_size - before["size"]
        age = (now - datetime.fromtimestamp(stat.st_mtime, timezone.utc)).total_seconds()
        is_active = growth > 0 and age <= 10.0
        if is_active:
            active.append(path)
        records.append(
            {
                "path": str(path),
                "size_initial": before["size"],
                "size_final": stat.st_size,
                "growth_bytes_3s": growth,
                "mtime_initial_utc": before["mtime_utc"].isoformat(),
                "mtime_final_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "mtime_age_seconds": age,
                "active": is_active,
            }
        )
    return records, active


def parse_appended_rows(
    path: Path,
    *,
    start_offset: int,
    end_offset: int,
    header: tuple[str, ...],
    encoding: str,
    delimiter: str,
) -> tuple[list[dict[str, Any]], bytes, bool]:
    with path.open("rb") as stream:
        stream.seek(start_offset)
        raw = stream.read(max(0, end_offset - start_offset))
    complete = raw
    incomplete_ignored = False
    if raw and not raw.endswith((b"\n", b"\r")):
        split = raw.splitlines(keepends=True)
        if split and not split[-1].endswith((b"\n", b"\r")):
            complete = b"".join(split[:-1])
            incomplete_ignored = True
    codec = encoding.removesuffix("-sig")
    text = complete.decode(codec, errors="strict")
    timezone_local = datetime.now().astimezone().tzinfo
    if timezone_local is None:
        raise RuntimeError("local timezone unavailable")
    current_header = header
    rows = []
    for values in csv.reader(io.StringIO(text), delimiter=delimiter):
        if not values or not any(item.strip() for item in values):
            continue
        if _is_header(values):
            current_header = tuple(values)
            continue
        if len(values) < len(current_header):
            continue
        try:
            stamp = _parse_timestamp(values[0], values[1], timezone_local).astimezone(timezone.utc)
        except (ValueError, IndexError):
            continue
        rows.append({"timestamp_utc": stamp, "values": tuple(values[: len(current_header)])})
    return rows, complete, incomplete_ignored


def sampling(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stamps = [item["timestamp_utc"] for item in rows]
    intervals = [(right - left).total_seconds() for left, right in zip(stamps, stamps[1:])]
    median = statistics.median(intervals) if intervals else None
    return {
        "new_samples": len(rows),
        "strictly_increasing_timestamps": all(value > 0 for value in intervals),
        "minimum_seconds": min(intervals) if intervals else None,
        "median_seconds": median,
        "p95_seconds": percentile(intervals, 0.95),
        "maximum_seconds": max(intervals) if intervals else None,
        "gaps_over_5x_median": [value for value in intervals if median and value > 5 * median],
        "first_timestamp_utc": stamps[0].isoformat() if stamps else None,
        "last_timestamp_utc": stamps[-1].isoformat() if stamps else None,
    }


def sensor_map(header: tuple[str, ...], energy_index: int) -> dict[str, Any]:
    normalized = [_normalize(item) for item in header]

    def first(predicate) -> int | None:
        return next((index for index, value in enumerate(normalized) if predicate(value)), None)

    throttle = [
        index
        for index, value in enumerate(normalized)
        if ("estrangulamento termico" in value or "thermal throttling" in value)
        and "maximum" not in value
        and "maximo" not in value
    ]
    power_limit = [
        index
        for index, value in enumerate(normalized)
        if ("limite de potencia" in value or "power limit" in value)
        and ("yes no" in value or value.endswith("yes no"))
        and "maximum" not in value
        and "maximo" not in value
    ]
    package_temperatures = [
        index for index, value in enumerate(normalized) if value == "cpu inteira c"
    ]
    indices = {
        "package_power": energy_index,
        "core_temperature": first(lambda value: "temperaturas centrais" in value and value.endswith("c")),
        "package_temperatures": package_temperatures,
        # HWiNFO exposes both actual busy time ("Total CPU Usage" / "Uso total
        # da CPU") and clock-weighted "Total CPU Utility".  Quiescence is a
        # utilization gate, so it must use the former.  Keep utility only as a
        # diagnostic and never substitute it for occupancy.
        "total_cpu_usage": first(lambda value: value in {"uso total da cpu", "total cpu usage"}),
        "total_cpu_utility": first(lambda value: value in {"utilizacao total da cpu", "total cpu utility"}),
        "effective_clock": first(lambda value: "relogios efetivos nucleo" in value and "mhz" in value),
        "battery_level": first(lambda value: value == "nivel de carga"),
        "battery_rate": first(lambda value: value.startswith("taxa de carga") and value.endswith("w")),
        "thermal_throttling": throttle,
        "power_limit": power_limit,
    }
    literal = {
        key: ([header[index] for index in value] if isinstance(value, list) else (header[value] if value is not None else None))
        for key, value in indices.items()
    }
    return {"indices": indices, "literal_names": literal}


def values_for(rows: list[dict[str, Any]], index: int | None) -> list[float]:
    if index is None:
        return []
    values = [number(row["values"][index]) for row in rows]
    return [value for value in values if value is not None]


def process_inventory() -> tuple[dict[str, Any], dict[str, Any]]:
    own = os.getpid()
    processes = list(psutil.process_iter())
    for process in processes:
        try:
            process.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(2.0)
    rows = []
    orphans = []
    project_markers = (
        "run_full_worker_energy.py",
        "run_definitive_idle_controls.py",
        "run_energy_host_qualification.py",
        "qemu-system",
    )
    for process in processes:
        if process.pid == own:
            continue
        try:
            cpu = process.cpu_percent(None)
            command = process.cmdline()
            command_text = " ".join(command).lower()
            row = {
                "pid": process.pid,
                "name": process.name(),
                "cpu_percent_all_logical": cpu,
                "working_set_bytes": process.memory_info().rss,
                "executable": process.exe(),
                "command_line": command,
            }
            if cpu >= 0.5:
                rows.append(row)
            if any(marker in command_text for marker in project_markers):
                orphans.append(row)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    rows.sort(key=lambda item: item["cpu_percent_all_logical"], reverse=True)
    # Fail closed: inventory only. No process is terminated unless an exact,
    # separately reviewed project owner is proven. None is assumed from a name.
    return (
        {
            "sample_seconds": 2.0,
            "logical_cpu_count": psutil.cpu_count(logical=True),
            "relevant_processes": rows,
            "captured_at_utc": utc_now().isoformat(),
        },
        {
            "candidate_project_orphans": orphans,
            "terminated": [],
            "policy": "no process terminated without separately proven ownership; browser, Codex, HWiNFO, Windows, security and unknown processes preserved",
        },
    )


def power_profile() -> dict[str, Any]:
    active = run_capture(["powercfg", "/getactivescheme"])
    match = re.search(r"([0-9a-fA-F-]{36})\s+\(([^)]+)\)", active["stdout"])
    previous = {"guid": match.group(1).lower(), "name": match.group(2)} if match else {"guid": None, "name": None}
    changed = False
    change_command = None
    if previous["guid"] and any(term in (previous["name"] or "").lower() for term in ("alto desempenho", "ultimate", "high performance")):
        change = run_capture(["powercfg", "/setactive", "SCHEME_BALANCED"])
        changed = change["returncode"] == 0
        change_command = change
        active = run_capture(["powercfg", "/getactivescheme"])
        match = re.search(r"([0-9a-fA-F-]{36})\s+\(([^)]+)\)", active["stdout"])
    chosen = {"guid": match.group(1).lower(), "name": match.group(2)} if match else {"guid": None, "name": None}
    settings = {
        name: run_capture(["powercfg", "/qh", "SCHEME_CURRENT", "SUB_PROCESSOR", name])
        for name in ("PROCTHROTTLEMIN", "PROCTHROTTLEMAX", "PERFBOOSTMODE", "SYSCOOLPOL")
    }
    oem = run_capture(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model | ConvertTo-Json -Compress",
        ]
    )
    return {
        "captured_at_utc": utc_now().isoformat(),
        "previous": previous,
        "chosen": chosen,
        "changed": changed,
        "change_command": change_command,
        "active_raw": active,
        "processor_settings": settings,
        "oem_system": oem,
        "oem_mode": "NOT_EXPOSED_BY_READ_ONLY_WINDOWS_INTERFACE",
        "frozen_for_future_campaign": chosen["guid"] is not None,
    }


def windows_battery_snapshot() -> dict[str, Any]:
    return run_capture(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Battery | Select-Object Name,BatteryStatus,EstimatedChargeRemaining,EstimatedRunTime,Status,DesignCapacity,FullChargeCapacity | ConvertTo-Json -Compress",
        ]
    )


def metric_summary(values: list[float]) -> dict[str, Any]:
    return {
        "samples": len(values),
        "minimum": min(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p95": percentile(values, 0.95),
        "maximum": max(values) if values else None,
        "initial": values[0] if values else None,
        "final": values[-1] if values else None,
    }


def analyze_rows(rows: list[dict[str, Any]], sensors: dict[str, Any], expected_seconds: float) -> dict[str, Any]:
    indices = sensors["indices"]
    stamps = [item["timestamp_utc"] for item in rows]
    sample_info = sampling(rows)
    power = values_for(rows, indices["package_power"])
    core_temp = values_for(rows, indices["core_temperature"])
    package_temp = values_for(rows, indices["package_temperatures"][0] if indices["package_temperatures"] else None)
    usage = values_for(rows, indices["total_cpu_usage"])
    utility = values_for(rows, indices["total_cpu_utility"])
    clock = values_for(rows, indices["effective_clock"])
    battery_level = values_for(rows, indices["battery_level"])
    battery_rate = values_for(rows, indices["battery_rate"])
    throttle_events = []
    power_limit_events = []
    throttle_indices = indices["thermal_throttling"]
    power_limit_indices = indices["power_limit"]
    for position, row in enumerate(rows):
        active_throttle = [
            sensors["literal_names"]["thermal_throttling"][offset]
            for offset, index in enumerate(throttle_indices)
            if _truthy(row["values"][index])
        ]
        active_power = [
            sensors["literal_names"]["power_limit"][offset]
            for offset, index in enumerate(power_limit_indices)
            if _truthy(row["values"][index])
        ]
        if active_throttle:
            throttle_events.append(
                {
                    "position": position,
                    "timestamp_utc": row["timestamp_utc"].isoformat(),
                    "active_columns": active_throttle,
                    "core_temperature_c": number(row["values"][indices["core_temperature"]]) if indices["core_temperature"] is not None else None,
                    "package_power_w": number(row["values"][indices["package_power"]]),
                    "total_cpu_usage_percent": number(row["values"][indices["total_cpu_usage"]]) if indices["total_cpu_usage"] is not None else None,
                    "total_cpu_utility_percent": number(row["values"][indices["total_cpu_utility"]]) if indices["total_cpu_utility"] is not None else None,
                    "previous_timestamp_utc": rows[position - 1]["timestamp_utc"].isoformat() if position else None,
                    "next_timestamp_utc": rows[position + 1]["timestamp_utc"].isoformat() if position + 1 < len(rows) else None,
                }
            )
        if active_power:
            power_limit_events.append({"timestamp_utc": row["timestamp_utc"].isoformat(), "active_columns": active_power})
    last_60_start = stamps[-1] - timedelta(seconds=60) if stamps else None
    last_30_start = stamps[-1] - timedelta(seconds=30) if stamps else None
    last_60_positions = [index for index, stamp in enumerate(stamps) if last_60_start and stamp >= last_60_start]
    last_30_positions = [index for index, stamp in enumerate(stamps) if last_30_start and stamp >= last_30_start]
    last_30_temps = [
        (stamps[index] - stamps[last_30_positions[0]]).total_seconds()
        for index in last_30_positions
        if number(rows[index]["values"][indices["core_temperature"]]) is not None
    ]
    last_30_values = [
        number(rows[index]["values"][indices["core_temperature"]])
        for index in last_30_positions
        if number(rows[index]["values"][indices["core_temperature"]]) is not None
    ]
    if len(last_30_temps) >= 2:
        x_mean = statistics.mean(last_30_temps)
        y_mean = statistics.mean(last_30_values)
        denominator = sum((value - x_mean) ** 2 for value in last_30_temps)
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(last_30_temps, last_30_values)) / denominator if denominator else 0.0
    else:
        slope = None
    observed_span = (stamps[-1] - stamps[0]).total_seconds() if len(stamps) >= 2 else 0.0
    coverage = min(1.0, observed_span / expected_seconds) if expected_seconds else 0.0
    last_60_throttles = [event for event in throttle_events if last_60_start and datetime.fromisoformat(event["timestamp_utc"]) >= last_60_start]
    return {
        "sampling": sample_info,
        "coverage": coverage,
        "observed_span_seconds": observed_span,
        "package_power_w": metric_summary(power),
        "core_temperature_c": metric_summary(core_temp),
        "package_temperature_c": metric_summary(package_temp),
        "total_cpu_usage_percent": metric_summary(usage),
        "total_cpu_utility_percent": metric_summary(utility),
        "effective_clock_mhz": metric_summary(clock),
        "battery_level_percent": metric_summary(battery_level),
        "battery_rate_w": metric_summary(battery_rate),
        "thermal_throttle_events": throttle_events,
        "power_limit_events": power_limit_events,
        "zero_throttling_last_60s": not last_60_throttles,
        "last_60_second_samples": len(last_60_positions),
        "last_30_seconds": {
            "samples": len(last_30_values),
            "temperature_slope_c_per_s": slope,
            "temperature_range_c": max(last_30_values) - min(last_30_values) if last_30_values else None,
        },
    }


def seal(directory: Path, terminal: str) -> dict[str, str]:
    files = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.name not in {"MANIFEST.json", "SHA256SUMS"}):
        files.append({"path": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    write_json(directory / "MANIFEST.json", {"schema": "casulo-energy-host-qualification-manifest/1.0", "qualification_id": directory.name, "terminal_state": terminal, "files": files})
    lines = [f"{item['sha256']}  {item['path']}" for item in files]
    lines.append(f"{sha256_file(directory / 'MANIFEST.json')}  MANIFEST.json")
    (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return {"MANIFEST.json": sha256_file(directory / "MANIFEST.json"), "SHA256SUMS": sha256_file(directory / "SHA256SUMS")}


def finalize(
    directory: Path,
    *,
    terminal: str,
    primary: str,
    secondary: list[str],
    csv_path: Path | None,
    polling: dict[str, Any],
    profile: dict[str, Any],
    battery: dict[str, Any],
    process_data: dict[str, Any],
    observer: dict[str, Any],
    idle_analysis: dict[str, Any],
    throttle_events: dict[str, Any],
) -> None:
    report = [
        "# Qualificação física do host para energia",
        "",
        f"**Estado terminal:** `{terminal}`",
        "",
        f"Causa primária: {primary}",
        "",
        "Causas secundárias:",
        *([f"- {item}" for item in secondary] or ["- nenhuma"]),
        "",
        "Nenhum TCAP, PyTorch Eager, build, teste, compilação ou empacotamento foi executado.",
        "",
        f"CSV: `{csv_path}`" if csv_path else "CSV: indisponível",
        f"Polling mediano/p95: {polling.get('median_seconds')} / {polling.get('p95_seconds')} s",
        f"Plano congelado: {profile.get('chosen')}",
        f"AC/bateria: {battery.get('gate_summary')}",
        f"Idle de 20 minutos: {idle_analysis.get('status')}",
        "",
        "A campanha energética não foi iniciada.",
    ]
    (directory / "qualification_report.md").write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    hashes = seal(directory, terminal)
    print(json.dumps({"terminal_state": terminal, "primary_cause": primary, "secondary_causes": secondary, "hashes": hashes}, ensure_ascii=False, indent=2), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    started = utc_now()

    candidates, active = discover_csvs()
    active_record: dict[str, Any] = {
        "schema": "casulo-energy-active-csv/1.0",
        "searched_roots": [str(path) for path in SEARCH_ROOTS],
        "candidates": candidates,
        "active_count": len(active),
        "selected": str(active[0]) if len(active) == 1 else None,
    }
    write_json(directory / "active_csv.json", active_record)
    if len(active) != 1:
        for name in ("polling_validation.json", "ac_battery.json", "power_profile.json", "process_inventory_before.json", "orphan_process_actions.json", "observer_budget.json", "idle_analysis.json", "throttle_events.json"):
            write_json(directory / name, {"status": "NOT_RUN", "reason": "exactly one active HWiNFO CSV was not found"})
        (directory / "idle_20min.csv").write_text("", encoding="utf-8")
        finalize(directory, terminal="BLOCKED_HWINFO_NOT_ADVANCING", primary=f"active HWiNFO CSV count was {len(active)}", secondary=[], csv_path=None, polling={}, profile={}, battery={}, process_data={}, observer={}, idle_analysis={"status": "NOT_RUN"}, throttle_events={})
        return 2

    csv_path = active[0]
    snapshot, parsed, inspection = inspect_file(csv_path)
    if not parsed.headers or not parsed.rows or not inspection.get("selected_energy_sensor"):
        raise RuntimeError("active HWiNFO CSV lacks a parseable header or package-power sensor")
    header = parsed.headers[-1]
    energy_sensor = inspection["selected_energy_sensor"]
    sensors = sensor_map(header, int(energy_sensor["index"]))
    active_record.update(
        {
            "encoding": inspection["encoding"],
            "bom": inspection["bom"],
            "delimiter": inspection["delimiter"],
            "decimal_separator": inspection["decimal_separator"],
            "last_timestamp_before_polling_utc": parsed.rows[-1].timestamp_utc.isoformat(),
            "package_power_sensor": energy_sensor,
            "selected_sensors": sensors["literal_names"],
            "snapshot_before_polling": snapshot.metadata(),
        }
    )
    write_json(directory / "active_csv.json", active_record)

    watcher = HWiNFOIncrementalWatcher(csv_path)
    watcher.initialize()
    polling_offset = watcher.offset
    polling_initial_timestamp = watcher.latest_timestamp_utc.isoformat() if watcher.latest_timestamp_utc else None
    polling_monotonic_start = time.monotonic()
    cpu_before = time.process_time()
    observer_process = psutil.Process()
    rss_before = observer_process.memory_info().rss
    io_before = observer_process.io_counters()
    guards = []
    new_polling_timestamps: set[str] = set()
    deadline = time.monotonic() + POLLING_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        state = incremental_guard(watcher)
        guards.append(state)
        stamp = state.get("hwinfo_timestamp_utc")
        if stamp and stamp != polling_initial_timestamp and state.get("source_last_size", polling_offset) > polling_offset:
            new_polling_timestamps.add(stamp)
        if len(new_polling_timestamps) >= POLLING_MINIMUM_NEW_ROWS:
            break
        time.sleep(0.20)
    polling_end_size = csv_path.stat().st_size
    rows, _, partial_ignored = parse_appended_rows(
        csv_path,
        start_offset=polling_offset,
        end_offset=polling_end_size,
        header=header,
        encoding=inspection["encoding"],
        delimiter=inspection["delimiter"],
    )
    polling_monotonic_end = time.monotonic()
    cpu_after_polling = time.process_time()
    rss_after_polling = observer_process.memory_info().rss
    io_after_polling = observer_process.io_counters()
    polling_info = sampling(rows)
    power_values = values_for(rows, sensors["indices"]["package_power"])
    polling_info.update(
        {
            "finite_package_power": len(power_values) == len(rows) and bool(rows) and all(value >= 0 for value in power_values),
            "partial_final_line_ignored": partial_ignored,
            "source_start_offset": polling_offset,
            "source_end_offset": polling_end_size,
            "gate": "PASS" if len(rows) >= 60 and polling_info["strictly_increasing_timestamps"] and polling_info["median_seconds"] is not None and polling_info["median_seconds"] <= 0.300 and polling_info["p95_seconds"] is not None and polling_info["p95_seconds"] <= 0.350 and len(power_values) == len(rows) and all(value >= 0 for value in power_values) else "FAIL",
        }
    )
    write_json(directory / "polling_validation.json", polling_info)

    process_data, orphan_actions = process_inventory()
    write_json(directory / "process_inventory_before.json", process_data)
    write_json(directory / "orphan_process_actions.json", orphan_actions)
    profile = power_profile()
    write_json(directory / "power_profile.json", profile)
    windows_battery = windows_battery_snapshot()
    polling_analysis = analyze_rows(rows, sensors, max(1.0, polling_info.get("maximum_seconds") or 1.0))
    guard_ac = [item.get("ac_connected") for item in guards if item.get("ac_connected") is not None]
    level = polling_analysis["battery_level_percent"]
    rate = polling_analysis["battery_rate_w"]
    battery_stable = (
        bool(guard_ac)
        and all(guard_ac)
        and level["samples"] == len(rows)
        and level["minimum"] is not None
        and level["minimum"] >= 95.0
        and rate["samples"] == len(rows)
        and rate["maximum"] is not None
        and max(abs(rate["minimum"]), abs(rate["maximum"])) <= 1.0
    )
    battery = {
        "schema": "casulo-energy-ac-battery/1.0",
        "windows_battery": windows_battery,
        "ac_observations": guard_ac,
        "ac_continuous": bool(guard_ac) and all(guard_ac),
        "battery_level_percent": level,
        "charge_discharge_rate_w": rate,
        "battery_stable": battery_stable,
        "gate_summary": "PASS" if battery_stable else "FAIL: battery is not near full and materially idle",
    }
    write_json(directory / "ac_battery.json", battery)

    elapsed_polling = max(1e-9, polling_monotonic_end - polling_monotonic_start)
    observer = {
        "schema": "casulo-energy-observer-budget/1.0",
        "watcher": "append-only-incremental-v1",
        "measurement_scope": "watcher polling plus one bounded appended-segment parse; process inventory, powercfg and battery queries excluded",
        "elapsed_seconds": elapsed_polling,
        "cpu_time_seconds": cpu_after_polling - cpu_before,
        "cpu_percent_of_one_core": (cpu_after_polling - cpu_before) / elapsed_polling * 100,
        "working_set_initial_bytes": rss_before,
        "working_set_final_bytes": rss_after_polling,
        "working_set_growth_bytes": rss_after_polling - rss_before,
        "io_read_bytes_delta": io_after_polling.read_bytes - io_before.read_bytes,
        "io_write_bytes_delta": io_after_polling.write_bytes - io_before.write_bytes,
        "watcher_budget": watcher.budget(),
        "source_file_size_bytes": polling_end_size,
    }
    observer["constant_space_gate"] = watcher.maximum_observed_chunk_bytes <= OBSERVER_MAXIMUM_CHUNK_BYTES and len(watcher.partial) <= OBSERVER_MAXIMUM_CHUNK_BYTES
    observer["cpu_gate"] = observer["cpu_percent_of_one_core"] <= OBSERVER_CPU_ONE_CORE_LIMIT
    observer["status"] = "PASS" if observer["constant_space_gate"] and observer["cpu_gate"] else "FAIL"
    write_json(directory / "observer_budget.json", observer)

    required_sensor_gate = all(
        [
            sensors["indices"]["package_power"] is not None,
            sensors["indices"]["core_temperature"] is not None,
            bool(sensors["indices"]["package_temperatures"]),
            sensors["indices"]["total_cpu_usage"] is not None,
            sensors["indices"]["effective_clock"] is not None,
            sensors["indices"]["battery_level"] is not None,
            sensors["indices"]["battery_rate"] is not None,
            bool(sensors["indices"]["thermal_throttling"]),
            bool(sensors["indices"]["power_limit"]),
        ]
    )
    profile_gate = profile["chosen"].get("guid") == "381b4222-f694-41f0-9685-ff5bb260df2e" and profile["frozen_for_future_campaign"]
    usage = polling_analysis["total_cpu_usage_percent"]
    background_gate = usage["median"] is not None and usage["median"] <= 5.0 and usage["p95"] is not None and usage["p95"] <= 15.0
    preliminary_throttles = polling_analysis["thermal_throttle_events"]

    blockers = []
    if polling_info["gate"] != "PASS":
        blockers.append(("BLOCKED_HWINFO_INTERVAL", "new HWiNFO samples failed the frozen 250 ms polling gate"))
    if preliminary_throttles:
        blockers.append(("BLOCKED_THERMAL_THROTTLING", "instantaneous thermal throttling occurred during preflight polling validation"))
    if not battery_stable:
        blockers.append(("BLOCKED_AC_OR_BATTERY", "battery is materially charging/discharging or is not near full despite AC"))
    if not profile_gate:
        blockers.append(("BLOCKED_POWER_PROFILE", "the Windows power profile could not be frozen as Balanced"))
    if not background_gate:
        blockers.append(("BLOCKED_BACKGROUND_ACTIVITY", "preflight CPU utilization exceeds median 5% or p95 15%"))
    if observer["status"] != "PASS":
        blockers.append(("BLOCKED_OBSERVER_OVERHEAD", "append-only watcher exceeds its frozen CPU or memory budget"))
    if not required_sensor_gate:
        blockers.append(("BLOCKED_HWINFO_NOT_ADVANCING", "one or more mandatory HWiNFO sensors are unavailable"))

    if blockers:
        priority = ["BLOCKED_THERMAL_THROTTLING", "BLOCKED_HWINFO_INTERVAL", "BLOCKED_AC_OR_BATTERY", "BLOCKED_POWER_PROFILE", "BLOCKED_BACKGROUND_ACTIVITY", "BLOCKED_OBSERVER_OVERHEAD", "BLOCKED_HWINFO_NOT_ADVANCING"]
        blockers.sort(key=lambda item: priority.index(item[0]))
        terminal, primary = blockers[0]
        secondary = [f"{state}: {reason}" for state, reason in blockers[1:]]
        (directory / "idle_20min.csv").write_text("", encoding="utf-8")
        idle_analysis = {
            "status": "NOT_STARTED",
            "reason": "P0-P7 prerequisite gate failed; starting a 20-minute qualifying window would violate the frozen protocol",
            "preliminary_metrics": polling_analysis,
            "workloads_executed": False,
        }
        write_json(directory / "idle_analysis.json", idle_analysis)
        throttle_document = {"preflight_polling_events": preliminary_throttles, "idle_20min_events": [], "power_limit_events": polling_analysis["power_limit_events"]}
        write_json(directory / "throttle_events.json", throttle_document)
        finalize(directory, terminal=terminal, primary=primary, secondary=secondary, csv_path=csv_path, polling=polling_info, profile=profile, battery=battery, process_data=process_data, observer=observer, idle_analysis=idle_analysis, throttle_events=throttle_document)
        return 2

    # All preparation is complete before this point. During the idle window the
    # only active project component is the existing append-only watcher.
    idle_watcher = HWiNFOIncrementalWatcher(csv_path)
    idle_watcher.initialize()
    idle_offset = idle_watcher.offset
    idle_start = utc_now()
    monotonic_start = time.monotonic()
    observer_cpu_start = time.process_time()
    observer_process = psutil.Process()
    observer_rss_start = observer_process.memory_info().rss
    observer_io_start = observer_process.io_counters()
    ac_observations = []
    last_status = 0
    while time.monotonic() - monotonic_start < IDLE_SECONDS:
        state = incremental_guard(idle_watcher)
        ac_observations.append(state.get("ac_connected"))
        elapsed = int(time.monotonic() - monotonic_start)
        if elapsed >= last_status + 60:
            print(json.dumps({"event": "IDLE_PROGRESS", "elapsed_seconds": elapsed, "temperature_c": state.get("temperature_c"), "throttling": state.get("throttling")}, separators=(",", ":")), flush=True)
            last_status = elapsed
        time.sleep(0.20)
    time.sleep(0.5)
    idle_end = utc_now()
    idle_end_size = csv_path.stat().st_size
    idle_rows, idle_raw, idle_partial = parse_appended_rows(csv_path, start_offset=idle_offset, end_offset=idle_end_size, header=header, encoding=inspection["encoding"], delimiter=inspection["delimiter"])
    with (directory / "idle_20min.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for row in idle_rows:
            writer.writerow(row["values"])
    idle = analyze_rows(idle_rows, sensors, IDLE_SECONDS)
    idle["status"] = "COMPLETE"
    idle["window_start_utc"] = idle_start.isoformat()
    idle["window_end_utc"] = idle_end.isoformat()
    idle["partial_final_line_ignored"] = idle_partial
    idle["ac_continuous"] = bool(ac_observations) and all(value is True for value in ac_observations)
    idle_battery = idle["battery_level_percent"]
    idle_rate = idle["battery_rate_w"]
    idle["battery_stable"] = idle_battery["minimum"] is not None and idle_battery["minimum"] >= 95 and idle_rate["minimum"] is not None and max(abs(idle_rate["minimum"]), abs(idle_rate["maximum"])) <= 1.0
    idle_observer_cpu = time.process_time() - observer_cpu_start
    idle_rss_end = observer_process.memory_info().rss
    idle_io_end = observer_process.io_counters()
    observer["idle_20min"] = {
        "cpu_time_seconds": idle_observer_cpu,
        "cpu_percent_of_one_core": idle_observer_cpu / IDLE_SECONDS * 100,
        "working_set_initial_bytes": observer_rss_start,
        "working_set_final_bytes": idle_rss_end,
        "working_set_growth_bytes": idle_rss_end - observer_rss_start,
        "io_read_bytes_delta": idle_io_end.read_bytes - observer_io_start.read_bytes,
        "io_write_bytes_delta": idle_io_end.write_bytes - observer_io_start.write_bytes,
        "watcher_budget": idle_watcher.budget(),
        "source_file_size_bytes": idle_end_size,
    }
    observer["status"] = "PASS" if observer["idle_20min"]["cpu_percent_of_one_core"] <= OBSERVER_CPU_ONE_CORE_LIMIT and idle_watcher.maximum_observed_chunk_bytes <= OBSERVER_MAXIMUM_CHUNK_BYTES else "FAIL"
    write_json(directory / "observer_budget.json", observer)
    gates = {
        "zero_thermal_throttling_entire_window": not idle["thermal_throttle_events"],
        "zero_throttling_last_60s": idle["zero_throttling_last_60s"],
        "temperature_slope_last_30s": idle["last_30_seconds"]["temperature_slope_c_per_s"] is not None and abs(idle["last_30_seconds"]["temperature_slope_c_per_s"]) <= 0.05,
        "temperature_range_last_30s": idle["last_30_seconds"]["temperature_range_c"] is not None and idle["last_30_seconds"]["temperature_range_c"] <= 3.0,
        "logger_coverage": idle["coverage"] >= 0.98,
        "observer_append_only": observer["status"] == "PASS",
        "ac_continuous": idle["ac_continuous"],
        "battery_stable": idle["battery_stable"],
        "median_total_cpu": idle["total_cpu_usage_percent"]["median"] is not None and idle["total_cpu_usage_percent"]["median"] <= 5.0,
        "p95_total_cpu": idle["total_cpu_usage_percent"]["p95"] is not None and idle["total_cpu_usage_percent"]["p95"] <= 15.0,
    }
    idle["gates"] = gates
    idle["qualification_pass"] = all(gates.values())
    write_json(directory / "idle_analysis.json", idle)
    write_json(directory / "throttle_events.json", {"preflight_polling_events": preliminary_throttles, "idle_20min_events": idle["thermal_throttle_events"], "power_limit_events": idle["power_limit_events"]})
    if idle["qualification_pass"]:
        terminal = "PREFLIGHT_PHYSICAL_PASS"
        primary = "all physical host qualification gates passed"
        secondary = []
    elif idle["thermal_throttle_events"]:
        terminal, primary = "BLOCKED_THERMAL_THROTTLING", "instantaneous thermal throttling occurred during the 20-minute idle window"
        secondary = [name for name, passed in gates.items() if not passed and name != "zero_thermal_throttling_entire_window"]
    elif not gates["median_total_cpu"] or not gates["p95_total_cpu"]:
        terminal, primary = "BLOCKED_BACKGROUND_ACTIVITY", "20-minute idle CPU utilization exceeded the frozen quiescence limits"
        secondary = [name for name, passed in gates.items() if not passed and name not in {"median_total_cpu", "p95_total_cpu"}]
    elif not gates["temperature_slope_last_30s"] or not gates["temperature_range_last_30s"]:
        terminal, primary = "BLOCKED_THERMAL_INSTABILITY", "last-30-second thermal trend or range failed"
        secondary = [name for name, passed in gates.items() if not passed and name not in {"temperature_slope_last_30s", "temperature_range_last_30s"}]
    elif not gates["observer_append_only"]:
        terminal, primary = "BLOCKED_OBSERVER_OVERHEAD", "watcher overhead failed"
        secondary = [name for name, passed in gates.items() if not passed and name != "observer_append_only"]
    elif not gates["ac_continuous"] or not gates["battery_stable"]:
        terminal, primary = "BLOCKED_AC_OR_BATTERY", "AC or battery stability failed during idle"
        secondary = [name for name, passed in gates.items() if not passed and name not in {"ac_continuous", "battery_stable"}]
    else:
        terminal, primary = "BLOCKED_HWINFO_NOT_ADVANCING", "one or more logger/coverage gates failed"
        secondary = [name for name, passed in gates.items() if not passed]
    finalize(directory, terminal=terminal, primary=primary, secondary=secondary, csv_path=csv_path, polling=polling_info, profile=profile, battery=battery, process_data=process_data, observer=observer, idle_analysis=idle, throttle_events={})
    return 0 if terminal == "PREFLIGHT_PHYSICAL_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
