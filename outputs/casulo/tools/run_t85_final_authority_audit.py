from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from casulo.t.authority import AuthorityAudit, DecisionTrace, load_surfaces, write_audit


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "product-demos/t85-sovereign-engine"

MIGRATED = {
    "material_intent": ("ts05-critical-authority-attempt1", "ts14-integrated-rehearsal-attempt3"),
    "capabilities_effects": ("ts05-critical-authority-attempt1", "ts14-integrated-rehearsal-attempt3"),
    "hard_requirement_fulfillment": ("ts05-critical-authority-attempt1", "ts06-requirement-graph-attempt1", "ts14-integrated-rehearsal-attempt3"),
    "publish_commit": ("ts05-critical-authority-attempt1", "ts14-integrated-rehearsal-attempt3"),
    "agent_behavior": ("ts07-nontrivial-holdouts-attempt7", "ts14-integrated-rehearsal-attempt3"),
    "memory_governance": ("ts08-guide-memory-attempt1", "ts14-integrated-rehearsal-attempt3"),
    "semantic_routing_lifecycle": ("ts10-physical-multiverse-attempt5", "ts14-integrated-rehearsal-attempt3"),
    "jobs_concurrency_cancel": ("ts09-presence-voice-attempt1", "ts14-integrated-rehearsal-attempt3"),
    "simulation_acceptance": ("ts11-sovereign-materialization-attempt3", "ts14-integrated-rehearsal-attempt3"),
    "materialization_lifecycle": ("ts11-sovereign-materialization-attempt3", "ts14-integrated-rehearsal-attempt3"),
}

NOT_MIGRATED = {
    "tools_composition": "foreign simulation/tool primitives remain Python-owned; T gates use and publication but does not compose arbitrary tools",
    "interface_state": "renderer and Creation Field state remain foreign implementations",
    "recovery_update": "A/B updater is fail-closed and signed but not decided by a T module",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_seal(directory: Path) -> dict[str, object]:
    manifest_path = directory / "MANIFEST.json"
    if not manifest_path.is_file():
        return {"valid": False, "cause": "manifest_absent", "directory": str(directory)}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    mismatches = [
        name for name, expected in files.items()
        if not (directory / name).is_file() or sha256(directory / name) != expected
    ]
    return {
        "valid": not mismatches,
        "gate": manifest.get("gate"),
        "files": len(files),
        "mismatches": mismatches,
        "manifest_sha256": sha256(manifest_path),
    }


def build_audit(matrix: Path) -> tuple[AuthorityAudit, dict[str, object]]:
    surfaces = load_surfaces(matrix)
    seals: dict[str, dict[str, object]] = {}
    for names in MIGRATED.values():
        for name in names:
            seals.setdefault(name, verify_seal(EVIDENCE_ROOT / name))
    invalid = [name for name, result in seals.items() if not result["valid"]]
    if invalid:
        raise RuntimeError(f"sealed evidence diverged: {invalid}")

    traces: list[DecisionTrace] = []
    for surface in surfaces:
        names = MIGRATED.get(surface.surface_id)
        if names is None:
            traces.append(DecisionTrace(
                surface.surface_id, f"unmigrated:{surface.surface_id}",
                False, False, True, True, False, False, True, False,
                (NOT_MIGRATED[surface.surface_id],),
            ))
            continue
        traces.append(DecisionTrace(
            surface.surface_id, f"t85-final:{surface.surface_id}",
            True, True, False, False, True, True, True, True,
            tuple(
                f"product-demos/t85-sovereign-engine/{name}/MANIFEST.json#{seals[name]['manifest_sha256']}"
                for name in names
            ),
        ))
    return AuthorityAudit(surfaces, tuple(traces)), seals


def main() -> int:
    parser = argparse.ArgumentParser(description="Final evidence-bound T85 authority audit")
    parser.add_argument("--matrix", type=Path, default=ROOT / "docs/product/TS_SOVEREIGNTY_MATRIX.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seals", type=Path, required=True)
    args = parser.parse_args()
    audit, seals = build_audit(args.matrix)
    write_audit(args.output, audit)
    args.seals.parent.mkdir(parents=True, exist_ok=True)
    args.seals.write_text(json.dumps({
        "schema": "casulo.t85-final-authority-evidence/1.0",
        "migrated_surfaces": sorted(MIGRATED),
        "unmigrated_surfaces": NOT_MIGRATED,
        "sealed_evidence": seals,
        "critical_degrees": {
            item["id"]: item["degree"] for item in audit.to_dict()["surfaces"] if item["critical"]
        },
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    result = audit.to_dict()
    passed = result["s_authority"] >= 0.85 and result["s_execution"] >= 0.60 and result["c_critical"] == 1.0
    print(json.dumps({
        "gate": "T85_FINAL_AUTHORITY_PASS" if passed else "T85_FINAL_AUTHORITY_FAIL",
        "s_authority": result["s_authority"], "s_execution": result["s_execution"],
        "c_critical": result["c_critical"], "migrated": len(MIGRATED),
    }, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
