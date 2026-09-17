"""Recompose and preserve the invalid 2026-08-07 TCAP energy campaign.

This script is intentionally read-only with respect to the source campaign.  It
does not execute a benchmark and never upgrades a wrapper-reported K into an
observed work counter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from casulo.livelab.energy_v1.hwinfo import inspect_file, integrate_window
from casulo.livelab.energy_v1.hwinfo_campaign import verify_hwinfo_seal
from casulo.livelab.energy_v1.hwinfo_workers import load_workload


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "energy/2026-08-07-g5-hwinfo-thermal-recovery-250ms-90c-start70-kfreeze-fixed"
OUTPUT = ROOT / "outputs/casulo/forensic/2026-08-08-tcap-work-unit-forensic-audit"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def inventory() -> dict[str, Any]:
    seal = verify_hwinfo_seal(SOURCE)
    files = []
    for path in sorted(item for item in SOURCE.rglob("*") if item.is_file()):
        files.append(
            {
                "path": path.relative_to(SOURCE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    tcap = ROOT / "release/FloodSurrogate.tcap"
    code, canary_raw, canary = load_workload(tcap)
    evidence = json.loads((ROOT / "release/FloodSurrogate.evidence.json").read_text(encoding="utf-8"))
    definitive = json.loads((SOURCE / "definitive_worker_build.json").read_text(encoding="utf-8"))
    worker_source = Path(definitive["source"])
    worker_source_text = worker_source.read_text(encoding="utf-8")
    campaign_contract_literals_present = all(
        token in worker_source_text
        for token in ("records: 8", "epochs: 400", "for _ in 0..k", "entry(&mut context)")
    )
    return {
        "schema": "casulo-forensic-original-evidence-inventory/1.0",
        "source_campaign": SOURCE.name,
        "source_campaign_terminal_state": "INCONCLUSIVE_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS",
        "seal_verification": seal,
        "files": files,
        "artifact": {
            "campaign_recorded_tcap": definitive["tcap"],
            "campaign_recorded_tcap_sha256": definitive["tcap_sha256"],
            "campaign_worker_source": definitive["source"],
            "campaign_worker_source_sha256": definitive["source_sha256"],
            "campaign_worker_executable_sha256": definitive["executable_sha256"],
            "campaign_contract_literals_present": campaign_contract_literals_present,
            "current_rebuild_tcap": str(tcap.resolve()),
            "current_rebuild_tcap_sha256": sha256_file(tcap),
            "current_rebuild_is_campaign_artifact": sha256_file(tcap) == definitive["tcap_sha256"],
            "current_rebuild_role": "semantic corroboration only",
            "code_bytes": len(code),
            "canary_bytes": len(canary_raw),
            "canary_records": canary.records,
            "epochs": canary.epochs,
            "records_visited_per_wrapper_unit": canary.records * canary.epochs,
            "required_scientific_records": 1024,
            "required_records_visited": 1024 * 400,
            "fraction_of_required_records": canary.records / 1024,
            "evidence_canary_scope": evidence["canary_scope"],
            "campaign_dataset_sha256": definitive["dataset_sha256"],
            "current_rebuild_canary_sha256": hashlib.sha256(canary_raw).hexdigest(),
            "canary_semantics_match_campaign_dataset_hash": (
                definitive["dataset_sha256"] == hashlib.sha256(canary_raw).hexdigest()
            ),
        },
    }


def recompose_pairs() -> dict[str, Any]:
    _, parsed, inspection = inspect_file(SOURCE / "source_segment.csv")
    frozen = json.loads((SOURCE / "frozen_k.json").read_text(encoding="utf-8"))
    rows = []
    temperature_pairs: list[tuple[float, float]] = []
    for pair_file in sorted((SOURCE / "raw").glob("*-pair-result.json")):
        pair = json.loads(pair_file.read_text(encoding="utf-8"))
        if not pair.get("accepted"):
            continue
        values: dict[str, Any] = {"pair_id": pair["pair_id"], "implementations": {}}
        for implementation, sample in pair["windows"].items():
            start = datetime.fromisoformat(sample["start_utc"])
            end = datetime.fromisoformat(sample["end_utc"])
            integrated = integrate_window(parsed, start, end, minimum_samples=60)
            result = sample["numeric_result"]
            k = int(sample["K"])
            frozen_name = "K_TCAP" if "tcap" in implementation else "K_Eager"
            reported_energy = float(sample["window"]["energy_joules"])
            reported_duration = float(sample["window"]["duration_seconds"])
            integration_passed = integrated.status == "PASS"
            energy = float(integrated.energy_joules) if integration_passed else reported_energy
            duration = float(integrated.duration_seconds) if integration_passed else reported_duration
            average_watts = (
                float(integrated.average_watts)
                if integration_passed
                else float(sample["window"]["average_watts"])
            )
            item = {
                "K_requested": k,
                "K_frozen": int(frozen[frozen_name]),
                "K_dispatched": k,
                "K_started": None,
                "K_completed": None,
                "wrapper_self_reported_K": result.get("K"),
                "epochs_completed": None,
                "optimizer_steps": None,
                "records_visited": None,
                "missing_counter_policy": "not inferred from wrapper K",
                "canary_records_per_epoch": 8,
                "canary_epochs_per_call": result.get("epochs_per_training"),
                "window_seconds": duration,
                "integrated_joules": energy,
                "independent_reintegration": integrated.to_dict(),
                "numeric_source": "independent_csv_reintegration" if integration_passed else "original_recorded_window",
                "average_watts": average_watts,
                "seconds_per_wrapper_call": duration / k,
                "joules_per_wrapper_call": energy / k,
                "worker_elapsed_seconds": result.get("elapsed_seconds"),
                "result_hash": result.get("numeric_output_sha256"),
                "checks": {
                    "reintegration_energy_abs_error_j": abs(energy - reported_energy) if integration_passed else None,
                    "reintegration_duration_abs_error_s": abs(duration - reported_duration) if integration_passed else None,
                    "joules_times_K_abs_error_j": abs((energy / k) * k - energy),
                    "seconds_times_K_abs_error_s": abs((duration / k) * k - duration),
                    "power_times_seconds_abs_error_j": abs(average_watts * duration - energy),
                    "dispatched_matches_wrapper_report": result.get("K") == k,
                    "frozen_matches_dispatched": int(frozen[frozen_name]) == k,
                },
                "temperature": sample["thermal"],
            }
            values["implementations"][implementation] = item
        tcap = values["implementations"]["t-general-ir-tcap/0.1"]
        eager = values["implementations"]["pytorch-eager-fullstep/1"]
        energy_ratio = tcap["joules_per_wrapper_call"] / eager["joules_per_wrapper_call"]
        power_ratio = tcap["average_watts"] / eager["average_watts"]
        time_ratio = tcap["seconds_per_wrapper_call"] / eager["seconds_per_wrapper_call"]
        values["algebra"] = {
            "energy_ratio": energy_ratio,
            "power_ratio": power_ratio,
            "time_ratio": time_ratio,
            "power_ratio_times_time_ratio": power_ratio * time_ratio,
            "identity_abs_error": abs(energy_ratio - power_ratio * time_ratio),
        }
        temperature_pairs.append(
            (tcap["temperature"]["maximum_temperature_c"], eager["temperature"]["maximum_temperature_c"])
        )
        rows.append(values)
    absolute = [abs(t - e) for t, e in temperature_pairs]
    signed = [t - e for t, e in temperature_pairs]
    tcap_maxima = [t for t, _ in temperature_pairs]
    eager_maxima = [e for _, e in temperature_pairs]
    return {
        "schema": "casulo-forensic-pair-recomposition/1.0",
        "source_csv_inspection": inspection,
        "pair_count": len(rows),
        "pairs": rows,
        "thermal_reconciliation": {
            "reported_7c_definition": "abs(median(TCAP maxima) - median(Eager maxima))",
            "reported_7c_value": abs(statistics.median(tcap_maxima) - statistics.median(eager_maxima)),
            "median_paired_absolute_difference_c": statistics.median(absolute),
            "median_paired_signed_difference_c": statistics.median(signed),
            "conclusion": "7 C is reproducible but was ambiguously labelled; 6 C is the paired absolute median",
        },
    }


def gate_artifacts(recomposition: dict[str, Any]) -> None:
    analysis = json.loads((SOURCE / "analysis.json").read_text(encoding="utf-8"))
    historical_path = ROOT / "benchmarks/results/2026-07-30-scientific-covenant-eager/training-report.json"
    historical = json.loads(historical_path.read_text(encoding="utf-8"))
    required_records = 1_024
    epochs = 400
    canary_records = 8
    parameter_count = 81
    write_json(
        OUTPUT / "receipt_chain.json",
        {
            "schema": "casulo-forensic-receipt-chain/1.0",
            "status": "FAIL_NOT_IMPLEMENTED_IN_AFFECTED_WORKER",
            "receipts": 0,
            "aggregate_hash": None,
            "reason": "old worker emitted wrapper K and final output, not per-unit runtime receipts",
        },
    )
    (OUTPUT / "work_receipts.jsonl").write_text("", encoding="utf-8", newline="\n")
    write_json(
        OUTPUT / "k_linearity.json",
        {
            "schema": "casulo-forensic-k-linearity/1.0",
            "status": "NOT_EXECUTED_RECEIPTS_GATE_FAILED",
            "requested_K": [1, 2, 5, 10, 20, 50, 100],
            "R2": None,
            "reason": "F7 is forbidden until a full 1,024-record unit has internal counters and receipts",
        },
    )
    child_parent_differences = []
    for pair in recomposition["pairs"]:
        for implementation, item in pair["implementations"].items():
            child = item["worker_elapsed_seconds"]
            if child is not None:
                child_parent_differences.append(
                    {
                        "pair_id": pair["pair_id"],
                        "implementation": implementation,
                        "window_seconds": item["window_seconds"],
                        "child_seconds": child,
                        "difference_seconds": item["window_seconds"] - child,
                    }
                )
    write_json(
        OUTPUT / "timing_crosscheck.json",
        {
            "schema": "casulo-forensic-timing-crosscheck/1.0",
            "status": "FAIL_THIRD_INDEPENDENT_CLOCK_ABSENT",
            "parent_utc_window_and_child_monotonic": child_parent_differences,
            "query_performance_counter": None,
            "thread_cycles": None,
            "conclusion": "old evidence cannot prove the required three-clock synchronization",
        },
    )
    conservative_record_arithmetic = 315
    conservative_update_arithmetic = parameter_count * 2
    write_json(
        OUTPUT / "operation_accounting.json",
        {
            "schema": "casulo-forensic-operation-accounting/1.0",
            "topology": "8x8x1-relu-mse-sgd-float64-full-batch",
            "epochs": epochs,
            "parameter_count": parameter_count,
            "required": {
                "records": required_records,
                "records_visited": required_records * epochs,
                "optimizer_steps": epochs,
                "parameter_writes": parameter_count * epochs,
                "conservative_arithmetic_operator_events": (
                    required_records * epochs * conservative_record_arithmetic
                    + epochs * conservative_update_arithmetic
                ),
            },
            "affected_canary": {
                "records": canary_records,
                "records_visited": canary_records * epochs,
                "optimizer_steps_by_static_loop": epochs,
                "parameter_writes_by_static_loop": parameter_count * epochs,
                "fraction_of_required_record_work": canary_records / required_records,
                "runtime_counters_observed": False,
            },
        },
    )
    current_tcap_ms = statistics.median(
        item["implementations"]["t-general-ir-tcap/0.1"]["seconds_per_wrapper_call"] * 1000
        for item in recomposition["pairs"]
    )
    current_eager_ms = statistics.median(
        item["implementations"]["pytorch-eager-fullstep/1"]["seconds_per_wrapper_call"] * 1000
        for item in recomposition["pairs"]
    )
    historical_tcap_ms = historical["casulo_t"]["median_wall_ns"] / 1e6
    historical_eager_ms = historical["pytorch"]["median_wall_ns"] / 1e6
    write_json(
        OUTPUT / "historical_comparison.json",
        {
            "schema": "casulo-forensic-historical-comparison/1.0",
            "status": "NOT_THE_SAME_WORKLOAD",
            "current": {
                "route": "raw TCAP bounded correctness canary",
                "records": 8,
                "tcap_median_ms": current_tcap_ms,
                "eager_median_ms": current_eager_ms,
            },
            "historical": {
                "route": "T/C99 OpenMP fused full training",
                "records": historical["dataset"]["records"],
                "tcap_c99_median_ms": historical_tcap_ms,
                "eager_median_ms": historical_eager_ms,
                "paired_speedup": historical["comparison"]["paired_speedup_median"],
                "report_sha256": sha256_file(historical_path),
            },
            "record_ratio": required_records / canary_records,
            "historical_to_canary_tcap_time_ratio": historical_tcap_ms / current_tcap_ms,
            "causal_reconciliation": "record ratio 128x explains nearly all of the approximately 131x route gap",
            "direct_comparison_withdrawn": True,
        },
    )
    write_json(
        OUTPUT / "terminal_state.json",
        {
            "schema": "casulo-forensic-terminal-state/1.0",
            "state": "INVALIDATED_INCOMPLETE_WORK_UNIT",
            "affected_energy_analysis_terminal_state": analysis["terminal_state"],
            "affected_numbers_must_not_be_reused": True,
            "corrected_energy_campaign_started": False,
            "reason": "F10 failed before energy: 8 records, no receipts, no internal counters, no unique cases",
            "gates": {
                "WORK_UNIT_SPEC": "PASS",
                "K_DATAFLOW": "FAIL_WRONG_DIMENSION",
                "K_LINEARITY": "NOT_EXECUTED_RECEIPTS_GATE_FAILED",
                "UNIQUE_CASES": "FAIL_IDENTICAL_CANARY",
                "RECEIPTS": "FAIL_NOT_IMPLEMENTED_IN_AFFECTED_WORKER",
                "SYNCHRONIZATION": "FAIL_THIRD_INDEPENDENT_CLOCK_ABSENT",
                "EQUIVALENCE": "PASS_EIGHT_RECORD_CANARY_ONLY",
                "NO_RESULT_CACHE": "STATIC_CALL_LOOP_PASS_INDEPENDENT_CASES_FAIL",
                "ALGEBRAIC_RECOMPOSITION": "PASS_20_PAIRS_ONE_COVERAGE_EXCEPTION",
            },
        },
    )


def seal() -> dict[str, Any]:
    files = []
    for path in sorted(item for item in OUTPUT.rglob("*") if item.is_file() and item.name not in {"MANIFEST.json", "SHA256SUMS"}):
        files.append({"path": path.relative_to(OUTPUT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {
        "schema": "casulo-forensic-manifest/1.0",
        "campaign_id": OUTPUT.name,
        "terminal_state": "INVALIDATED_INCOMPLETE_WORK_UNIT",
        "files": files,
    }
    write_json(OUTPUT / "MANIFEST.json", manifest)
    lines = [f"{item['sha256']}  {item['path']}" for item in files]
    lines.append(f"{sha256_file(OUTPUT / 'MANIFEST.json')}  MANIFEST.json")
    (OUTPUT / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return manifest


def main() -> int:
    global OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    OUTPUT = args.output.resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT / "original_evidence_inventory.json", inventory())
    recomposition = recompose_pairs()
    write_json(OUTPUT / "pair_recomposition.json", recomposition)
    gate_artifacts(recomposition)
    seal()
    print(json.dumps({"status": "INVALIDATED_INCOMPLETE_WORK_UNIT", "output": str(OUTPUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
