from __future__ import annotations

import argparse
import json
from pathlib import Path

from .capabilities import Effect
from .creation_pipeline import creation_units
from .domain import CreationSpec, CreationState
from .materializer import Materializer
from .simulation import (
    SimulatedResponse,
    SimulationCapabilityDouble,
    SimulationPlan,
    SimulationRuntime,
    SimulationStep,
)
from .t_forge import TForge


def main() -> int:
    parser = argparse.ArgumentParser(description="Materializa pacote Casulo local")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    creation = CreationSpec(
        "creation:materializer-demo",
        version=1,
        state=CreationState.AGREEMENT,
        content={"identity": {"name": "Guia Casulo"}, "behavior": {"tone": "resiliente"}},
        capabilities=frozenset({Effect.NETWORK_CONNECT.value}),
    )
    forge = TForge().compile(creation_units(creation))
    simulation_creation = CreationSpec(
        creation.creation_id,
        version=creation.version,
        state=CreationState.CONFIRMATION,
        content=creation.content,
        capabilities=creation.capabilities,
    )
    simulation = SimulationRuntime(
        {
            Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
                Effect.NETWORK_CONNECT,
                (SimulatedResponse(True, {"status": 202, "virtual": True}),),
            )
        }
    ).run(
        simulation_creation,
        SimulationPlan(
            "simulation:materializer-demo",
            creation.creation_id,
            (
                SimulationStep(
                    "virtual-request",
                    Effect.NETWORK_CONNECT,
                    "preview",
                    {"endpoint": "simulation://casulo"},
                    (),
                    (("behavior", "tone"),),
                    ("voice:simulation",),
                ),
            ),
            ("voice:simulation",),
        ),
    )
    receipt = Materializer(args.output).materialize(
        creation,
        forge_receipt=forge,
        simulation_receipt=simulation,
    )
    print(json.dumps({"ok": True, **receipt.to_dict()}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
