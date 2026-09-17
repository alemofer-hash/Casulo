from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from typing import Any, Iterable

from .schemas import ANALYSIS_SCHEMA, TERMINAL_STATES, validate_sample


def paired_bootstrap_ci(
    ratios: tuple[float, ...],
    *,
    seed: int,
    resamples: int = 20_000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    if len(ratios) < 2 or not 100 <= resamples <= 1_000_000:
        raise ValueError("paired bootstrap requires >=2 ratios and >=100 resamples")
    if not 0.5 < confidence < 1.0:
        raise ValueError("invalid bootstrap confidence")
    if any(not math.isfinite(item) or item < 0 for item in ratios):
        raise ValueError("ratios must be finite and nonnegative")
    rng = random.Random(seed)
    n = len(ratios)
    medians = sorted(statistics.median(ratios[rng.randrange(n)] for _ in range(n)) for _ in range(resamples))
    alpha = (1.0 - confidence) / 2.0
    low = medians[max(0, math.floor(alpha * (resamples - 1)))]
    high = medians[min(resamples - 1, math.ceil((1.0 - alpha) * (resamples - 1)))]
    return float(low), float(high)


def exact_sign_test(candidate_values: Iterable[float], baseline_values: Iterable[float]) -> dict[str, Any]:
    candidate = tuple(candidate_values)
    baseline = tuple(baseline_values)
    if len(candidate) != len(baseline):
        raise ValueError("paired sign test cardinality differs")
    wins = sum(left < right for left, right in zip(candidate, baseline))
    losses = sum(left > right for left, right in zip(candidate, baseline))
    ties = len(candidate) - wins - losses
    n = wins + losses
    if n == 0:
        p_value = 1.0
    else:
        k = min(wins, losses)
        tail = sum(math.comb(n, index) for index in range(k + 1)) / (2**n)
        p_value = min(1.0, 2.0 * tail)
    return {"wins": wins, "losses": losses, "ties": ties, "nonties": n, "two_sided_p_value": p_value}


def analyze_campaign(
    samples: tuple[dict[str, Any], ...],
    *,
    campaign_id: str,
    candidate: str,
    baseline: str,
    energy_domain: str,
    expected_sessions: int,
    expected_pairs_per_session: int,
    bootstrap_seed: int,
    bootstrap_resamples: int = 20_000,
) -> dict[str, Any]:
    rejected = []
    accepted = []
    for sample in samples:
        try:
            validate_sample(sample)
        except Exception as exc:
            rejected.append({"pair_id": sample.get("pair_id"), "implementation": sample.get("implementation"), "reason": f"schema:{exc}"})
            continue
        if sample["campaign_id"] != campaign_id or sample["energy_domain"] != energy_domain:
            rejected.append({"pair_id": sample["pair_id"], "implementation": sample["implementation"], "reason": "campaign_or_domain_mismatch"})
            continue
        if not sample["accepted"]:
            rejected.append({"pair_id": sample["pair_id"], "implementation": sample["implementation"], "reason": sample["reason_code"]})
            continue
        if sample["equivalence"].get("status") != "PASS":
            rejected.append({"pair_id": sample["pair_id"], "implementation": sample["implementation"], "reason": "equivalence_not_pass"})
            continue
        accepted.append(sample)
    by_pair: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for sample in accepted:
        key = (sample["session_id"], sample["pair_id"])
        implementation = sample["implementation"]
        if implementation in by_pair[key]:
            rejected.append({"pair_id": sample["pair_id"], "implementation": implementation, "reason": "duplicate_sample"})
            continue
        by_pair[key][implementation] = sample
    pairs = []
    for (session_id, pair_id), values in sorted(by_pair.items()):
        if set(values) != {candidate, baseline}:
            rejected.append({"pair_id": pair_id, "implementation": None, "reason": "incomplete_pair"})
            continue
        c = values[candidate]
        b = values[baseline]
        c_jpt = c["energy_delta_joules"] / c["K"]
        b_jpt = b["energy_delta_joules"] / b["K"]
        if b_jpt <= 0:
            rejected.append({"pair_id": pair_id, "implementation": baseline, "reason": "baseline_zero_energy"})
            continue
        pairs.append({
            "session_id": session_id,
            "pair_id": pair_id,
            "candidate_joules_per_training": c_jpt,
            "baseline_joules_per_training": b_jpt,
            "candidate_seconds_per_training": c["elapsed_seconds"] / c["K"],
            "baseline_seconds_per_training": b["elapsed_seconds"] / b["K"],
            "ratio_candidate_over_baseline": c_jpt / b_jpt,
            "candidate_raw_joules": c["energy_delta_joules"],
            "baseline_raw_joules": b["energy_delta_joules"],
        })
    expected_pairs = expected_sessions * expected_pairs_per_session
    complete = len(pairs) == expected_pairs and len({item["session_id"] for item in pairs}) == expected_sessions
    ratios = tuple(item["ratio_candidate_over_baseline"] for item in pairs)
    session_medians = {}
    for session in sorted({item["session_id"] for item in pairs}):
        session_medians[session] = statistics.median(item["ratio_candidate_over_baseline"] for item in pairs if item["session_id"] == session)
    if ratios:
        median_ratio = statistics.median(ratios)
        ci = paired_bootstrap_ci(ratios, seed=bootstrap_seed, resamples=bootstrap_resamples) if len(ratios) >= 2 else None
        sign = exact_sign_test(
            (item["candidate_joules_per_training"] for item in pairs),
            (item["baseline_joules_per_training"] for item in pairs),
        )
    else:
        median_ratio = None
        ci = None
        sign = None
    all_sessions_below_one = bool(session_medians) and all(value < 1.0 for value in session_medians.values())
    advantage = bool(complete and median_ratio is not None and median_ratio < 1.0 and ci and ci[1] < 1.0 and all_sessions_below_one)
    if not complete:
        terminal = "BLOCKED_PHYSICAL_INSTRUMENT"
    elif advantage and energy_domain == "TOTAL_SYSTEM_WALL":
        terminal = "PASS_TOTAL_SYSTEM_ENERGY"
    elif advantage and energy_domain == "CPU_PACKAGE_RAPL":
        terminal = "PASS_CPU_PACKAGE_ENERGY"
    else:
        terminal = "FAIL_NO_ENERGY_ADVANTAGE"
    assert terminal in TERMINAL_STATES
    improvement = None if median_ratio is None else 1.0 - median_ratio
    implementation_summary = {}
    for name, prefix in ((candidate, "candidate"), (baseline, "baseline")):
        if not pairs:
            implementation_summary[name] = None
            continue
        joules_per_training = [item[f"{prefix}_joules_per_training"] for item in pairs]
        seconds_per_training = [item[f"{prefix}_seconds_per_training"] for item in pairs]
        raw_joules = [item[f"{prefix}_raw_joules"] for item in pairs]
        implementation_summary[name] = {
            "median_raw_joules_per_window": statistics.median(raw_joules),
            "median_joules_per_training": statistics.median(joules_per_training),
            "median_seconds_per_training": statistics.median(seconds_per_training),
            "median_average_watts": statistics.median(
                raw / (seconds * (next_sample_k(samples, name) or 1))
                for raw, seconds in zip(raw_joules, seconds_per_training)
                if seconds > 0
            ),
        }
    compilation_scopes = sorted({bool(item.get("compilation_included")) for item in accepted})
    idle_incremental = [
        item["energy_delta_joules"] - item["idle_energy_joules"]
        for item in accepted
        if isinstance(item.get("idle_energy_joules"), (int, float))
    ]
    return {
        "schema": ANALYSIS_SCHEMA,
        "campaign_id": campaign_id,
        "energy_domain": energy_domain,
        "candidate": candidate,
        "baseline": baseline,
        "expected_pairs": expected_pairs,
        "valid_pairs": len(pairs),
        "complete_confirmatory_design": complete,
        "pairs": pairs,
        "rejected": rejected,
        "median_ratio_candidate_over_baseline": median_ratio,
        "paired_bootstrap_ci95": {"lower": ci[0], "upper": ci[1], "seed": bootstrap_seed, "resamples": bootstrap_resamples} if ci else None,
        "exact_sign_test": sign,
        "session_median_ratios": session_medians,
        "direction_consistent_across_sessions": all_sessions_below_one,
        "relative_improvement": improvement,
        "material_improvement_at_least_10_percent": bool(improvement is not None and improvement >= 0.10),
        "implementation_summary": implementation_summary,
        "power_mean_definition": "raw_joules / measured_window_seconds",
        "incremental_energy_over_idle_secondary": {
            "status": "available" if idle_incremental else "unavailable",
            "values_joules": idle_incremental,
            "never_primary": True,
        },
        "compilation": {
            "observed_scopes": ["included" if item else "excluded" for item in compilation_scopes],
            "included_and_excluded_are_distinct_campaign_metrics": True,
            "amortization_point_trainings": None,
            "reason": "requires paired physical campaigns with compilation included and excluded" if len(compilation_scopes) < 2 else "derive only from matched campaign-level scopes",
        },
        "advantage_gate_passed": advantage,
        "terminal_state": terminal,
        "claims": {
            "scope": "total system energy" if energy_domain == "TOTAL_SYSTEM_WALL" else "CPU package energy",
            "inductor_superiority": False,
            "historical_8_957846x_attributed_to_casulo_os": False,
            "outliers_removed": False,
        },
    }


def next_sample_k(samples: tuple[dict[str, Any], ...], implementation: str) -> int | None:
    for sample in samples:
        if sample.get("implementation") == implementation and isinstance(sample.get("K"), int):
            return sample["K"]
    return None
