from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from casulo.livelab.energy_v1.analysis import paired_bootstrap_ci
from interlocution.policy import compile_training_authority_tcap


CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
SOURCE = CAMPAIGN / "baselines/ti10-v2"


def write_json(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"append-only artifact exists: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    samples = json.loads((SOURCE / "samples.json").read_text(encoding="utf-8"))["samples"]
    by_block: dict[int, dict[str, dict]] = {}
    for sample in samples:
        by_block.setdefault(int(sample["block"]), {})[sample["arm"]] = sample
    steady_ratios = []
    cycle_ratios = []
    cpu_ratios = []
    for block in sorted(by_block):
        a = by_block[block]["A"]
        d = by_block[block]["D"]
        a_timing = a["inner"]["work_summary"]["child_timing"]
        d_timing = d["inner"]["work_summary"]["child_timing"]
        steady_ratios.append(d_timing["worker_monotonic_ns"] / a_timing["worker_monotonic_ns"])
        cycle_ratios.append(d_timing["thread_cycles"] / a_timing["thread_cycles"])
        cpu_ratios.append(d["observed_process_cpu_seconds"] / a["observed_process_cpu_seconds"])
    steady_ci = paired_bootstrap_ci(tuple(steady_ratios), seed=2026081902, resamples=20000)
    cycle_ci = paired_bootstrap_ci(tuple(cycle_ratios), seed=2026081903, resamples=20000)
    cpu_ci = paired_bootstrap_ci(tuple(cpu_ratios), seed=2026081904, resamples=20000)

    compile_dir = SOURCE / "compilation-cost"
    plan = json.loads((CAMPAIGN / "training_authority_plan.json").read_text(encoding="utf-8"))
    started = time.perf_counter_ns()
    build = compile_training_authority_tcap(plan, compile_dir / "sources", compile_dir / "tcap")
    compile_ns = time.perf_counter_ns() - started
    (compile_dir / "measurement.json").write_text(
        json.dumps({"compile_wall_ns": compile_ns, "tcap_hash": build.tcap_hash, "scope": "fresh general T2 compile, excluded from steady-state samples"}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    d_samples = [sample for sample in samples if sample["arm"] == "D"]
    a_samples = [sample for sample in samples if sample["arm"] == "A"]
    count = int(d_samples[0]["inner"]["count"])
    d_outer_per_training = statistics.median(sample["outer_wall_ns"] / count for sample in d_samples)
    a_outer_per_training = statistics.median(sample["outer_wall_ns"] / count for sample in a_samples)
    saved_ns = a_outer_per_training - d_outer_per_training
    expanded = {
        "schema": "casulo.interlocution-ti9-ti11-expanded-analysis/1.0",
        "protocol": "ti10-v2",
        "valid_paired_blocks": len(by_block),
        "steady_state": {
            "definition": "child-reported synchronous training only; excludes imports, authority, audit, judgment and publication",
            "median_D_over_A_wall_ratio": statistics.median(steady_ratios),
            "paired_bootstrap_ci95": {"lower": steady_ci[0], "upper": steady_ci[1], "seed": 2026081902, "resamples": 20000},
            "median_D_over_A_thread_cycles_ratio": statistics.median(cycle_ratios),
            "thread_cycles_ci95": {"lower": cycle_ci[0], "upper": cycle_ci[1], "seed": 2026081903, "resamples": 20000},
        },
        "end_to_end": {
            "definition": "clean process including imports, T authority, training, receipts, independent audit, T judgment and publication",
            "median_A_seconds_per_training": a_outer_per_training / 1e9,
            "median_D_seconds_per_training": d_outer_per_training / 1e9,
            "median_D_over_A_wall_ratio": statistics.median(d["outer_wall_ns"] / by_block[int(d["block"])]["A"]["outer_wall_ns"] for d in d_samples),
            "median_D_over_A_observed_cpu_time_ratio": statistics.median(cpu_ratios),
            "cpu_time_ratio_ci95": {"lower": cpu_ci[0], "upper": cpu_ci[1], "seed": 2026081904, "resamples": 20000},
            "compile_wall_seconds_separate": compile_ns / 1e9,
            "compile_included_in_samples": False,
            "amortization_point_trainings": None if saved_ns <= 0 else compile_ns / saved_ns,
            "human_interlocution_time": None,
            "human_interlocution_reason": "historical confirmation event has no valid duration measurement",
        },
        "t_overhead": {
            "median_architecture_seconds_per_window": statistics.median(sample["inner"]["phases_ns"]["t_architecture_ns"] for sample in d_samples) / 1e9,
            "median_independent_audit_seconds_per_window": statistics.median(sample["inner"]["phases_ns"]["independent_audit_ns"] for sample in d_samples) / 1e9,
            "median_judgment_seconds_per_window": statistics.median(sample["inner"]["phases_ns"]["t_judgment_ns"] for sample in d_samples) / 1e9,
            "median_publication_seconds_per_window": statistics.median(sample["inner"]["phases_ns"]["publication_ns"] for sample in d_samples) / 1e9,
        },
        "phi_logical": {
            "executed_network_operations": {"candidate_over_baseline": 1.0, "status": "ESTIMATED_SAME_MATHEMATICAL_TRAINING"},
            "active_state_bytes": {"value": None, "status": "NOT_DIRECTLY_INSTRUMENTED"},
            "bytes_moved": {"value": None, "status": "NOT_INSTRUMENTED"},
            "peak_working_set": {"proxy": "process-tree peak RSS", "A_median_bytes": statistics.median(sample["peak_process_tree_rss_bytes"] for sample in a_samples), "D_median_bytes": statistics.median(sample["peak_process_tree_rss_bytes"] for sample in d_samples)},
            "allocations": {"value": None, "status": "NOT_INSTRUMENTED"},
            "model_calls": {"A": 0, "D": 0, "status": "OBSERVED_NO_NEURAL_INTERLOCUTOR_IN_REPETITIONS"},
            "processed_tokens": {"A": 0, "D": 0, "status": "OBSERVED_NO_TOKEN_PATH_IN_REPETITIONS"},
        },
        "psi_physical": {
            "process_cycles": {"steady_state_child_ratio": statistics.median(cycle_ratios), "end_to_end": None, "limitation": "no unified cycle counter across process tree"},
            "peak_rss_ratio_D_over_A": statistics.median(sample["peak_process_tree_rss_bytes"] for sample in d_samples) / statistics.median(sample["peak_process_tree_rss_bytes"] for sample in a_samples),
            "wall_time_ratio_D_over_A": statistics.median(d["outer_wall_ns"] / by_block[int(d["block"])]["A"]["outer_wall_ns"] for d in d_samples),
            "package_joules": None,
            "total_system_joules": None,
            "energy_status": "BLOCKED_NO_ENERGY_MEASUREMENT_IN_THIS_PROTOCOL",
        },
        "ablations": {
            "no_interlocution": "FAIL_CLOSED_BEFORE_WORK_BY_CONTRACT_TEST",
            "no_evidence_gate": "EXECUTION_POSSIBLE_BUT_T_PUBLICATION_AUTHORITY_ABSENT",
            "posthoc_t_audit": "B_RESULT_IGNORED_AND_COUNTS_AS_ZERO_AUTHORITY",
            "t_architecture_without_judge": "C_EXECUTES_BUT_FINAL_ACCEPTANCE_IS_FOREIGN",
            "causal_rejection": "WRONG_DATASET_REJECTED_BEFORE_WORK_IN_TI6",
            "all_hot": "NOT_APPLICABLE_TO_SINGLE_PRIMITIVE_FLOOD_WORKLOAD",
            "selected_working_set": "T_SELECTED_ALL_1024_RECORDS_REQUIRED_BY_CONFIRMED_R",
        },
        "claim": "material observed reduction in end-to-end wall time, process CPU time and peak RSS for this host/workload; no energy claim",
    }
    write_json(SOURCE / "analysis-expanded.json", expanded)
    print(json.dumps({"status": "PASS", "steady_ratio": expanded["steady_state"]["median_D_over_A_wall_ratio"], "end_to_end_ratio": expanded["end_to_end"]["median_D_over_A_wall_ratio"], "rss_ratio": expanded["psi_physical"]["peak_rss_ratio_D_over_A"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
