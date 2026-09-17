from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from casulo.livelab.energy_v1.hwinfo import inspect_file, integrate_window
from casulo.livelab.energy_v1.hwinfo_campaign import HWiNFOIncrementalWatcher, _normalize, _truthy, incremental_guard
from casulo.livelab.energy_v1.hwinfo_campaign import _wait_for_bracketing_sample


ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV"
OUTPUT = ROOT / "outputs/casulo/energy/2026-08-08-g5-full-worker-energy-definitive"
DURATION_SECONDS = 300.0
POLL_SECONDS = 0.25
OBSERVER_CPU_PERCENT_LIMIT = 2.0
OBSERVER_POWER_DELTA_W_LIMIT = 1.0
OBSERVER_TEMPERATURE_MEDIAN_DELTA_C_LIMIT = 2.0
OBSERVER_TEMPERATURE_MAX_DELTA_C_LIMIT = 3.0
P95_INTERVAL_LIMIT_SECONDS = 0.300


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _numeric(raw: str) -> float | None:
    try:
        value = float(raw.strip().replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def _summarize(csv_path: Path, start: datetime, end: datetime) -> dict[str, Any]:
    _, parsed, _ = inspect_file(csv_path)
    rows = [row for row in parsed.rows if start <= row.timestamp_utc <= end]
    if len(rows) < 60:
        raise RuntimeError("idle control has insufficient HWiNFO rows")
    window = integrate_window(parsed, start, end, minimum_samples=60)
    session = rows[0].session_id
    header = parsed.headers[session]
    normalized = [_normalize(name) for name in header]
    temp_indices = [i for i, name in enumerate(normalized) if "temperaturas centrais" in name and "avg" in name]
    utility_indices = [i for i, name in enumerate(normalized) if "total cpu utility" in name or "utilizacao total da cpu" in name]
    throttle_indices = [i for i, name in enumerate(normalized) if ("estrangulamento termico" in name or "thermal throttling" in name)]
    temperatures = [_numeric(row.values[temp_indices[0]]) for row in rows] if temp_indices else []
    temperatures = [value for value in temperatures if value is not None]
    utilities = [_numeric(row.values[utility_indices[0]]) for row in rows] if utility_indices else []
    utilities = [value for value in utilities if value is not None]
    throttle_events = []
    for row in rows:
        active = [{"column": header[index], "raw": row.values[index]} for index in throttle_indices if _truthy(row.values[index])]
        if active:
            throttle_events.append({"timestamp_utc": row.timestamp_utc.isoformat(), "active": active})
    intervals = [(right.timestamp_utc - left.timestamp_utc).total_seconds() for left, right in zip(rows, rows[1:]) if right.timestamp_utc > left.timestamp_utc]
    median_interval = statistics.median(intervals)
    return {
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "rows": len(rows),
        "energy_window": window.to_dict(),
        "temperature_c": {"initial": temperatures[0], "median": statistics.median(temperatures), "maximum": max(temperatures), "final": temperatures[-1]},
        "total_cpu_utility_percent": {"median": statistics.median(utilities) if utilities else None, "maximum": max(utilities) if utilities else None},
        "sampling": {"median_seconds": median_interval, "p95_seconds": _percentile(intervals, 0.95), "maximum_seconds": max(intervals), "gaps_over_5x_median": [value for value in intervals if value > 5 * median_interval]},
        "throttle_events": throttle_events,
        "throttle_event_count": len(throttle_events),
        "csv_size_end": csv_path.stat().st_size,
    }


def _run_control(name: str, csv_path: Path, *, watcher: bool, load_runner: bool) -> dict[str, Any]:
    loaded = None
    if load_runner:
        from casulo.livelab.energy_v1.full_workers import validate_full_tcap

        loaded = validate_full_tcap(ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2/artifact/FloodSurrogate.full.tcap")
        import torch

        torch.set_num_threads(1)
    incremental = HWiNFOIncrementalWatcher(csv_path) if watcher else None
    if incremental:
        incremental.initialize()
    process = psutil.Process(os.getpid())
    cpu_start = process.cpu_times()
    size_start = csv_path.stat().st_size
    rss_max = process.memory_info().rss
    start = datetime.now(timezone.utc)
    deadline = time.monotonic() + DURATION_SECONDS
    next_progress = time.monotonic() + 60.0
    polls = 0
    while time.monotonic() < deadline:
        if incremental:
            incremental.read_latest()
            polls += 1
        rss_max = max(rss_max, process.memory_info().rss)
        now = time.monotonic()
        if now >= next_progress:
            print(json.dumps({"control": name, "elapsed_seconds": round(DURATION_SECONDS - max(0, deadline - now), 1)}, separators=(",", ":")), flush=True)
            next_progress += 60.0
        time.sleep(min(POLL_SECONDS if incremental else 1.0, max(0, deadline - time.monotonic())))
    end = datetime.now(timezone.utc)
    cpu_end = process.cpu_times()
    _wait_for_bracketing_sample(csv_path, end, timeout_seconds=60.0)
    cpu_seconds = (cpu_end.user + cpu_end.system) - (cpu_start.user + cpu_start.system)
    summary = _summarize(csv_path, start, end)
    summary.update({
        "control": name,
        "watcher": "append-only-incremental-v1" if watcher else "disabled",
        "runner_loaded": load_runner,
        "duration_seconds": (end - start).total_seconds(),
        "csv_growth_bytes": csv_path.stat().st_size - size_start,
        "observer_process_cpu_seconds": cpu_seconds,
        "observer_process_cpu_percent_of_one_core": cpu_seconds / (end - start).total_seconds() * 100,
        "observer_maximum_rss_bytes": rss_max,
        "watcher_polls": polls,
        "watcher_budget": incremental.budget() if incremental else None,
        "runner_resident_reference_retained": loaded is not None,
    })
    return summary


def _wait_matched_start(
    csv_path: Path,
    target_c: float | None,
    *,
    initial_ceiling_c: float = 55.0,
    seconds: float = 30.0,
    timeout: float = 1200.0,
) -> dict[str, Any]:
    watcher = HWiNFOIncrementalWatcher(csv_path)
    watcher.initialize()
    deadline = time.monotonic() + timeout
    stable_since: datetime | None = None
    stability_anchor_c: float | None = target_c
    previous = None
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = incremental_guard(watcher)
        temperature = last.get("temperature_c")
        stamp_text = last.get("hwinfo_timestamp_utc")
        if target_c is None and stability_anchor_c is None and temperature is not None and temperature <= initial_ceiling_c:
            stability_anchor_c = temperature
        matched = (
            last.get("logger_live")
            and last.get("ac_connected") is True
            and not last.get("throttling")
            and temperature is not None
            and stability_anchor_c is not None
            and abs(temperature - stability_anchor_c) <= 1.0
        )
        if matched and stamp_text and stamp_text != previous:
            stamp = datetime.fromisoformat(stamp_text)
            if stable_since is None:
                stable_since = stamp
            if (stamp - stable_since).total_seconds() >= seconds:
                last["stability_anchor_temperature_c"] = stability_anchor_c
                last["stability_band_tolerance_c"] = 1.0
                last["stability_seconds"] = seconds
                return last
            previous = stamp_text
        elif not matched:
            stable_since = None
            if target_c is None:
                stability_anchor_c = None
        time.sleep(0.25)
    raise RuntimeError("matched idle control start timeout: " + json.dumps(last))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=CSV)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--initial-ceiling-c", type=float, default=55.0)
    args = parser.parse_args()
    csv_path = args.csv.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    controls = []
    reference_temperature = None
    for name, watcher, runner in (("A_HWINFO_ONLY", False, False), ("B_HWINFO_INCREMENTAL_WATCHER", True, False), ("C_HWINFO_WATCHER_RUNNER_LOADED", True, True)):
        checkpoint = output / "raw" / f"idle-control-{name}.json"
        if checkpoint.is_file():
            control = json.loads(checkpoint.read_text(encoding="utf-8"))
            print(json.dumps({"event": "CONTROL_RESUME", "control": name}, separators=(",", ":")), flush=True)
        else:
            matched_start = _wait_matched_start(
                csv_path,
                reference_temperature,
                initial_ceiling_c=args.initial_ceiling_c,
            )
            print(json.dumps({"event": "CONTROL_START", "control": name, "duration_seconds": DURATION_SECONDS}, separators=(",", ":")), flush=True)
            control = _run_control(name, csv_path, watcher=watcher, load_runner=runner)
            control["matched_start_guard"] = matched_start
            _write_json(checkpoint, control)
        if reference_temperature is None:
            reference_temperature = control["matched_start_guard"]["temperature_c"]
        controls.append(control)
        print(json.dumps({"event": "CONTROL_END", "control": name, "temperature": control["temperature_c"], "throttles": control["throttle_event_count"]}, separators=(",", ":")), flush=True)
    a, b, c = controls
    b_power_delta = b["energy_window"]["average_watts"] - a["energy_window"]["average_watts"]
    b_temp_median_delta = b["temperature_c"]["median"] - a["temperature_c"]["median"]
    b_temp_max_delta = b["temperature_c"]["maximum"] - a["temperature_c"]["maximum"]
    c_power_delta = c["energy_window"]["average_watts"] - b["energy_window"]["average_watts"]
    c_temp_median_delta = c["temperature_c"]["median"] - b["temperature_c"]["median"]
    frozen_limits = {
        "observer_cpu_percent_of_one_core_max": OBSERVER_CPU_PERCENT_LIMIT,
        "observer_power_delta_w_max": OBSERVER_POWER_DELTA_W_LIMIT,
        "observer_temperature_median_delta_c_max": OBSERVER_TEMPERATURE_MEDIAN_DELTA_C_LIMIT,
        "observer_temperature_max_delta_c_max": OBSERVER_TEMPERATURE_MAX_DELTA_C_LIMIT,
        "p95_interval_seconds_max": P95_INTERVAL_LIMIT_SECONDS,
        "throttle_events_allowed": 0,
    }
    gates = {
        "no_idle_throttling": all(item["throttle_event_count"] == 0 for item in controls),
        "watcher_cpu_budget": b["observer_process_cpu_percent_of_one_core"] <= OBSERVER_CPU_PERCENT_LIMIT,
        "watcher_power_budget": b_power_delta <= OBSERVER_POWER_DELTA_W_LIMIT,
        "watcher_temperature_median_budget": b_temp_median_delta <= OBSERVER_TEMPERATURE_MEDIAN_DELTA_C_LIMIT,
        "watcher_temperature_maximum_budget": b_temp_max_delta <= OBSERVER_TEMPERATURE_MAX_DELTA_C_LIMIT,
        "runner_idle_power_budget": c_power_delta <= OBSERVER_POWER_DELTA_W_LIMIT,
        "runner_idle_temperature_budget": c_temp_median_delta <= OBSERVER_TEMPERATURE_MEDIAN_DELTA_C_LIMIT,
        "sampling_budget": all(item["sampling"]["p95_seconds"] <= P95_INTERVAL_LIMIT_SECONDS and not item["sampling"]["gaps_over_5x_median"] for item in controls),
        "append_only_budget": b["watcher_budget"]["maximum_observed_chunk_bytes"] <= b["watcher_budget"]["maximum_chunk_bytes"] and c["watcher_budget"]["maximum_observed_chunk_bytes"] <= c["watcher_budget"]["maximum_chunk_bytes"],
    }
    result = {
        "schema": "casulo-definitive-idle-controls/1.0",
        "initial_ceiling_c": args.initial_ceiling_c,
        "frozen_limits": frozen_limits,
        "controls": controls,
        "deltas": {"watcher_vs_hwinfo_only_power_w": b_power_delta, "watcher_vs_hwinfo_only_temperature_median_c": b_temp_median_delta, "watcher_vs_hwinfo_only_temperature_max_c": b_temp_max_delta, "runner_loaded_vs_watcher_power_w": c_power_delta, "runner_loaded_vs_watcher_temperature_median_c": c_temp_median_delta},
        "gates": gates,
        "status": "PASS" if all(gates.values()) else "FAIL",
    }
    _write_json(output / "idle_controls.json", result)
    _write_json(output / "observer_budget.json", {"schema": "casulo-observer-budget/1.0", "frozen_limits": frozen_limits, "observed": result["deltas"], "gates": gates, "status": result["status"]})
    print(json.dumps({"status": result["status"], "gates": gates, "deltas": result["deltas"], "output": str(output)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
