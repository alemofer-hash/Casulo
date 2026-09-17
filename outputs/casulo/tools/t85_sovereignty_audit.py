from __future__ import annotations

import argparse
from pathlib import Path

from casulo.t.authority import AuthorityAudit, load_surfaces, traces_for_absent_authority, write_audit


ROOT = Path(__file__).resolve().parents[1]


BASELINE_EVIDENCE = {
    "material_intent": ("src/casulo/product/intent_engine.py",),
    "capabilities_effects": ("src/casulo/product/capabilities.py",),
    "hard_requirement_fulfillment": ("src/casulo/product/semantic_fulfillment.py",),
    "publish_commit": ("src/casulo/product/materializer.py",),
    "agent_behavior": ("private/casulo-owner/src/casulo_owner/generative_forge.py",),
    "memory_governance": ("src/casulo/product/living_memory.py",),
    "semantic_routing_lifecycle": ("src/casulo/product/semantic_multiverse.py",),
    "tools_composition": ("src/casulo/product/simulation.py",),
    "jobs_concurrency_cancel": ("src/casulo/product/guide_presence.py",),
    "simulation_acceptance": ("src/casulo/product/simulation.py",),
    "interface_state": ("src/casulo/product/creation_field.py",),
    "materialization_lifecycle": ("src/casulo/product/materializer.py",),
    "recovery_update": ("src/casulo/product/offline_update.py",),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit T85 authority without promoting shadow T")
    parser.add_argument("--matrix", type=Path, default=ROOT / "docs/product/TS_SOVEREIGNTY_MATRIX.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    surfaces = load_surfaces(args.matrix)
    audit = AuthorityAudit(surfaces, traces_for_absent_authority(surfaces, BASELINE_EVIDENCE))
    write_audit(args.output, audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

