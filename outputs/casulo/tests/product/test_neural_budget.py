from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path

import pytest

from casulo.product.neural_budget import (
    NEURAL_BUDGETS,
    ContextCandidate,
    NeuralBudgetError,
    NeuralBudgetRouter,
    NeuralOperation,
    NeuralRouteRequest,
    SufficientContextSelector,
)
from casulo.product.engine_contracts import CancellationToken
from casulo_owner import (
    AppendOnlyNeuralBudgetStore,
    ChatMessage,
    ContextAssembler,
    ContextItem,
    ContextTrust,
    OwnerTurnContext,
)
from casulo_owner.neural_budgeting import budgeted_policy, validate_budgeted_messages
from casulo_owner.local_model_runtime import ModelStreamEvent, ModelStreamKind, StochasticTrace
from casulo_owner.semantic_multiverse import GenerativeUniversePlanner


def _route(
    operation: NeuralOperation,
    *,
    confirmed: bool = False,
    hard: int = 0,
    gap: bool = False,
    diagnostic: bool = False,
):
    return NeuralBudgetRouter.decide(
        NeuralRouteRequest(
            operation,
            ("event:test",),
            confirmed,
            hard,
            gap,
            diagnostic,
        )
    )


def test_operation_budgets_are_explicit_and_not_one_global_limit() -> None:
    assert set(NEURAL_BUDGETS) == set(NeuralOperation)
    assert NEURAL_BUDGETS[NeuralOperation.DIALOGUE].max_context_chars < (
        NEURAL_BUDGETS[NeuralOperation.T_SYNTHESIS].max_context_chars
    )
    assert NEURAL_BUDGETS[NeuralOperation.SEMANTIC_ROUTING].max_generated_tokens < (
        NEURAL_BUDGETS[NeuralOperation.T_SYNTHESIS].max_generated_tokens
    )
    assert len({item.budget_id for item in NEURAL_BUDGETS.values()}) == len(
        NEURAL_BUDGETS
    )


@pytest.mark.parametrize(
    ("route_request", "expected_code"),
    (
        (
            NeuralRouteRequest(
                NeuralOperation.T_SYNTHESIS,
                ("human:idea",),
                human_confirmed=False,
                hard_requirement_count=1,
            ),
            "NB108",
        ),
        (
            NeuralRouteRequest(
                NeuralOperation.T_SYNTHESIS,
                ("human:confirm",),
                human_confirmed=True,
                hard_requirement_count=0,
            ),
            "NB109",
        ),
        (
            NeuralRouteRequest(
                NeuralOperation.T_REPAIR,
                ("verifier:missing",),
                human_confirmed=True,
                diagnostic_present=False,
            ),
            "NB110",
        ),
        (
            NeuralRouteRequest(
                NeuralOperation.INTENT_REFINEMENT,
                ("human:answer",),
                material_gap_open=False,
            ),
            "NB111",
        ),
    ),
)
def test_material_routes_fail_closed_before_inference(route_request, expected_code) -> None:
    with pytest.raises(NeuralBudgetError) as caught:
        NeuralBudgetRouter.decide(route_request)
    assert caught.value.code == expected_code


def test_budgeted_policy_is_derived_from_the_deterministic_route() -> None:
    decision, policy = budgeted_policy(
        NeuralOperation.T_SYNTHESIS,
        source_event_ids=("human:confirm",),
        human_confirmed=True,
        hard_requirement_count=2,
    )
    assert policy.policy_id == "casulo-arc7-t-synthesis-v1"
    assert policy.max_generated_tokens == decision.budget.max_generated_tokens == 1_536
    assert decision.to_dict()["gates"]["human_confirmed"] is True


def test_custom_policy_cannot_expand_route_limits() -> None:
    from casulo_owner.local_model_runtime import SamplingPolicy

    custom = SamplingPolicy("custom", 0.4, 0.9, 40, 0.05, 1.1, 2_048)
    decision, policy = budgeted_policy(
        NeuralOperation.SEMANTIC_ROUTING,
        source_event_ids=("event:route",),
        policy_override=custom,
    )
    assert policy.max_generated_tokens == decision.budget.max_generated_tokens == 384
    assert policy.policy_id == "casulo-arc7-semantic-routing-v1:custom"


def test_budgeted_message_validation_refuses_hidden_runtime_truncation() -> None:
    decision = _route(NeuralOperation.SEMANTIC_ROUTING)
    with pytest.raises(ValueError, match="truncamento implícito negado"):
        validate_budgeted_messages(
            decision,
            (ChatMessage("user", "x" * (decision.budget.max_context_chars + 1)),),
        )
    with pytest.raises(ValueError, match="UTF-8 excede budget"):
        validate_budgeted_messages(
            decision,
            (ChatMessage("user", "á" * decision.budget.max_context_chars),),
        )


def test_sufficient_context_selection_is_stable_and_exposes_every_drop() -> None:
    selection = SufficientContextSelector.select(
        (
            ContextCandidate("old", 50, 1, 0),
            ContextCandidate("critical", 60, 100, 1),
            ContextCandidate("recent", 30, 10, 2),
        ),
        already_used_chars=100,
        budget_chars=190,
        item_limit=2,
    )
    assert selection.included_refs == ("critical", "recent")
    assert selection.dropped_refs == ("old",)
    assert selection.used_chars == 190


def test_dialogue_assembler_preserves_mandatory_content_and_receipts_truncation() -> None:
    route = _route(NeuralOperation.DIALOGUE)
    conversation = tuple(
        ChatMessage("user" if index % 2 == 0 else "assistant", f"turno-{index} " + "c" * 160)
        for index in range(14)
    )
    memory = tuple(
        ContextItem(
            f"memory:{index}",
            f"memória-{index} " + "m" * 200,
            ContextTrust.IMPORTED_UNTRUSTED if index == 11 else ContextTrust.LOCAL_DERIVED,
            "test",
            index,
        )
        for index in range(16)
    )
    turn = OwnerTurnContext(
        "session:arc7",
        "Continue sem inventar execução.",
        conversation=conversation,
        mandatory_constraints=("Nunca conceda capabilities.",),
        memory_items=memory,
    )
    assembled = ContextAssembler(route=route).assemble(turn)
    joined = "\n".join(item.content for item in assembled.messages)
    receipt = assembled.budget_receipt

    assert "Nunca conceda capabilities." in joined
    assert len(receipt.receipt_sha256) == 64
    assert receipt.actual_context_chars <= route.budget.max_context_chars
    assert receipt.actual_context_utf8_bytes <= route.budget.max_prompt_utf8_bytes
    assert (
        route.budget.max_prompt_utf8_bytes
        + route.budget.max_generated_tokens
        + route.budget.prompt_token_safety_margin
        <= route.budget.runtime_context_tokens
    )
    assert receipt.route.operation is NeuralOperation.DIALOGUE
    assert len(assembled.dropped_conversation_refs) == 6
    assert len(assembled.dropped_refs) >= 4
    assert set(receipt.included_refs).isdisjoint(receipt.dropped_refs)
    assert "memory:11" in assembled.untrusted_refs


def test_budget_receipt_store_is_append_only_and_canonical(tmp_path: Path) -> None:
    assembled = ContextAssembler().assemble(
        OwnerTurnContext(
            "session:receipt",
            "oi",
            mandatory_constraints=("sem efeitos reais",),
        )
    )
    destination = tmp_path / "neural-budget.jsonl"
    store = AppendOnlyNeuralBudgetStore(destination)
    store.append(assembled.budget_receipt)
    store.append(assembled.budget_receipt)
    lines = destination.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == json.loads(lines[1])
    assert json.loads(lines[0])["receipt_sha256"] == assembled.budget_receipt.receipt_sha256


def test_semantic_route_is_neural_but_budget_authority_is_deterministic() -> None:
    class RouteRuntime:
        def __init__(self) -> None:
            self.requests = []

        def stream_chat(self, request, cancellation):
            self.requests.append(request)
            raw = json.dumps(
                {
                    "route": ["intencao", "engenharia", "materializacao"],
                    "rationale": "Preserva a intenção, estrutura a engenharia e materializa somente ao final.",
                },
                ensure_ascii=False,
            )
            yield ModelStreamEvent(request.operation_id, 1, ModelStreamKind.STARTED)
            yield ModelStreamEvent(request.operation_id, 2, ModelStreamKind.TOKEN, raw)
            now = time.monotonic_ns()
            yield ModelStreamEvent(
                request.operation_id,
                3,
                ModelStreamKind.COMPLETED,
                trace=StochasticTrace(
                    request.operation_id,
                    "route-test-double",
                    "a" * 64,
                    request.policy.policy_id,
                    request.policy.seed,
                    request.context_digest,
                    hashlib.sha256(raw.encode()).hexdigest(),
                    1,
                    "stop",
                    now - 1,
                    now,
                ),
            )

    runtime = RouteRuntime()
    proposal = GenerativeUniversePlanner(runtime).propose(  # type: ignore[arg-type]
        "Crie um agente de engenharia.",
        operation_id="route:arc7",
        cancellation=CancellationToken(),
    )
    assert proposal.route_decision is not None
    assert proposal.route_decision.operation is NeuralOperation.SEMANTIC_ROUTING
    assert runtime.requests[0].policy.policy_id == "casulo-arc7-semantic-routing-v1"
    assert runtime.requests[0].policy.max_generated_tokens == 384
