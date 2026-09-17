from __future__ import annotations

import gc
import hashlib
import json
import platform
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .benchmark import Measurement, _measure, _safe_ratio, _summarize
from .native import (
    NATIVE_SIMD_PROTOCOL,
    NativeBuild,
    prepare_native_executor,
)
from .native_benchmark import _bootstrap_median_ci


SIMD_BENCHMARK_PROTOCOL = "casulo-simd-benchmark/0.1"
SIMD_MIN_BATCH_RECORDS = 512


class SimdBenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SimdBenchmarkReport:
    protocol: str
    artifact_id: str
    operation: str
    batch_size: int
    dataset_sha256: str
    environment: dict[str, str]
    scalar_compiler: dict[str, Any]
    simd_compiler: dict[str, Any]
    scalar_kernel: Measurement
    simd_kernel: Measurement
    comparison: dict[str, Any]
    equivalence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def benchmark_simd_artifact(
    artifact_dir: str | Path,
    payloads: list[dict[str, float]],
    operation: str | None = None,
    *,
    samples: int = 9,
    iterations: int = 2_000,
) -> SimdBenchmarkReport:
    if not payloads:
        raise SimdBenchmarkError("benchmark SIMD exige ao menos um registro")
    if samples < 1 or iterations < 1:
        raise SimdBenchmarkError("samples e iterations precisam ser positivos")

    scalar, manifest, native_entry, scalar_build = prepare_native_executor(
        artifact_dir,
        operation,
        profile="scalar",
    )
    simd, simd_manifest, simd_entry, simd_build = prepare_native_executor(
        artifact_dir,
        operation,
        profile="simd",
    )
    if (
        manifest["artifact_id"] != simd_manifest["artifact_id"]
        or native_entry["name"] != simd_entry["name"]
    ):
        raise SimdBenchmarkError("perfis não pertencem à mesma operação")

    scalar_reference = scalar(payloads)
    simd_reference = simd(payloads)
    scalar_digest = _digest(scalar_reference)
    if scalar_digest != _digest(simd_reference):
        raise SimdBenchmarkError("SIMD divergiu do perfil escalar estrito")

    scalar.marshal(payloads)
    simd.marshal(payloads)

    def scalar_call() -> None:
        scalar.kernel(len(payloads))

    def simd_call() -> None:
        simd.kernel(len(payloads))

    scalar_call()
    simd_call()
    scalar_wall: list[int] = []
    scalar_cpu: list[int] = []
    simd_wall: list[int] = []
    simd_cpu: list[int] = []
    gc_was_enabled = gc.isenabled()
    try:
        gc.disable()
        for sample in range(samples):
            order = (
                (
                    (scalar_call, scalar_wall, scalar_cpu),
                    (simd_call, simd_wall, simd_cpu),
                )
                if sample % 2 == 0
                else (
                    (simd_call, simd_wall, simd_cpu),
                    (scalar_call, scalar_wall, scalar_cpu),
                )
            )
            for function, wall_values, cpu_values in order:
                wall, cpu = _measure(function, iterations)
                wall_values.append(wall)
                cpu_values.append(cpu)
    finally:
        if gc_was_enabled:
            gc.enable()

    scalar_measurement = _summarize(
        "c99_scalar_strict_kernel",
        len(payloads),
        iterations,
        scalar_wall,
        scalar_cpu,
    )
    simd_measurement = _summarize(
        "c99_host_simd_strict_kernel",
        len(payloads),
        iterations,
        simd_wall,
        simd_cpu,
    )
    paired = tuple(
        scalar_value / simd_value
        for scalar_value, simd_value in zip(scalar_wall, simd_wall)
        if simd_value
    )
    ci = _bootstrap_median_ci(
        paired,
        seed=11_011,
    )
    vectorized_lines = tuple(
        line
        for line in simd_build.vectorization_report
        if "optimized: loop vectorized" in line.lower()
        or "vectorized loop" in line.lower()
    )
    widths = tuple(
        sorted(
            {
                int(token)
                for line in vectorized_lines
                for token in line.replace("-", " ").split()
                if token.isdigit() and int(token) in {8, 16, 32, 64}
            }
        )
    )
    gate = (
        len(payloads) >= SIMD_MIN_BATCH_RECORDS
        and bool(vectorized_lines)
        and ci["lower"] > 1.0
    )
    return SimdBenchmarkReport(
        protocol=SIMD_BENCHMARK_PROTOCOL,
        artifact_id=manifest["artifact_id"],
        operation=native_entry["name"],
        batch_size=len(payloads),
        dataset_sha256=_digest(payloads),
        environment={
            "implementation": platform.python_implementation(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
        },
        scalar_compiler=_compiler_payload(scalar_build),
        simd_compiler=_compiler_payload(simd_build),
        scalar_kernel=scalar_measurement,
        simd_kernel=simd_measurement,
        comparison={
            "protocol": NATIVE_SIMD_PROTOCOL,
            "scope": "kernel C99 estrito pré-materializado",
            "semantically_equivalent": True,
            "floating_point": "strict-no-reassociation",
            "wall_speedup": _safe_ratio(
                scalar_measurement.median_wall_ns,
                simd_measurement.median_wall_ns,
            ),
            "cpu_work_ratio": _safe_ratio(
                scalar_measurement.median_cpu_ns,
                simd_measurement.median_cpu_ns,
            ),
            "paired_wall_speedup_median": statistics.median(paired),
            "paired_wall_speedup_samples": list(paired),
            "paired_wall_speedup_ci95": ci,
            "vectorized_report_lines": list(vectorized_lines),
            "reported_vector_width_bytes": list(widths),
            "minimum_batch_records": SIMD_MIN_BATCH_RECORDS,
            "sprint_011_exit_reached": gate,
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
