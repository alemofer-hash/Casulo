from __future__ import annotations

import gc
import hashlib
import json
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .artifact import ArtifactError
from .runner import load_artifact, select_operation


BENCHMARK_VERSION = "metamorfose-benchmark/0.1"


class BenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Measurement:
    name: str
    records_per_sample: int
    iterations: int
    samples: int
    wall_ns_samples: tuple[int, ...]
    cpu_ns_samples: tuple[int, ...]
    median_wall_ns: int
    median_cpu_ns: int
    wall_ns_per_record: float
    cpu_ns_per_record: float
    throughput_records_per_second: float


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    version: str
    artifact_id: str
    operation: str
    batch_size: int
    environment: dict[str, str]
    scalar: Measurement
    batch: Measurement
    comparison: dict[str, float | None]
    equivalence_sha256: str
    energy_proxy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def benchmark_artifact(
    artifact_dir: str | Path,
    payloads: list[Any],
    operation: str | None = None,
    *,
    samples: int = 5,
    iterations: int = 10,
) -> BenchmarkReport:
    if not payloads:
        raise BenchmarkError("benchmark exige ao menos um registro")
    if samples < 1 or iterations < 1:
        raise BenchmarkError("samples e iterations precisam ser positivos")

    loaded = load_artifact(artifact_dir)
    selected = select_operation(loaded.manifest, operation)
    scalar_execute = loaded.namespace.get("execute")
    batch_execute = loaded.namespace.get("execute_batch")
    clear_cache = loaded.namespace.get("clear_cache")
    if not callable(scalar_execute) or not callable(batch_execute):
        raise ArtifactError(
            "artefato não expõe execução escalar e execução em lote"
        )

    def scalar_call() -> list[dict[str, Any]]:
        return [
            scalar_execute(selected, item, use_cache=False)
            for item in payloads
        ]

    def batch_call() -> list[dict[str, Any]]:
        return batch_execute(
            selected,
            payloads,
            use_cache=False,
        )["items"]

    if callable(clear_cache):
        clear_cache(selected)
    scalar_reference = scalar_call()
    batch_reference = batch_call()
    scalar_digest = _digest(scalar_reference)
    batch_digest = _digest(batch_reference)
    if scalar_digest != batch_digest:
        raise BenchmarkError(
            "kernel de lote divergiu semanticamente da execução escalar"
        )

    scalar_wall: list[int] = []
    scalar_cpu: list[int] = []
    batch_wall: list[int] = []
    batch_cpu: list[int] = []
    gc_was_enabled = gc.isenabled()
    try:
        gc.disable()
        for sample in range(samples):
            order = (
                (
                    (scalar_call, scalar_wall, scalar_cpu),
                    (batch_call, batch_wall, batch_cpu),
                )
                if sample % 2 == 0
                else (
                    (batch_call, batch_wall, batch_cpu),
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

    scalar = _summarize(
        "python_scalar_loop",
        len(payloads),
        iterations,
        scalar_wall,
        scalar_cpu,
    )
    batch = _summarize(
        "metamorfose_fused_batch",
        len(payloads),
        iterations,
        batch_wall,
        batch_cpu,
    )
    return BenchmarkReport(
        version=BENCHMARK_VERSION,
        artifact_id=loaded.manifest["artifact_id"],
        operation=selected,
        batch_size=len(payloads),
        environment={
            "implementation": platform.python_implementation(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
        },
        scalar=scalar,
        batch=batch,
        comparison={
            "wall_speedup": _safe_ratio(
                scalar.median_wall_ns,
                batch.median_wall_ns,
            ),
            "cpu_work_ratio": _safe_ratio(
                scalar.median_cpu_ns,
                batch.median_cpu_ns,
            ),
            "throughput_ratio": _safe_ratio(
                batch.throughput_records_per_second,
                scalar.throughput_records_per_second,
            ),
        },
        equivalence_sha256=scalar_digest,
        energy_proxy={
            "method": "process_cpu_time",
            "unit": "cpu_nanoseconds",
            "electrical_energy_joules": None,
            "scalar_median": scalar.median_cpu_ns,
            "batch_median": batch.median_cpu_ns,
            "warning": (
                "tempo de CPU é proxy de trabalho computacional; "
                "não é medição elétrica"
            ),
        },
    )


def _measure(
    function: Callable[[], Any],
    iterations: int,
) -> tuple[int, int]:
    wall_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    for _ in range(iterations):
        function()
    cpu_elapsed = time.process_time_ns() - cpu_start
    wall_elapsed = time.perf_counter_ns() - wall_start
    return wall_elapsed, cpu_elapsed


def _summarize(
    name: str,
    records: int,
    iterations: int,
    wall_values: list[int],
    cpu_values: list[int],
) -> Measurement:
    wall_median = int(statistics.median(wall_values))
    cpu_median = int(statistics.median(cpu_values))
    processed = records * iterations
    wall_per_record = wall_median / processed
    cpu_per_record = cpu_median / processed
    throughput = (
        processed / (wall_median / 1_000_000_000)
        if wall_median
        else float("inf")
    )
    return Measurement(
        name=name,
        records_per_sample=records,
        iterations=iterations,
        samples=len(wall_values),
        wall_ns_samples=tuple(wall_values),
        cpu_ns_samples=tuple(cpu_values),
        median_wall_ns=wall_median,
        median_cpu_ns=cpu_median,
        wall_ns_per_record=wall_per_record,
        cpu_ns_per_record=cpu_per_record,
        throughput_records_per_second=throughput,
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_ratio(
    numerator: float,
    denominator: float,
) -> float | None:
    return numerator / denominator if denominator else None
