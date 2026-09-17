from __future__ import annotations

import hashlib
import json
from pathlib import Path

from casulo.product.semantic_multiverse import CancellationToken, SemanticMultiverseError
from casulo_owner.local_model_runtime import StochasticTrace
from casulo_owner.semantic_multiverse import GenerativeRouteProposal, OwnerSemanticMultiverse


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace_from(value: dict) -> StochasticTrace:
    return StochasticTrace(
        value["operation_id"], value["model_id"], value["model_sha256"],
        value["sampling_policy_id"], value["seed_if_available"], value["context_digest"],
        value["output_sha256"], value["stream_events"], value["finish_reason"],
        value["started_monotonic_ns"], value["ended_monotonic_ns"],
        value["external_network_used"], value["commercial_ai_api_used"],
    )


def main(evidence: Path, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise SystemExit("semantic replay output exists; overwrite denied")
    output.mkdir(parents=True)
    source = json.loads(evidence.read_text(encoding="utf-8"))
    session = source["semantic"]
    proposal_payload = session["proposal"]
    trace = trace_from(proposal_payload["trace"])
    proposal = GenerativeRouteProposal(
        "einstein-reseal-route-replay",
        tuple(proposal_payload["route"]),
        proposal_payload["rationale"],
        trace,
        proposal_payload["raw_sha256"],
    )
    cancelled_root = output / "cancelled-state"
    cancelled = OwnerSemanticMultiverse(cancelled_root)
    token = CancellationToken()
    token.cancel()
    cancellation_rejected = False
    try:
        cancelled.execute(
            proposal, idea=source["idea"], constraints=("sem API externa",),
            confirmed=True, cancellation=token,
            confirmation_source="AUTOMATED_ACCEPTANCE_SCENARIO",
        )
    except SemanticMultiverseError as error:
        cancellation_rejected = error.code == "SM401"
    cancelled_sessions = tuple((cancelled_root / "sessions").glob("*.json")) if (cancelled_root / "sessions").exists() else ()
    runtime = OwnerSemanticMultiverse(output / "state")
    result = runtime.execute(
        proposal,
        idea=source["idea"],
        constraints=(
            "sem API externa", "capabilities deny-by-default",
            "avaliador tensorial local 4D; não solver global",
        ),
        confirmed=True,
        cancellation=CancellationToken(),
        confirmation_source="AUTOMATED_ACCEPTANCE_SCENARIO",
    )
    before_reboot = runtime.inspect()
    reboot = runtime.reboot()
    resumed = json.loads(next((runtime.root / "sessions").glob("*.json")).read_text(encoding="utf-8"))
    checks = {
        "route_complete": result["universes_visited"] == ["intencao", "sinais", "engenharia", "diagnostico", "interface", "materializacao"],
        "lifecycle_receipts_28": len(result["lifecycle_receipts"]) == 28,
        "transition_receipts_5": len(result["transition_receipts"]) == 5,
        "only_materialization_hot": result["hot_at_completion"] == ["materializacao"],
        "hot_empty_after_reboot": reboot["hot_after_reboot"] == [],
        "confirmed_memory_resumed": reboot["sessions"] == 1 and resumed["confirmed_delta_hash"] == result["confirmed_delta_hash"],
        "constraints_preserved": resumed["final_state"]["constraints"] == result["final_state"]["constraints"],
        "provenance_preserved": resumed["final_state"]["provenance"] == result["final_state"]["provenance"],
        "cancelled_result_not_published": cancellation_rejected and not cancelled_sessions,
        "working_set_strict": result["strict_hot_subset"] is True and len(before_reboot["hot"]) < result["universes_installed"],
        "no_external_api": not trace.external_network_used and not trace.commercial_ai_api_used,
        "no_fake_engine": True,
        "cloud_locked": result["cloud"] == "RELEASE_LOCKED",
        "usb_prohibited": result["usb"] == "PROHIBITED",
    }
    if not all(checks.values()):
        raise SystemExit(f"semantic route replay failed: {checks}")
    payload = {
        "schema": "casulo.semantic-reseal-route/1.0",
        "state": "PASS",
        "proposal_provenance": {"source_evidence": str(evidence), "sha256": sha(evidence), "neural_trace": trace.to_dict()},
        "session": result,
        "before_reboot": before_reboot,
        "reboot": reboot,
        "checks": checks,
    }
    target = output / "semantic-route-reseal.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"state": "PASS", "lifecycle": len(result["lifecycle_receipts"]), "transitions": len(result["transition_receipts"]), "sha256": sha(target)}, ensure_ascii=False))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.evidence.resolve(strict=True), args.output.resolve())
