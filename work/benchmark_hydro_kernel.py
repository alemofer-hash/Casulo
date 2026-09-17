from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np


N = 1_000_000
REPEATS = 9


def scalar_python(
    precipitation: np.ndarray,
    evapotranspiration: np.ndarray,
    surface_flow: np.ndarray,
    base_flow: np.ndarray,
    output: np.ndarray,
) -> None:
    for index in range(precipitation.size):
        output[index] = (
            precipitation[index]
            - evapotranspiration[index]
            - surface_flow[index]
            - base_flow[index]
        )


def vectorized_numpy(
    precipitation: np.ndarray,
    evapotranspiration: np.ndarray,
    surface_flow: np.ndarray,
    base_flow: np.ndarray,
    output: np.ndarray,
) -> None:
    np.subtract(precipitation, evapotranspiration, out=output)
    np.subtract(output, surface_flow, out=output)
    np.subtract(output, base_flow, out=output)


def vectorized_numpy_chunk(
    precipitation: np.ndarray,
    evapotranspiration: np.ndarray,
    surface_flow: np.ndarray,
    base_flow: np.ndarray,
    output: np.ndarray,
) -> None:
    vectorized_numpy(precipitation, evapotranspiration, surface_flow, base_flow, output)


def vectorized_numpy_4_threads(
    precipitation: np.ndarray,
    evapotranspiration: np.ndarray,
    surface_flow: np.ndarray,
    base_flow: np.ndarray,
    output: np.ndarray,
    executor: ThreadPoolExecutor,
) -> None:
    boundaries = np.linspace(0, precipitation.size, 5, dtype=np.int64)
    futures = []
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        region = slice(int(start), int(stop))
        futures.append(
            executor.submit(
                vectorized_numpy_chunk,
                precipitation[region],
                evapotranspiration[region],
                surface_flow[region],
                base_flow[region],
                output[region],
            )
        )
    for future in futures:
        future.result()


def samples_ms(fn: object, *args: object, repeats: int = REPEATS) -> list[float]:
    result: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        fn(*args)
        result.append((time.perf_counter_ns() - start) / 1_000_000)
    return result


def summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "median_ms": statistics.median(samples),
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def main() -> None:
    rng = np.random.default_rng(42)
    inputs = [
        rng.uniform(0, high, size=N).astype(np.float32)
        for high in (200.0, 10.0, 80.0, 20.0)
    ]
    output = np.empty(N, dtype=np.float32)

    results = {
        "cells": N,
        "dtype": "float32",
        "input_plus_output_mib": (sum(item.nbytes for item in inputs) + output.nbytes)
        / (1024 * 1024),
        "worker_threads": 4,
        "steady_state": {},
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        functions = [
            ("python_scalar_loop", scalar_python, ()),
            ("numpy_vectorized_single_calling_thread", vectorized_numpy, ()),
            ("numpy_vectorized_4_worker_threads", vectorized_numpy_4_threads, (executor,)),
        ]
        baseline_median = None
        reference = None
        for name, fn, extra in functions:
            timings = samples_ms(fn, *inputs, output, *extra)
            current = summary(timings)
            if baseline_median is None:
                baseline_median = current["median_ms"]
            current["speedup_vs_python_loop"] = baseline_median / current["median_ms"]
            if reference is None:
                reference = output.copy()
            current["max_abs_error_vs_first"] = float(np.max(np.abs(output - reference)))
            results["steady_state"][name] = current

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
