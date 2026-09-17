from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Mapping


WORKLOAD_PROTOCOL = "casulo-livelab-workload/1.0"
DATA_PROTOCOL = "casulo-livelab-synthetic-data/1.0"
GENERATOR_PROTOCOL = "splitmix64-u53/1.0"
CATALOG_PROTOCOL = "casulo-livelab-workload-catalog/1.0"


@dataclass(frozen=True, slots=True)
class TensorContract:
    name: str
    shape: tuple[int | str, ...]
    role: str

    def __post_init__(self) -> None:
        if not self.name or self.role not in {"input", "target", "parameter", "output"}:
            raise ValueError("invalid tensor contract")
        if not self.shape or any(type(item) not in (int, str) for item in self.shape):
            raise ValueError("tensor shape must be non-empty")
        if any(type(item) is int and item <= 0 for item in self.shape):
            raise ValueError("tensor dimensions must be positive")


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    workload_id: str
    revision: int
    family: str
    purpose: str
    seed: int
    dtype: str
    tensors: tuple[TensorContract, ...]
    initialization: Mapping[str, Any]
    operation_expectations: tuple[str, ...]
    quality: Mapping[str, Any]
    equivalence: Mapping[str, Any]
    campaign: Mapping[str, Any]
    smoke: Mapping[str, Any]
    semantic_class: str = "FLOW"
    protocol: str = WORKLOAD_PROTOCOL

    def __post_init__(self) -> None:
        if self.protocol != WORKLOAD_PROTOCOL or not self.workload_id or self.revision < 1:
            raise ValueError("invalid workload identity")
        if self.dtype not in {"float32", "float64"}:
            raise ValueError("unsupported workload dtype")
        if self.semantic_class not in {"FLOW", "SYSTEM", "ATTRACTOR_AUDIT"}:
            raise ValueError("invalid semantic class")
        if len({tensor.name for tensor in self.tensors}) != len(self.tensors):
            raise ValueError("duplicate tensor name")
        required_quality = {"metric", "absolute_tolerance", "relative_tolerance"}
        if not required_quality <= set(self.quality):
            raise ValueError("quality contract is incomplete")
        if tuple(self.equivalence.get("included_operations", ())) != self.operation_expectations:
            raise ValueError("equivalence scope differs from operation expectations")
        for profile in (self.campaign, self.smoke):
            if type(profile.get("batch")) is not int or profile["batch"] < 1:
                raise ValueError("profile batch must be positive")
            if type(profile.get("steps")) is not int or profile["steps"] < 1:
                raise ValueError("profile steps must be positive")

    @property
    def identity(self) -> str:
        return f"{self.workload_id}@{self.revision}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "revision": self.revision,
            "family": self.family,
            "purpose": self.purpose,
            "seed": self.seed,
            "dtype": self.dtype,
            "tensors": [asdict(item) for item in self.tensors],
            "initialization": dict(self.initialization),
            "operation_expectations": list(self.operation_expectations),
            "quality": dict(self.quality),
            "equivalence": dict(self.equivalence),
            "campaign": dict(self.campaign),
            "smoke": dict(self.smoke),
            "semantic_class": self.semantic_class,
            "protocol": self.protocol,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class GeneratedWorkload:
    spec_identity: str
    profile: str
    seed: int
    dtype: str
    shapes: Mapping[str, tuple[int, ...]]
    values: Mapping[str, tuple[float, ...]]
    lengths: tuple[int, ...]
    sha256: str
    protocol: str = DATA_PROTOCOL

    def value(self, name: str) -> tuple[float, ...]:
        return self.values[name]

    def shape(self, name: str) -> tuple[int, ...]:
        return self.shapes[name]


def _tensor(name: str, shape: tuple[int | str, ...], role: str) -> TensorContract:
    return TensorContract(name, shape, role)


def _spec(
    workload_id: str,
    family: str,
    purpose: str,
    *,
    seed: int,
    dtype: str,
    tensors: tuple[TensorContract, ...],
    operations: tuple[str, ...],
    campaign: Mapping[str, Any],
    smoke: Mapping[str, Any],
    initialization: Mapping[str, Any] | None = None,
    tolerance: float | None = None,
    semantic_class: str = "FLOW",
) -> WorkloadSpec:
    tol = tolerance if tolerance is not None else (1e-12 if dtype == "float64" else 2e-5)
    return WorkloadSpec(
        workload_id=workload_id,
        revision=1,
        family=family,
        purpose=purpose,
        seed=seed,
        dtype=dtype,
        tensors=tensors,
        initialization=MappingProxyType(dict(initialization or {
            "generator": GENERATOR_PROTOCOL,
            "distribution": "uniform[-0.125,0.125)",
            "bias": "zeros",
        })),
        operation_expectations=operations,
        quality=MappingProxyType({
            "metric": "max_abs_and_relative_error",
            "absolute_tolerance": tol,
            "relative_tolerance": tol,
            "nan_policy": "reject",
        }),
        equivalence=MappingProxyType({
            "included_operations": operations,
            "required_outputs": ["loss", "parameters"] if "sgd_update" in operations else ["output"],
            "comparison": "same frozen inputs, initialization, dtype and operation scope",
            "fail_closed_on_scope_difference": True,
        }),
        campaign=MappingProxyType(dict(campaign)),
        smoke=MappingProxyType(dict(smoke)),
        semantic_class=semantic_class,
    )


_FULL_STEP = ("forward", "loss", "backward", "sgd_update")
_FORWARD = ("forward",)

_SPECS = (
    _spec(
        "flood-surrogate-historical", "dense-mlp", "Preserve the declared 2026 FloodSurrogate workload.",
        seed=260730, dtype="float64",
        tensors=(
            _tensor("inputs", ("batch", 8), "input"), _tensor("targets", ("batch", 1), "target"),
            _tensor("w1", (8, 8), "parameter"), _tensor("b1", (8,), "parameter"),
            _tensor("w2", (8, 1), "parameter"), _tensor("b2", (1,), "parameter"),
            _tensor("predictions", ("batch", 1), "output"),
        ),
        operations=_FULL_STEP,
        campaign={"batch": 1024, "steps": 400, "learning_rate": 0.018, "activation": "relu", "dataset": "casulo-hydrology-surrogate/0.1", "dataset_seed": 20260730},
        smoke={"batch": 8, "steps": 2, "learning_rate": 0.018, "activation": "relu", "not_a_performance_campaign": True},
        initialization={"generator": "numpy-pcg64-historical/1", "weights": "fan-in-normal", "bias": "zeros"},
    ),
    _spec(
        "mlp-small", "dense-mlp", "Small full-step dense training control.",
        seed=10101, dtype="float64",
        tensors=(_tensor("inputs", ("batch", 8), "input"), _tensor("targets", ("batch", 4), "target"), _tensor("w1", (8, 16), "parameter"), _tensor("b1", (16,), "parameter"), _tensor("w2", (16, 4), "parameter"), _tensor("b2", (4,), "parameter"), _tensor("predictions", ("batch", 4), "output")),
        operations=_FULL_STEP, campaign={"batch": 256, "steps": 200, "learning_rate": 0.01, "activation": "tanh"}, smoke={"batch": 4, "steps": 2, "learning_rate": 0.01, "activation": "tanh", "not_a_performance_campaign": True},
    ),
    _spec(
        "mlp-medium", "dense-mlp", "Medium full-step dense crossover point.",
        seed=20202, dtype="float32",
        tensors=(_tensor("inputs", ("batch", 64), "input"), _tensor("targets", ("batch", 16), "target"), _tensor("w1", (64, 128), "parameter"), _tensor("b1", (128,), "parameter"), _tensor("w2", (128, 16), "parameter"), _tensor("b2", (16,), "parameter"), _tensor("predictions", ("batch", 16), "output")),
        operations=_FULL_STEP, campaign={"batch": 512, "steps": 100, "learning_rate": 0.005, "activation": "relu"}, smoke={"batch": 3, "steps": 1, "learning_rate": 0.005, "activation": "relu", "not_a_performance_campaign": True},
    ),
    _spec(
        "mlp-large", "dense-mlp", "Large bounded dense saturation point.",
        seed=30303, dtype="float32",
        tensors=(_tensor("inputs", ("batch", 256), "input"), _tensor("targets", ("batch", 64), "target"), _tensor("w1", (256, 512), "parameter"), _tensor("b1", (512,), "parameter"), _tensor("w2", (512, 64), "parameter"), _tensor("b2", (64,), "parameter"), _tensor("predictions", ("batch", 64), "output")),
        operations=_FULL_STEP, campaign={"batch": 1024, "steps": 50, "learning_rate": 0.002, "activation": "relu"}, smoke={"batch": 1, "steps": 1, "learning_rate": 0.002, "activation": "relu", "not_a_performance_campaign": True},
    ),
    _spec(
        "cnn-small", "convolution", "Small NCHW convolution inference control.",
        seed=40404, dtype="float32",
        tensors=(_tensor("inputs", ("batch", 1, 8, 8), "input"), _tensor("kernel", (4, 1, 3, 3), "parameter"), _tensor("bias", (4,), "parameter"), _tensor("output", ("batch", 4, 6, 6), "output")),
        operations=_FORWARD, campaign={"batch": 128, "steps": 500, "stride": 1, "padding": 0}, smoke={"batch": 2, "steps": 1, "stride": 1, "padding": 0, "not_a_performance_campaign": True},
    ),
    _spec(
        "attention-compact", "attention", "Compact single-head self-attention block.",
        seed=50505, dtype="float32",
        tensors=(_tensor("inputs", ("batch", 8, 16), "input"), _tensor("wq", (16, 16), "parameter"), _tensor("wk", (16, 16), "parameter"), _tensor("wv", (16, 16), "parameter"), _tensor("wo", (16, 16), "parameter"), _tensor("output", ("batch", 8, 16), "output")),
        operations=("qkv_projection", "scaled_dot_product", "softmax", "output_projection"), campaign={"batch": 64, "steps": 200, "sequence": 8, "heads": 1}, smoke={"batch": 2, "steps": 1, "sequence": 8, "heads": 1, "not_a_performance_campaign": True}, tolerance=4e-5,
    ),
    _spec(
        "dynamic-length", "dynamic-control", "Ragged masked reduction that stresses dynamic shapes.",
        seed=60606, dtype="float64",
        tensors=(_tensor("inputs", ("batch", "max_length", 8), "input"), _tensor("lengths", ("batch",), "input"), _tensor("output", ("batch", 8), "output")),
        operations=("length_mask", "masked_sum", "length_normalize"), campaign={"batch": 256, "steps": 400, "max_length": 31}, smoke={"batch": 5, "steps": 1, "max_length": 7, "not_a_performance_campaign": True},
    ),
    _spec(
        "t-unfavorable-opaque-branch", "unfavorable", "Branch-heavy scalar recurrence expected to resist fusion.",
        seed=70707, dtype="float64",
        tensors=(_tensor("inputs", ("batch", 64), "input"), _tensor("output", ("batch", 1), "output")),
        operations=("data_dependent_branch", "scalar_recurrence", "ordered_reduction"), campaign={"batch": 512, "steps": 200}, smoke={"batch": 3, "steps": 1, "not_a_performance_campaign": True},
    ),
    _spec(
        "flow-residual-interference", "scheduler-interference", "FLOW latency under a concurrent heavy residual stream.",
        seed=80808, dtype="float64",
        tensors=(_tensor("flow", ("batch", 8), "input"), _tensor("residual", ("batch", 256), "input"), _tensor("output", ("batch", 1), "output")),
        operations=("flow_reduction", "residual_dense_work", "audit_progress"), campaign={"batch": 256, "steps": 1000, "audit_interval": 8}, smoke={"batch": 4, "steps": 3, "audit_interval": 2, "not_a_performance_campaign": True},
    ),
)

WORKLOADS: Mapping[str, WorkloadSpec] = MappingProxyType({item.workload_id: item for item in _SPECS})


def workload_specs() -> tuple[WorkloadSpec, ...]:
    return _SPECS


def canonical_catalog_bytes() -> bytes:
    document = {
        "protocol": CATALOG_PROTOCOL,
        "workloads": [
            {"sha256": spec.sha256, "spec": spec.to_dict()} for spec in _SPECS
        ],
    }
    return json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def catalog_sha256() -> str:
    return hashlib.sha256(canonical_catalog_bytes()).hexdigest()


def get_workload(workload_id: str) -> WorkloadSpec:
    try:
        return WORKLOADS[workload_id]
    except KeyError as exc:
        raise KeyError(f"unknown workload: {workload_id}") from exc


def generate_workload(spec: WorkloadSpec, *, profile: str = "smoke") -> GeneratedWorkload:
    if profile not in {"smoke", "campaign"}:
        raise ValueError("profile must be smoke or campaign")
    selected = spec.smoke if profile == "smoke" else spec.campaign
    if spec.workload_id == "flood-surrogate-historical" and profile == "campaign":
        return _generate_historical_flood(spec)
    batch = int(selected["batch"])
    symbolic = {"batch": batch, "max_length": int(selected.get("max_length", 1))}
    shapes: dict[str, tuple[int, ...]] = {}
    values: dict[str, tuple[float, ...]] = {}
    lengths: tuple[int, ...] = ()
    stream = SplitMix64(spec.seed)
    for tensor in spec.tensors:
        shape = tuple(symbolic[item] if type(item) is str else item for item in tensor.shape)
        shapes[tensor.name] = shape
        count = math.prod(shape)
        if tensor.name == "lengths":
            maximum = symbolic["max_length"]
            lengths = tuple(1 + stream.uint64() % maximum for _ in range(batch))
            values[tensor.name] = tuple(float(item) for item in lengths)
        elif tensor.role == "output":
            continue
        elif tensor.name.startswith("b") or tensor.name == "bias":
            values[tensor.name] = (0.0,) * count
        else:
            values[tensor.name] = tuple(stream.uniform(-0.125, 0.125) for _ in range(count))
    digest = hashlib.sha256()
    digest.update(DATA_PROTOCOL.encode("ascii"))
    digest.update(spec.sha256.encode("ascii"))
    digest.update(profile.encode("ascii"))
    for name in sorted(values):
        digest.update(name.encode("utf-8"))
        for item in values[name]:
            digest.update(struct.pack("<d", item))
    return GeneratedWorkload(
        spec.identity, profile, spec.seed, spec.dtype,
        MappingProxyType(shapes), MappingProxyType(values), lengths, digest.hexdigest(),
    )


def _generate_historical_flood(spec: WorkloadSpec) -> GeneratedWorkload:
    """Delegate the frozen campaign data and initialization to their original code.

    The compact smoke fixture intentionally uses SplitMix64 and must never be
    represented as the historical data set.
    """

    from casulo.t.training import (
        generate_training_dataset,
        initial_parameters,
        parse_training_file,
    )
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "examples" / "t" / "flood_surrogate_training.t"
    training_spec = parse_training_file(source)
    data_seed = int(spec.campaign["dataset_seed"])
    dataset = generate_training_dataset(training_spec, records=1024, seed=data_seed)
    initial = initial_parameters(training_spec)
    f, h = training_spec.input_features, training_spec.hidden_features
    p0, p1, p2 = f * h, f * h + h, f * h + h + h
    values = {
        "inputs": tuple(float(item) for item in dataset.inputs.reshape(-1)),
        "targets": tuple(float(item) for item in dataset.targets.reshape(-1)),
        "w1": tuple(float(item) for item in initial[:p0]),
        "b1": tuple(float(item) for item in initial[p0:p1]),
        "w2": tuple(float(item) for item in initial[p1:p2]),
        "b2": (float(initial[p2]),),
    }
    shapes = {tensor.name: tuple(1024 if item == "batch" else int(item) for item in tensor.shape) for tensor in spec.tensors}
    digest = hashlib.sha256()
    digest.update(DATA_PROTOCOL.encode("ascii"))
    digest.update(spec.sha256.encode("ascii"))
    digest.update(b"campaign")
    digest.update(dataset.sha256.encode("ascii"))
    for name in ("w1", "b1", "w2", "b2"):
        for item in values[name]:
            digest.update(struct.pack("<d", item))
    return GeneratedWorkload(
        spec.identity, "campaign", data_seed, spec.dtype,
        MappingProxyType(shapes), MappingProxyType(values), (), digest.hexdigest(),
    )


class SplitMix64:
    """Small specified generator used only for portable synthetic fixtures."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def uint64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return value ^ (value >> 31)

    def uniform(self, low: float, high: float) -> float:
        unit = (self.uint64() >> 11) * (1.0 / (1 << 53))
        return low + (high - low) * unit
