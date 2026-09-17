from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from interlocution.authority import TrainingAuthority
from interlocution.contracts import canonical_sha256
from interlocution.equivalence import compare_result_files
from interlocution.worker import run_governed_worker, sha256_file
from interlocution.policy import MODULES
from casulo.t.productive import ProductiveTExecutor

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


def capabilities() -> dict[str, bool]:
    return {
        "float64_supported": True,
        "mse_supported": True,
        "sgd_supported": True,
        "reset_supported": True,
        "no_cross_case_state": True,
        "selection_supported": True,
        "fixed_epoch_supported": True,
        "counter_supported": True,
        "independent_verifier_available": True,
        "publisher_requires_t": True,
    }


def fresh_authority(output: Path) -> tuple[TrainingAuthority, dict, Path]:
    authority = TrainingAuthority(
        RUNTIME,
        CAMPAIGN / "tcap/training-authority-plan.tcap",
        output / "t-runtime-inputs",
    )
    initialization = json.loads(
        (FULL / "artifact/initialization_bundle.json").read_text(encoding="utf-8")
    )
    grant = authority.authorize(
        dataset_sha256=sha256_file(FULL / "artifact/FloodSurrogate.dataset.bin"),
        records=1024,
        input_features=8,
        initialization_sha256=sha256_file(
            FULL / "artifact/FloodSurrogate.initializations.bin"
        ),
        cases_unique=bool(initialization["all_parameter_hashes_unique"]),
        nonces_unique=bool(initialization["all_nonces_unique"]),
        capabilities=capabilities(),
    )
    receipts = output / "policy-authority.jsonl"
    receipts.write_text(
        "".join(
            json.dumps(call.receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
            for call in grant.calls
        ),
        encoding="utf-8",
        newline="\n",
    )
    plan = json.loads((CAMPAIGN / "training_authority_plan.json").read_text(encoding="utf-8"))
    binding = json.loads((CAMPAIGN / "tcap-binding.json").read_text(encoding="utf-8"))
    document = {
        "schema": "casulo.interlocution-authority-grant/1.0",
        "campaign_id": CAMPAIGN.name,
        "plan_sha256": plan["plan_sha256"],
        "tcap_hash": binding["tcap_hash"],
        "config_from_t": dict(grant.config),
        "receipt_chain": list(grant.receipt_chain),
        "surfaces": [call.receipt["surface_id"] for call in grant.calls],
        "foreign_affirmative_fallback": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    document["grant_sha256"] = canonical_sha256(document)
    write_json(output / "authority-grant.json", document)
    return authority, document, receipts


def run_eager(output: Path, count: int, start: int) -> tuple[Path, dict]:
    result = output / "result.bin"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "casulo.livelab.energy_v1.full_workers",
            "--eager",
            "--tcap",
            str(FULL / "artifact/FloodSurrogate.full.tcap"),
            "--start",
            str(start),
            "--count",
            str(count),
            "--output",
            str(result),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(120.0, count * 5.0),
        check=False,
    )
    if process.returncode != 0 or not result.is_file():
        raise RuntimeError(f"Eager failed: rc={process.returncode} {process.stderr}")
    return result, json.loads(process.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=("A", "B", "C", "D"), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"append-only arm output exists: {output}")
    output.mkdir(parents=True)
    phases: dict[str, int] = {}
    process_start = time.perf_counter_ns()
    authority = None
    grant = None
    authority_receipts = None

    if args.arm in {"C", "D"}:
        started = time.perf_counter_ns()
        authority, grant, authority_receipts = fresh_authority(output)
        phases["t_architecture_ns"] = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    if args.arm in {"A", "B"}:
        result_file, child_timing = run_eager(output, args.count, args.start)
        phases["training_ns"] = time.perf_counter_ns() - started
        work_summary = {
            "K_completed": args.count,
            "implementation": "PYTORCH_EAGER_TRANSPARENT",
            "child_timing": child_timing,
        }
    else:
        governed = run_governed_worker(
            grant_file=output / "authority-grant.json",
            authority_receipt_file=authority_receipts,
            primitive_manifest_file=CAMPAIGN / "primitive-manifest.json",
            executable=FULL / "worker/tcap_full_worker.exe",
            dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
            initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
            output_directory=output / "worker",
            start=args.start,
            count=args.count,
        )
        phases["training_and_receipting_ns"] = time.perf_counter_ns() - started
        result_file = governed.result_file
        work_summary = dict(governed.summary)

    verification = None
    equivalence = None
    judgment = None
    if args.arm == "B":
        started = time.perf_counter_ns()
        audit_executor = ProductiveTExecutor(
            RUNTIME,
            CAMPAIGN / "tcap/training-authority-plan.tcap",
            output / "posthoc-audit-input",
        )
        call = audit_executor.execute(
            MODULES["equivalence_acceptance"],
            "judge",
            {
                "equivalence_status": "UNKNOWN",
                "counter_status": "PASS",
                "receipt_status": "UNKNOWN",
                "semantic_status": "UNKNOWN",
                "human_contract_confirmed": True,
                "cancelled": False,
            },
            call_id="posthoc-audit-only",
            surface_id="equivalence_acceptance",
            scope_id="training:flood-surrogate-full-v1",
            previous_receipt_hash="0" * 64,
        )
        # The expected DENY/err result is evidence that post-hoc auditing cannot
        # create authority. Whatever T returns is deliberately ignored by B.
        judgment = {"observable": dict(call.observable), "runtime_receipt": dict(call.receipt)}
        phases["posthoc_t_audit_ns"] = time.perf_counter_ns() - started
    elif args.arm == "D":
        if args.reference is None:
            raise ValueError("arm D requires a frozen reference")
        started = time.perf_counter_ns()
        verification = independent_verifier.verify_bundle(
            grant_file=output / "authority-grant.json",
            authority_receipt_file=authority_receipts,
            primitive_manifest_file=CAMPAIGN / "primitive-manifest.json",
            work_receipt_file=output / "worker/work-receipts.jsonl",
            result_file=result_file,
            summary_file=output / "worker/worker-summary.json",
            dataset_file=FULL / "artifact/FloodSurrogate.dataset.bin",
            initialization_file=FULL / "artifact/FloodSurrogate.initializations.bin",
        )
        equivalence = compare_result_files(result_file, args.reference, tolerance=1e-9)
        phases["independent_audit_ns"] = time.perf_counter_ns() - started
        started = time.perf_counter_ns()
        judgment_call = authority.judge(
            {
                "equivalence_status": equivalence["status"],
                "counter_status": "PASS",
                "receipt_status": verification["status"],
                "semantic_status": equivalence["status"],
                "human_contract_confirmed": True,
                "cancelled": False,
            },
            previous_receipt_hash=grant["receipt_chain"][-1],
            call_id="measured-final-judgment",
        )
        judgment = {
            "observable": dict(judgment_call.observable),
            "runtime_receipt": dict(judgment_call.receipt),
        }
        phases["t_judgment_ns"] = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    publication_authority = {
        "A": "FOREIGN_BASELINE",
        "B": "FOREIGN_POSTHOC_T_RESULT_IGNORED",
        "C": "T_ARCHITECTURE_FOREIGN_ACCEPTANCE",
        "D": "T_JUDGE_CONSUMED",
    }[args.arm]
    accepted = args.arm != "D" or (
        equivalence is not None
        and equivalence["status"] == "PASS"
        and judgment is not None
        and judgment["observable"]["result"]["value"].get("decision") == "PUBLISH"
    )
    publication = {
        "arm": args.arm,
        "accepted": accepted,
        "publication_authority": publication_authority,
        "t_judge_required": args.arm == "D",
        "result_sha256": sha256_file(result_file),
    }
    write_json(output / "publication.json", publication)
    phases["publication_ns"] = time.perf_counter_ns() - started
    if judgment is not None:
        write_json(output / "judgment.json", judgment)
    if verification is not None:
        write_json(output / "independent-verification.json", verification)
    if equivalence is not None:
        write_json(output / "equivalence.json", equivalence)
    total_ns = time.perf_counter_ns() - process_start
    summary = {
        "schema": "casulo.interlocution-arm-result/1.0",
        "arm": args.arm,
        "count": args.count,
        "start": args.start,
        "phases_ns": phases,
        "inner_total_ns": total_ns,
        "work_summary": work_summary,
        "result_file": str(result_file),
        "result_sha256": sha256_file(result_file),
        "publication": publication,
        "energy": {
            "package_joules": None,
            "total_system_joules": None,
            "reason": "NO_ENERGY_INSTRUMENT_USED_IN_TI9_TI10",
        },
    }
    summary["summary_sha256"] = canonical_sha256(summary)
    write_json(output / "arm-result.json", summary)
    print(json.dumps({"status": "PASS", "arm": args.arm, "total_ns": total_ns}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
