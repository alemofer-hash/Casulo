from __future__ import annotations

import json

from .domain import (
    CapabilityGrant,
    CreationAggregate,
    CreationSpec,
    CreationState,
    DeltaConfirmation,
    DomainError,
    IntentDelta,
    IntentOperation,
)


def main() -> int:
    aggregate = CreationAggregate(CreationSpec("creation:continuity-guide"))
    aggregate.transition(CreationState.FIRST_INTENT, "voice:1")
    aggregate.apply_delta(
        IntentDelta(
            delta_id="delta:1",
            creation_id=aggregate.current.creation_id,
            base_version=aggregate.current.version,
            operations=(
                IntentOperation("set", ("identity", "name"), "Guia de Continuidade"),
                IntentOperation("set", ("behavior", "tone"), "colega direto"),
            ),
            rationale="O Inventor definiu identidade e tom.",
            source_event_ids=("voice:1",),
            confidence=1.0,
            confirmation=DeltaConfirmation.CONFIRMED,
            affected_paths=(("identity", "name"), ("behavior", "tone")),
        )
    )
    aggregate.transition(CreationState.FIRST_FORM, "guide:preview:1")
    aggregate.transition(CreationState.CONFIRMATION, "voice:2")

    implicit_grant_blocked = False
    try:
        CapabilityGrant(
            capability="network.connect",
            granted_by="model",
            source_event_id="model:proposal:1",
            explicit_human_approval=False,
        )
    except DomainError:
        implicit_grant_blocked = True

    print(
        json.dumps(
            {
                "ok": True,
                "creation": aggregate.current.to_dict(),
                "creation_sha256": aggregate.current.sha256,
                "events": [event.to_dict() for event in aggregate.events],
                "rehydrated_version_1": aggregate.rehydrate(1).to_dict(),
                "implicit_grant_blocked": implicit_grant_blocked,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
