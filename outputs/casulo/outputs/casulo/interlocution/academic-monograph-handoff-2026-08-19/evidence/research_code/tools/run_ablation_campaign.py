from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from casulo.livelab.energy_v1.analysis import exact_sign_test, paired_bootstrap_ci
from casulo.livelab.energy_v1.hwinfo_campaign import HWiNFOIncrementalWatcher, incremental_guard


CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
HWINFO = ROOT / "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV"
ARM_SCRIPT = ROOT / "research/interlocution/tools/run_arm.py"


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"append-only artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def process_metrics(command: list[str], output: Path) -> dict[str, Any]:
    started = time.perf_counter_ns()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
    )
    parent = psutil.Process(process.pid)
    try:
        parent.cpu_affinity([4])
    except (AttributeError, psutil.Error, ValueError):
        pass
    peak_rss = 0
    last_cpu = 0.0
    io_read = 0
    io_write = 0
    while process.poll() is None:
        members = []
        try:
            members = [parent, *parent.children(recursive=True)]
        except psutil.Error:
            members = [parent]
        rss = 0
        cpu = 0.0
        read = 0
        write = 0
        for member in members:
            try:
                rss += member.memory_info().rss
                times = member.cpu_times()
                cpu += times.user + times.system
                io = member.io_counters()
                read += io.read_bytes
                write += io.write_bytes
            except psutil.Error:
                continue
        peak_rss = max(peak_rss, rss)
        last_cpu = max(last_cpu, cpu)
        io_read = max(io_read, read)
        io_write = max(io_write, write)
        time.sleep(0.01)
    stdout, stderr = process.communicate(timeout=5)
    elapsed_ns = time.perf_counter_ns() - started
    if process.returncode != 0:
        raise RuntimeError(f"arm failed rc={process.returncode}: {stderr[-2000:]}")
    inner = json.loads((output / "arm-result.json").read_text(encoding="utf-8"))
    return {
        "outer_wall_ns": elapsed_ns,
        "observed_process_cpu_seconds": last_cpu,
        "peak_process_tree_rss_bytes": peak_rss,
        "process_tree_read_bytes": io_read,
        "process_tree_write_bytes": io_write,
        "stdout": stdout.strip(),
        "inner": inner,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--attempt", default="ti10-v1")
    args = parser.parse_args()
    if not args.attempt.startswith("ti10-v") or not args.attempt[6:].isdigit():
        raise ValueError("attempt must be an append-only ti10-vN identifier")
    output = CAMPAIGN / "baselines" / args.attempt
    if output.exists():
        raise FileExistsError(f"append-only campaign exists: {output}")
    output.mkdir(parents=True)
    rotations = (("A", "B", "C", "D"), ("D", "C", "B", "A"), ("B", "D", "A", "C"), ("C", "A", "D", "B"))
    schedule = [
        {"block": index + 1, "order": list(rotations[index % len(rotations)])}
        for index in range(args.repetitions)
    ]
    protocol = {
        "schema": "casulo.interlocution-ti10-protocol/1.0",
        "frozen_before_samples": True,
        "workload": "FloodSurrogate 1024x8x8x1 float64 400 epochs",
        "count_per_arm": args.count,
        "repetitions": args.repetitions,
        "arms": {
            "A": "transparent PyTorch Eager; no T",
            "B": "PyTorch Eager plus post-hoc T audit ignored by publisher",
            "C": "T architect plus native primitive; foreign acceptance",
            "D": "T architect, independent audit and consumed T judge",
        },
        "primary_comparison": "D/A",
        "bootstrap_seed": 2026081901,
        "bootstrap_resamples": 20000,
        "affinity": [4],
        "threads": 1,
        "energy": "NOT_MEASURED",
        "thermal_guard": "live HWiNFO safety only; no watt integration",
        "schedule": schedule,
        "predeclared_ablations": {
            "no_interlocution": "must block because confirmed intent seal is absent",
            "no_evidence_gate": "may execute but cannot claim T-judged publication",
            "global_reexecution": "contrast against fail-before-work causal rejection",
            "all_hot": "not semantically applicable to this single-primitive workload",
            "selected_working_set": "T chooses all 1024 records required by R",
        },
    }
    write_json(output / "frozen-protocol.json", protocol)

    # Oracle is frozen before measured arms and never consumed by the trainer.
    reference = output / "frozen-reference.bin"
    reference_command = [sys.executable, "-m", "casulo.livelab.energy_v1.full_workers", "--eager", "--tcap", str(FULL / "artifact/FloodSurrogate.full.tcap"), "--start", "0", "--count", str(args.count), "--output", str(reference)]
    ref = subprocess.run(reference_command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
    if ref.returncode != 0 or not reference.is_file():
        raise RuntimeError(f"failed to freeze Eager oracle: {ref.stderr}")
    (output / "frozen-reference-timing.json").write_text(ref.stdout, encoding="utf-8", newline="\n")

    watcher = HWiNFOIncrementalWatcher(HWINFO)
    preflight = incremental_guard(watcher)
    write_json(output / "thermal-preflight.json", preflight)
    if not preflight.get("ready_to_start"):
        raise RuntimeError(f"thermal preflight denied: {preflight}")

    # One unmeasured warm-up per arm.
    for arm in ("A", "B", "C", "D"):
        guard = incremental_guard(watcher)
        if not guard.get("safe_during_load"):
            raise RuntimeError(f"thermal guard denied warm-up {arm}: {guard}")
        warm = output / "warmups" / arm
        command = [sys.executable, str(ARM_SCRIPT), "--arm", arm, "--count", "1", "--start", "0", "--output", str(warm)]
        if arm == "D":
            # A one-case oracle is required for the one-case warm-up.
            warm_ref = output / "warmup-reference.bin"
            if not warm_ref.exists():
                r = subprocess.run([sys.executable, "-m", "casulo.livelab.energy_v1.full_workers", "--eager", "--tcap", str(FULL / "artifact/FloodSurrogate.full.tcap"), "--start", "0", "--count", "1", "--output", str(warm_ref)], cwd=ROOT, capture_output=True, text=True, timeout=180, check=False)
                if r.returncode != 0:
                    raise RuntimeError("failed warm-up reference")
            command += ["--reference", str(warm_ref)]
        process_metrics(command, warm)

    samples = []
    for block in schedule:
        for arm in block["order"]:
            before = incremental_guard(watcher)
            if not before.get("safe_during_load"):
                write_json(output / "thermal-block.json", {"status": "BLOCKED", "block": block["block"], "arm": arm, "guard": before})
                raise RuntimeError(f"thermal guard denied block {block['block']} arm {arm}")
            sample_dir = output / "samples" / f"block-{block['block']:02d}-{arm}"
            command = [sys.executable, str(ARM_SCRIPT), "--arm", arm, "--count", str(args.count), "--start", "0", "--output", str(sample_dir)]
            if arm == "D":
                command += ["--reference", str(reference)]
            measured = process_metrics(command, sample_dir)
            after = incremental_guard(watcher)
            if not after.get("safe_after_load"):
                raise RuntimeError(f"thermal guard rejected block {block['block']} arm {arm}: {after}")
            samples.append({"block": block["block"], "arm": arm, "thermal_before": before, "thermal_after": after, **measured})
    write_json(output / "samples.json", {"samples": samples})

    by_block = {block["block"]: {} for block in schedule}
    for sample in samples:
        by_block[sample["block"]][sample["arm"]] = sample
    ratios = []
    for block, values in by_block.items():
        ratios.append(values["D"]["outer_wall_ns"] / values["A"]["outer_wall_ns"])
    ci = paired_bootstrap_ci(tuple(ratios), seed=protocol["bootstrap_seed"], resamples=protocol["bootstrap_resamples"])
    sign = exact_sign_test(
        (by_block[index]["D"]["outer_wall_ns"] for index in sorted(by_block)),
        (by_block[index]["A"]["outer_wall_ns"] for index in sorted(by_block)),
    )
    arm_summary = {}
    for arm in ("A", "B", "C", "D"):
        arm_samples = [sample for sample in samples if sample["arm"] == arm]
        arm_summary[arm] = {
            "median_outer_wall_seconds": statistics.median(sample["outer_wall_ns"] for sample in arm_samples) / 1e9,
            "median_seconds_per_training": statistics.median(sample["outer_wall_ns"] / args.count for sample in arm_samples) / 1e9,
            "median_observed_process_cpu_seconds": statistics.median(sample["observed_process_cpu_seconds"] for sample in arm_samples),
            "median_peak_process_tree_rss_bytes": statistics.median(sample["peak_process_tree_rss_bytes"] for sample in arm_samples),
            "median_process_tree_read_bytes": statistics.median(sample["process_tree_read_bytes"] for sample in arm_samples),
            "median_process_tree_write_bytes": statistics.median(sample["process_tree_write_bytes"] for sample in arm_samples),
        }
    analysis = {
        "schema": "casulo.interlocution-ti10-analysis/1.0",
        "status": "PASS_MEASUREMENT_NO_ENERGY",
        "valid_blocks": len(by_block),
        "arm_summary": arm_summary,
        "paired_D_over_A_wall_ratios": ratios,
        "median_D_over_A_wall_ratio": statistics.median(ratios),
        "paired_bootstrap_ci95": {"lower": ci[0], "upper": ci[1], "seed": protocol["bootstrap_seed"], "resamples": protocol["bootstrap_resamples"]},
        "exact_sign_test": sign,
        "energy": {"package_joules": None, "total_system_joules": None, "claim": "BLOCKED_NOT_MEASURED"},
        "interpretation_rule": "Only predeclared dimensions are reported; no aggregate compression score.",
    }
    write_json(output / "analysis.json", analysis)
    print(json.dumps({"status": analysis["status"], "blocks": len(by_block), "median_D_A": analysis["median_D_over_A_wall_ratio"], "ci95": analysis["paired_bootstrap_ci95"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
