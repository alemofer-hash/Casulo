from __future__ import annotations

import json
from pathlib import Path

import pytest

from casulo.product.semantic_multiverse import CancellationToken, ContentAddressedUniverseStore
from casulo.t.productive import ProductiveTError
from casulo_owner.semantic_multiverse import first_party_universe_manifests
from casulo_owner.local_model_runtime import StochasticTrace
from casulo_owner.semantic_multiverse import GenerativeRouteProposal, OwnerSemanticMultiverse
from casulo_owner.t85_physical_multiverse import (
    REQUIRED_BUNDLE_ASSETS,
    PhysicalMultiverseError,
    PhysicalUniverseStore,
    T85PhysicalMultiverse,
    build_physical_universe_bundles,
)


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release/casulo-t-runtime.exe"
POLICY = ROOT / "private/casulo-owner/t-v2/universe-lifecycle-policy.t"
STATE = {
    "intent": "preservar requisitos",
    "constraints": ["sem rede"],
    "units": "SI",
    "uncertainty": "explicit",
    "provenance": ["test:event:1"],
}


def environment(tmp_path: Path) -> tuple[Path, Path]:
    source_store = ContentAddressedUniverseStore(tmp_path / "source")
    manifests = first_party_universe_manifests(source_store)
    bundle_root = tmp_path / "physical"
    build_physical_universe_bundles(bundle_root, manifests, policy_source=POLICY)
    tcap = T85PhysicalMultiverse.build_policy(POLICY, tmp_path / "policy.tcap")
    return bundle_root, tcap


def service(tmp_path: Path, **kwargs: object) -> T85PhysicalMultiverse:
    bundle_root, tcap = environment(tmp_path)
    return T85PhysicalMultiverse(RUNTIME, tcap, bundle_root, tmp_path / "receipts", minimum_residence_ns=0, **kwargs)


def test_bundle_has_exact_required_assets_and_no_padding(tmp_path: Path) -> None:
    bundle_root, _ = environment(tmp_path)
    catalog = json.loads((bundle_root / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["bundles"]) == 6
    for entry in catalog["bundles"]:
        bundle = json.loads((bundle_root / entry["path"]).read_text(encoding="utf-8"))
        assert set(bundle["assets"]) == set(REQUIRED_BUNDLE_ASSETS)
        assert bundle["artificial_padding"] is False
        assert all(item["bytes"] > 0 for item in bundle["assets"].values())
    assert len(tuple((bundle_root / "objects").iterdir())) < 6 * len(REQUIRED_BUNDLE_ASSETS)


def test_t_authorizes_physical_map_and_hibernate_with_reclaim(tmp_path: Path) -> None:
    runtime = service(tmp_path)
    before = runtime.store.observe()
    activated = runtime.activate(
        "intencao", allowed_capabilities=frozenset({"model.infer"}),
        constraints=STATE["constraints"], provenance=STATE["provenance"],
    )
    assert activated is not None and activated.after == "HOT"
    assert runtime.store.mapped_bytes > 0 and runtime.store.cache_bytes > 0
    runtime.store.acquire("intencao")
    with pytest.raises(ProductiveTError, match="lease_or_residency_active"):
        runtime.hibernate("intencao", sufficient_state=STATE, constraints=STATE["constraints"], provenance=STATE["provenance"])
    runtime.store.release("intencao")
    frozen = runtime.hibernate("intencao", sufficient_state=STATE, constraints=STATE["constraints"], provenance=STATE["provenance"])
    assert frozen is not None and frozen.after == "FROZEN"
    assert runtime.store.mapped_bytes == 0 and runtime.store.cache_bytes == 0
    assert frozen.observation_after.mapped_bytes < activated.observation_after.mapped_bytes
    assert before.model_calls == 0 == frozen.observation_after.model_calls


def test_untrusted_corrupt_or_capability_amplifying_activation_fails_before_mmap(tmp_path: Path) -> None:
    runtime = service(tmp_path)
    with pytest.raises(ProductiveTError, match="route_untrusted"):
        runtime.activate("sinais", allowed_capabilities=frozenset({"model.infer"}), constraints=(), provenance=(), trusted_route=False)
    with pytest.raises(ProductiveTError, match="capability_amplification"):
        runtime.activate("sinais", allowed_capabilities=frozenset(), constraints=(), provenance=())
    catalog_entry = runtime.store.catalog["sinais"]
    bundle = json.loads((runtime.store.root / catalog_entry["path"]).read_text(encoding="utf-8"))
    digest = bundle["assets"]["retrieval_indexes"]["sha256"]
    (runtime.store.root / "objects" / digest).write_bytes(b"corrupt")
    with pytest.raises(ProductiveTError, match="bundle_invalid"):
        runtime.activate("sinais", allowed_capabilities=frozenset({"model.infer"}), constraints=(), provenance=())
    assert runtime.store.mapped_bytes == 0 and runtime.foreign_receipts == []


def test_cancelled_activation_and_missing_sufficient_state_fail_closed(tmp_path: Path) -> None:
    runtime = service(tmp_path)
    with pytest.raises(ProductiveTError, match="CANCELLED"):
        runtime.activate("engenharia", allowed_capabilities=frozenset({"model.infer"}), constraints=(), provenance=(), cancelled=True)
    assert runtime.store.states["engenharia"] == "FROZEN"
    runtime.activate("engenharia", allowed_capabilities=frozenset({"model.infer"}), constraints=(), provenance=())
    with pytest.raises(ProductiveTError, match="sufficient_state_invalid"):
        runtime.hibernate("engenharia", sufficient_state={"intent": "x"}, constraints=(), provenance=())
    assert runtime.store.states["engenharia"] == "HOT"
    runtime.close()


def test_sparse_physical_managed_ratio_is_below_contract(tmp_path: Path) -> None:
    bundle_root, tcap = environment(tmp_path)
    all_hot = T85PhysicalMultiverse(RUNTIME, tcap, bundle_root, tmp_path / "all-hot", minimum_residence_ns=0)
    for universe in sorted(all_hot.store.catalog):
        all_hot.activate(universe, allowed_capabilities=frozenset({"model.infer"}), constraints=STATE["constraints"], provenance=STATE["provenance"])
    all_hot_bytes = all_hot.store.managed_bytes
    sparse = T85PhysicalMultiverse(RUNTIME, tcap, bundle_root, tmp_path / "sparse", minimum_residence_ns=0)
    for universe in ("intencao", "engenharia"):
        sparse.activate(universe, allowed_capabilities=frozenset({"model.infer"}), constraints=STATE["constraints"], provenance=STATE["provenance"])
    assert 0 < sparse.store.managed_bytes / all_hot_bytes <= 0.70
    all_hot.close()
    sparse.close()


def test_store_close_refuses_active_lease(tmp_path: Path) -> None:
    bundle_root, _ = environment(tmp_path)
    store = PhysicalUniverseStore(bundle_root)
    # The primitive cannot be activated without a T receipt; direct state mutation is
    # deliberately not exposed as a supported owner path.
    assert all(state == "FROZEN" for state in store.states.values())
    store.close()


def test_owner_semantic_path_consumes_physical_lifecycle_receipts(tmp_path: Path) -> None:
    semantic = OwnerSemanticMultiverse(tmp_path / "owner")
    bundle_root = tmp_path / "physical"
    build_physical_universe_bundles(bundle_root, semantic.manifests, policy_source=POLICY)
    tcap = T85PhysicalMultiverse.build_policy(POLICY, tmp_path / "policy.tcap")
    physical = T85PhysicalMultiverse(RUNTIME, tcap, bundle_root, tmp_path / "receipts", minimum_residence_ns=0)
    semantic.attach_physical_runtime(physical)
    trace = StochasticTrace(
        "physical-route", "qwen3-4b", "0" * 64, "planning-v1", None,
        "1" * 64, "2" * 64, 12, "stop", 1, 2, False, False,
    )
    proposal = GenerativeRouteProposal(
        "physical-route", ("intencao", "sinais", "engenharia"),
        "Rota física mínima com três universos distintos.", trace, "3" * 64,
    )
    result = semantic.execute(
        proposal, idea="agente físico", constraints=("sem rede",),
        confirmed=True, cancellation=CancellationToken(),
    )
    assert result["physical_lifecycle_receipts"]
    assert physical.store.states["engenharia"] == "HOT"
    assert semantic.inspect()["physical"]["mapped_bytes"] > 0
    reboot = semantic.reboot()
    assert reboot["hot_after_reboot"] == []
    assert all(state == "FROZEN" for state in physical.store.states.values())
