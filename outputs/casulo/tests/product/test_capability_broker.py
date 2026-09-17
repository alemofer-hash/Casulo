from __future__ import annotations

import pytest

from casulo.product.capabilities import (
    ApprovalToken,
    CapabilityBroker,
    CapabilityDenied,
    Effect,
    EffectRequest,
)


ACTION = "a" * 64


def request(effect: Effect, *, declared: bool = True) -> EffectRequest:
    return EffectRequest("effect:1", "creation:1", effect, ACTION, declared)


def test_missing_declaration_and_grant_are_denied() -> None:
    broker = CapabilityBroker()
    with pytest.raises(CapabilityDenied, match="não declarado"):
        broker.authorize(request(Effect.MEMORY_READ, declared=False))
    with pytest.raises(CapabilityDenied, match="não concedida"):
        broker.authorize(request(Effect.MEMORY_READ))


def test_granted_non_sensitive_effect_is_allowed() -> None:
    broker = CapabilityBroker({"creation:1": frozenset({Effect.MEMORY_READ})})
    broker.authorize(request(Effect.MEMORY_READ))


def test_sensitive_effect_requires_matching_one_shot_human_approval() -> None:
    broker = CapabilityBroker({"creation:1": frozenset({Effect.NETWORK_CONNECT})})
    item = request(Effect.NETWORK_CONNECT)
    with pytest.raises(CapabilityDenied, match="aprovação humana ausente"):
        broker.authorize(item)
    approval = ApprovalToken(
        "creation:1", Effect.NETWORK_CONNECT, ACTION, "voice:approval:1"
    )
    broker.authorize(item, approval)
    with pytest.raises(CapabilityDenied, match="já consumida"):
        broker.authorize(item, approval)


def test_model_proposal_is_only_a_request_not_a_grant() -> None:
    proposal = request(Effect.PROCESS_SPAWN)
    with pytest.raises(CapabilityDenied, match="não concedida"):
        CapabilityBroker().authorize(proposal)


def test_qpu_cannot_be_granted_even_if_manifest_requests_it() -> None:
    broker = CapabilityBroker(
        {"creation:1": frozenset({Effect.QUANTUM_QPU_SUBMIT})}
    )
    with pytest.raises(CapabilityDenied, match="CAP106"):
        broker.authorize(request(Effect.QUANTUM_QPU_SUBMIT))
