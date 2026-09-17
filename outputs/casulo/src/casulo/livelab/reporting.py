from __future__ import annotations

import csv
import json
from pathlib import Path

from .campaign import CampaignResult


def write_campaign_reports(result: CampaignResult, output_directory: Path) -> dict[str, Path]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "campaign.json"
    csv_path = output / "trials.csv"
    markdown_path = output / "report.md"
    payload = result.to_dict()
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "pair_index", "order_in_pair", "label", "elapsed_ns", "energy_joules",
            "maximum_temperature_c", "output_digest", "compile_elapsed_ns",
            "phase_timings_ns", "power_state_signature", "exclusion_reason",
            "evidence_kind",
        ))
        writer.writeheader()
        for trial in result.trials:
            row = {**trial.to_dict(), "evidence_kind": result.spec.evidence_kind}
            row["phase_timings_ns"] = json.dumps(row["phase_timings_ns"], sort_keys=True, separators=(",", ":"))
            writer.writerow(row)
    markdown_path.write_text(_markdown(result), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": markdown_path}


def _markdown(result: CampaignResult) -> str:
    lines = [
        f"# LiveLab campaign `{result.spec.campaign_id}`",
        "",
        f"Status: **{result.status.value}**",
        "",
        f"Evidence kind: **{result.spec.evidence_kind}**",
        "",
        f"Workload started: **{'yes' if result.workload_started else 'no'}**",
        "",
        "## Preflight gates",
        "",
        "| Gate | Status | Reason |",
        "|---|---|---|",
    ]
    for gate in result.preflight.gates:
        lines.append(f"| {gate.gate} | {gate.status.value} | `{gate.reason_code}` |")
    lines.extend(("", "## Result", ""))
    aggregates = result.to_dict()["aggregates"]
    if result.spec.evidence_kind == "synthetic":
        lines.extend(("**SYNTHETIC DATA: reporting/statistics test only; not benchmark evidence.**", ""))
    if aggregates is None:
        lines.append("No comparative estimate was produced. Missing or failed gates are not converted into measurements.")
    else:
        lines.extend((
            f"- Trials per label: {aggregates['trial_count_per_label']}",
            f"- Median paired speedup (baseline/candidate): {aggregates['speedup_baseline_over_candidate']:.6g}x",
            f"- Energy ratio: {aggregates['energy_ratio_baseline_over_candidate'] if aggregates['energy_ratio_baseline_over_candidate'] is not None else 'unavailable'}",
            f"- Valid pairs: {aggregates['valid_pair_count']} (minimum for inference: {aggregates['minimum_main_pairs']})",
            f"- Statistical claim: {aggregates['scientific_claim']}",
        ))
        if aggregates["paired_ratio_ci95"] is not None:
            ci = aggregates["paired_ratio_ci95"]
            lines.append(f"- Seeded paired bootstrap CI95: [{ci['low']:.6g}, {ci['high']:.6g}] (seed={ci['seed']}, resamples={ci['resamples']})")
        if aggregates["paired_exact_sign_test"] is not None:
            sign = aggregates["paired_exact_sign_test"]
            lines.append(f"- Exact sign test: wins={sign['wins']}, losses={sign['losses']}, ties={sign['ties']}, two-sided p={sign['p_value']:.6g}")
        lines.extend((
            f"- Compile cost totals (ns): {json.dumps(aggregates['compile_elapsed_ns_total'], sort_keys=True)}",
            f"- Compile amortization count: {aggregates['compile_amortization_runs']}",
            f"- Amortized speedup: {aggregates['amortized_speedup_baseline_over_candidate']:.6g}x",
        ))
        if aggregates["scientific_claim"].startswith("descriptive_only"):
            lines.append("- Interpretation: descriptive only; no significance inference.")
    if result.abort_reason:
        lines.extend(("", f"Abort reason: `{result.abort_reason}`"))
    return "\n".join(lines) + "\n"
