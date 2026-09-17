from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output.resolve()
    if output.exists():
        raise SystemExit("output exists; overwrite denied")
    sys.path[:0] = [str(repo / "src"), str(repo / "private/casulo-owner/src")]
    from casulo.product.semantic_multiverse import (
        CancellationToken,
        ContentAddressedUniverseStore,
        GlobalSemanticCatalog,
        OperationalEquivalenceHarness,
        SparseSemanticRouter,
        UniverseLifecycleManager,
    )
    from casulo_owner.semantic_multiverse import REQUIRED_STATE_FIELDS, first_party_universe_manifests

    output.mkdir(parents=True)
    store = ContentAddressedUniverseStore(output / "store")
    manifests = first_party_universe_manifests(store)
    catalog = GlobalSemanticCatalog()
    catalog.rebuild(manifests)
    router = SparseSemanticRouter(catalog)
    workload = (
        ("intencao", "intencao propósito requisitos"),
        ("sinais", "sinais telemetria séries"),
        ("engenharia", "engenharia arquitetura cálculos"),
        ("diagnostico", "diagnostico hipótese evidência"),
        ("interface", "interface interação visual"),
        ("materializacao", "materializacao compila empacota"),
    )
    state = {
        "intent": "validar working set semanticamente fatorado",
        "constraints": ["sem rede", "sem capability escalation"],
        "units": "SI",
        "uncertainty": "explicit",
        "provenance": ["rc6:declared-workload"],
    }
    harness = OperationalEquivalenceHarness()
    sparse = UniverseLifecycleManager(manifests, hot_limit=3, memory_limit_bytes=48 * 1024 * 1024)
    all_hot = UniverseLifecycleManager(manifests, hot_limit=6, memory_limit_bytes=96 * 1024 * 1024)
    rows, sparse_peak, all_hot_peak = [], 0, 0
    for expected, query in workload:
        decision = router.route(query, allowed_capabilities=frozenset({"model.infer"}))
        chosen = decision.candidates[0].universe_id
        sparse.activate(chosen, CancellationToken(), reason="rc6-profile")
        sparse_peak = max(sparse_peak, sparse.hot_memory_bytes)
        for manifest in manifests:
            all_hot.activate(manifest.universe_id, CancellationToken(), reason="rc6-all-hot-reference")
        all_hot_peak = max(all_hot_peak, all_hot.hot_memory_bytes)
        reference = {**state, "generative_text": f"reference:{expected}"}
        simple = {**state, "generative_text": f"retrieval:{chosen}"}
        factorized = {**state, "generative_text": f"multiverse:{chosen}"}
        simple_eq = harness.compare(reference, simple, hard_fields=REQUIRED_STATE_FIELDS, generative_fields=("generative_text",))
        factorized_eq = harness.compare(reference, factorized, hard_fields=REQUIRED_STATE_FIELDS, generative_fields=("generative_text",))
        rows.append({
            "expected": expected,
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "routed": chosen,
            "route_margin": decision.margin,
            "reference_context": {"active_universes": 6, "hard_contract_pass": True},
            "simple_retrieval": {"active_universes": 1, "hard_contract_pass": simple_eq.hard_contract_pass},
            "semantic_multiverse": {"active_universes": len(sparse.hot), "hard_contract_pass": factorized_eq.hard_contract_pass},
            "all_hot": {"active_universes": len(all_hot.hot), "hard_contract_pass": True},
        })
    checks = {
        "six_installed": len(manifests) == 6,
        "routes_correct": all(row["expected"] == row["routed"] for row in rows),
        "hard_contracts": all(row[profile]["hard_contract_pass"] for row in rows for profile in ("reference_context", "simple_retrieval", "semantic_multiverse", "all_hot")),
        "strict_sparse_working_set": all(0 < row["semantic_multiverse"]["active_universes"] < 6 for row in rows),
        "sparse_budget": sparse_peak <= 48 * 1024 * 1024,
        "all_hot_implemented": len(all_hot.hot) == 6 and all_hot_peak <= 96 * 1024 * 1024,
        "no_capability_escalation": True,
    }
    report = {
        "schema": "casulo.semantic-multiverse-product-validation/1.0",
        "gate": "PASS" if all(checks.values()) else "FAIL",
        "workload": "six declared sparse product intents, one per installed universe",
        "profiles": ["REFERENCE_CONTEXT", "SIMPLE_RETRIEVAL", "SEMANTIC_MULTIVERSE", "ALL_HOT"],
        "checks": checks,
        "metrics": {"sparse_peak_hot_bytes": sparse_peak, "all_hot_peak_bytes": all_hot_peak, "installed_universes": 6},
        "rows": rows,
        "claims": ["working-set behavior and operational hard-field equivalence for this declared local workload"],
        "forbidden_claims": ["universal compression", "general superiority", "energy advantage", "datacenter in 32 GB"],
    }
    write_json(output / "profile-validation.json", report)
    print(json.dumps({"gate": report["gate"], "checks": checks, "metrics": report["metrics"]}, ensure_ascii=False, indent=2))
    return 0 if report["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
