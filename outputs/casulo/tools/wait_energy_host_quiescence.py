"""Wait for a legitimate background workload to settle without terminating it."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from casulo.livelab.energy_v1.hwinfo import inspect_file
from casulo.livelab.energy_v1.hwinfo_campaign import (
    HWiNFOIncrementalWatcher,
    _truthy,
    incremental_guard,
)
from tools.qualify_energy_host import (
    parse_appended_rows,
    percentile,
    sensor_map,
    utc_now,
    values_for,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args()
    path = args.csv.resolve(strict=True)
    output = args.output.resolve()
    snapshot, parsed, inspection = inspect_file(path)
    header = parsed.headers[-1]
    sensors = sensor_map(header, int(inspection["selected_energy_sensor"]["index"]))
    indices = sensors["indices"]
    watcher = HWiNFOIncrementalWatcher(path)
    watcher.initialize()
    segment_offset = watcher.offset
    started = time.monotonic()
    last_parse = started
    last_notice = started
    rows: list[dict] = []
    observations = []
    ready = False
    last_state = {}
    while time.monotonic() - started < args.timeout_seconds:
        last_state = incremental_guard(watcher)
        now = time.monotonic()
        if now - last_parse >= 10.0:
            current_size = path.stat().st_size
            appended, complete, _ = parse_appended_rows(
                path,
                start_offset=segment_offset,
                end_offset=current_size,
                header=header,
                encoding=inspection["encoding"],
                delimiter=inspection["delimiter"],
            )
            segment_offset += len(complete)
            rows.extend(appended)
            if rows:
                cutoff = rows[-1]["timestamp_utc"] - timedelta(seconds=70)
                rows = [row for row in rows if row["timestamp_utc"] >= cutoff]
            usage = values_for(rows, indices["total_cpu_usage"])
            level = values_for(rows, indices["battery_level"])
            rate = values_for(rows, indices["battery_rate"])
            throttles = [
                row
                for row in rows
                if any(_truthy(row["values"][index]) for index in indices["thermal_throttling"])
            ]
            span = (rows[-1]["timestamp_utc"] - rows[0]["timestamp_utc"]).total_seconds() if len(rows) >= 2 else 0.0
            observation = {
                "observed_at_utc": utc_now().isoformat(),
                "rolling_span_seconds": span,
                "samples": len(rows),
                "cpu_median_percent": statistics.median(usage) if usage else None,
                "cpu_p95_percent": percentile(usage, 0.95),
                "battery_level_minimum_percent": min(level) if level else None,
                "battery_rate_absolute_maximum_w": max((abs(value) for value in rate), default=None),
                "thermal_throttle_samples": len(throttles),
                "logger_live": last_state.get("logger_live"),
                "ac_connected": last_state.get("ac_connected"),
            }
            observations.append(observation)
            ready = (
                span >= 60.0
                and observation["cpu_median_percent"] is not None
                and observation["cpu_median_percent"] <= 5.0
                and observation["cpu_p95_percent"] is not None
                and observation["cpu_p95_percent"] <= 15.0
                and observation["battery_level_minimum_percent"] is not None
                and observation["battery_level_minimum_percent"] >= 95.0
                and observation["battery_rate_absolute_maximum_w"] is not None
                and observation["battery_rate_absolute_maximum_w"] <= 1.0
                and not throttles
                and last_state.get("logger_live")
                and last_state.get("ac_connected") is True
            )
            last_parse = now
            if ready:
                break
        if now - last_notice >= 60.0:
            print(json.dumps({"event": "QUIESCENCE_WAIT", "elapsed_seconds": round(now - started, 1), "latest": observations[-1] if observations else None}, separators=(",", ":")), flush=True)
            last_notice = now
        time.sleep(0.20)
    result = {
        "schema": "casulo-energy-host-quiescence-wait/1.0",
        "started_utc": observations[0]["observed_at_utc"] if observations else None,
        "finished_utc": utc_now().isoformat(),
        "timeout_seconds": args.timeout_seconds,
        "status": "QUIESCENT_READY" if ready else "BLOCKED_BACKGROUND_ACTIVITY",
        "observations": observations,
        "last_guard": last_state,
        "watcher_budget": watcher.budget(),
        "workloads_executed": False,
        "processes_terminated": False,
    }
    write_json(output, result)
    print(json.dumps({"status": result["status"], "latest": observations[-1] if observations else None, "output": str(output)}, ensure_ascii=False, indent=2), flush=True)
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
