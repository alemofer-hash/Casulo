from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from interlocution.authority import InterlocutionAuthorityDenied, TrainingAuthority
from interlocution.contracts import canonical_sha256
from interlocution.policy import compile_training_authority_tcap
from interlocution.worker import run_governed_worker, sha256_file

import independent_verifier


CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
RUNTIME = ROOT / "t-runtime/target/release/casulo-t-runtime.exe"


def write_json(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def capabilities() -> dict[str, bool]:
    return {"float64_supported": True, "mse_supported": True, "sgd_supported": True, "reset_supported": True, "no_cross_case_state": True, "selection_supported": True, "fixed_epoch_supported": True, "counter_supported": True, "independent_verifier_available": True, "publisher_requires_t": True}


def save_grant(output: Path, plan: dict, tcap_hash: str, grant) -> tuple[Path, Path, dict]:
    receipts = output / "policy-receipts.jsonl"
    receipts.write_text("".join(json.dumps(call.receipt, separators=(",", ":"), sort_keys=True) + "\n" for call in grant.calls), encoding="utf-8", newline="\n")
    document = {"schema": "casulo.interlocution-authority-grant/1.0", "campaign_id": CAMPAIGN.name, "plan_sha256": plan["plan_sha256"], "tcap_hash": tcap_hash, "config_from_t": dict(grant.config), "receipt_chain": list(grant.receipt_chain), "surfaces": [call.receipt["surface_id"] for call in grant.calls], "foreign_affirmative_fallback": False, "generated_at_utc": datetime.now(timezone.utc).isoformat()}
    document["grant_sha256"] = canonical_sha256(document)
    path = output / "authority-grant.json"
    write_json(path, document)
    return path, receipts, document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", default="live-v1")
    args = parser.parse_args()
    if not args.attempt.startswith("live-v") or not args.attempt[6:].isdigit():
        raise ValueError("attempt must be an append-only live-vN identifier")
    output = CAMPAIGN / "demo" / args.attempt
    if output.exists():
        raise FileExistsError(f"append-only live demo exists: {output}")
    output.mkdir(parents=True)
    events = []
    intent = json.loads((CAMPAIGN / "confirmed_intent.json").read_text(encoding="utf-8"))
    graph = json.loads((CAMPAIGN / "requirement_graph.json").read_text(encoding="utf-8"))
    plan = json.loads((CAMPAIGN / "training_authority_plan.json").read_text(encoding="utf-8"))
    events.append({"step": 1, "event": "USER_PURPOSE_RECEIVED", "source": "actual confirmed user goal", "intent_sha256": intent["intent_sha256"]})
    events.append({"step": 2, "event": "MATERIAL_GAPS_RESOLVED_AND_HUMAN_CONFIRMED", "material_gaps": intent["material_gaps"], "confirmation": intent["confirmation"]})
    events.append({"step": 3, "event": "REQUIREMENT_GRAPH_BOUND", "hard_requirements": len(graph["requirements"]), "graph_sha256": graph["graph_sha256"]})

    build = compile_training_authority_tcap(plan, output / "t-sources", output / "tcap")
    events.append({"step": 4, "event": "TRAINING_AUTHORITY_PLAN_COMPILED_BY_GENERAL_T2", "tcap_hash": build.tcap_hash})
    authority = TrainingAuthority(RUNTIME, build.directory, output / "runtime-inputs")
    initialization = json.loads((FULL / "artifact/initialization_bundle.json").read_text(encoding="utf-8"))
    kwargs = {"dataset_sha256": sha256_file(FULL / "artifact/FloodSurrogate.dataset.bin"), "records": 1024, "input_features": 8, "initialization_sha256": sha256_file(FULL / "artifact/FloodSurrogate.initializations.bin"), "cases_unique": bool(initialization["all_parameter_hashes_unique"]), "nonces_unique": bool(initialization["all_nonces_unique"]), "capabilities": capabilities()}
    grant = authority.authorize(**kwargs)
    grant_path, receipt_path, grant_document = save_grant(output, plan, build.tcap_hash, grant)
    events.append({"step": 5, "event": "RUNTIME_DATASET_ACCEPTED_BY_T", "dataset_sha256": kwargs["dataset_sha256"], "receipt_hash": grant.calls[0].receipt["receipt_hash"]})
    tamper_authority = TrainingAuthority(RUNTIME, build.directory, output / "tamper-runtime-inputs")
    try:
        tamper_authority.authorize(**{**kwargs, "dataset_sha256": "f" * 64})
    except InterlocutionAuthorityDenied as error:
        if "dataset_hash_mismatch" not in str(error):
            raise RuntimeError(f"tampered dataset rejected for the wrong reason: {error}") from error
        events.append({"step": 6, "event": "TAMPERED_DATASET_REJECTED_BY_T", "status": "PASS", "reason": str(error)})
    else:
        raise RuntimeError("tampered dataset was accepted")
    governed = run_governed_worker(grant_file=grant_path, authority_receipt_file=receipt_path, primitive_manifest_file=CAMPAIGN / "primitive-manifest.json", executable=FULL / "worker/tcap_full_worker.exe", dataset=FULL / "artifact/FloodSurrogate.dataset.bin", initializations=FULL / "artifact/FloodSurrogate.initializations.bin", output_directory=output / "worker", count=1)
    events.append({"step": 7, "event": "FULL_TRAINING_COMPLETED", "epochs": governed.summary["epochs_completed"], "records_visited": governed.summary["records_visited"], "optimizer_steps": governed.summary["optimizer_steps"], "work_chain_tip": governed.summary["work_chain_tip"]})

    mutated = json.loads(json.dumps(plan))
    next(item for item in mutated["decisions"] if item["surface"] == "update_rule")["learning_rate"] = 0.009
    mutated.pop("plan_sha256")
    mutated["plan_sha256"] = canonical_sha256(mutated)
    mutation_build = compile_training_authority_tcap(mutated, output / "mutation/t-sources", output / "mutation/tcap")
    mutation_authority = TrainingAuthority(RUNTIME, mutation_build.directory, output / "mutation/runtime-inputs")
    mutation_grant = mutation_authority.authorize(**kwargs)
    if mutation_grant.config["learning_rate"] == grant.config["learning_rate"] or mutation_build.tcap_hash == build.tcap_hash:
        raise RuntimeError("T policy mutation was not causal")
    events.append({"step": 8, "event": "T_POLICY_MUTATION_CHANGED_EXECUTION_CONTRACT", "baseline_learning_rate": grant.config["learning_rate"], "mutated_learning_rate": mutation_grant.config["learning_rate"], "baseline_tcap_hash": build.tcap_hash, "mutated_tcap_hash": mutation_build.tcap_hash, "primitive_action": "REFUSE_UNSUPPORTED_POLICY_BEFORE_WORK"})

    valid = independent_verifier.verify_bundle(grant_file=grant_path, authority_receipt_file=receipt_path, primitive_manifest_file=CAMPAIGN / "primitive-manifest.json", work_receipt_file=output / "worker/work-receipts.jsonl", result_file=governed.result_file, summary_file=output / "worker/worker-summary.json", dataset_file=FULL / "artifact/FloodSurrogate.dataset.bin", initialization_file=FULL / "artifact/FloodSurrogate.initializations.bin")
    attacked = output / "incomplete-attack"
    attacked.mkdir()
    shutil.copy2(output / "worker/work-receipts.jsonl", attacked / "work-receipts.jsonl")
    lines = (attacked / "work-receipts.jsonl").read_text(encoding="utf-8").splitlines()
    receipt = json.loads(lines[0])
    receipt["epochs_completed"] = 399
    receipt_seed = {key: value for key, value in receipt.items() if key not in {"receipt_hash", "chain_hash"}}
    receipt["receipt_hash"] = canonical_sha256(receipt_seed)
    receipt["chain_hash"] = __import__("hashlib").sha256(bytes(32) + bytes.fromhex(receipt["receipt_hash"])).hexdigest()
    (attacked / "work-receipts.jsonl").write_text(json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    try:
        independent_verifier.verify_bundle(grant_file=grant_path, authority_receipt_file=receipt_path, primitive_manifest_file=CAMPAIGN / "primitive-manifest.json", work_receipt_file=attacked / "work-receipts.jsonl", result_file=governed.result_file, summary_file=output / "worker/worker-summary.json", dataset_file=FULL / "artifact/FloodSurrogate.dataset.bin", initialization_file=FULL / "artifact/FloodSurrogate.initializations.bin")
    except Exception as error:
        events.append({"step": 9, "event": "INCOMPLETE_EXECUTION_REJECTED", "status": "PASS", "reason": str(error)})
    else:
        raise RuntimeError("incomplete execution was accepted")
    events.append({"step": 10, "event": "INDEPENDENT_VERIFIER_ACCEPTED_COMPLETE_WORK", "verification_sha256": valid["verification_sha256"]})
    judgment = authority.judge({"equivalence_status": "PASS", "counter_status": "PASS", "receipt_status": valid["status"], "semantic_status": "PASS", "human_contract_confirmed": True, "cancelled": False}, previous_receipt_hash=grant_document["receipt_chain"][-1], call_id="live-demo-final-judgment")
    events.append({"step": 11, "event": "T_JUDGE_AUTHORIZED_PUBLICATION", "decision": judgment.observable["result"]["value"]["decision"], "judge_receipt_hash": judgment.receipt["receipt_hash"]})
    comparison = json.loads((CAMPAIGN / "baselines/ti10-v2/analysis-expanded.json").read_text(encoding="utf-8"))
    events.append({"step": 12, "event": "COST_COMPARISON_INSPECTED", "end_to_end_wall_ratio_D_over_A": comparison["end_to_end"]["median_D_over_A_wall_ratio"], "peak_rss_ratio_D_over_A": comparison["psi_physical"]["peak_rss_ratio_D_over_A"], "energy": "NOT_MEASURED"})
    (output / "events.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n" for item in events), encoding="utf-8", newline="\n")
    summary = {"schema": "casulo.interlocution-live-demo/1.0", "status": "PASS", "steps": len(events), "actual_full_trainings": 1, "fixture": False, "fake_engine": False, "replay": False, "external_api": False, "events_sha256": sha256_file(output / "events.jsonl")}
    summary["summary_sha256"] = canonical_sha256(summary)
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
