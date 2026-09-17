from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Mapping


ABLATION_PROTOCOL = "casulo-livelab-ablation-plan/1.0"
PROFILE_PROTOCOL = "casulo-livelab-profile-contract/1.0"


@dataclass(frozen=True, slots=True)
class AblationAxis:
    axis_id: str
    mechanism: str
    variants: tuple[str, ...]
    control: str
    workloads: tuple[str, ...]
    primary_metric: str = "paired_elapsed_time_ratio"
    quality_gate: str = "exact_work_scope_and_registered_tolerance"

    def __post_init__(self) -> None:
        if not self.axis_id or not self.mechanism:
            raise ValueError("ablation identity must be non-empty")
        if len(self.variants) < 2 or len(set(self.variants)) != len(self.variants):
            raise ValueError("ablation variants must be unique and non-trivial")
        if self.control not in self.variants:
            raise ValueError("ablation control must be one of its variants")
        if not self.workloads or len(set(self.workloads)) != len(self.workloads):
            raise ValueError("ablation workloads must be unique and non-empty")


@dataclass(frozen=True, slots=True)
class ProfileContract:
    counters: tuple[str, ...]
    unavailable_value: None = None
    collection_boundary: str = "child_process_full_equivalent_step"
    protocol: str = PROFILE_PROTOCOL

    def __post_init__(self) -> None:
        if len(self.counters) != len(set(self.counters)) or not self.counters:
            raise ValueError("profiling counters must be unique and non-empty")
        if self.unavailable_value is not None:
            raise ValueError("unavailable profiling counters must remain null")


@dataclass(frozen=True, slots=True)
class AblationPlan:
    axes: tuple[AblationAxis, ...]
    minimum_pairs: int
    warmups: int
    bootstrap_resamples: int
    bootstrap_seed: int
    exclusion_policy: str
    thermal_policy: str
    power_policy: str
    profile: ProfileContract
    protocol: str = ABLATION_PROTOCOL

    def __post_init__(self) -> None:
        if self.protocol != ABLATION_PROTOCOL:
            raise ValueError("unexpected ablation protocol")
        if len(self.axes) != 9 or len({item.axis_id for item in self.axes}) != 9:
            raise ValueError("the preregistered plan requires exactly nine axes")
        if self.minimum_pairs < 21 or self.warmups < 3:
            raise ValueError("ablation evidence requires at least 21 pairs and 3 warmups")
        if self.bootstrap_resamples < 10_000:
            raise ValueError("ablation bootstrap requires at least 10,000 resamples")
        if self.exclusion_policy != "preregistered_only_no_posthoc_outliers":
            raise ValueError("ablation exclusions may not be relaxed")
        if self.thermal_policy != "thermal_covenant_fail_closed":
            raise ValueError("ablation thermal gate may not be relaxed")
        if self.power_policy != "identical_validated_power_state":
            raise ValueError("ablation power parity may not be relaxed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "axes": [asdict(item) for item in self.axes],
            "minimum_pairs": self.minimum_pairs,
            "warmups": self.warmups,
            "bootstrap_resamples": self.bootstrap_resamples,
            "bootstrap_seed": self.bootstrap_seed,
            "exclusion_policy": self.exclusion_policy,
            "thermal_policy": self.thermal_policy,
            "power_policy": self.power_policy,
            "profile": asdict(self.profile),
            "scientific_invariants": {
                "same_inputs_initialization_dtype_operations": True,
                "quality_before_timing": True,
                "failed_quality_invalidates_speed": True,
                "compilation_reported_separately": True,
                "energy_never_inferred_from_time_or_temperature": True,
                "unfavorable_results_preserved": True,
            },
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_plan_bytes(self)).hexdigest()


_DENSE = ("flood-surrogate-historical", "mlp-small", "mlp-medium", "mlp-large")
_GENERAL = (
    "mlp-small",
    "mlp-medium",
    "mlp-large",
    "cnn-small",
    "attention-compact",
    "dynamic-length",
    "t-unfavorable-opaque-branch",
)

ABLATION_AXES = (
    AblationAxis(
        "buffer-reuse",
        "physical arena reuse versus semantically identical fresh buffers",
        ("fresh-buffers", "arena-reuse"),
        "fresh-buffers",
        _DENSE,
    ),
    AblationAxis(
        "vectorization",
        "scalar loops versus explicitly vectorized native loops",
        ("scalar", "vectorized"),
        "scalar",
        _DENSE,
    ),
    AblationAxis(
        "optimization-level",
        "native compiler optimization level",
        ("O0", "O1", "O2", "O3"),
        "O0",
        _DENSE,
    ),
    AblationAxis(
        "workers",
        "fixed worker count under identical affinity",
        ("1", "2", "4"),
        "1",
        _GENERAL,
    ),
    AblationAxis(
        "autograd-specialization",
        "general autograd backward versus verified specialized backward",
        ("autograd", "specialized-backward"),
        "autograd",
        _DENSE,
    ),
    AblationAxis(
        "fusion",
        "materialized phases versus semantically equivalent fused loop regions",
        ("separate-phases", "fused-phases"),
        "separate-phases",
        _DENSE,
    ),
    AblationAxis(
        "shape-mode",
        "dynamic shape dispatch versus frozen static shapes",
        ("dynamic", "static"),
        "dynamic",
        ("dynamic-length", "mlp-small", "mlp-medium"),
    ),
    AblationAxis(
        "compiler-route",
        "historical direct route versus the general versioned T IR route",
        ("direct-legacy", "general-ir"),
        "direct-legacy",
        ("flood-surrogate-historical",),
    ),
    AblationAxis(
        "scheduler-policy",
        "conventional FIFO versus semantic Casulo queues",
        ("conventional", "semantic"),
        "conventional",
        ("flow-residual-interference",),
        primary_metric="paired_flow_p95_ratio",
    ),
)

PROFILE_CONTRACT = ProfileContract(
    counters=(
        "task-clock",
        "cycles",
        "instructions",
        "branches",
        "branch-misses",
        "cache-references",
        "cache-misses",
        "context-switches",
        "cpu-migrations",
        "page-faults",
    )
)

PREREGISTERED_ABLATION_PLAN = AblationPlan(
    axes=ABLATION_AXES,
    minimum_pairs=21,
    warmups=3,
    bootstrap_resamples=10_000,
    bootstrap_seed=20260807,
    exclusion_policy="preregistered_only_no_posthoc_outliers",
    thermal_policy="thermal_covenant_fail_closed",
    power_policy="identical_validated_power_state",
    profile=PROFILE_CONTRACT,
)


def canonical_plan_bytes(plan: AblationPlan = PREREGISTERED_ABLATION_PLAN) -> bytes:
    return json.dumps(
        plan.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def profiling_record(
    values: Mapping[str, int | float | None],
    *,
    status: str,
    reason: str | None,
) -> Mapping[str, Any]:
    if status not in {"measured", "unavailable", "blocked_permission", "error"}:
        raise ValueError("invalid profiling status")
    unknown = set(values) - set(PROFILE_CONTRACT.counters)
    if unknown:
        raise ValueError(f"unknown profiling counters: {sorted(unknown)}")
    complete = {
        counter: values.get(counter) for counter in PROFILE_CONTRACT.counters
    }
    if status != "measured" and any(value is not None for value in complete.values()):
        raise ValueError("unavailable profiling counters must be null")
    if status == "measured" and any(
        type(value) not in (int, float) or value < 0 for value in complete.values()
    ):
        raise ValueError("measured profiling counters must be complete and nonnegative")
    return MappingProxyType(
        {
            "protocol": PROFILE_PROTOCOL,
            "status": status,
            "reason": reason,
            "boundary": PROFILE_CONTRACT.collection_boundary,
            "counters": complete,
        }
    )
