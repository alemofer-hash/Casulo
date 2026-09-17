"""Compare HWiNFO Total CPU Usage with the Windows/psutil busy counter."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from casulo.livelab.energy_v1.hwinfo import inspect_file
from casulo.livelab.energy_v1.hwinfo_campaign import HWiNFOIncrementalWatcher
from tools.qualify_energy_host import (
    analyze_rows,
    parse_appended_rows,
    percentile,
    sensor_map,
    sha256_file,
    utc_now,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    args = parser.parse_args()

    path = args.csv.resolve(strict=True)
    output = args.output.resolve()
    snapshot, parsed, inspection = inspect_file(path)
    header = parsed.headers[-1]
    sensors = sensor_map(header, int(inspection["selected_energy_sensor"]["index"]))
    watcher = HWiNFOIncrementalWatcher(path)
    watcher.initialize()
    start_offset = watcher.offset
    started_utc = utc_now()
    started = time.monotonic()
    observer_cpu_start = time.process_time()
    logical_cpus = psutil.cpu_count(logical=True) or 1

    process_before: dict[int, tuple[float, str]] = {}
    for process in psutil.process_iter(["pid", "name", "cpu_times"]):
        try:
            cpu_times = process.info["cpu_times"]
            process_before[process.pid] = (cpu_times.user + cpu_times.system, process.info["name"] or "")
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue

    windows_samples: list[float] = []
    while time.monotonic() - started < args.duration_seconds:
        value = psutil.cpu_percent(interval=0.25)
        if math.isfinite(value):
            windows_samples.append(value)

    elapsed = time.monotonic() - started
    observer_cpu_seconds = time.process_time() - observer_cpu_start
    end_offset = path.stat().st_size
    hwinfo_rows, _, partial_ignored = parse_appended_rows(
        path,
        start_offset=start_offset,
        end_offset=end_offset,
        header=header,
        encoding=inspection["encoding"],
        delimiter=inspection["delimiter"],
    )
    hwinfo = analyze_rows(hwinfo_rows, sensors, elapsed)

    process_usage = []
    for process in psutil.process_iter(["pid", "name", "cpu_times"]):
        if process.pid not in process_before or process.pid in {0, os.getpid()}:
            continue
        try:
            cpu_times = process.info["cpu_times"]
            current = cpu_times.user + cpu_times.system
            delta = max(0.0, current - process_before[process.pid][0])
            total_percent = delta / elapsed / logical_cpus * 100.0
            if total_percent >= 0.05:
                process_usage.append(
                    {
                        "pid": process.pid,
                        "name": process.info["name"] or process_before[process.pid][1],
                        "cpu_percent_total_capacity": total_percent,
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue
    process_usage.sort(key=lambda item: item["cpu_percent_total_capacity"], reverse=True)

    windows = {
        "samples": len(windows_samples),
        "minimum": min(windows_samples) if windows_samples else None,
        "mean": statistics.mean(windows_samples) if windows_samples else None,
        "median": statistics.median(windows_samples) if windows_samples else None,
        "p95": percentile(windows_samples, 0.95),
        "maximum": max(windows_samples) if windows_samples else None,
    }
    hwinfo_usage = hwinfo["total_cpu_usage_percent"]
    median_difference = abs(windows["median"] - hwinfo_usage["median"])
    p95_difference = abs(windows["p95"] - hwinfo_usage["p95"])
    consistency = median_difference <= 2.0 and p95_difference <= 5.0
    accounted_process_percent = sum(item["cpu_percent_total_capacity"] for item in process_usage)
    observer_total_capacity_percent = observer_cpu_seconds / elapsed / logical_cpus * 100.0
    unattributed_percent = windows["mean"] - accounted_process_percent - observer_total_capacity_percent
    result = {
        "schema": "casulo-cpu-telemetry-crosscheck/1.0",
        "started_utc": started_utc.isoformat(),
        "finished_utc": utc_now().isoformat(),
        "duration_seconds": elapsed,
        "source_csv": str(path),
        "source_csv_sha256_after": sha256_file(path),
        "hwinfo_sensor": sensors["literal_names"]["total_cpu_usage"],
        "hwinfo_cpu_usage_percent": hwinfo_usage,
        "windows_psutil_cpu_usage_percent": windows,
        "absolute_median_difference_points": median_difference,
        "absolute_p95_difference_points": p95_difference,
        "frozen_consistency_thresholds_points": {"median": 2.0, "p95": 5.0},
        "consistent": consistency,
        "terminal_state": "PASS_CPU_TELEMETRY_CROSSCHECK" if consistency else "BLOCKED_SENSOR_SEMANTICS",
        "top_processes_by_total_capacity": process_usage[:20],
        "accounted_process_percent_total_capacity": accounted_process_percent,
        "observer_percent_total_capacity": observer_total_capacity_percent,
        "unattributed_percent_total_capacity": unattributed_percent,
        "observer_cpu_seconds": observer_cpu_seconds,
        "observer_percent_of_one_core": observer_cpu_seconds / elapsed * 100.0,
        "hwinfo_sampling": hwinfo["sampling"],
        "thermal_throttle_events": hwinfo["thermal_throttle_events"],
        "partial_final_line_ignored": partial_ignored,
        "workloads_executed": False,
    }
    write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if consistency else 2


if __name__ == "__main__":
    raise SystemExit(main())
