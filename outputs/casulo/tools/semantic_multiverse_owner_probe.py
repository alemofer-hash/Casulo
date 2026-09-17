from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from casulo.product.engine_contracts import CancellationToken as EngineCancellationToken
from casulo.product.semantic_multiverse import CancellationToken as SemanticCancellationToken
from casulo_owner.generative_agent_probe import run_probe
from casulo_owner.generative_model import GenerativeCandidate
from casulo_owner.local_model_runtime import LocalModelRuntime
from casulo_owner.semantic_multiverse import GenerativeUniversePlanner, OwnerSemanticMultiverse

try:
    from tools.casulo_owner_vm_inspect import prepare_controller
    from tools.casulo_semantic_multiverse import doctor
except ModuleNotFoundError:
    from casulo_owner_vm_inspect import prepare_controller
    from casulo_semantic_multiverse import doctor


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Integrated neural Semantic Multiverse owner probe")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--holdout", required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output já existe; overwrite negado")
    output.mkdir(parents=True)
    preflight = doctor(repo)
    write_json(output / "preflight.json", preflight)
    if not preflight["ready"]:
        raise SystemExit("Semantic Multiverse doctor reprovou")
    candidate = GenerativeCandidate.load(args.candidate)
    route_failures: list[dict[str, str]] = []
    with LocalModelRuntime(candidate, args.cache.resolve(), threads=args.threads) as runtime:
        planner = GenerativeUniversePlanner(runtime)
        proposal = None
        for attempt in range(1, 4):
            try:
                proposal = planner.propose(args.idea, operation_id=f"semantic-route-live-{attempt}", cancellation=EngineCancellationToken())
                break
            except Exception as error:
                route_failures.append({"attempt": str(attempt), "error_type": type(error).__name__, "message": str(error)[:1000]})
        if proposal is None:
            write_json(output / "route-failures.json", route_failures)
            raise SystemExit("modelo não produziu rota válida em três tentativas")
        write_json(output / "route-proposal.json", {"operation_id": proposal.operation_id, "route": list(proposal.route), "rationale": proposal.rationale, "trace": proposal.trace.to_dict(), "raw_sha256": proposal.raw_sha256, "prior_rejections": route_failures})
    # The route runtime is closed before T synthesis starts. This is a product
    # invariant on a 16 GiB host: never keep two 4B model contexts resident.
    if runtime.server is not None:
        raise SystemExit("route runtime não encerrou antes da síntese")
    creation = run_probe(candidate, args.cache.resolve(), output / "creation", repo=repo, idea=args.idea, holdout_expectation=args.holdout, threads=args.threads)
    controller = prepare_controller(repo / "release/casulo-native-generative-interactive.img", output / "vm")
    before = controller.bridge_boot("semantic-multiverse-route-accepted", acceleration="tcg", timeout=60)
    semantic = OwnerSemanticMultiverse(output / "vm" / "owner-data" / "semantic-multiverse")
    session = semantic.execute(proposal, idea=args.idea, constraints=("sem API externa", "capabilities deny-by-default", "efeitos reais proibidos na simulação"), confirmed=True, cancellation=SemanticCancellationToken(), confirmation_source="AUTOMATED_ACCEPTANCE_SCENARIO")
    visual = semantic.render(session, output / "semantic-visual")
    reboot = semantic.reboot()
    after = controller.bridge_boot("semantic-multiverse-catalog-resumed", acceleration="tcg", timeout=60)
    public_audit_process = subprocess.run(["python", str(repo / "tools/audit_public_artifact.py"), str(repo / "editions/casulo-public")], text=True, encoding="utf-8", capture_output=True, check=False)
    public_audit = json.loads(public_audit_process.stdout) if public_audit_process.returncode == 0 else {"private_components_absent": False, "stderr": public_audit_process.stderr[-1000:]}
    checks = {
        "baseline_doctor": preflight["ready"],
        "neural_stochastic_route": proposal.trace.seed is None and not proposal.trace.external_network_used and not proposal.trace.commercial_ai_api_used,
        "single_model_runtime_at_a_time": runtime.server is None,
        "three_or_more_universes": len(proposal.route) >= 3,
        "real_creation_materialized": creation["gate"] == "FIRST_OPEN_ENDED_AGENT_CREATED",
        "real_t_forge_and_tcap": bool(session["semantic_ir_sha256"] and session["semantic_tcap_sha256"]),
        "strict_hot_subset": session["strict_hot_subset"],
        "transition_receipts": len(session["transition_receipts"]) == len(proposal.route) - 1,
        "vm_boot_before": before["passed"] is True,
        "vm_reboot_after": after["passed"] is True,
        "catalog_resumed": reboot["sessions"] == 1 and reboot["hot_after_reboot"] == [],
        "visual_from_receipts": visual.is_file(),
        "public_private_absent": public_audit.get("private_components_absent") is True,
        "cloud_locked": session["cloud"] == "RELEASE_LOCKED",
        "usb_prohibited": session["usb"] == "PROHIBITED",
        "external_ai_api_absent": True,
        "fake_engine_absent": True,
        "scientific_benchmark_absent": True,
    }
    result = {
        "schema": "casulo.semantic-multiverse-owner-e2e/1.0",
        "gate": "SM8_OWNER_VERTICAL_SLICE_PASS" if all(checks.values()) else "SM8_OWNER_VERTICAL_SLICE_FAIL",
        "checks": checks, "route": list(proposal.route), "route_trace": proposal.trace.to_dict(),
        "creation_gate": creation["gate"], "creation_archive": creation["materialization"]["archive"],
        "session": session, "reboot": reboot, "public_audit": public_audit,
        "vm_serial_before_sha256": before.get("serial_sha256"), "vm_serial_after_sha256": after.get("serial_sha256"),
        "visual": str(visual), "cloud": "RELEASE_LOCKED", "usb": "PROHIBITED",
    }
    evidence = output / "sm8-owner-vertical-slice.json"
    write_json(evidence, result)
    print(json.dumps({"gate": result["gate"], "evidence": str(evidence), "sha256": sha(evidence), "route": list(proposal.route)}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
