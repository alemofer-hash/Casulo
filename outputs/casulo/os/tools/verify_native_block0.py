from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OS_ROOT = ROOT / "os"
DEFAULT_ORACLE = (
    ROOT
    / "outputs/casulo/native-neural-port/2026-08-21-np6/block0-oracle-attempt-3.json"
)
DEFAULT_RUNNER = OS_ROOT / "target/release/examples/block0_host.exe"
DEFAULT_MODEL = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362/model/Qwen3-4B-Q4_K_M.gguf"
)

STAGE_NAMES = {
    "embedding": "embedding",
    "attn_norm": "attn_norm",
    "query_projection": "query_projection",
    "key_projection": "key_projection",
    "value_projection": "value_projection",
    "query_norm": "q_norm",
    "key_norm": "k_norm",
    "query_rope": "q_rope",
    "key_rope": "k_rope",
    "attention_weights": "attention_weights",
    "attention_context": "attention_context",
    "attention_projection": "attention_projection",
    "attention_residual": "attention_residual",
    "ffn_norm": "ffn_norm",
    "ffn_gate": "ffn_gate",
    "ffn_up": "ffn_up",
    "ffn_activated": "ffn_activated",
    "ffn_down": "ffn_down",
    "block_output": "block_output",
}

EXPECTED_COUNTERS = {
    "TOKENS_COMPLETED": 2,
    "DESCRIPTORS_SCANNED": 398,
    "MATVEC_CALLS": 14,
    "QUANTIZED_BLOCKS": 788_480,
    "WEIGHT_BYTES_READ": 127_733_760,
    "MULTIPLY_ACCUMULATES": 201_850_880,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_stdout(stdout: str) -> tuple[dict[str, str], dict[str, dict[str, float | int]]]:
    counters: dict[str, str] = {}
    stages: dict[str, dict[str, float | int]] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("STAGE|"):
            fields = line.split("|")
            if len(fields) != 7:
                raise ValueError(f"invalid stage receipt: {line}")
            _, name, values, total, square_sum, minimum, maximum = fields[0:7]
            if name in stages:
                raise ValueError(f"duplicate stage receipt: {name}")
            stages[name] = {
                "values": int(values),
                "sum_f64": float(total),
                "square_sum_f64": float(square_sum),
                "minimum": float(minimum),
                "maximum": float(maximum),
            }
        elif "=" in line:
            key, value = line.split("=", 1)
            if key in counters:
                raise ValueError(f"duplicate counter: {key}")
            counters[key] = value
    return counters, stages


def within(observed: float, expected: float, *, absolute: float, relative: float) -> bool:
    return abs(observed - expected) <= max(absolute, abs(expected) * relative)


def compare(oracle: dict[str, object], counters: dict[str, str], stages: dict[str, dict[str, float | int]]) -> dict[str, object]:
    counter_checks = {
        key: {
            "expected": expected,
            "observed": int(counters[key]) if key in counters else None,
            "pass": key in counters and int(counters[key]) == expected,
        }
        for key, expected in EXPECTED_COUNTERS.items()
    }
    expected_stages = oracle["intermediates"]
    stage_checks: list[dict[str, object]] = []
    for token in range(2):
        for native_suffix, oracle_suffix in STAGE_NAMES.items():
            native_name = f"token_{token}.{native_suffix}"
            oracle_name = f"token_{token}.{oracle_suffix}"
            expected = expected_stages.get(oracle_name)
            observed = stages.get(native_name)
            if expected is None or observed is None:
                stage_checks.append(
                    {
                        "native_stage": native_name,
                        "oracle_stage": oracle_name,
                        "pass": False,
                        "reason": "missing stage",
                    }
                )
                continue
            expected_square_sum = float(expected["l2_f64"]) ** 2
            checks = {
                "values": int(observed["values"]) == int(expected["shape"][0] if len(expected["shape"]) == 1 else __import__("math").prod(expected["shape"])),
                "sum": within(float(observed["sum_f64"]), float(expected["sum_f64"]), absolute=0.001, relative=0.0005),
                "square_sum": within(float(observed["square_sum_f64"]), expected_square_sum, absolute=0.001, relative=0.0005),
                "minimum": within(float(observed["minimum"]), float(expected["min"]), absolute=0.0001, relative=0.0005),
                "maximum": within(float(observed["maximum"]), float(expected["max"]), absolute=0.0001, relative=0.0005),
            }
            stage_checks.append(
                {
                    "native_stage": native_name,
                    "oracle_stage": oracle_name,
                    "observed": observed,
                    "expected": {
                        "values": __import__("math").prod(expected["shape"]),
                        "sum_f64": expected["sum_f64"],
                        "square_sum_f64": expected_square_sum,
                        "minimum": expected["min"],
                        "maximum": expected["max"],
                    },
                    "checks": checks,
                    "pass": all(checks.values()),
                }
            )
    return {
        "schema": "casulo-native-block0-comparison/0.1",
        "tolerance_frozen": {
            "sum_and_square_sum": {"absolute": 0.001, "relative": 0.0005},
            "minimum_and_maximum": {"absolute": 0.0001, "relative": 0.0005},
            "bit_identity_required": False,
            "reason": "independent NumPy and scalar Rust accumulation orders",
        },
        "counter_checks": counter_checks,
        "stage_checks": stage_checks,
        "stages_expected": 38,
        "stages_observed": len(stages),
        "status": (
            "PASS"
            if all(item["pass"] for item in counter_checks.values())
            and len(stage_checks) == 38
            and all(item["pass"] for item in stage_checks)
            else "FAIL"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Native block-zero worker against the frozen NumPy oracle")
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    oracle_path = args.oracle.resolve(strict=True)
    runner = args.runner.resolve(strict=True)
    model = args.model.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    if sha256(model) != oracle["model"]["sha256"] or model.stat().st_size != oracle["model"]["bytes"]:
        raise SystemExit("model identity diverges from oracle")
    started = time.time()
    process = subprocess.run(
        [str(runner), str(model)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=120,
    )
    ended = time.time()
    stdout_path = output_dir / "host-block0-stdout.txt"
    stdout_path.write_text(process.stdout, encoding="utf-8")
    if process.stderr:
        (output_dir / "host-block0-stderr.txt").write_text(process.stderr, encoding="utf-8")
    if process.returncode != 0:
        raise SystemExit(f"host block worker failed with {process.returncode}")
    counters, stages = parse_stdout(process.stdout)
    comparison = compare(oracle, counters, stages)
    receipt = {
        "schema": "casulo-native-block0-host-receipt/0.1",
        "claim": "two adopted-model tokens completed block zero only; no logits or output token",
        "runner": {"path": str(runner), "sha256": sha256(runner)},
        "model": {"path": str(model), "bytes": model.stat().st_size, "sha256": sha256(model)},
        "oracle": {"path": str(oracle_path), "sha256": sha256(oracle_path)},
        "started_unix": started,
        "ended_unix": ended,
        "duration_seconds_observational_not_benchmark": ended - started,
        "counters": counters,
        "stages": stages,
        "comparison_status": comparison["status"],
    }
    (output_dir / "host-block0-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "block0-comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": comparison["status"], "stages": len(stages), "output_dir": str(output_dir)}, indent=2))
    return 0 if comparison["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
