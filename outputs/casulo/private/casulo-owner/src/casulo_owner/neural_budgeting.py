from __future__ import annotations

from dataclasses import replace

from casulo.product.neural_budget import (
    NeuralBudgetRouter,
    NeuralOperation,
    NeuralRouteDecision,
    NeuralRouteRequest,
)

from .local_model_runtime import SamplingPolicy, initial_sampling_policies


def budgeted_policy(
    operation: NeuralOperation,
    *,
    source_event_ids: tuple[str, ...],
    human_confirmed: bool = False,
    hard_requirement_count: int = 0,
    material_gap_open: bool = False,
    diagnostic_present: bool = False,
    policy_override: SamplingPolicy | None = None,
) -> tuple[NeuralRouteDecision, SamplingPolicy]:
    decision = NeuralBudgetRouter.decide(
        NeuralRouteRequest(
            operation,
            source_event_ids,
            human_confirmed,
            hard_requirement_count,
            material_gap_open,
            diagnostic_present,
        )
    )
    base = policy_override or initial_sampling_policies()[decision.budget.sampling_family]
    policy_id = f"casulo-{decision.budget.budget_id}"
    if policy_override is not None:
        policy_id = f"{policy_id}:{policy_override.policy_id}"
    max_generated_tokens = decision.budget.max_generated_tokens
    if policy_override is not None:
        max_generated_tokens = min(
            base.max_generated_tokens,
            decision.budget.max_generated_tokens,
        )
    policy = replace(
        base,
        policy_id=policy_id,
        max_generated_tokens=max_generated_tokens,
    )
    return decision, policy


def validate_budgeted_messages(
    decision: NeuralRouteDecision,
    messages: tuple[object, ...],
) -> int:
    try:
        actual_chars = sum(len(str(getattr(item, "content"))) for item in messages)
        actual_utf8_bytes = sum(
            len(str(getattr(item, "content")).encode("utf-8")) for item in messages
        )
    except (TypeError, ValueError) as error:
        raise ValueError("mensagens neurais inválidas") from error
    if actual_chars > decision.budget.max_context_chars:
        raise ValueError(
            "contexto neural excede budget; truncamento implícito negado "
            f"({actual_chars}>{decision.budget.max_context_chars})"
        )
    if actual_utf8_bytes > decision.budget.max_prompt_utf8_bytes:
        raise ValueError(
            "contexto neural UTF-8 excede budget; truncamento implícito negado "
            f"({actual_utf8_bytes}>{decision.budget.max_prompt_utf8_bytes})"
        )
    return actual_chars
