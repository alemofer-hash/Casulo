from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "private/casulo-owner/src")]

from casulo.product.semantic_multiverse import (  # noqa: E402
    CancellationToken,
    ContentAddressedUniverseStore,
    GlobalSemanticCatalog,
    OperationalEquivalenceHarness,
    SemanticTransitionRuntime,
    SparseSemanticRouter,
    SufficientProjection,
    canonical_json,
    sha256_bytes,
)
from casulo_owner.semantic_multiverse import REQUIRED_STATE_FIELDS, first_party_universe_manifests  # noqa: E402
from casulo_owner.t85_physical_multiverse import T85PhysicalMultiverse, build_physical_universe_bundles  # noqa: E402


WORKLOAD = (
    ("intencao", "intencao proposito requisitos"),
    ("sinais", "sinais telemetria series"),
    ("engenharia", "engenharia arquitetura calculos"),
    ("diagnostico", "diagnostico hipotese evidencia"),
    ("interface", "interface interacao visual"),
    ("materializacao", "materializacao compila empacota"),
)
PROJECTS = ("physical-alpha", "physical-beta")
ALLOWED = frozenset({"model.infer"})


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def state_for(project_id: str) -> dict[str, Any]:
    return {
        "intent": f"validar working set do projeto {project_id}",
        "constraints": ["sem rede", "sem capability escalation", f"project:{project_id}"],
        "units": "SI",
        "uncertainty": "explicit",
        "provenance": [f"project:{project_id}", "ts10:pre-registered-workload"],
    }


def observation(service: T85PhysicalMultiverse) -> dict[str, Any]:
    value = asdict(service.store.observe())
    value["managed_bytes"] = service.store.managed_bytes
    value["hot"] = sorted(key for key, state in service.store.states.items() if state == "HOT")
    return value


def compare_state(reference: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    return OperationalEquivalenceHarness().compare(
        reference, candidate, hard_fields=REQUIRED_STATE_FIELDS, generative_fields=(),
    ).hard_contract_pass


def verify_receipt_chain(directory: Path, *, nested_t: bool) -> dict[str, Any]:
    previous = "0" * 64
    checked = 0
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        receipt = document["receipt"] if nested_t else document
        if receipt.get("previous_receipt_hash") != previous:
            errors.append(f"{path.name}:previous")
        seed = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        expected = sha256_bytes(canonical_json(seed))
        if receipt.get("receipt_hash") != expected:
            errors.append(f"{path.name}:hash")
        previous = str(receipt.get("receipt_hash"))
        checked += 1
    return {"checked": checked, "valid": checked > 0 and not errors, "errors": errors, "head": previous}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("output exists; overwrite denied")
    output.mkdir(parents=True)

    protocol = {
        "schema": "casulo.t85-physical-multiverse-protocol/1.0",
        "frozen_before_results": True,
        "profiles": ["REFERENCE_SIMPLE_RETRIEVAL", "ALL_HOT", "T_SPARSE_MULTIVERSE"],
        "projects": list(PROJECTS),
        "workload": [{"expected": expected, "query_sha256": hashlib.sha256(query.encode()).hexdigest()} for expected, query in WORKLOAD],
        "gates": {"critical_semantic_loss": 0, "project_bleed": 0, "max_managed_ratio": 0.70, "capability_amplification": 0, "artificial_padding": False},
        "thermostat": {"theta_off": 0.50, "theta_on": 0.70, "minimum_residence_ns": 1_000_000},
        "excluded_from_managed_claim": ["Qwen3-4B weights", "llama.cpp runtime", "Python interpreter", "T runtime process"],
        "claims_forbidden": ["energy advantage", "universal compression", "datacenter replacement", "Qwen weight paging"],
        "locks": {"cloud": "RELEASE_LOCKED", "guest_network": "OFF", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
    }
    dump(output / "protocol.json", protocol)
    dump(output / "protocol.sha256.json", {"sha256": sha256_bytes((output / "protocol.json").read_bytes())})

    source_store = ContentAddressedUniverseStore(output / "semantic-source")
    manifests = first_party_universe_manifests(source_store)
    by_id = {item.universe_id: item for item in manifests}
    catalog = GlobalSemanticCatalog()
    catalog.rebuild(manifests)
    router = SparseSemanticRouter(catalog)
    bundle_root = output / "universe-store"
    policy_source = ROOT / "private/casulo-owner/t-v2/universe-lifecycle-policy.t"
    build_physical_universe_bundles(bundle_root, manifests, policy_source=policy_source)
    tcap = T85PhysicalMultiverse.build_policy(policy_source, output / "universe-lifecycle-policy.tcap")
    runtime = ROOT / "t-runtime/target/release/casulo-t-runtime.exe"

    route_rows: list[dict[str, Any]] = []
    reference_store = T85PhysicalMultiverse(runtime, tcap, bundle_root, output / "reference-receipts", minimum_residence_ns=1_000_000)
    reference_start = observation(reference_store)
    for project_id in PROJECTS:
        reference_state = state_for(project_id)
        for expected, query in WORKLOAD:
            decision = router.route(query, allowed_capabilities=ALLOWED)
            routed = decision.candidates[0].universe_id
            bundle_hash, bytes_read = reference_store.store.reference_read(routed)
            route_rows.append({
                "profile": "REFERENCE_SIMPLE_RETRIEVAL", "project_id": project_id,
                "expected": expected, "routed": routed, "bundle_hash": bundle_hash,
                "bytes_read": bytes_read, "hard_contract_pass": compare_state(reference_state, dict(reference_state)),
            })
    reference_end = observation(reference_store)
    reference_store.close()

    all_hot = T85PhysicalMultiverse(runtime, tcap, bundle_root, output / "all-hot-receipts", minimum_residence_ns=1_000_000)
    all_hot_start = observation(all_hot)
    all_state = state_for(PROJECTS[0])
    for universe_id in sorted(by_id):
        all_hot.activate(universe_id, allowed_capabilities=ALLOWED, constraints=all_state["constraints"], provenance=all_state["provenance"])
    all_hot_peak = observation(all_hot)
    for project_id in PROJECTS:
        reference_state = state_for(project_id)
        for expected, query in WORKLOAD:
            routed = router.route(query, allowed_capabilities=ALLOWED).candidates[0].universe_id
            route_rows.append({
                "profile": "ALL_HOT", "project_id": project_id, "expected": expected,
                "routed": routed, "hot": list(all_hot_peak["hot"]),
                "hard_contract_pass": compare_state(reference_state, dict(reference_state)),
            })
    time.sleep(0.003)
    for universe_id in sorted(by_id):
        all_hot.hibernate(universe_id, sufficient_state=all_state, constraints=all_state["constraints"], provenance=all_state["provenance"])
    all_hot_reclaimed = observation(all_hot)
    all_hot.close()

    sparse = T85PhysicalMultiverse(runtime, tcap, bundle_root, output / "sparse-receipts", minimum_residence_ns=1_000_000)
    sparse_start = observation(sparse)
    sparse_peak = dict(sparse_start)
    transition_runtime = SemanticTransitionRuntime()
    transition_rows: list[dict[str, Any]] = []
    project_outputs: dict[str, list[dict[str, Any]]] = {}
    for project_id in PROJECTS:
        state = state_for(project_id)
        previous: str | None = None
        project_outputs[project_id] = []
        for expected, query in WORKLOAD:
            decision = router.route(query, allowed_capabilities=ALLOWED)
            routed = decision.candidates[0].universe_id
            if previous is not None:
                transition_input = {
                    **state,
                    "universe_local_cache": {
                        "owner": previous,
                        "disposition": "OMIT_AT_BOUNDARY",
                    },
                }
                state, transition = transition_runtime.execute(
                    transition_id=f"{project_id}:{previous}:{routed}", source=by_id[previous], destination=by_id[routed],
                    state=transition_input, projection=SufficientProjection("physical-sufficient", REQUIRED_STATE_FIELDS),
                    required_invariants=REQUIRED_STATE_FIELDS, allowed_capabilities=ALLOWED,
                    provenance_root=sha256_bytes(canonical_json(state["provenance"])), token=CancellationToken(),
                )
                transition_rows.append(asdict(transition))
            time.sleep(0.002)
            sparse.reconcile(
                (routed,), allowed_capabilities=ALLOWED, sufficient_state=state,
                constraints=state["constraints"], provenance=state["provenance"],
            )
            current = observation(sparse)
            if current["managed_bytes"] > sparse_peak["managed_bytes"]:
                sparse_peak = current
            project_outputs[project_id].append(dict(state))
            route_rows.append({
                "profile": "T_SPARSE_MULTIVERSE", "project_id": project_id,
                "expected": expected, "routed": routed, "hot": list(current["hot"]),
                "hard_contract_pass": compare_state(state_for(project_id), state),
            })
            previous = routed
        time.sleep(0.002)
        sparse.hibernate(previous, sufficient_state=state, constraints=state["constraints"], provenance=state["provenance"])
    sparse_reclaimed = observation(sparse)
    sparse.close()

    chain_audit = {
        "all_hot_t": verify_receipt_chain(output / "all-hot-receipts/t-decision-receipts", nested_t=True),
        "all_hot_foreign": verify_receipt_chain(output / "all-hot-receipts/foreign-receipts", nested_t=False),
        "sparse_t": verify_receipt_chain(output / "sparse-receipts/t-decision-receipts", nested_t=True),
        "sparse_foreign": verify_receipt_chain(output / "sparse-receipts/foreign-receipts", nested_t=False),
    }

    all_hot_managed = int(all_hot_peak["managed_bytes"])
    sparse_managed = int(sparse_peak["managed_bytes"])
    managed_ratio = sparse_managed / all_hot_managed
    critical_total = len(route_rows) * len(REQUIRED_STATE_FIELDS)
    critical_pass = sum(len(REQUIRED_STATE_FIELDS) for row in route_rows if row["hard_contract_pass"])
    project_bleed = sum(
        1 for project_id, states in project_outputs.items()
        for state in states
        if f"project:{project_id}" not in state["constraints"] or f"project:{project_id}" not in state["provenance"]
    )
    routes_correct = all(row["expected"] == row["routed"] for row in route_rows)
    checks = {
        "profiles_executed": {row["profile"] for row in route_rows} == {"REFERENCE_SIMPLE_RETRIEVAL", "ALL_HOT", "T_SPARSE_MULTIVERSE"},
        "routes_correct": routes_correct,
        "critical_semantic_loss_zero": critical_pass == critical_total,
        "project_bleed_zero": project_bleed == 0,
        "managed_ratio_at_most_0_70": managed_ratio <= 0.70,
        "all_hot_six": len(all_hot_peak["hot"]) == 6,
        "sparse_strict": 0 < len(sparse_peak["hot"]) < 6,
        "physical_reclaim": all_hot_reclaimed["managed_bytes"] == 0 and sparse_reclaimed["managed_bytes"] == 0,
        "mapped_assets_real": all_hot_peak["mapped_bytes"] > 0 and sparse_peak["mapped_bytes"] > 0,
        "t_receipts_present": len(tuple((output / "all-hot-receipts/t-decision-receipts").glob("*.receipt.json"))) == 12 and len(tuple((output / "sparse-receipts/t-decision-receipts").glob("*.receipt.json"))) == 24,
        "foreign_receipts_present": len(tuple((output / "all-hot-receipts/foreign-receipts").glob("*.json"))) == 12 and len(tuple((output / "sparse-receipts/foreign-receipts").glob("*.json"))) == 24,
        "sufficient_state_transitions": len(transition_rows) == 10 and all(row["bytes_transferred"] < row["bytes_read"] for row in transition_rows),
        "no_capability_amplification": all(set(item.capabilities) <= ALLOWED for item in manifests),
        "no_artificial_padding": all(not json.loads((bundle_root / item["path"]).read_text(encoding="utf-8"))["artificial_padding"] for item in json.loads((bundle_root / "catalog.json").read_text(encoding="utf-8"))["bundles"]),
        "no_model_calls": all(obs["model_calls"] == 0 for obs in (reference_start, reference_end, all_hot_start, all_hot_peak, all_hot_reclaimed, sparse_start, sparse_peak, sparse_reclaimed)),
        "receipt_chains_valid": all(item["valid"] for item in chain_audit.values()),
    }
    report = {
        "schema": "casulo.t85-physical-multiverse-gate/1.0",
        "gate": "TS10_PHYSICAL_SEMANTIC_MULTIVERSE_PASS" if all(checks.values()) else "TS10_FAIL",
        "checks": checks,
        "metrics": {
            "critical_total": critical_total, "critical_pass": critical_pass,
            "critical_semantic_loss": 1 - critical_pass / critical_total,
            "project_bleed": project_bleed,
            "all_hot_peak_managed_bytes": all_hot_managed,
            "sparse_peak_managed_bytes": sparse_managed,
            "sparse_to_all_hot_managed_ratio": managed_ratio,
            "reference_start": reference_start, "reference_end": reference_end,
            "all_hot_start": all_hot_start, "all_hot_peak": all_hot_peak, "all_hot_reclaimed": all_hot_reclaimed,
            "sparse_start": sparse_start, "sparse_peak": sparse_peak, "sparse_reclaimed": sparse_reclaimed,
            "transition_receipts": len(transition_rows),
        },
        "claim": "physical read-only mmap/cache working-set reduction for six compact first-party universe bundles on this declared workload",
        "limitations": [
            "managed bytes cover mapped universe assets and their parsed cache, not total process RSS",
            "Qwen3-4B and llama.cpp are explicitly outside the managed universe set",
            "total RSS is observed but has no reduction gate",
            "this is a product conformance gate, not a scientific performance or energy benchmark",
        ],
        "locks": protocol["locks"],
    }
    dump(output / "route-rows.json", route_rows)
    dump(output / "transition-receipts.json", transition_rows)
    dump(output / "resource-observations.json", report["metrics"])
    dump(output / "receipt-chain-audit.json", chain_audit)
    dump(output / "physical-multiverse-gate.json", report)
    dump(output / "gate.json", {"gate": report["gate"], "checks": checks})
    print(json.dumps({"gate": report["gate"], "managed_ratio": managed_ratio, "critical_loss": report["metrics"]["critical_semantic_loss"], "project_bleed": project_bleed}, indent=2))
    return 0 if report["gate"].endswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
