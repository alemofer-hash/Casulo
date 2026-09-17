from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from casulo.livelab.energy_v1.full_workers import (
    compare_results,
    create_receipts,
    parse_initializations,
    parse_result_file,
    validate_full_tcap,
    validate_receipts,
)


@dataclass(frozen=True, slots=True)
class SameKernelResult:
    implementation: str
    K_requested: int
    K_frozen: int
    K_dispatched: int
    K_started: int
    K_completed: int
    receipt_count: int
    epochs_completed: int
    optimizer_steps: int
    records_visited: int
    parent_monotonic_ns: int
    child_monotonic_ns: int
    qpc_ticks: int
    qpc_frequency: int
    thread_cycles: int
    start_unix_ns: int
    end_unix_ns: int
    result_sha256: str
    receipt_chain_hash: str
    receipt_provenance: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_static_policy_same_kernel(
    *,
    executable: Path,
    tcap: Path,
    dataset: Path,
    initializations: Path,
    start: int,
    count: int,
    output_directory: Path,
) -> SameKernelResult:
    """Run the frozen primitive without T policy or T judgment.

    This is arm E: it shares the exact executable and work inputs with the
    T-governed arm, but uses a static foreign policy. Receipts are explicitly
    supervisor-derived from the completed binary result; they are not claimed
    as counters emitted incrementally by the native kernel.
    """

    output = Path(output_directory).resolve()
    if output.exists():
        raise FileExistsError(f"append-only same-kernel output exists: {output}")
    output.mkdir(parents=True)
    executable = Path(executable).resolve(strict=True)
    tcap = Path(tcap).resolve(strict=True)
    dataset = Path(dataset).resolve(strict=True)
    initializations = Path(initializations).resolve(strict=True)
    contract, segments, cases = validate_full_tcap(tcap)
    if hashlib.sha256(segments["scientific_dataset"]).hexdigest() != _sha256_file(dataset):
        raise ValueError("external dataset differs from the TCAP scientific dataset")
    if hashlib.sha256(segments["initialization_bundle"]).hexdigest() != _sha256_file(initializations):
        raise ValueError("external initialization bundle differs from the TCAP bundle")
    external_cases = parse_initializations(initializations.read_bytes())
    if external_cases != cases:
        raise ValueError("external initialization cases differ from the TCAP cases")
    if count < 1 or start < 0 or start + count > len(cases):
        raise ValueError("requested case range is invalid")
    result_path = output / "worker-result.bin"
    command = [
        str(executable),
        str(dataset),
        str(initializations),
        str(start),
        str(count),
        str(result_path),
    ]
    start_unix_ns = time.time_ns()
    parent_start = time.perf_counter_ns()
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(60.0, count * 2.0),
        check=False,
        env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
    )
    parent_ns = time.perf_counter_ns() - parent_start
    end_unix_ns = time.time_ns()
    if process.returncode != 0 or not result_path.is_file():
        raise RuntimeError(f"same-kernel primitive failed: rc={process.returncode} stderr={process.stderr.strip()}")
    fields = process.stdout.strip().split()
    if len(fields) != 7 or fields[0] != "RESULT":
        raise RuntimeError("same-kernel timing envelope is invalid")
    results = parse_result_file(result_path)
    receipts, chain = create_receipts(
        contract=contract,
        cases=cases[start : start + count],
        results=results,
    )
    validate_receipts(receipts, count)
    receipt_path = output / "supervisor-derived-work-receipts.jsonl"
    receipt_path.write_text(
        "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in receipts),
        encoding="utf-8",
        newline="\n",
    )
    result = SameKernelResult(
        "E_STATIC_POLICY_SAME_NATIVE_KERNEL",
        count,
        count,
        count,
        count,
        len(results),
        len(receipts),
        sum(item.epochs_completed for item in results),
        sum(item.optimizer_steps for item in results),
        sum(item.records_visited for item in results),
        parent_ns,
        int(fields[3]),
        int(fields[4]),
        int(fields[5]),
        int(fields[6]),
        start_unix_ns,
        end_unix_ns,
        _sha256_file(result_path),
        str(chain["aggregate_hash"]),
        "SUPERVISOR_DERIVED_FROM_COMPLETED_RESULT_NOT_KERNEL_INTERNAL",
    )
    (output / "same-kernel-result.json").write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def compare_same_work(candidate_result: Path, baseline_result: Path, *, tolerance: float = 1e-9) -> dict[str, Any]:
    return compare_results(parse_result_file(candidate_result), parse_result_file(baseline_result), tolerance=tolerance)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
