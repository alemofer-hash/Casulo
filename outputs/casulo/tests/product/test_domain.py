from __future__ import annotations

import json

import pytest

from casulo.product import (
    CapabilityGrant,
    CollaborationContract,
    CreationAggregate,
    CreationSpec,
    CreationState,
    DeltaConfirmation,
    DomainError,
    IntentDelta,
    IntentOperation,
    MemoryPolicy,
    canonical_json,
    migrate_creation_document,
)


def delta_for(aggregate: CreationAggregate, *, confirmation=DeltaConfirmation.CONFIRMED):
    return IntentDelta(
        delta_id=f"delta:{aggregate.current.version}",
        creation_id=aggregate.current.creation_id,
        base_version=aggregate.current.version,
        operations=(IntentOperation("set", ("behavior", "tone"), "direto"),),
        rationale="Preferência expressa pelo usuário.",
        source_event_ids=("voice:1",),
        confidence=1.0,
        confirmation=confirmation,
        affected_paths=(("behavior", "tone"),),
    )


def test_canonical_serialization_golden() -> None:
    payload = {"z": "ação", "a": [3, True, None], "nested": {"b": 2, "a": 1}}
    assert canonical_json(payload) == (
        b'{"a":[3,true,null],"nested":{"a":1,"b":2},"z":"a\xc3\xa7\xc3\xa3o"}\n'
    )


def test_confirmed_delta_rehydrates_without_implicit_capability() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:1"))
    before = aggregate.current
    after = aggregate.apply_delta(delta_for(aggregate))
    assert after.version == 1
    assert after.content["behavior"]["tone"] == "direto"
    assert after.capabilities == frozenset()
    assert aggregate.rehydrate(0).sha256 == before.sha256
    assert aggregate.events[0].payload_sha256


def test_proposed_delta_does_not_mutate_state() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:1"))
    before = aggregate.current.sha256
    with pytest.raises(DomainError, match="somente delta confirmado"):
        aggregate.apply_delta(
            delta_for(aggregate, confirmation=DeltaConfirmation.PROPOSED)
        )
    assert aggregate.current.sha256 == before
    assert aggregate.events == ()


def test_rejected_delta_is_preserved_but_not_applied() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:1"))
    rejected = aggregate.apply_delta(
        delta_for(aggregate, confirmation=DeltaConfirmation.REJECTED)
    )
    assert rejected.content == {}
    assert rejected.rejected_delta_ids == ("delta:0",)
    assert aggregate.events[-1].kind == "DELTA_REJECTED"


def test_delta_cannot_modify_capabilities() -> None:
    with pytest.raises(DomainError, match="delta não pode alterar capabilities"):
        IntentOperation("set", ("capabilities", "network.connect"), True)


def test_only_explicit_human_grant_can_elevate_capability() -> None:
    with pytest.raises(DomainError, match="aprovação humana explícita"):
        CapabilityGrant("network.connect", "model", "model:1", False)
    aggregate = CreationAggregate(CreationSpec("creation:1"))
    granted = aggregate.grant(
        CapabilityGrant("network.connect", "human", "voice:approval:1", True)
    )
    assert granted.capabilities == frozenset({"network.connect"})
    revoked = aggregate.revoke("network.connect", "voice:revoke:1")
    assert revoked.capabilities == frozenset()


def test_base_version_conflict_is_fail_closed() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:1"))
    stale = delta_for(aggregate)
    aggregate.transition(CreationState.FIRST_INTENT, "voice:1")
    with pytest.raises(DomainError, match="conflito de base_version"):
        aggregate.apply_delta(stale)


def test_state_machine_covers_twelve_states_and_rejects_skips() -> None:
    assert len(CreationState) == 12
    aggregate = CreationAggregate(CreationSpec("creation:1"))
    with pytest.raises(DomainError, match="transição inválida"):
        aggregate.transition(CreationState.MATERIALIZATION, "voice:1")
    for state in (
        CreationState.FIRST_INTENT,
        CreationState.FIRST_FORM,
        CreationState.CONFIRMATION,
        CreationState.PERSONALITY,
        CreationState.SIMULATION,
        CreationState.AGREEMENT,
        CreationState.MATERIALIZATION,
    ):
        aggregate.transition(state, f"event:{state.value}")
    assert aggregate.current.state is CreationState.MATERIALIZATION


def test_creation_schema_migration_is_deterministic() -> None:
    old = {
        "schema": "casulo.creation/0.1",
        "id": "creation:legacy",
        "revision": 2,
        "phase": "FIRST_FORM",
        "title": "Guardião",
        "content": {"purpose": "continuidade"},
        "capabilities": ["memory.read", "memory.read"],
    }
    migrated = migrate_creation_document(old)
    assert migrated["schema"] == "casulo.creation/1.0"
    assert migrated["content"] == {"name": "Guardião", "purpose": "continuidade"}
    assert migrated["capabilities"] == ["memory.read"]
    assert migrate_creation_document(migrated) == migrated


def test_contracts_validate_consent_and_privacy_defaults() -> None:
    collaboration = CollaborationContract()
    memory = MemoryPolicy()
    assert collaboration.consented is False
    assert memory.training_with_user_content is False
    assert memory.remote_context == "ephemeral_opt_in"
    document = json.loads(canonical_json(collaboration))
    assert document["schema"] == "casulo.collaboration/1.0"


def test_non_finite_values_are_rejected() -> None:
    with pytest.raises(DomainError, match="NaN"):
        canonical_json({"bad": float("nan")})
