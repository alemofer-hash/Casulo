from __future__ import annotations

import gc
import hashlib
import json
import platform
import random
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .benchmark import Measurement, _measure, _safe_ratio, _summarize
from .native import (
    NATIVE_ARENA_PROTOCOL,
    NATIVE_BOUNDARY_AOT_PROTOCOL,
    NATIVE_SIMD_PROTOCOL,
    NativeBuild,
    prepare_native_executor,
)
from .runner import load_artifact, select_operation


NATIVE_BENCHMARK_PROTOCOL = "casulo-native-benchmark/0.3"


class NativeBenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NativeBenchmarkReport:
    protocol: str
    artifact_id: str
    operation: str
    batch_size: int
    dataset_sha256: str
    input_profile: dict[str, Any]
    environment: dict[str, str]
    compiler: dict[str, Any]
    python_scalar: Measurement
    c99_native: Measurement
    native_marshal: Measurement
    native_kernel: Measurement
    native_manifestation: Measurement
    comparison: dict[str, Any]
    equivalence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def benchmark_native_artifact(
    artifact_dir: str | Path,
    payloads: list[dict[str, float]],
    operation: str | None = None,
    *,
    samples: int = 7,
    iterations: int = 5,
) -> NativeBenchmarkReport:
    if not payloads:
        raise NativeBenchmarkError("benchmark nativo exige ao menos um registro")
    if samples < 1 or iterations < 1:
        raise NativeBenchmarkError("samples e iterations precisam ser positivos")
    loaded = load_artifact(artifact_dir)
    selected = select_operation(loaded.manifest, operation)
    scalar_execute = loaded.namespace.get("execute")
    if not callable(scalar_execute):
        raise NativeBenchmarkError("artefato não expõe execução escalar")
    native_execute, manifest, _native_entry, build = prepare_native_executor(
        loaded.directory,
        selected,
    )

    def scalar_call() -> list[dict[str, Any]]:
        return [
            scalar_execute(selected, item, use_cache=False)
            for item in payloads
        ]

    def native_call() -> list[dict[str, Any]]:
        return native_execute(payloads)

    scalar_reference = scalar_call()
    native_reference = native_call()
    scalar_digest = _digest(scalar_reference)
    native_digest = _digest(native_reference)
    if scalar_digest != native_digest:
        raise NativeBenchmarkError(
            "backend C99 divergiu semanticamente do Python escalar"
        )

    scalar_wall: list[int] = []
    scalar_cpu: list[int] = []
    native_wall: list[int] = []
    native_cpu: list[int] = []
    marshal_wall: list[int] = []
    marshal_cpu: list[int] = []
    kernel_wall: list[int] = []
    kernel_cpu: list[int] = []
    manifestation_wall: list[int] = []
    manifestation_cpu: list[int] = []
    kernel_iterations = max(2_000, iterations * 200)

    def marshal_call() -> int:
        return native_execute.marshal(payloads)

    def kernel_call() -> None:
        native_execute.kernel(len(payloads))

    def manifestation_call() -> list[dict[str, Any]]:
        return native_execute.manifest_items(payloads, len(payloads))

    gc_was_enabled = gc.isenabled()
    try:
        gc.disable()
        for sample in range(samples):
            order = (
                (
                    (scalar_call, scalar_wall, scalar_cpu),
                    (native_call, native_wall, native_cpu),
                )
                if sample % 2 == 0
                else (
                    (native_call, native_wall, native_cpu),
                    (scalar_call, scalar_wall, scalar_cpu),
                )
            )
            for function, wall_values, cpu_values in order:
                wall, cpu = _measure(function, iterations)
                wall_values.append(wall)
                cpu_values.append(cpu)
            stage_order = (
                (
                    (marshal_call, iterations, marshal_wall, marshal_cpu),
                    (
                        manifestation_call,
                        iterations,
                        manifestation_wall,
                        manifestation_cpu,
                    ),
                    (
                        kernel_call,
                        kernel_iterations,
                        kernel_wall,
                        kernel_cpu,
                    ),
                )
                if sample % 2 == 0
                else (
                    (
                        kernel_call,
                        kernel_iterations,
                        kernel_wall,
                        kernel_cpu,
                    ),
                    (
                        manifestation_call,
                        iterations,
                        manifestation_wall,
                        manifestation_cpu,
                    ),
                    (marshal_call, iterations, marshal_wall, marshal_cpu),
                )
            )
            for function, stage_iterations, wall_values, cpu_values in stage_order:
                wall, cpu = _measure(function, stage_iterations)
                wall_values.append(wall)
                cpu_values.append(cpu)
    finally:
        if gc_was_enabled:
            gc.enable()

    scalar = _summarize(
        "python_scalar_full_envelope",
        len(payloads),
        iterations,
        scalar_wall,
        scalar_cpu,
    )
    native = _summarize(
        "c99_native_full_envelope",
        len(payloads),
        iterations,
        native_wall,
        native_cpu,
    )
    marshal = _summarize(
        "python_to_c99_fused_validation_marshal",
        len(payloads),
        iterations,
        marshal_wall,
        marshal_cpu,
    )
    kernel = _summarize(
        "c99_kernel_only_premarshaled",
        len(payloads),
        kernel_iterations,
        kernel_wall,
        kernel_cpu,
    )
    manifestation = _summarize(
        "python_boundary_manifestation",
        len(payloads),
        iterations,
        manifestation_wall,
        manifestation_cpu,
    )
    stage_total = (
        marshal.wall_ns_per_record
        + kernel.wall_ns_per_record
        + manifestation.wall_ns_per_record
    )
    paired_speedups = tuple(
        scalar_value / native_value
        for scalar_value, native_value in zip(
            scalar.wall_ns_samples,
            native.wall_ns_samples,
        )
        if native_value
    )
    speedup_ci = _bootstrap_median_ci(paired_speedups)
    return NativeBenchmarkReport(
        protocol=NATIVE_BENCHMARK_PROTOCOL,
        artifact_id=manifest["artifact_id"],
        operation=selected,
        batch_size=len(payloads),
        dataset_sha256=_digest(payloads),
        input_profile=_input_profile(payloads),
        environment={
            "implementation": platform.python_implementation(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
        },
        compiler=_compiler_payload(build),
        python_scalar=scalar,
        c99_native=native,
        native_marshal=marshal,
        native_kernel=kernel,
        native_manifestation=manifestation,
        comparison={
            "scope": (
                "execução completa: validação/marshal, kernel C99 e "
                "manifestação do envelope em Python"
            ),
            "semantically_equivalent": True,
            "arena_protocol": NATIVE_ARENA_PROTOCOL,
            "boundary_aot_protocol": NATIVE_BOUNDARY_AOT_PROTOCOL,
            "simd_protocol": NATIVE_SIMD_PROTOCOL,
            "native_profile": build.profile,
            "native_target": build.target,
            "wall_speedup": _safe_ratio(
                scalar.median_wall_ns,
                native.median_wall_ns,
            ),
            "paired_wall_speedup_median": statistics.median(
                paired_speedups
            ),
            "paired_wall_speedup_samples": list(paired_speedups),
            "paired_wall_speedup_ci95": speedup_ci,
            "cpu_work_ratio": _safe_ratio(
                scalar.median_cpu_ns,
                native.median_cpu_ns,
            ),
            "throughput_ratio": _safe_ratio(
                native.throughput_records_per_second,
                scalar.throughput_records_per_second,
            ),
            "marco_3_exit_reached": (
                speedup_ci["lower"] >= 5.0
            ),
            "stage_breakdown": {
                "independent_stage_sum_ns_per_record": stage_total,
                "marshal_share": _safe_ratio(
                    marshal.wall_ns_per_record,
                    stage_total,
                ),
                "kernel_share": _safe_ratio(
                    kernel.wall_ns_per_record,
                    stage_total,
                ),
                "manifestation_share": _safe_ratio(
                    manifestation.wall_ns_per_record,
                    stage_total,
                ),
                "warning": (
                    "estágios são medidos isoladamente; a soma não substitui "
                    "a medição ponta a ponta"
                ),
            },
        },
        equivalence_sha256=scalar_digest,
    )


def _compiler_payload(build: NativeBuild) -> dict[str, Any]:
    return {
        "path": build.compiler,
        "version": build.compiler_version,
        "binary_sha256": build.binary_sha256,
        "command": list(build.command),
        "cache_hit": build.cache_hit,
        "profile": build.profile,
        "target": build.target,
        "vectorization_report": list(build.vectorization_report),
    }


def _input_profile(payloads: list[dict[str, float]]) -> dict[str, Any]:
    fingerprints = {
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for payload in payloads
    }
    unique = len(fingerprints)
    return {
        "records": len(payloads),
        "unique_records": unique,
        "duplicate_rate": 1.0 - (unique / len(payloads)),
    }


def _bootstrap_median_ci(
    values: tuple[float, ...],
    *,
    resamples: int = 2_000,
    seed: int = 10_010,
) -> dict[str, Any]:
    if not values:
        raise NativeBenchmarkError("intervalo exige amostras de speedup")
    generator = random.Random(seed)
    size = len(values)
    medians = sorted(
        statistics.median(
            values[generator.randrange(size)]
            for _ in range(size)
        )
        for _ in range(resamples)
    )
    lower_index = int(0.025 * (resamples - 1))
    upper_index = int(0.975 * (resamples - 1))
    return {
        "lower": medians[lower_index],
        "upper": medians[upper_index],
        "confidence": 0.95,
        "method": "paired-bootstrap-median",
        "resamples": resamples,
        "seed": seed,
    }


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
