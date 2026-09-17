from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from casulo.t.v2_tcap import TcapV2Builder
from interlocution.authority import InterlocutionAuthorityDenied, TrainingAuthority
from interlocution.contracts import canonical_sha256
from interlocution.policy import MODULES, POLICY_SURFACES
from interlocution.worker import WorkerDenied, run_governed_worker


CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
RUNTIME = ROOT / "t-runtime/target/release/casulo-t-runtime.exe"
ORIGINAL_TCAP_HASH = "4c3a538736c68f0343e2050aa939ea3a55b3fd930ce4ffbe2c2341a1d0fd45d0"


MUTATIONS = (
    ("dataset_identity_integrity", "dataset_identity_integrity.t", "f393212f183a28a663adeb11995c5ab3ac769df7f06ded2dcfbc5e91cd31f802", "c" * 64, "T_DENIED"),
    ("initialization_bundle", "initialization_bundle.t", "1b77bc6f3ee729282756b8244c4b198395e2fe6bcda6a8d4dd255aa370af13e3", "d" * 64, "T_DENIED"),
    ("numerical_precision", "numerical_precision.t", "{'dtype': 'float64'}", "{'dtype': 'float32'}", "PRIMITIVE_DENIED"),
    ("loss_function", "loss_function.t", "{'loss': 'mse'}", "{'loss': 'mae'}", "PRIMITIVE_DENIED"),
    ("update_rule", "update_rule.t", "'learning_rate': '0.018'", "'learning_rate': '0.009'", "PRIMITIVE_DENIED"),
    ("optimizer_state", "optimizer_state.t", "'optimizer_state_policy': 'reset_each_case'", "'optimizer_state_policy': 'preserve_across_cases'", "PRIMITIVE_DENIED"),
    ("working_set", "working_set.t", "'working_set_count': '1024'", "'working_set_count': '512'", "PRIMITIVE_DENIED"),
    ("stopping", "stopping.t", "'epochs': '400'", "'epochs': '399'", "PRIMITIVE_DENIED"),
    ("equivalence_acceptance", "equivalence_acceptance.t", "return ok {'decision': 'PUBLISH'}", "return error 'mutated_judge_denied'", "T_JUDGE_DENIED"),
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"append-only mutation artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def grant_document(authority: TrainingAuthority, root: Path) -> tuple[dict, Any]:
    grant = authority.authorize(
        dataset_sha256="f393212f183a28a663adeb11995c5ab3ac769df7f06ded2dcfbc5e91cd31f802",
        records=1024,
        input_features=8,
        initialization_sha256="1b77bc6f3ee729282756b8244c4b198395e2fe6bcda6a8d4dd255aa370af13e3",
        cases_unique=True,
        nonces_unique=True,
        capabilities=capabilities(),
    )
    receipt_file = root / "policy-receipts.jsonl"
    receipt_file.write_text(
        "".join(json.dumps(call.receipt, sort_keys=True, separators=(",", ":")) + "\n" for call in grant.calls),
        encoding="utf-8",
        newline="\n",
    )
    seed = {
        "schema": "casulo.interlocution-authority-grant/1.0",
        "campaign_id": "causal-mutation",
        "plan_sha256": "18bfc5d0d80fe52c347744ba7ca330653e7ba064ecba2f406efe63f05e8ded4e",
        "tcap_hash": grant.calls[0].receipt["tcap_hash"],
        "config_from_t": dict(grant.config),
        "receipt_chain": list(grant.receipt_chain),
        "surfaces": [call.receipt["surface_id"] for call in grant.calls],
        "foreign_affirmative_fallback": False,
        "generated_at_utc": "FROZEN_CAUSAL_MUTATION",
    }
    document = {**seed, "grant_sha256": canonical_sha256(seed)}
    write_json(root / "authority-grant.json", document)
    return document, grant


def main() -> int:
    destination = CAMPAIGN / "causal_mutations-attempt2"
    if destination.exists():
        raise FileExistsError(f"append-only mutation campaign already exists: {destination}")
    destination.mkdir(parents=True)
    original_sources = CAMPAIGN / "t_sources"
    results = []
    for index, (surface, filename, old, new, expected) in enumerate(MUTATIONS, 1):
        root = destination / f"{index:02d}-{surface}"
        sources = root / "sources"
        sources.mkdir(parents=True)
        for source in sorted(original_sources.glob("*.t")):
            text = source.read_text(encoding="utf-8")
            if source.name == filename:
                occurrences = text.count(old)
                expected_occurrences = 2 if surface in {
                    "dataset_identity_integrity", "initialization_bundle"
                } else 1
                if occurrences != expected_occurrences:
                    raise RuntimeError(
                        f"mutation anchor cardinality mismatch: {surface}: "
                        f"expected {expected_occurrences}, observed {occurrences}"
                    )
                text = text.replace(old, new)
            (sources / source.name).write_text(text, encoding="utf-8", newline="\n")
        source_paths = tuple(sorted(sources.glob("*.t")))
        build = TcapV2Builder().build(
            source_paths,
            root / "policy.tcap",
            entry_module=MODULES["dataset_identity_integrity"],
            entry_function="decide",
            tests={"properties":["causal_mutation",surface]},
            foreign_boundaries=({"name":"interlocution_training_primitive","kind":"foreign_primitive","decision_authority":False,"invocation_authority":"T"},),
        )
        if build.tcap_hash == ORIGINAL_TCAP_HASH:
            raise RuntimeError(f"mutation did not change TCAP: {surface}")
        authority = TrainingAuthority(RUNTIME, build.directory, root / "policy-inputs")
        observed = "NO_EFFECT"
        message = ""
        t_receipts = 0
        config_from_t: dict[str, Any] | None = None
        try:
            document, grant = grant_document(authority, root)
            t_receipts = len(grant.calls)
            config_from_t = dict(grant.config)
            if expected == "T_JUDGE_DENIED":
                authority.judge(
                    {
                        "equivalence_status":"PASS",
                        "counter_status":"PASS",
                        "receipt_status":"PASS",
                        "semantic_status":"PASS",
                        "human_contract_confirmed":True,
                    },
                    previous_receipt_hash=grant.receipt_chain[-1],
                    call_id="mutated-final-judgment",
                )
                observed = "UNEXPECTED_ACCEPT"
            else:
                run_governed_worker(
                    grant_file=root / "authority-grant.json",
                    authority_receipt_file=root / "policy-receipts.jsonl",
                    primitive_manifest_file=CAMPAIGN / "primitive-manifest.json",
                    executable=FULL / "worker/tcap_full_worker.exe",
                    dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
                    initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
                    output_directory=root / "work-attempt",
                )
                observed = "UNEXPECTED_WORK_EXECUTED"
        except InterlocutionAuthorityDenied as error:
            observed = "T_JUDGE_DENIED" if expected == "T_JUDGE_DENIED" and "mutated_judge_denied" in str(error) else "T_DENIED"
            message = str(error)
        except WorkerDenied as error:
            observed = "PRIMITIVE_DENIED"
            message = str(error)
        passed = observed == expected
        result = {
            "surface": surface,
            "mutation": {"file":filename,"old":old,"new":new},
            "source_occurrences_changed": expected_occurrences,
            "original_tcap_hash": ORIGINAL_TCAP_HASH,
            "mutated_tcap_hash": build.tcap_hash,
            "mutated_source_sha256": sha256_file(sources / filename),
            "expected_effect": expected,
            "observed_effect": observed,
            "message": message,
            "t_receipts_before_effect": t_receipts,
            "config_from_t": config_from_t,
            "python_or_worker_policy_changed": False,
            "pass": passed,
        }
        write_json(root / "result.json", result)
        results.append(result)
    summary_seed = {
        "schema": "casulo.interlocution-causal-mutations/1.0",
        "protocol_frozen_before_results": True,
        "mutations": results,
        "passed": sum(1 for item in results if item["pass"]),
        "required": 9,
        "gate": "PASS" if all(item["pass"] for item in results) else "FAIL",
    }
    summary = {**summary_seed, "summary_sha256": canonical_sha256(summary_seed)}
    write_json(destination / "summary.json", summary)
    print(json.dumps({"gate":summary["gate"],"passed":summary["passed"],"summary_sha256":summary["summary_sha256"]}, sort_keys=True))
    return 0 if summary["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
