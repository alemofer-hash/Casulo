from __future__ import annotations

import json

from .capabilities import Effect
from .creation_pipeline import CreationPipeline
from .domain import CreationAggregate, CreationSpec, CreationState
from .simulation import (
    SimulatedResponse,
    SimulationCapabilityDouble,
    SimulationPlan,
    SimulationRuntime,
    SimulationStep,
)


def main() -> int:
    aggregate = CreationAggregate(
        CreationSpec(
            "creation:simulation-demo",
            state=CreationState.CONFIRMATION,
            capabilities=frozenset({Effect.NETWORK_CONNECT.value}),
        )
    )
    pipeline = CreationPipeline(aggregate)
    initial = pipeline.bootstrap()
    plan = SimulationPlan(
        "simulation:demo",
        aggregate.current.creation_id,
        (
            SimulationStep(
                "virtual-request",
                Effect.NETWORK_CONNECT,
                "send preview",
                {"endpoint": "simulation://casulo"},
                (),
                (("behavior", "tone"),),
                ("voice:simulate",),
            ),
        ),
        ("voice:simulate",),
    )
    failed = SimulationRuntime(
        {
            Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
                Effect.NETWORK_CONNECT,
                (SimulatedResponse(False, error="timeout virtual"),),
            )
        }
    ).run(aggregate.current, plan)
    pipeline.propose(
        source_event_id="voice:correction",
        utterance="defina behavior.tone como resiliente",
    )
    correction = pipeline.decide(
        human_event_id="voice:confirm",
        accepted=True,
        explicit_human_approval=True,
    )
    passed = SimulationRuntime(
        {
            Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
                Effect.NETWORK_CONNECT,
                (SimulatedResponse(True, {"status": 202, "virtual": True}),),
            )
        }
    ).run(aggregate.current, plan)
    assert correction.forge_receipt is not None
    before = {item.unit_id: item.artifact_sha256 for item in initial.artifacts}
    after = {item.unit_id: item.artifact_sha256 for item in correction.forge_receipt.artifacts}
    print(
        json.dumps(
            {
                "schema": "casulo.simulation-demo/1.0",
                "ok": passed.status == "PASS",
                "first_simulation": failed.to_dict(),
                "correction": {
                    "affected_paths": [list(path) for path in failed.correction_paths],
                    "rebuilt_units": list(correction.forge_receipt.rebuilt_units),
                    "reused_units": list(correction.forge_receipt.reused_units),
                    "identity_hash_preserved": before["identity"] == after["identity"],
                },
                "second_simulation": passed.to_dict(),
                "real_effects_executed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
