from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from casulo.livelab.energy_v1.hwinfo import inspect_file, integrate_window
from casulo.livelab.energy_v1.hwinfo_campaign import (
    HWiNFOIncrementalWatcher,
    _wait_for_bracketing_sample,
    _wait_safe_start,
    incremental_guard,
)
from energy_confirmatory.same_kernel import compare_same_work


FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
INTERLOCUTION = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
HWINFO = ROOT / "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV"
ARM_D = ROOT / "research/interlocution/tools/run_arm.py"
ARM_E = ROOT / "research/interlocution/tools/run_same_kernel_arm.py"


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"append-only artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def run_guarded(command: list[str], *, watcher: HWiNFOIncrementalWatcher) -> dict[str, Any]:
    start_utc = datetime.now(timezone.utc)
    start_mono = time.perf_counter_ns()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "CASULO_ENABLE_LEGACY_RESEARCH": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
    )
    observations = []
    unsafe = None
    while process.poll() is None:
        state = incremental_guard(watcher)
        observations.append(state)
        if not state.get("safe_during_load"):
            unsafe = state
            process.terminate()
            break
        time.sleep(0.25)
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
    end_mono = time.perf_counter_ns()
    end_utc = datetime.now(timezone.utc)
    if unsafe is not None:
        raise RuntimeError(f"thermal_guard_aborted:{unsafe['reason_code']}:{unsafe.get('temperature_c')}")
    if process.returncode != 0:
        raise RuntimeError(f"arm_process_failed:{process.returncode}:{stderr[-2000:]}")
    _wait_for_bracketing_sample(HWINFO, end_utc)
    _, parsed, _ = inspect_file(HWINFO)
    energy = integrate_window(parsed, start_utc, end_utc, minimum_samples=60)
    after = incremental_guard(watcher)
    return {
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "start_monotonic_ns": start_mono,
        "end_monotonic_ns": end_mono,
        "outer_elapsed_seconds": (end_mono - start_mono) / 1e9,
        "stdout": stdout.strip(),
        "stderr": stderr.strip(),
        "thermal_observations": observations,
        "thermal_after": after,
        "energy_window": energy.to_dict(),
    }


def result_path(arm: str, output: Path) -> Path:
    return output / ("worker-result.bin" if arm == "E" else "worker/worker-result.bin")


def work_summary(arm: str, output: Path, count: int) -> dict[str, Any]:
    if arm == "E":
        raw = json.loads((output / "same-kernel-result.json").read_text(encoding="utf-8"))
        return raw
    raw = json.loads((output / "arm-result.json").read_text(encoding="utf-8"))["work_summary"]
    receipts = sum(1 for line in (output / "worker/work-receipts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
    return {
        **raw,
        "K_frozen": count,
        "K_dispatched": count,
        "receipt_count": receipts,
        "receipt_provenance": "SUPERVISOR_DERIVED_FROM_COMPLETED_RESULT_PLUS_T_AUTHORITY_RECEIPTS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Exploratory HWiNFO D/E campaign; never confirmatory total-system energy")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=520)
    parser.add_argument("--pairs", type=int, default=3)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"append-only campaign exists: {output}")
    output.mkdir(parents=True)
    schedule = [
        {"pair_id": f"pair-{index + 1:02d}", "order": ["E", "D"] if index % 2 == 0 else ["D", "E"]}
        for index in range(args.pairs)
    ]
    protocol = {
        "schema": "casulo.interlocution-energy-local-exploratory/1.0",
        "frozen_before_measurement": True,
        "source": "HWiNFO-reported CPU package power",
        "source_literal": "Potência total da CPU [W]",
        "scientific_class": "EXPLORATORY_HWINFO_NOT_CONFIRMATORY_ENERGY",
        "candidate": "D_T_ARCHITECT_AUDITOR_JUDGE",
        "baseline": "E_STATIC_POLICY_SAME_NATIVE_KERNEL",
        "same_executable_required": True,
        "K": args.count,
        "pairs": args.pairs,
        "minimum_samples_per_window": 60,
        "temperature_abort_c": 75.0,
        "throttling_allowed": False,
        "schedule": schedule,
    }
    write_json(output / "frozen-protocol.json", protocol)
    watcher = HWiNFOIncrementalWatcher(HWINFO)
    initial = _wait_safe_start(HWINFO)
    write_json(output / "thermal-preflight.json", initial)

    # Three short warm-ups per arm remain outside every measured window.
    for index in range(3):
        for arm in ("E", "D"):
            warm = output / "warmups" / f"warm-{index + 1}-{arm}"
            if arm == "E":
                command = [sys.executable, str(ARM_E), "--count", "1", "--start", str(index), "--output", str(warm)]
            else:
                reference = output / "warmups" / f"warm-{index + 1}-E" / "worker-result.bin"
                command = [sys.executable, str(ARM_D), "--arm", "D", "--count", "1", "--start", str(index), "--output", str(warm), "--reference", str(reference)]
            warm.mkdir(parents=True, exist_ok=False) if False else None
            # The child creates its own append-only directory.
            guard = _wait_safe_start(HWINFO)
            process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False, env={**os.environ, "CASULO_ENABLE_LEGACY_RESEARCH": "1"})
            if process.returncode != 0:
                raise RuntimeError(f"warmup_failed:{arm}:{process.stderr[-2000:]}")

    reference: Path | None = None
    samples = []
    for scheduled in schedule:
        pair_rows = []
        for arm in scheduled["order"]:
            before = _wait_safe_start(HWINFO)
            arm_output = output / "raw" / f"{scheduled['pair_id']}-{arm}"
            if arm == "E":
                command = [sys.executable, str(ARM_E), "--count", str(args.count), "--start", "0", "--output", str(arm_output)]
            else:
                if reference is None:
                    raise RuntimeError("schedule attempted D before a frozen E reference existed")
                command = [sys.executable, str(ARM_D), "--arm", "D", "--count", str(args.count), "--start", "0", "--output", str(arm_output), "--reference", str(reference)]
            measured = run_guarded(command, watcher=watcher)
            if arm == "E" and reference is None:
                reference = result_path(arm, arm_output)
            summary = work_summary(arm, arm_output, args.count)
            row = {
                "pair_id": scheduled["pair_id"],
                "arm": arm,
                "implementation": "D_T_ARCHITECT_AUDITOR_JUDGE" if arm == "D" else "E_STATIC_POLICY_SAME_NATIVE_KERNEL",
                "thermal_before": before,
                "work_summary": summary,
                **measured,
            }
            write_json(output / "samples" / f"{scheduled['pair_id']}-{arm}.json", row)
            pair_rows.append(row)
        d = next(item for item in pair_rows if item["arm"] == "D")
        e = next(item for item in pair_rows if item["arm"] == "E")
        equivalence = compare_same_work(
            result_path("D", output / "raw" / f"{scheduled['pair_id']}-D"),
            result_path("E", output / "raw" / f"{scheduled['pair_id']}-E"),
        )
        initial_delta = abs(float(d["thermal_before"]["temperature_c"]) - float(e["thermal_before"]["temperature_c"]))
        for row in pair_rows:
            window = row["energy_window"]
            completed = int(row["work_summary"]["K_completed"])
            row["joules_per_training"] = window["energy_joules"] / completed if window["energy_joules"] is not None else None
            row["equivalence"] = equivalence["status"]
            row["initial_temperature_pair_delta_c"] = initial_delta
            row["accepted_exploratory"] = bool(
                window["status"] == "PASS"
                and row["thermal_after"].get("safe_after_load")
                and not any(obs.get("throttling") for obs in row["thermal_observations"])
                and equivalence["status"] == "PASS"
                and initial_delta <= 1.0
            )
        write_json(output / "equivalence" / f"{scheduled['pair_id']}.json", equivalence)
        samples.extend(pair_rows)
    valid_pairs = []
    for scheduled in schedule:
        rows = [item for item in samples if item["pair_id"] == scheduled["pair_id"]]
        if len(rows) != 2 or not all(item["accepted_exploratory"] for item in rows):
            continue
        d = next(item for item in rows if item["arm"] == "D")
        e = next(item for item in rows if item["arm"] == "E")
        valid_pairs.append({
            "pair_id": scheduled["pair_id"],
            "D_joules_per_training": d["joules_per_training"],
            "E_joules_per_training": e["joules_per_training"],
            "D_over_E": d["joules_per_training"] / e["joules_per_training"],
            "D_seconds_per_training": d["outer_elapsed_seconds"] / args.count,
            "E_seconds_per_training": e["outer_elapsed_seconds"] / args.count,
            "D_average_watts": d["energy_window"]["average_watts"],
            "E_average_watts": e["energy_window"]["average_watts"],
            "initial_temperature_delta_c": d["initial_temperature_pair_delta_c"],
        })
    analysis = {
        "schema": "casulo.interlocution-energy-local-exploratory-analysis/1.0",
        "status": "EXPLORATORY_COMPLETE" if len(valid_pairs) == args.pairs else "EXPLORATORY_INCOMPLETE",
        "valid_pairs": len(valid_pairs),
        "required_pairs": args.pairs,
        "pairs": valid_pairs,
        "median_D_over_E": statistics.median(item["D_over_E"] for item in valid_pairs) if valid_pairs else None,
        "median_D_joules_per_training": statistics.median(item["D_joules_per_training"] for item in valid_pairs) if valid_pairs else None,
        "median_E_joules_per_training": statistics.median(item["E_joules_per_training"] for item in valid_pairs) if valid_pairs else None,
        "claim_authorized": False,
        "claim_boundary": "Exploratory HWiNFO-reported CPU package energy on one Windows host; not total-system, not calibrated, not E1/E2 confirmation.",
    }
    write_json(output / "analysis.json", analysis)
    print(json.dumps(analysis, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
