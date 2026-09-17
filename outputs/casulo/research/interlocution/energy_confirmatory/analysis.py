from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from typing import Any, Iterable


K_FIELDS = ("K_requested", "K_frozen", "K_dispatched", "K_started", "K_completed")


def validate_arm_sample(sample: dict[str, Any]) -> None:
    missing = [name for name in K_FIELDS if name not in sample]
    if missing:
        raise ValueError(f"missing work counters: {','.join(missing)}")
    values = [sample[name] for name in K_FIELDS]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
        raise ValueError("K counters must be positive integers")
    if len(set(values)) != 1:
        raise ValueError("requested/frozen/dispatched/started/completed work differs")
    completed = sample["K_completed"]
    if sample.get("receipt_count") != completed:
        raise ValueError("receipt count differs from completed work")
    expected = {
        "epochs_completed": 400 * completed,
        "optimizer_steps": 400 * completed,
        "records_visited": 409_600 * completed,
    }
    for name, value in expected.items():
        if sample.get(name) != value:
            raise ValueError(f"scientific work counter mismatch: {name}")
    for name in ("energy_joules", "elapsed_seconds"):
        value = sample.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid positive metric: {name}")
    if sample.get("equivalence") != "PASS":
        raise ValueError("equivalence did not pass")
    if sample.get("accepted") is not True:
        raise ValueError("sample is not accepted")


def hierarchical_paired_bootstrap(
    pairs: Iterable[dict[str, Any]],
    *,
    seed: int,
    resamples: int = 20_000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    rows = tuple(pairs)
    if len(rows) < 2:
        raise ValueError("hierarchical bootstrap requires at least two pairs")
    if not 100 <= resamples <= 1_000_000 or not 0.5 < confidence < 1:
        raise ValueError("invalid bootstrap configuration")
    hierarchy: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        ratio = row.get("ratio_candidate_over_baseline")
        if not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio < 0:
            raise ValueError("invalid pair ratio")
        hierarchy[str(row["host_id"])][str(row["session_id"])].append(float(ratio))
    hosts = sorted(hierarchy)
    rng = random.Random(seed)
    boot = []
    for _ in range(resamples):
        replicate: list[float] = []
        for _host_index in hosts:
            host = hosts[rng.randrange(len(hosts))]
            sessions = sorted(hierarchy[host])
            for _session_index in sessions:
                session = sessions[rng.randrange(len(sessions))]
                values = hierarchy[host][session]
                replicate.extend(values[rng.randrange(len(values))] for _ in values)
        boot.append(statistics.median(replicate))
    boot.sort()
    alpha = (1 - confidence) / 2
    low = boot[max(0, math.floor(alpha * (resamples - 1)))]
    high = boot[min(resamples - 1, math.ceil((1 - alpha) * (resamples - 1)))]
    return float(low), float(high)


def analyze_confirmatory_campaign(
    samples: Iterable[dict[str, Any]],
    *,
    candidate: str,
    baseline: str,
    expected_hosts: int,
    expected_cpu_families: int,
    expected_labs: int,
    expected_workloads: int,
    expected_pairs_per_host_workload: int,
    bootstrap_seed: int,
    bootstrap_resamples: int = 20_000,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for sample in samples:
        try:
            validate_arm_sample(sample)
        except ValueError as error:
            rejected.append({"sample_id": sample.get("sample_id"), "reason": str(error)})
        else:
            accepted.append(sample)
    grouped: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for sample in accepted:
        key = (
            str(sample["host_id"]),
            str(sample["workload_id"]),
            str(sample["session_id"]),
            str(sample["pair_id"]),
        )
        implementation = str(sample["implementation"])
        if implementation in grouped[key]:
            rejected.append({"sample_id": sample.get("sample_id"), "reason": "duplicate arm in pair"})
        else:
            grouped[key][implementation] = sample
    pairs: list[dict[str, Any]] = []
    for key, arms in sorted(grouped.items()):
        if set(arms) != {candidate, baseline}:
            rejected.append({"pair": key, "reason": "incomplete pair"})
            continue
        left, right = arms[candidate], arms[baseline]
        candidate_jpt = left["energy_joules"] / left["K_completed"]
        baseline_jpt = right["energy_joules"] / right["K_completed"]
        pairs.append(
            {
                "host_id": key[0],
                "workload_id": key[1],
                "session_id": key[2],
                "pair_id": key[3],
                "cpu_family": left["cpu_family"],
                "lab_id": left["lab_id"],
                "candidate_joules_per_training": candidate_jpt,
                "baseline_joules_per_training": baseline_jpt,
                "ratio_candidate_over_baseline": candidate_jpt / baseline_jpt,
            }
        )
    hosts = {row["host_id"] for row in pairs}
    families = {row["cpu_family"] for row in pairs}
    labs = {row["lab_id"] for row in pairs}
    workloads = {row["workload_id"] for row in pairs}
    pair_counts: dict[str, int] = defaultdict(int)
    for row in pairs:
        pair_counts[f"{row['host_id']}::{row['workload_id']}"] += 1
    topology_pass = (
        len(hosts) >= expected_hosts
        and len(families) >= expected_cpu_families
        and len(labs) >= expected_labs
        and len(workloads) >= expected_workloads
        and bool(pair_counts)
        and all(count >= expected_pairs_per_host_workload for count in pair_counts.values())
        and len(pair_counts) >= expected_hosts * expected_workloads
    )
    ratios = [row["ratio_candidate_over_baseline"] for row in pairs]
    median = statistics.median(ratios) if ratios else None
    ci = hierarchical_paired_bootstrap(
        pairs, seed=bootstrap_seed, resamples=bootstrap_resamples
    ) if len(pairs) >= 2 else None
    host_medians = {
        host: statistics.median(row["ratio_candidate_over_baseline"] for row in pairs if row["host_id"] == host)
        for host in sorted(hosts)
    }
    direction_consistent = bool(host_medians) and all(value < 1 for value in host_medians.values())
    advantage = bool(topology_pass and median is not None and median < 1 and ci and ci[1] < 1 and direction_consistent)
    terminal = (
        "PASS_MULTIHOST_TOTAL_SYSTEM_ENERGY"
        if advantage
        else "FAIL_NO_MULTIHOST_ENERGY_ADVANTAGE"
        if topology_pass and ci and ci[0] >= 1
        else "INCONCLUSIVE_MULTIHOST_ENERGY"
        if topology_pass
        else "BLOCKED_INSUFFICIENT_EXTERNAL_SCALE"
    )
    return {
        "schema": "casulo.interlocution-energy-analysis/2.0",
        "candidate": candidate,
        "baseline": baseline,
        "valid_pairs": len(pairs),
        "rejected_samples_or_pairs": rejected,
        "observed_topology": {
            "hosts": len(hosts),
            "cpu_families": len(families),
            "labs": len(labs),
            "workloads": len(workloads),
            "pairs_per_host_workload": dict(sorted(pair_counts.items())),
        },
        "required_topology": {
            "hosts": expected_hosts,
            "cpu_families": expected_cpu_families,
            "labs": expected_labs,
            "workloads": expected_workloads,
            "pairs_per_host_workload": expected_pairs_per_host_workload,
        },
        "topology_pass": topology_pass,
        "median_ratio_candidate_over_baseline": median,
        "hierarchical_bootstrap_ci95": {
            "lower": ci[0],
            "upper": ci[1],
            "seed": bootstrap_seed,
            "resamples": bootstrap_resamples,
        } if ci else None,
        "host_median_ratios": host_medians,
        "direction_consistent_across_hosts": direction_consistent,
        "terminal_state": terminal,
        "claim_authorized": advantage,
    }
