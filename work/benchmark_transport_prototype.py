from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any


PROJECT = Path(r"C:\Users\guimo\Downloads\telencefalus_desktop_v0_4_0")
sys.path.insert(0, str(PROJECT / "src"))

from telencefalus.core.hbits_transport import HBitsFactorizer, HBitsTransport


NETWORK = {
    "latency_ms": 10,
    "bandwidth_mbps": 100,
    "packet_loss_percent": 0,
    "cpu_cost_factor": 1.0,
    "priority_semantic": 1.0,
}


def json_size(value: Any) -> int:
    return len(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    )


def encoded_factorization(payload: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    factor = HBitsFactorizer.factorize("bench", payload, previous)
    return {
        "kernel": factor.kernel.content,
        "delta": factor.delta.changes,
        "metadata": {
            "payload_id": factor.metadata.payload_id,
            "version": factor.metadata.version,
            "integrity_hash": factor.metadata.integrity_hash,
            "canonical_schema": factor.metadata.canonical_schema,
            "rehydration_rules": factor.metadata.rehydration_rules,
        },
    }


def median_ms(fn: Any, iterations: int = 30) -> float:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
    return statistics.median(samples)


def main() -> None:
    flat_initial: dict[str, Any] = {
        "schema_version": 1,
        "config_model": "hydrology",
        **{f"station_{index:04d}": float(index) for index in range(2_000)},
    }
    flat_next = dict(flat_initial)
    flat_next["station_1000"] = 1000.25

    nested_initial = {
        "schema_version": 1,
        "config_model": "hydrology",
        "readings": [float(index) for index in range(2_000)],
    }
    nested_next = {
        **nested_initial,
        "readings": list(nested_initial["readings"]),
    }
    nested_next["readings"][1000] = 1000.25

    cases = [
        ("flat_initial", flat_initial, None),
        ("flat_one_change", flat_next, flat_initial),
        ("nested_initial", nested_initial, None),
        ("nested_one_change", nested_next, nested_initial),
    ]
    report: dict[str, Any] = {"cases": {}}
    transport = HBitsTransport()

    for name, payload, previous in cases:
        encoded = encoded_factorization(payload, previous)
        rehydrated, _ = transport.transport("bench", payload, NETWORK, previous)
        full_bytes = json_size(payload)
        encoded_bytes = json_size(encoded)
        report["cases"][name] = {
            "full_json_bytes": full_bytes,
            "prototype_representation_bytes": encoded_bytes,
            "size_ratio_vs_full": encoded_bytes / full_bytes,
            "input_top_level_fields": len(payload),
            "rehydrated_top_level_fields": len(rehydrated),
            "rehydration_equals_full_input": rehydrated == payload,
            "json_encode_median_ms": median_ms(lambda: json_size(payload)),
            "prototype_pipeline_median_ms": median_ms(
                lambda: transport.transport("bench", payload, NETWORK, previous)
            ),
        }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
