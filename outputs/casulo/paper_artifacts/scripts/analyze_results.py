from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "paper_artifacts" / "generated" / "benchmarks"

REPORTS = {
    "pytorch_eager": ROOT
    / "benchmarks/results/2026-07-30-scientific-covenant-eager/training-report.json",
    "pytorch_inductor": ROOT
    / "benchmarks/results/2026-07-30-scientific-covenant-compile/training-report.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mean_ci(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return values[0], values[0]
    mean = statistics.fmean(values)
    sem = statistics.stdev(values) / math.sqrt(len(values))
    # Descriptive normal approximation; the paired bootstrap below is the
    # inferential interval used for speedup.
    return mean - 1.96 * sem, mean + 1.96 * sem


def bootstrap_median_ci(
    values: list[float], *, seed: int, resamples: int
) -> tuple[float, float]:
    rng = random.Random(seed)
    medians = sorted(
        statistics.median(rng.choices(values, k=len(values)))
        for _ in range(resamples)
    )
    return (
        medians[math.floor(0.025 * (resamples - 1))],
        medians[math.floor(0.975 * (resamples - 1))],
    )


def two_sided_sign_test(successes: int, trials: int) -> float:
    tail = sum(math.comb(trials, k) for k in range(0, successes + 1)) / 2**trials
    mirrored = min(successes, trials - successes)
    tail = sum(math.comb(trials, k) for k in range(0, mirrored + 1)) / 2**trials
    return min(1.0, 2.0 * tail)


def summarize_report(label: str, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    candidate = [float(x) for x in report["casulo_t"]["wall_ns_samples"]]
    baseline = [float(x) for x in report["pytorch"]["wall_ns_samples"]]
    if len(candidate) != len(baseline):
        raise ValueError(f"{label}: amostras não pareadas")
    ratios = [b / c for b, c in zip(baseline, candidate, strict=True)]
    reported = [float(x) for x in report["comparison"]["paired_speedup_samples"]]
    if any(not math.isclose(a, b, rel_tol=1e-12) for a, b in zip(ratios, reported, strict=True)):
        raise ValueError(f"{label}: ratios brutos divergem do relatório")

    ci = report["comparison"]["paired_speedup_ci95"]
    recomputed_ci = bootstrap_median_ci(
        ratios,
        seed=int(ci["seed"]),
        resamples=int(ci["resamples"]),
    )
    reported_ci = (float(ci["lower"]), float(ci["upper"]))
    ci_matches = all(
        math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12)
        for actual, expected in zip(recomputed_ci, reported_ci, strict=True)
    )

    positive = sum(value > 1.0 for value in ratios)
    log_ratios = [math.log(value) for value in ratios]
    candidate_mean_ci = mean_ci(candidate)
    baseline_mean_ci = mean_ci(baseline)
    summary = {
        "label": label,
        "source": path.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(path),
        "historical_measurement": True,
        "current_execution_reproduced_performance": False,
        "baseline_name": report["baseline"]["name"],
        "baseline_version": report["baseline"]["version"],
        "baseline_threads": report["baseline"]["threads"],
        "candidate_backend": report["outcomes"]["casulo_t"]["backend"],
        "samples": len(ratios),
        "warmups": int(report["scientific"]["bound_design"]["warmups"]),
        "candidate_median_wall_ns": statistics.median(candidate),
        "candidate_mean_wall_ns": statistics.fmean(candidate),
        "candidate_stdev_wall_ns": statistics.stdev(candidate),
        "candidate_mean_ci95_normal_ns": list(candidate_mean_ci),
        "baseline_median_wall_ns": statistics.median(baseline),
        "baseline_mean_wall_ns": statistics.fmean(baseline),
        "baseline_stdev_wall_ns": statistics.stdev(baseline),
        "baseline_mean_ci95_normal_ns": list(baseline_mean_ci),
        "paired_speedup_median": statistics.median(ratios),
        "paired_speedup_mean": statistics.fmean(ratios),
        "paired_speedup_ci95_bootstrap": list(recomputed_ci),
        "reported_ci95": list(reported_ci),
        "reported_statistics_reproduced": ci_matches,
        "ratio_of_medians": statistics.median(baseline) / statistics.median(candidate),
        "all_pairs_favor_candidate": positive == len(ratios),
        "two_sided_exact_sign_test_p": two_sided_sign_test(positive, len(ratios)),
        "mean_log_ratio": statistics.fmean(log_ratios),
        "paired_log_ratio_effect_dz": statistics.fmean(log_ratios) / statistics.stdev(log_ratios),
        "equivalent_training": bool(report["quality"]["equivalent_training"]),
        "quality_target_reached": bool(report["quality"]["quality_target_reached"]),
        "parameter_max_abs_difference": report["quality"]["parameter_max_abs_difference"],
        "prediction_max_abs_difference": report["quality"]["prediction_max_abs_difference"],
        "validation_loss_difference": report["quality"]["validation_loss_difference"],
        "electrical_energy_measured": bool(report["energy"]["electrical_energy_measured"]),
        "energy_joules": report["energy"]["joules"],
        "model": report["model"],
        "dataset": report["dataset"],
        "environment": report["environment"],
        "limitations": [
            "single historical host and measurement session",
            "small synthetic CPU-only full-batch MLP",
            "float64, one selected worker, in-memory data",
            "no electrical energy measurement",
            "no current independent performance rerun",
            "speedup cannot be generalized beyond this workload and configuration",
        ],
    }
    rows = [
        {
            "comparison": label,
            "sample_index": index,
            "candidate_wall_ns": int(candidate_wall),
            "baseline_wall_ns": int(baseline_wall),
            "paired_speedup": ratio,
            "excluded": False,
            "exclusion_reason": "",
        }
        for index, (candidate_wall, baseline_wall, ratio) in enumerate(
            zip(candidate, baseline, ratios, strict=True)
        )
    ]
    return summary, rows


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_svg(path: Path, summaries: list[dict[str, Any]]) -> None:
    width, height = 920, 500
    margin = 80
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    max_value = max(
        value
        for summary in summaries
        for value in summary["paired_speedup_ci95_bootstrap"]
    ) * 1.08
    colors = ["#2166ac", "#b2182b"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#111}.axis{stroke:#333;stroke-width:1.5}.grid{stroke:#ddd;stroke-width:1}</style>',
        '<text x="460" y="34" text-anchor="middle" font-size="20">Historical paired speedup on FloodSurrogate</text>',
        '<text x="460" y="58" text-anchor="middle" font-size="13">median and paired-bootstrap 95% CI; no energy claim</text>',
    ]
    for tick in range(0, math.ceil(max_value) + 1, 2):
        x = margin + plot_w * tick / max_value
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{margin}" x2="{x:.1f}" y2="{height-margin}"/>')
        parts.append(f'<text x="{x:.1f}" y="{height-margin+24}" text-anchor="middle" font-size="12">{tick}×</text>')
    parts.append(f'<line class="axis" x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}"/>')
    for idx, (summary, color) in enumerate(zip(summaries, colors, strict=True)):
        y = 175 + idx * 145
        low, high = summary["paired_speedup_ci95_bootstrap"]
        med = summary["paired_speedup_median"]
        x0 = margin + plot_w * low / max_value
        x1 = margin + plot_w * high / max_value
        xm = margin + plot_w * med / max_value
        label = "PyTorch Eager" if "eager" in summary["label"] else "PyTorch Inductor (warmed)"
        parts.extend(
            [
                f'<text x="{margin}" y="{y-28}" font-size="15">{label}</text>',
                f'<line x1="{x0:.1f}" y1="{y}" x2="{x1:.1f}" y2="{y}" stroke="{color}" stroke-width="8" stroke-linecap="round"/>',
                f'<circle cx="{xm:.1f}" cy="{y}" r="9" fill="{color}"/>',
                f'<text x="{xm:.1f}" y="{y-15}" text-anchor="middle" font-size="13">{med:.3f}× [{low:.3f}, {high:.3f}]</text>',
            ]
        )
    parts.append(f'<line x1="{margin + plot_w/max_value:.1f}" y1="{margin}" x2="{margin + plot_w/max_value:.1f}" y2="{height-margin}" stroke="#111" stroke-dasharray="5 5"/>')
    parts.append('</svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for label, path in REPORTS.items():
        summary, sample_rows = summarize_report(label, path)
        summaries.append(summary)
        rows.extend(sample_rows)

    (OUT / "processed").mkdir(exist_ok=True)
    (OUT / "figures").mkdir(exist_ok=True)
    (OUT / "tables").mkdir(exist_ok=True)
    (OUT / "processed" / "historical_training_statistics.json").write_text(
        json.dumps({"comparisons": summaries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(OUT / "processed" / "historical_training_samples.csv", rows)
    table_rows = [
        {
            "baseline": item["baseline_name"],
            "n": item["samples"],
            "candidate_median_ms": item["candidate_median_wall_ns"] / 1e6,
            "baseline_median_ms": item["baseline_median_wall_ns"] / 1e6,
            "paired_speedup_median": item["paired_speedup_median"],
            "ci95_low": item["paired_speedup_ci95_bootstrap"][0],
            "ci95_high": item["paired_speedup_ci95_bootstrap"][1],
            "equivalence": item["equivalent_training"],
            "energy_measured": item["electrical_energy_measured"],
        }
        for item in summaries
    ]
    write_csv(OUT / "tables" / "training_summary.csv", table_rows)
    write_svg(OUT / "figures" / "historical_training_speedup.svg", summaries)
    print(json.dumps({"status": "OK", "comparisons": summaries}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
