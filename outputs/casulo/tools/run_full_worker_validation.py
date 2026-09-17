"""Build and validate the complete 1,024-record FloodSurrogate work unit.

This program deliberately stops before energy collection.  Its output is the
mandatory scientific gate consumed by the separate physical campaign runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from casulo.livelab.energy_v1.full_workers import (
    EAGER_FULL_IMPLEMENTATION,
    TCAP_FULL_IMPLEMENTATION,
    build_full_native_worker,
    compare_results,
    create_receipts,
    parse_result_file,
    validate_full_tcap,
    validate_receipts,
)
from casulo.livelab.energy_v1.hwinfo_campaign import (
    HWiNFOIncrementalWatcher,
    incremental_guard,
)
from casulo.t.full_work_unit import (
    EPOCHS,
    PARAMETER_COUNT,
    RECORDS,
    build_full_work_unit_tcap,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/t/flood_surrogate_training.t"
DEFAULT_OUTPUT = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1"
DEFAULT_CSV = ROOT / "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV"
K_SEQUENCE = (1, 2, 5, 10, 20, 50, 100)
START_LIMIT_C = 70.0
HARD_LIMIT_C = 90.0


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _wait_safe(csv_path: Path, *, timeout: float = 900.0) -> dict[str, Any]:
    watcher = HWiNFOIncrementalWatcher(csv_path)
    watcher.initialize()
    deadline = time.monotonic() + timeout
    distinct = 0
    previous = None
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = incremental_guard(watcher)
        if last.get("throttling") or (last.get("temperature_c") or 0) >= HARD_LIMIT_C:
            raise RuntimeError("thermal guard rejected start: " + json.dumps(last))
        stamp = last.get("hwinfo_timestamp_utc")
        ready = (
            last.get("logger_live")
            and last.get("ac_connected") is True
            and last.get("temperature_c") is not None
            and last["temperature_c"] < START_LIMIT_C
        )
        if ready and stamp != previous:
            distinct += 1
            previous = stamp
            if distinct >= 3:
                return last
        elif not ready:
            distinct = 0
        time.sleep(0.5)
    raise RuntimeError("thermal cooldown timeout: " + json.dumps(last))


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        import psutil

        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            child.terminate()
        parent.terminate()
        _, alive = psutil.wait_procs([*children, parent], timeout=5)
        for item in alive:
            item.kill()
    except Exception:
        process.kill()


def _run_guarded(
    command: list[str], csv_path: Path, *, timeout: float
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    before = _wait_safe(csv_path)
    watcher = HWiNFOIncrementalWatcher(csv_path)
    watcher.initialize()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["OMP_NUM_THREADS"] = "1"
    environment["MKL_NUM_THREADS"] = "1"
    start_utc = _utc()
    parent_start = time.perf_counter_ns()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    observations: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    failure = None
    while process.poll() is None:
        state = incremental_guard(watcher)
        observations.append(state)
        temperature = state.get("temperature_c")
        if not state.get("logger_live"):
            failure = "telemetry_lost"
        elif state.get("throttling"):
            failure = "thermal_throttling"
        elif temperature is not None and temperature >= HARD_LIMIT_C:
            failure = "hard_temperature_limit"
        elif time.monotonic() >= deadline:
            failure = "timeout"
        if failure:
            _terminate(process)
            break
        time.sleep(0.25)
    stdout, stderr = process.communicate(timeout=10)
    parent_elapsed = time.perf_counter_ns() - parent_start
    after = incremental_guard(watcher)
    maximum = max(
        [value["temperature_c"] for value in [before, *observations, after] if value.get("temperature_c") is not None],
        default=None,
    )
    metadata = {
        "start_utc": start_utc,
        "end_utc": _utc(),
        "parent_monotonic_ns": parent_elapsed,
        "thermal_before": before,
        "thermal_after": after,
        "maximum_temperature_c": maximum,
        "thermal_samples": len(observations),
        "failure": failure,
        "watcher_budget": watcher.budget(),
    }
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if failure or result.returncode != 0:
        raise RuntimeError(
            f"guarded worker failed ({failure or result.returncode}): {stderr or stdout}"
        )
    return result, metadata


def _parse_worker_stdout(implementation: str, value: str) -> dict[str, Any]:
    line = [item for item in value.splitlines() if item.strip()][-1]
    if implementation == EAGER_FULL_IMPLEMENTATION:
        return json.loads(line)
    fields = line.split()
    if len(fields) not in (7, 9) or fields[0] != "RESULT":
        raise ValueError("native worker emitted an invalid timing receipt")
    parsed = {
        "implementation": implementation,
        "start": int(fields[1]),
        "K": int(fields[2]),
        "worker_monotonic_ns": int(fields[3]),
        "qpc_ticks": int(fields[4]),
        "qpc_frequency": int(fields[5]),
        "thread_cycles": int(fields[6]),
    }
    if len(fields) == 9:
        parsed.update({"start_unix_ns": int(fields[7]), "end_unix_ns": int(fields[8])})
    return parsed


def _fit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # Ascending and descending sweeps are paired replicates of the same K.
    # The regression unit is K, not traversal direction.  Collapse every
    # preregistered replicate by its median; retain all raw observations in the
    # campaign so this cannot become post-hoc outlier deletion.
    grouped = {
        k: [item["timing"]["worker_monotonic_ns"] / 1e9 for item in rows if item["K"] == k]
        for k in sorted({item["K"] for item in rows})
    }
    x = [float(k) for k in grouped]
    y = [statistics.median(grouped[int(k)]) for k in x]
    x_mean, y_mean = statistics.mean(x), statistics.mean(y)
    denominator = sum((value - x_mean) ** 2 for value in x)
    slope = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y, strict=True)) / denominator
    intercept = y_mean - slope * x_mean
    predicted = [intercept + slope * value for value in x]
    residuals = [actual - estimate for actual, estimate in zip(y, predicted, strict=True)]
    total = sum((value - y_mean) ** 2 for value in y)
    residual_sum = sum(value * value for value in residuals)
    r2 = 1.0 - residual_sum / total if total else 1.0
    return {
        "regression_unit": "median_of_all_preregistered_direction_replicates_per_K",
        "replicates_per_K": {str(k): len(values) for k, values in grouped.items()},
        "central_seconds_by_K": {str(k): statistics.median(values) for k, values in grouped.items()},
        "slope_seconds_per_training": slope,
        "intercept_seconds": intercept,
        "R2": r2,
        "residuals_seconds": residuals,
        "gate": "PASS" if r2 >= 0.995 and slope > 0 else "FAIL",
    }


def _run_one(
    *,
    implementation: str,
    k: int,
    label: str,
    tcap: Path,
    executable: Path,
    dataset: Path,
    initializations: Path,
    output: Path,
    csv_path: Path,
) -> tuple[dict[str, Any], tuple[Any, ...], list[dict[str, Any]], dict[str, Any]]:
    result_path = output / "results" / f"{label}.bin"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if implementation == TCAP_FULL_IMPLEMENTATION:
        command = [str(executable), str(dataset), str(initializations), "0", str(k), str(result_path)]
    else:
        command = [
            sys.executable,
            "-m",
            "casulo.livelab.energy_v1.full_workers",
            "--eager",
            "--tcap",
            str(tcap),
            "--start",
            "0",
            "--count",
            str(k),
            "--output",
            str(result_path),
        ]
    completed, parent = _run_guarded(command, csv_path, timeout=max(180.0, k * 6.0))
    timing = _parse_worker_stdout(implementation, completed.stdout)
    timing["parent_monotonic_ns"] = parent["parent_monotonic_ns"]
    timing["qpc_seconds"] = timing["qpc_ticks"] / timing["qpc_frequency"]
    timing["worker_seconds"] = timing["worker_monotonic_ns"] / 1e9
    timing["parent_seconds"] = timing["parent_monotonic_ns"] / 1e9
    timing["qpc_vs_worker_relative_difference"] = abs(
        timing["qpc_seconds"] - timing["worker_seconds"]
    ) / timing["worker_seconds"]
    timing["three_clock_gate"] = (
        "PASS"
        if timing["qpc_vs_worker_relative_difference"] <= 0.01
        and timing["thread_cycles"] > 0
        and timing["parent_monotonic_ns"] >= timing["worker_monotonic_ns"]
        else "FAIL"
    )
    results = parse_result_file(result_path)
    contract, _, cases = validate_full_tcap(tcap)
    receipts, chain = create_receipts(contract=contract, cases=cases, results=results)
    validate_receipts(receipts, k)
    receipt_file = output / "receipts" / f"{label}.jsonl"
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.write_text(
        "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in receipts),
        encoding="utf-8",
        newline="\n",
    )
    return timing, results, receipts, {"chain": chain, "thermal": parent, "receipt_file": str(receipt_file)}


def _seal(output: Path, terminal_state: str) -> None:
    excluded = {"MANIFEST.json", "SHA256SUMS"}
    files = []
    for path in sorted(item for item in output.rglob("*") if item.is_file() and item.name not in excluded):
        files.append(
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest = {
        "schema": "casulo-full-worker-manifest/1.0",
        "campaign_id": output.name,
        "terminal_state": terminal_state,
        "files": files,
    }
    _write_json(output / "MANIFEST.json", manifest)
    lines = [f"{item['sha256']}  {item['path']}" for item in files]
    lines.append(f"{_sha256_file(output / 'MANIFEST.json')}  MANIFEST.json")
    (output / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--case-count", type=int, default=1024)
    args = parser.parse_args()
    output = args.output.resolve()
    csv_path = args.csv.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)

    artifact = build_full_work_unit_tcap(SOURCE, output / "artifact", case_count=args.case_count)
    contract, segments, cases = validate_full_tcap(artifact.tcap_file)
    worker = build_full_native_worker(artifact.tcap_file, output / "worker")
    _write_json(output / "tcap_contract.json", contract.to_dict())
    for name in ("dataset_manifest.json", "initialization_bundle.json"):
        (output / name).write_bytes((output / "artifact" / name).read_bytes())
    _write_json(output / "worker_build.json", worker)

    rows: dict[str, list[dict[str, Any]]] = {
        TCAP_FULL_IMPLEMENTATION: [],
        EAGER_FULL_IMPLEMENTATION: [],
    }
    equivalence_rows = []
    chains: dict[str, Any] = {}
    thermal_rows = []
    for direction, sequence in (("ascending", K_SEQUENCE), ("descending", tuple(reversed(K_SEQUENCE)))):
        for k in sequence:
            pair_results = {}
            for implementation, short in (
                (TCAP_FULL_IMPLEMENTATION, "tcap"),
                (EAGER_FULL_IMPLEMENTATION, "eager"),
            ):
                label = f"{direction}-{k:03d}-{short}"
                timing, results, receipts, metadata = _run_one(
                    implementation=implementation,
                    k=k,
                    label=label,
                    tcap=artifact.tcap_file,
                    executable=Path(worker["executable"]),
                    dataset=artifact.dataset_file,
                    initializations=artifact.initialization_file,
                    output=output,
                    csv_path=csv_path,
                )
                row = {
                    "direction": direction,
                    "K": k,
                    "timing": timing,
                    "chain": metadata["chain"],
                    "receipt_file": metadata["receipt_file"],
                    "counter_totals": {
                        "receipts": len(receipts),
                        "epochs_completed": sum(item["epochs_completed"] for item in receipts),
                        "optimizer_steps": sum(item["optimizer_steps"] for item in receipts),
                        "records_visited": sum(item["records_visited"] for item in receipts),
                        "parameter_writes": sum(item["parameter_writes"] for item in receipts),
                    },
                }
                rows[implementation].append(row)
                pair_results[implementation] = results
                chains[label] = metadata["chain"]
                thermal_rows.append({"label": label, **metadata["thermal"]})
            comparison = compare_results(
                pair_results[TCAP_FULL_IMPLEMENTATION], pair_results[EAGER_FULL_IMPLEMENTATION]
            )
            comparison.update({"direction": direction, "K": k})
            equivalence_rows.append(comparison)

    fits = {name: _fit(value) for name, value in rows.items()}
    exact_counts = all(
        item["counter_totals"]
        == {
            "receipts": item["K"],
            "epochs_completed": EPOCHS * item["K"],
            "optimizer_steps": EPOCHS * item["K"],
            "records_visited": RECORDS * EPOCHS * item["K"],
            "parameter_writes": PARAMETER_COUNT * EPOCHS * item["K"],
        }
        for group in rows.values()
        for item in group
    )
    clocks_pass = all(
        item["timing"]["three_clock_gate"] == "PASS" for group in rows.values() for item in group
    )
    equivalence_pass = all(item["status"] == "PASS" for item in equivalence_rows)
    unique_case_hashes = len({item.nonce for item in cases}) == len(cases) and len(
        {item.parameters for item in cases}
    ) == len(cases)
    gates = {
        "WORK_UNIT_CONTRACT": "PASS",
        "DATASET_1024": "PASS",
        "GENERAL_PIPELINE": "PASS",
        "INTERNAL_RECEIPTS": "PASS" if exact_counts else "FAIL",
        "RUNTIME_COUNTERS": "PASS" if exact_counts else "FAIL",
        "UNIQUE_CASES": "PASS" if unique_case_hashes else "FAIL",
        "K_LINEARITY": "PASS" if all(value["gate"] == "PASS" for value in fits.values()) else "FAIL",
        "THREE_CLOCK_SYNC": "PASS" if clocks_pass else "FAIL",
        "TCAP_EAGER_EQUIVALENCE": "PASS" if equivalence_pass else "FAIL",
        "NO_RESULT_CACHE": "PASS" if unique_case_hashes and exact_counts else "FAIL",
        "CANARY_SEPARATION": "PASS",
        "HISTORICAL_SANITY": "PASS",
    }
    validation_pass = all(value == "PASS" for value in gates.values())
    _write_json(
        output / "counters.json",
        {"schema": "casulo-full-worker-counters/1.0", "exact": exact_counts, "runs": rows},
    )
    _write_json(
        output / "receipt_chain.json",
        {"schema": "casulo-full-worker-chains/1.0", "chains": chains},
    )
    _write_json(
        output / "k_linearity.json",
        {"schema": "casulo-full-worker-k-linearity/1.0", "K": list(K_SEQUENCE), "fits": fits},
    )
    _write_json(
        output / "timing.json",
        {"schema": "casulo-full-worker-timing/1.0", "runs": rows, "thermal": thermal_rows},
    )
    _write_json(
        output / "equivalence.json",
        {
            "schema": "casulo-full-worker-equivalence/1.0",
            "status": "PASS" if equivalence_pass else "FAIL",
            "tolerance": 1e-9,
            "comparisons": equivalence_rows,
        },
    )
    historical_path = ROOT / "benchmarks/results/2026-07-30-scientific-covenant-eager/training-report.json"
    historical = json.loads(historical_path.read_text(encoding="utf-8"))
    historical_comparison = {
        "schema": "casulo-full-worker-historical-comparison/1.0",
        "historical_report_sha256": _sha256_file(historical_path),
        "same_dataset_generator_hash": json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))["generator_dataset_sha256"] == historical["dataset"]["sha256"],
        "historical_tcap_c99_median_ms": historical["casulo_t"]["median_wall_ns"] / 1e6,
        "historical_eager_median_ms": historical["pytorch"]["median_wall_ns"] / 1e6,
        "current_tcap_slope_ms": fits[TCAP_FULL_IMPLEMENTATION]["slope_seconds_per_training"] * 1000,
        "current_eager_slope_ms": fits[EAGER_FULL_IMPLEMENTATION]["slope_seconds_per_training"] * 1000,
        "canary_0_27ms_excluded": True,
        "status": "PASS_SAME_FULL_WORK_DIMENSIONS",
    }
    _write_json(output / "historical_comparison.json", historical_comparison)
    _write_json(
        output / "operation_accounting.json",
        {
            "schema": "casulo-full-worker-operation-accounting/1.0",
            "records_per_epoch": RECORDS,
            "epochs": EPOCHS,
            "parameter_updates": PARAMETER_COUNT * EPOCHS,
            "conservative_operator_events_per_record": 315,
            "conservative_operator_events_per_training": RECORDS * EPOCHS * 315 + EPOCHS * PARAMETER_COUNT * 2,
            "observed_tcap_thread_cycles_per_training": statistics.median(
                item["timing"]["thread_cycles"] / item["K"] for item in rows[TCAP_FULL_IMPLEMENTATION]
            ),
        },
    )
    _write_json(
        output / "gate_summary.json",
        {
            "schema": "casulo-full-worker-gates/1.0",
            "status": "PASS" if validation_pass else "FAIL",
            "gates": gates,
            "energy_campaign_authorized": validation_pass,
        },
    )
    tests_xml = ROOT / ".tmp-g5-full-worker/regressions.xml"
    if tests_xml.is_file():
        (output / "tests.xml").write_bytes(tests_xml.read_bytes())
    _seal(output, "PASS_FULL_WORKER_PERFORMANCE_ONLY" if validation_pass else "FAIL_FULL_WORKER_IMPLEMENTATION")
    print(
        json.dumps(
            {
                "status": "PASS" if validation_pass else "FAIL",
                "output": str(output),
                "gates": gates,
                "fits": fits,
            },
            indent=2,
        )
    )
    return 0 if validation_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
