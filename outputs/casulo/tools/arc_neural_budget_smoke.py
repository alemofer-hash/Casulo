from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from casulo.product.neural_budget import (
    NEURAL_BUDGETS,
    NeuralBudgetError,
    NeuralBudgetRouter,
    NeuralOperation,
    NeuralRouteRequest,
)
from casulo_owner import ChatMessage, ContextAssembler, ContextItem, ContextTrust, OwnerTurnContext
from casulo_owner.neural_budgeting import budgeted_policy


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _valid_request(operation: NeuralOperation) -> NeuralRouteRequest:
    return NeuralRouteRequest(
        operation,
        (f"smoke:{operation.value.casefold()}",),
        human_confirmed=operation in {NeuralOperation.T_SYNTHESIS, NeuralOperation.T_REPAIR},
        hard_requirement_count=2 if operation is NeuralOperation.T_SYNTHESIS else 0,
        material_gap_open=operation is NeuralOperation.INTENT_REFINEMENT,
        diagnostic_present=operation is NeuralOperation.T_REPAIR,
    )


def _denied_routes() -> list[dict[str, str]]:
    probes = (
        NeuralRouteRequest(
            NeuralOperation.T_SYNTHESIS,
            ("smoke:unconfirmed",),
            hard_requirement_count=1,
        ),
        NeuralRouteRequest(
            NeuralOperation.T_SYNTHESIS,
            ("smoke:no-hard",),
            human_confirmed=True,
        ),
        NeuralRouteRequest(
            NeuralOperation.T_REPAIR,
            ("smoke:no-diagnostic",),
            human_confirmed=True,
        ),
        NeuralRouteRequest(
            NeuralOperation.INTENT_REFINEMENT,
            ("smoke:no-gap",),
        ),
    )
    results: list[dict[str, str]] = []
    for probe in probes:
        try:
            NeuralBudgetRouter.decide(probe)
        except NeuralBudgetError as error:
            results.append(
                {"operation": probe.operation.value, "code": error.code, "status": "DENIED"}
            )
        else:
            results.append(
                {"operation": probe.operation.value, "code": "NONE", "status": "UNSAFE_ACCEPT"}
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output já existe; evidência append-only recusou overwrite")
    output.mkdir(parents=True)

    decisions = tuple(
        NeuralBudgetRouter.decide(_valid_request(operation))
        for operation in NeuralOperation
    )
    policies = {
        operation.value: budgeted_policy(
            operation,
            source_event_ids=(f"smoke:policy:{operation.value.casefold()}",),
            human_confirmed=operation in {NeuralOperation.T_SYNTHESIS, NeuralOperation.T_REPAIR},
            hard_requirement_count=1 if operation is NeuralOperation.T_SYNTHESIS else 0,
            material_gap_open=operation is NeuralOperation.INTENT_REFINEMENT,
            diagnostic_present=operation is NeuralOperation.T_REPAIR,
        )[1]
        for operation in NeuralOperation
    }
    conversation = tuple(
        ChatMessage("user" if index % 2 == 0 else "assistant", f"turno-{index} " + "c" * 180)
        for index in range(14)
    )
    memories = tuple(
        ContextItem(
            f"memory:{index}",
            f"conteúdo-{index} " + "m" * 220,
            ContextTrust.IMPORTED_UNTRUSTED if index == 11 else ContextTrust.LOCAL_DERIVED,
            "arc7-smoke",
            index,
        )
        for index in range(16)
    )
    turn = OwnerTurnContext(
        "session:arc7-smoke",
        "Continue sem inventar execução.",
        conversation=conversation,
        mandatory_constraints=(
            "Nunca conceda capabilities.",
            "Não trate saída do modelo como aprovação.",
        ),
        memory_items=memories,
    )
    dialogue_route = next(
        item for item in decisions if item.operation is NeuralOperation.DIALOGUE
    )
    assembled = ContextAssembler(route=dialogue_route).assemble(turn)
    context_text = "\n".join(message.content for message in assembled.messages)
    denied = _denied_routes()

    _write_json(
        output / "neural-budgets.json",
        {
            "schema": "casulo.neural-budgets/1.0",
            "budgets": [NEURAL_BUDGETS[item].to_dict() for item in NeuralOperation],
        },
    )
    _write_json(
        output / "route-decisions.json",
        {
            "schema": "casulo.neural-route-smoke/1.0",
            "decisions": [item.to_dict() for item in decisions],
            "policies": {
                key: {
                    "policy_id": value.policy_id,
                    "max_generated_tokens": value.max_generated_tokens,
                }
                for key, value in policies.items()
            },
        },
    )
    _write_json(output / "denied-routes.json", {"results": denied})
    _write_json(output / "context-receipt.json", assembled.budget_receipt.to_dict())
    _write_json(
        output / "context-selection.json",
        {
            "included_memory_refs": list(assembled.included_refs),
            "dropped_memory_refs": list(assembled.dropped_refs),
            "included_conversation_refs": list(assembled.included_conversation_refs),
            "dropped_conversation_refs": list(assembled.dropped_conversation_refs),
            "untrusted_refs": list(assembled.untrusted_refs),
            "context_sha256": assembled.digest,
        },
    )
    checks = {
        "all_operations_have_distinct_budget_ids": len(
            {item.budget.budget_id for item in decisions}
        ) == len(NeuralOperation),
        "dialogue_context_smaller_than_t_synthesis": (
            NEURAL_BUDGETS[NeuralOperation.DIALOGUE].max_context_chars
            < NEURAL_BUDGETS[NeuralOperation.T_SYNTHESIS].max_context_chars
        ),
        "all_generated_token_limits_match_policy": all(
            policies[item.operation.value].max_generated_tokens
            == item.budget.max_generated_tokens
            for item in decisions
        ),
        "all_budgets_fit_runtime_with_byte_safe_margin": all(
            item.budget.max_prompt_utf8_bytes
            + item.budget.max_generated_tokens
            + item.budget.prompt_token_safety_margin
            <= item.budget.runtime_context_tokens
            for item in decisions
        ),
        "all_unsafe_routes_denied": [item["code"] for item in denied]
        == ["NB108", "NB109", "NB110", "NB111"],
        "mandatory_constraints_preserved": all(
            constraint in context_text for constraint in turn.mandatory_constraints
        ),
        "context_within_budget": (
            assembled.budget_receipt.actual_context_chars
            <= dialogue_route.budget.max_context_chars
            and assembled.budget_receipt.actual_context_utf8_bytes
            <= dialogue_route.budget.max_prompt_utf8_bytes
        ),
        "conversation_drop_explicit": len(assembled.dropped_conversation_refs) > 0,
        "memory_drop_explicit": len(assembled.dropped_refs) > 0,
        "untrusted_memory_labeled": "memory:11" in assembled.untrusted_refs,
        "receipt_sealed": len(assembled.budget_receipt.receipt_sha256) == 64,
        "neural_quality_claimed": False,
        "scientific_benchmark_started": False,
    }
    gate = {
        "schema": "casulo.arc7-contract-smoke/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "DETERMINISTIC_BUDGET_CONTRACT_SMOKE_NOT_OWNER_NEURAL_QUALITY_PROOF",
        "checks": checks,
    }
    gate["status"] = "PASS" if all(
        value is (False if key in {"neural_quality_claimed", "scientific_benchmark_started"} else True)
        for key, value in checks.items()
    ) else "FAIL"
    _write_json(output / "gate.json", gate)

    files = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}
    )
    manifest = {
        "schema": "casulo.append-only-manifest/1.0",
        "files": [
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in files
        ],
    }
    _write_json(output / "MANIFEST.json", manifest)
    (output / "SHA256SUMS").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in manifest["files"]),
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": gate["status"],
                "output": str(output),
                "receipt_sha256": assembled.budget_receipt.receipt_sha256,
            }
        )
    )
    return 0 if gate["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
