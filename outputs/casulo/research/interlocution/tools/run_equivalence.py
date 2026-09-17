from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from interlocution.authority import TrainingAuthority
from interlocution.contracts import canonical_sha256
from interlocution.equivalence import compare_result_files
from interlocution.worker import run_governed_worker, sha256_file

import independent_verifier


CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
RUNTIME = ROOT / "t-runtime/target/release/casulo-t-runtime.exe"


def write_json(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"append-only artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()
    output = CAMPAIGN / "equivalence/flood-v1"
    if output.exists():
        raise FileExistsError(f"append-only equivalence artifact exists: {output}")
    output.mkdir(parents=True)
    candidate = run_governed_worker(
        grant_file=CAMPAIGN / "authority-grant.json",
        authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
        primitive_manifest_file=CAMPAIGN / "primitive-manifest.json",
        executable=FULL / "worker/tcap_full_worker.exe",
        dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
        initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
        output_directory=output / "candidate",
        count=args.count,
    )
    reference_path = output / "eager-result.bin"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "casulo.livelab.energy_v1.full_workers",
            "--eager",
            "--tcap",
            str(FULL / "artifact/FloodSurrogate.full.tcap"),
            "--start",
            "0",
            "--count",
            str(args.count),
            "--output",
            str(reference_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(120.0, args.count * 5.0),
        check=False,
    )
    if process.returncode != 0 or not reference_path.is_file():
        raise RuntimeError(f"Eager oracle failed: {process.stderr}")
    eager_timing = json.loads(process.stdout)
    write_json(output / "eager-timing.json", eager_timing)
    equivalence = compare_result_files(
        candidate.result_file, reference_path, tolerance=1e-9
    )
    equivalence_seed = {
        **equivalence,
        "candidate_result_sha256": sha256_file(candidate.result_file),
        "reference_result_sha256": sha256_file(reference_path),
    }
    equivalence_document = {
        **equivalence_seed,
        "equivalence_sha256": canonical_sha256(equivalence_seed),
    }
    write_json(output / "equivalence.json", equivalence_document)
    verification = independent_verifier.verify_bundle(
        grant_file=CAMPAIGN / "authority-grant.json",
        authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
        primitive_manifest_file=CAMPAIGN / "primitive-manifest.json",
        work_receipt_file=output / "candidate/work-receipts.jsonl",
        result_file=candidate.result_file,
        summary_file=output / "candidate/worker-summary.json",
        dataset_file=FULL / "artifact/FloodSurrogate.dataset.bin",
        initialization_file=FULL / "artifact/FloodSurrogate.initializations.bin",
    )
    write_json(output / "independent-work-verification.json", verification)
    evidence = {
        "equivalence_status": equivalence["status"],
        "counter_status": "PASS" if all(item["counters_equal"] for item in equivalence["cases"]) else "FAIL",
        "receipt_status": verification["status"],
        "semantic_status": "PASS" if equivalence["status"] == "PASS" else "FAIL",
        "human_contract_confirmed": True,
        "cancelled": False,
    }
    authority = TrainingAuthority(
        RUNTIME,
        CAMPAIGN / "tcap/training-authority-plan.tcap",
        output / "judge-input",
    )
    grant = json.loads((CAMPAIGN / "authority-grant.json").read_text(encoding="utf-8"))
    judgment = authority.judge(
        evidence,
        previous_receipt_hash=grant["receipt_chain"][-1],
        call_id="flood-v1-final-judgment",
    )
    write_json(
        output / "judgment-receipt.json",
        {"observable":dict(judgment.observable),"runtime_receipt":dict(judgment.receipt)},
    )
    if judgment.observable["result"]["value"].get("decision") != "PUBLISH":
        raise RuntimeError("T judge did not authorize publication")
    accepted_seed = {
        "schema":"casulo.interlocution-accepted-instance/1.0",
        "status":"ACCEPTED_BY_T_JUDGE",
        "equivalence_sha256":equivalence_document["equivalence_sha256"],
        "independent_verification_sha256":verification["verification_sha256"],
        "judge_receipt_hash":judgment.receipt["receipt_hash"],
        "publisher_consumed_t_result":True,
    }
    accepted = {**accepted_seed,"acceptance_sha256":canonical_sha256(accepted_seed)}
    write_json(output / "accepted.json", accepted)
    print(json.dumps({"status":equivalence["status"],"work_units":args.count,"max_parameter":equivalence["maximum_parameter_abs_difference"],"max_prediction":equivalence["maximum_prediction_abs_difference"],"judge_receipt":judgment.receipt["receipt_hash"]}, sort_keys=True))
    return 0 if equivalence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

