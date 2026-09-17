from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass
from dataclasses import field
from enum import StrEnum
from typing import Any, Callable, Mapping, Protocol

from .capabilities import Capability, CapabilityStatus


class CampaignStatus(StrEnum):
    READY = "ready"
    BLOCKED_BEFORE_START = "blocked_before_start"
    ABORTED = "aborted"
    COMPLETE = "complete"


class GateStatus(StrEnum):
    PASS = "pass"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: str
    status: GateStatus
    reason_code: str
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ThermalEvidence:
    sensor_id: str
    observed_ns: tuple[int, ...]
    temperatures_c: tuple[float, ...]
    throttling_detected: bool
    operator_odor_absent: bool | None


@dataclass(frozen=True, slots=True)
class PowerStateEvidence:
    source: str
    on_ac_power: bool
    power_mode: str
    cpu_policy: str
    stable: bool


@dataclass(frozen=True, slots=True)
class IsolationEvidence:
    applied: bool
    cpu_affinity: tuple[int, ...]
    threads: int
    cgroup_path: str | None
    controls: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CampaignPolicy:
    maximum_temperature_c: float = 55.0
    minimum_thermal_samples: int = 3
    require_operator_odor_confirmation: bool = True
    require_external_power_meter: bool = True
    require_cgroup_isolation: bool = True
    required_capabilities: tuple[str, ...] = (
        "process_affinity",
        "thread_environment",
        "cgroups_v2",
        "cgroup_cpuset",
        "cpu_weight",
        "cpu_max",
    )

    def __post_init__(self) -> None:
        if not 20.0 <= self.maximum_temperature_c <= 100.0:
            raise ValueError("maximum temperature outside supported bounds")
        if not 3 <= self.minimum_thermal_samples <= 10_000:
            raise ValueError("minimum thermal samples outside supported bounds")


@dataclass(frozen=True, slots=True)
class PreflightReport:
    status: CampaignStatus
    gates: tuple[GateResult, ...]

    @property
    def ready(self) -> bool:
        return self.status is CampaignStatus.READY

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "gates": [gate.to_dict() for gate in self.gates]}


def evaluate_preflight(
    capabilities: Mapping[str, Capability],
    *,
    thermal: ThermalEvidence | None,
    power: PowerStateEvidence | None,
    isolation: IsolationEvidence | None,
    policy: CampaignPolicy = CampaignPolicy(),
) -> PreflightReport:
    gates = (
        _capability_gate(capabilities, policy),
        _thermal_gate(thermal, policy),
        _power_gate(power),
        _isolation_gate(isolation, policy),
    )
    status = CampaignStatus.READY if all(item.status is GateStatus.PASS for item in gates) else CampaignStatus.BLOCKED_BEFORE_START
    return PreflightReport(status, gates)


@dataclass(frozen=True, slots=True)
class CampaignSpec:
    campaign_id: str
    baseline_label: str
    candidate_label: str
    repetitions: int
    warmups: int = 0
    maximum_trial_seconds: float = 60.0
    strict_statistics: bool = False
    bootstrap_seed: int = 20260807
    bootstrap_resamples: int = 10_000
    minimum_main_pairs: int = 21
    compile_amortization_runs: int = 1
    require_power_parity: bool = False
    preregistered_exclusions: tuple[str, ...] = ()
    evidence_kind: str = "measured"

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.baseline_label or not self.candidate_label:
            raise ValueError("campaign and workload labels must be non-empty")
        if self.baseline_label == self.candidate_label:
            raise ValueError("baseline and candidate labels must differ")
        if not 3 <= self.repetitions <= 10_000:
            raise ValueError("repetitions outside supported bounds")
        if not 0 <= self.warmups <= 100:
            raise ValueError("warmups outside supported bounds")
        if not math.isfinite(self.maximum_trial_seconds) or not 0.01 <= self.maximum_trial_seconds <= 3600.0:
            raise ValueError("maximum trial duration outside supported bounds")
        if self.strict_statistics and self.repetitions < self.minimum_main_pairs:
            raise ValueError("strict campaigns require at least minimum_main_pairs")
        if not 21 <= self.minimum_main_pairs <= 10_000:
            raise ValueError("minimum_main_pairs must be at least 21")
        if not 1_000 <= self.bootstrap_resamples <= 1_000_000:
            raise ValueError("bootstrap_resamples outside supported bounds")
        if not 1 <= self.compile_amortization_runs <= 1_000_000:
            raise ValueError("compile_amortization_runs outside supported bounds")
        if len(set(self.preregistered_exclusions)) != len(self.preregistered_exclusions):
            raise ValueError("preregistered exclusions must be unique")
        if self.evidence_kind not in {"measured", "synthetic"}:
            raise ValueError("evidence_kind must be measured or synthetic")


@dataclass(frozen=True, slots=True)
class TrialMeasurement:
    elapsed_ns: int
    energy_joules: float | None
    maximum_temperature_c: float
    output_digest: str
    compile_elapsed_ns: int = 0
    phase_timings_ns: Mapping[str, int] = field(default_factory=dict)
    power_state_signature: str | None = None
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if self.elapsed_ns <= 0:
            raise ValueError("elapsed time must be positive")
        if self.energy_joules is not None and (not math.isfinite(self.energy_joules) or self.energy_joules < 0):
            raise ValueError("energy must be finite and nonnegative")
        if not math.isfinite(self.maximum_temperature_c):
            raise ValueError("temperature must be finite")
        if len(self.output_digest) != 64 or any(item not in "0123456789abcdef" for item in self.output_digest):
            raise ValueError("output digest must be lowercase SHA-256")
        if self.compile_elapsed_ns < 0:
            raise ValueError("compile time must be nonnegative")
        if any(not name or value < 0 for name, value in self.phase_timings_ns.items()):
            raise ValueError("phase timings must have names and nonnegative values")


@dataclass(frozen=True, slots=True)
class TrialRecord:
    pair_index: int
    order_in_pair: int
    label: str
    measurement: TrialMeasurement

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_index": self.pair_index,
            "order_in_pair": self.order_in_pair,
            "label": self.label,
            **asdict(self.measurement),
        }


class TrialExecutor(Protocol):
    def safety_check(self) -> PreflightReport:
        ...

    def run_trial(
        self,
        label: str,
        workload: Callable[[], Any],
        *,
        maximum_seconds: float,
    ) -> TrialMeasurement:
        ...


@dataclass(frozen=True, slots=True)
class CampaignResult:
    spec: CampaignSpec
    status: CampaignStatus
    preflight: PreflightReport
    trials: tuple[TrialRecord, ...]
    workload_invocations: int = 0
    abort_reason: str | None = None

    @property
    def workload_started(self) -> bool:
        return self.workload_invocations > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo-livelab-paired-campaign/1",
            "spec": asdict(self.spec),
            "status": self.status.value,
            "workload_started": self.workload_started,
            "workload_invocations": self.workload_invocations,
            "preflight": self.preflight.to_dict(),
            "trials": [trial.to_dict() for trial in self.trials],
            "abort_reason": self.abort_reason,
            "aggregates": aggregate_campaign(self),
        }


def execute_paired_campaign(
    spec: CampaignSpec,
    preflight: PreflightReport,
    workloads: Mapping[str, Callable[[], Any]],
    executor: TrialExecutor,
) -> CampaignResult:
    """Run deterministic AB/BA pairs only after every safety gate passes.

    There is intentionally no permissive override. Missing evidence returns a
    zero-trial result and never invokes a workload callable.
    """

    if not preflight.ready:
        return CampaignResult(spec, CampaignStatus.BLOCKED_BEFORE_START, preflight, ())
    expected = {spec.baseline_label, spec.candidate_label}
    if set(workloads) != expected:
        raise ValueError("workloads must exactly match baseline and candidate labels")

    records: list[TrialRecord] = []
    workload_invocations = 0
    power_signature_reference: str | None = None

    def invoke(label: str) -> Any:
        nonlocal workload_invocations
        workload_invocations += 1
        return workloads[label]()

    for warmup in range(spec.warmups):
        labels = _pair_order(warmup, spec)
        for label in labels:
            dynamic = executor.safety_check()
            if not dynamic.ready:
                return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "safety_gate_failed_during_warmup")
            try:
                executor.run_trial(label, lambda label=label: invoke(label), maximum_seconds=spec.maximum_trial_seconds)
            except Exception as exc:
                return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, f"warmup_executor_error:{type(exc).__name__}")

    for pair_index in range(spec.repetitions):
        pair_start = len(records)
        for order_in_pair, label in enumerate(_pair_order(pair_index, spec)):
            dynamic = executor.safety_check()
            if not dynamic.ready:
                return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "safety_gate_failed_before_trial")
            try:
                measurement = executor.run_trial(label, lambda label=label: invoke(label), maximum_seconds=spec.maximum_trial_seconds)
            except Exception as exc:
                return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, f"trial_executor_error:{type(exc).__name__}")
            if measurement.maximum_temperature_c > _thermal_limit(preflight):
                records.append(TrialRecord(pair_index, order_in_pair, label, measurement))
                return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "thermal_limit_exceeded")
            if measurement.exclusion_reason is not None and measurement.exclusion_reason not in spec.preregistered_exclusions:
                records.append(TrialRecord(pair_index, order_in_pair, label, measurement))
                return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "unregistered_exclusion")
            if spec.require_power_parity:
                if measurement.power_state_signature is None:
                    records.append(TrialRecord(pair_index, order_in_pair, label, measurement))
                    return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "power_state_parity_failed")
                if power_signature_reference is None:
                    power_signature_reference = measurement.power_state_signature
                elif measurement.power_state_signature != power_signature_reference:
                    records.append(TrialRecord(pair_index, order_in_pair, label, measurement))
                    return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "power_state_parity_failed")
            records.append(TrialRecord(pair_index, order_in_pair, label, measurement))
        pair = records[pair_start:]
        if pair[0].measurement.output_digest != pair[1].measurement.output_digest:
            return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "output_digest_mismatch")
        if spec.require_power_parity:
            signatures = {item.measurement.power_state_signature for item in pair}
            if None in signatures or len(signatures) != 1:
                return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "power_state_parity_failed")
    included_pairs = sum(
        all(item.measurement.exclusion_reason is None for item in records if item.pair_index == pair_index)
        for pair_index in range(spec.repetitions)
    )
    if included_pairs == 0:
        return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "no_valid_pairs")
    if spec.strict_statistics and included_pairs < spec.minimum_main_pairs:
        return CampaignResult(spec, CampaignStatus.ABORTED, preflight, tuple(records), workload_invocations, "insufficient_valid_pairs")
    return CampaignResult(spec, CampaignStatus.COMPLETE, preflight, tuple(records), workload_invocations)


def aggregate_campaign(result: CampaignResult) -> dict[str, Any] | None:
    if result.status is not CampaignStatus.COMPLETE:
        return None
    baseline = result.spec.baseline_label
    candidate = result.spec.candidate_label
    pairs: dict[int, dict[str, TrialMeasurement]] = {}
    for trial in result.trials:
        pairs.setdefault(trial.pair_index, {})[trial.label] = trial.measurement
    valid_pairs = []
    excluded_pairs = []
    for pair_index, pair in sorted(pairs.items()):
        reasons = sorted({item.exclusion_reason for item in pair.values() if item.exclusion_reason is not None})
        if reasons:
            excluded_pairs.append({"pair_index": pair_index, "reasons": reasons})
            continue
        if set(pair) == {baseline, candidate}:
            valid_pairs.append(pair)
    elapsed: dict[str, list[int]] = {
        label: [pair[label].elapsed_ns for pair in valid_pairs]
        for label in (baseline, candidate)
    }
    energy: dict[str, list[float]] = {
        label: [pair[label].energy_joules for pair in valid_pairs if pair[label].energy_joules is not None]
        for label in (baseline, candidate)
    }
    compile_ns: dict[str, list[int]] = {
        label: [pair[label].compile_elapsed_ns for pair in valid_pairs]
        for label in (baseline, candidate)
    }
    phases: dict[str, dict[str, list[int]]] = {baseline: {}, candidate: {}}
    for pair in valid_pairs:
        for label in (baseline, candidate):
            for name, value in pair[label].phase_timings_ns.items():
                phases[label].setdefault(name, []).append(value)
    baseline_time = _median(elapsed[baseline])
    candidate_time = _median(elapsed[candidate])
    energy_complete = len(energy[baseline]) == len(valid_pairs) and len(energy[candidate]) == len(valid_pairs)
    ratios = [pair[baseline].elapsed_ns / pair[candidate].elapsed_ns for pair in valid_pairs]
    energy_ratios = [
        pair[baseline].energy_joules / pair[candidate].energy_joules
        for pair in valid_pairs
        if pair[baseline].energy_joules is not None
        and pair[candidate].energy_joules is not None
        and pair[candidate].energy_joules > 0
    ]
    strict_eligible = len(valid_pairs) >= result.spec.minimum_main_pairs
    bootstrap = _paired_bootstrap_median_ci(ratios, result.spec.bootstrap_seed, result.spec.bootstrap_resamples) if strict_eligible else None
    sign_test = _exact_sign_test(ratios) if strict_eligible else None
    compile_totals = {label: sum(compile_ns[label]) for label in (baseline, candidate)}
    amortized = {
        label: _median(elapsed[label]) + compile_totals[label] / result.spec.compile_amortization_runs
        for label in (baseline, candidate)
    }
    return {
        "estimator": "median_of_paired_ratios",
        "trial_count_per_label": len(result.trials) // 2,
        "valid_pair_count": len(valid_pairs),
        "excluded_pairs": excluded_pairs,
        "median_elapsed_ns": {baseline: baseline_time, candidate: candidate_time},
        "speedup_baseline_over_candidate": _median(ratios),
        "paired_ratio_ci95": bootstrap,
        "paired_exact_sign_test": sign_test,
        "strict_statistics_eligible": strict_eligible,
        "minimum_main_pairs": result.spec.minimum_main_pairs,
        "median_energy_joules": {
            baseline: _median(energy[baseline]),
            candidate: _median(energy[candidate]),
        } if energy_complete else None,
        "energy_ratio_baseline_over_candidate": _median(energy_ratios) if len(energy_ratios) == len(valid_pairs) and energy_ratios else None,
        "compile_elapsed_ns_total": compile_totals,
        "compile_amortization_runs": result.spec.compile_amortization_runs,
        "amortized_elapsed_ns": amortized,
        "amortized_speedup_baseline_over_candidate": amortized[baseline] / amortized[candidate],
        "median_phase_timings_ns": {
            label: {name: _median(values) for name, values in sorted(phases[label].items())}
            for label in (baseline, candidate)
        },
        "scientific_claim": (
            "synthetic_paired_inference_test_only"
            if result.spec.evidence_kind == "synthetic" and result.spec.strict_statistics and strict_eligible
            else "paired_inference"
            if result.spec.strict_statistics and strict_eligible
            else "descriptive_only_insufficient_or_not_requested"
        ),
    }


def sha256_output(value: bytes | str) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _pair_order(index: int, spec: CampaignSpec) -> tuple[str, str]:
    if index % 2 == 0:
        return spec.baseline_label, spec.candidate_label
    return spec.candidate_label, spec.baseline_label


def _capability_gate(capabilities: Mapping[str, Capability], policy: CampaignPolicy) -> GateResult:
    missing = []
    required = list(policy.required_capabilities)
    if policy.require_external_power_meter:
        required.append("external_power_meter")
    for name in dict.fromkeys(required):
        capability = capabilities.get(name)
        if capability is None or capability.status is not CapabilityStatus.AVAILABLE:
            missing.append({
                "capability": name,
                "status": "missing" if capability is None else capability.status.value,
                "reason_code": "not_reported" if capability is None else capability.reason_code,
            })
    status = GateStatus.PASS if not missing else GateStatus.BLOCKED
    return GateResult("capabilities", status, "all_required_available" if not missing else "required_capabilities_unavailable", {"missing": missing})


def _thermal_gate(evidence: ThermalEvidence | None, policy: CampaignPolicy) -> GateResult:
    if evidence is None:
        return GateResult("thermal", GateStatus.BLOCKED, "trusted_thermal_evidence_missing", {})
    count = len(evidence.observed_ns)
    if count != len(evidence.temperatures_c) or count < policy.minimum_thermal_samples:
        return GateResult("thermal", GateStatus.BLOCKED, "thermal_samples_insufficient", {"sample_count": count})
    if not evidence.sensor_id or any(right <= left for left, right in zip(evidence.observed_ns, evidence.observed_ns[1:])):
        return GateResult("thermal", GateStatus.BLOCKED, "thermal_stream_not_advancing", {"sensor_id": evidence.sensor_id})
    if any(not math.isfinite(value) for value in evidence.temperatures_c):
        return GateResult("thermal", GateStatus.BLOCKED, "thermal_values_invalid", {})
    maximum = max(evidence.temperatures_c)
    if evidence.throttling_detected:
        return GateResult("thermal", GateStatus.BLOCKED, "throttling_detected", {"maximum_temperature_c": maximum})
    if maximum > policy.maximum_temperature_c:
        return GateResult("thermal", GateStatus.BLOCKED, "thermal_limit_exceeded", {"maximum_temperature_c": maximum, "limit_c": policy.maximum_temperature_c})
    if policy.require_operator_odor_confirmation and evidence.operator_odor_absent is not True:
        return GateResult("thermal", GateStatus.BLOCKED, "operator_odor_confirmation_missing", {"operator_odor_absent": evidence.operator_odor_absent})
    return GateResult("thermal", GateStatus.PASS, "thermal_stream_stable", {"sensor_id": evidence.sensor_id, "sample_count": count, "maximum_temperature_c": maximum, "limit_c": policy.maximum_temperature_c, "operator_odor_absent": evidence.operator_odor_absent})


def _power_gate(evidence: PowerStateEvidence | None) -> GateResult:
    if evidence is None:
        return GateResult("power_state", GateStatus.BLOCKED, "power_state_evidence_missing", {})
    if not evidence.source or not evidence.power_mode or not evidence.cpu_policy:
        return GateResult("power_state", GateStatus.BLOCKED, "power_state_incomplete", {})
    if not evidence.on_ac_power:
        return GateResult("power_state", GateStatus.BLOCKED, "ac_power_required", {"on_ac_power": False})
    if not evidence.stable:
        return GateResult("power_state", GateStatus.BLOCKED, "power_state_not_stable", {})
    return GateResult("power_state", GateStatus.PASS, "power_state_stable", asdict(evidence))


def _isolation_gate(evidence: IsolationEvidence | None, policy: CampaignPolicy) -> GateResult:
    if evidence is None:
        return GateResult("isolation", GateStatus.BLOCKED, "isolation_evidence_missing", {})
    if not evidence.applied or not evidence.cpu_affinity or evidence.threads < 1:
        return GateResult("isolation", GateStatus.BLOCKED, "isolation_not_applied", asdict(evidence))
    if policy.require_cgroup_isolation and not evidence.cgroup_path:
        return GateResult("isolation", GateStatus.BLOCKED, "cgroup_isolation_required", asdict(evidence))
    return GateResult("isolation", GateStatus.PASS, "isolation_verified", asdict(evidence))


def _thermal_limit(preflight: PreflightReport) -> float:
    for gate in preflight.gates:
        if gate.gate == "thermal" and gate.status is GateStatus.PASS:
            return float(gate.evidence["limit_c"])
    raise ValueError("ready preflight lacks a passing thermal gate")


def _median(values: list[int] | list[float]) -> float:
    if not values:
        raise ValueError("median requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2.0


def _paired_bootstrap_median_ci(ratios: list[float], seed: int, resamples: int) -> dict[str, Any]:
    rng = random.Random(seed)
    count = len(ratios)
    estimates = sorted(_median([ratios[rng.randrange(count)] for _ in range(count)]) for _ in range(resamples))
    low = estimates[int(0.025 * (resamples - 1))]
    high = estimates[int(0.975 * (resamples - 1))]
    return {"method": "seeded_paired_bootstrap_median", "seed": seed, "resamples": resamples, "low": low, "high": high}


def _exact_sign_test(ratios: list[float]) -> dict[str, Any]:
    wins = sum(value > 1.0 for value in ratios)
    losses = sum(value < 1.0 for value in ratios)
    ties = len(ratios) - wins - losses
    n = wins + losses
    if n == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / (2**n)
        p_value = min(1.0, 2.0 * tail)
    return {"method": "two_sided_exact_sign_test", "wins": wins, "losses": losses, "ties": ties, "p_value": p_value}
