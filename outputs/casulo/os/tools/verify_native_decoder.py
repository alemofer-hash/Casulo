from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
ABSOLUTE_TOLERANCE = 0.001
RELATIVE_TOLERANCE = 0.0005


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def within(observed: float, expected: float) -> bool:
    return abs(observed - expected) <= max(ABSOLUTE_TOLERANCE, abs(expected) * RELATIVE_TOLERANCE)


def parse_summary(parts: list[str]) -> dict[str, float | int]:
    if len(parts) != 6:
        raise ValueError("summary field count")
    return {
        "values": int(parts[1]),
        "sum_f64": float(parts[2]),
        "square_sum_f64": float(parts[3]),
        "minimum": float(parts[4]),
        "maximum": float(parts[5]),
    }


def parse_stdout(stdout: str) -> dict[str, object]:
    scalar: dict[str, str] = {}
    blocks: dict[int, dict[str, float | int]] = {}
    summaries: dict[str, dict[str, float | int]] = {}
    for line in stdout.splitlines():
        if line.startswith("BLOCK|"):
            parts = line.split("|")
            if len(parts) != 6:
                raise ValueError("block field count")
            blocks[int(parts[1])] = {
                "sum_f64": float(parts[2]),
                "square_sum_f64": float(parts[3]),
                "minimum": float(parts[4]),
                "maximum": float(parts[5]),
            }
        elif line.startswith("FINAL_NORM|") or line.startswith("LOGITS|"):
            parts = line.split("|")
            summaries[parts[0]] = parse_summary(parts)
        elif "=" in line and not line.startswith(("Finished", "Running")):
            key, value = line.split("=", 1)
            scalar[key] = value
    return {"scalar": scalar, "blocks": blocks, "summaries": summaries}


def compare_summary(observed: dict[str, float | int], expected: dict[str, object]) -> dict[str, bool]:
    expected_square = float(expected["l2_f64"]) ** 2
    return {
        "values": int(observed["values"]) == int(expected["shape"][0]),
        "sum_f64": within(float(observed["sum_f64"]), float(expected["sum_f64"])),
        "square_sum_f64": within(float(observed["square_sum_f64"]), expected_square),
        "minimum": within(float(observed["minimum"]), float(expected["min"])),
        "maximum": within(float(observed["maximum"]), float(expected["max"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the scalar Rust 36-block decoder against NumPy")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--oracle-logits", type=Path, required=True)
    parser.add_argument("--rust-logits", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    model = args.model.resolve(strict=True)
    oracle_path = args.oracle.resolve(strict=True)
    oracle_logits_path = args.oracle_logits.resolve(strict=True)
    rust_logits_path = args.rust_logits.resolve()
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    if output.exists():
        raise SystemExit(f"append-only output exists: {output}")
    if ROOT.resolve() not in rust_logits_path.parents or rust_logits_path.exists():
        raise SystemExit("rust logits output must be a new file inside repository")
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    model_before = sha256(model)
    completed = subprocess.run(
        [str(binary), str(model), str(rust_logits_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout,
    )
    model_after = sha256(model)
    parsed = parse_stdout(completed.stdout)
    block_checks: list[dict[str, object]] = []
    for expected in oracle["block_receipts"]:
        index = int(expected["block"])
        observed = parsed["blocks"].get(index)
        checks = (
            {"present": False}
            if observed is None
            else {
                "present": True,
                "sum_f64": within(float(observed["sum_f64"]), float(expected["output"]["sum_f64"])),
                "square_sum_f64": within(
                    float(observed["square_sum_f64"]), float(expected["output"]["l2_f64"]) ** 2
                ),
                "minimum": within(float(observed["minimum"]), float(expected["output"]["min"])),
                "maximum": within(float(observed["maximum"]), float(expected["output"]["max"])),
            }
        )
        block_checks.append({"block": index, "checks": checks, "passed": all(checks.values())})
    norm_checks = compare_summary(parsed["summaries"].get("FINAL_NORM", {}), oracle["normalized_output"])
    logits_checks = compare_summary(parsed["summaries"].get("LOGITS", {}), oracle["logits"]["summary"])
    oracle_logits = np.fromfile(oracle_logits_path, dtype="<f4")
    if not rust_logits_path.is_file():
        raise SystemExit("decoder did not produce the requested logit vector")
    rust_logits = np.fromfile(rust_logits_path, dtype="<f4")
    if oracle_logits.shape != rust_logits.shape or oracle_logits.shape != (151_936,):
        raise SystemExit("logit vector shape mismatch")
    difference = rust_logits.astype(np.float64) - oracle_logits.astype(np.float64)
    allowed = np.maximum(
        ABSOLUTE_TOLERANCE,
        np.abs(oracle_logits.astype(np.float64)) * RELATIVE_TOLERANCE,
    )
    logit_vector_checks = {
        "values": int(oracle_logits.size),
        "all_finite": bool(np.isfinite(oracle_logits).all() and np.isfinite(rust_logits).all()),
        "values_outside_frozen_tolerance": int(np.count_nonzero(np.abs(difference) > allowed)),
        "max_absolute_difference": float(np.max(np.abs(difference))),
        "mean_absolute_difference": float(np.mean(np.abs(difference))),
        "root_mean_square_difference": float(np.sqrt(np.mean(difference * difference))),
        "mean_bias": float(np.mean(difference)),
        "top20_identical": bool(
            np.array_equal(np.argsort(oracle_logits)[-20:][::-1], np.argsort(rust_logits)[-20:][::-1])
        ),
    }
    logit_vector_passed = bool(
        logit_vector_checks["all_finite"]
        and logit_vector_checks["values_outside_frozen_tolerance"] == 0
        and logit_vector_checks["top20_identical"]
    )
    scalar = parsed["scalar"]
    accounting = {
        "blocks": scalar.get("BLOCKS_COMPLETED") == "36",
        "matvec_calls": int(scalar.get("MATVEC_CALLS", -1)) == int(oracle["operation_counts"]["matvec_calls"]),
        "multiply_accumulates": int(scalar.get("MULTIPLY_ACCUMULATES", -1))
        == int(oracle["operation_counts"]["multiply_accumulates"]),
        "greedy_token": int(scalar.get("GREEDY_TOKEN_ID", -1)) == int(oracle["logits"]["greedy_token_id"]),
        "greedy_logit": within(
            float(scalar.get("GREEDY_TOKEN_LOGIT", "nan")), float(oracle["logits"]["greedy_token_logit"])
        ),
    }
    passed = bool(
        completed.returncode == 0
        and model_before == model_after == oracle["model"]["sha256"]
        and len(block_checks) == 36
        and all(item["passed"] for item in block_checks)
        and all(norm_checks.values())
        and logit_vector_passed
        and all(accounting.values())
    )
    report = {
        "schema": "casulo-native-qwen-decoder-comparison/0.1",
        "status": "PASS" if passed else "FAIL",
        "binary": {"path": str(binary), "sha256": sha256(binary)},
        "model": {"path": str(model), "sha256_before": model_before, "sha256_after": model_after},
        "oracle": {"path": str(oracle_path), "sha256": sha256(oracle_path)},
        "logit_vectors": {
            "oracle_path": str(oracle_logits_path),
            "oracle_sha256": sha256(oracle_logits_path),
            "rust_path": str(rust_logits_path),
            "rust_sha256": sha256(rust_logits_path),
            "checks": logit_vector_checks,
            "passed": logit_vector_passed,
        },
        "process": {
            "returncode": completed.returncode,
            "stderr": completed.stderr,
            "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        },
        "tolerances": {"absolute": ABSOLUTE_TOLERANCE, "relative": RELATIVE_TOLERANCE},
        "block_checks": block_checks,
        "final_norm_checks": norm_checks,
        "logits_checks": logits_checks,
        "aggregate_logit_sum_is_diagnostic_only": True,
        "accounting": accounting,
        "observed": parsed,
        "claims": {
            "blocks_completed": 36 if scalar.get("BLOCKS_COMPLETED") == "36" else 0,
            "logits_executed": "LOGITS" in parsed["summaries"],
            "sampling_executed": False,
            "output_token_published": False,
            "external_api": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "accounting": accounting, "output": str(output)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
