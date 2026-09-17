from __future__ import annotations

import json
from pathlib import Path

import pytest

from casulo.t.v2_tcap import verify_tcap_v2
from interlocution.authority import InterlocutionAuthorityDenied, TrainingAuthority
from interlocution.contracts import (
    ContractError,
    build_confirmed_intent,
    build_requirement_graph,
    build_training_authority_plan,
    canonical_sha256,
    validate_confirmed_intent,
)
from interlocution.policy import POLICY_SURFACES, compile_training_authority_tcap


ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"


def documents():
    confirmation = canonical_sha256({"event": "explicit user goal", "confirmed": True})
    intent = build_confirmed_intent(
        campaign_id="test-campaign",
        dataset_sha256="a" * 64,
        initialization_sha256="b" * 64,
        confirmation_event_sha256=confirmation,
    )
    graph = build_requirement_graph(intent)
    return intent, graph, build_training_authority_plan(intent, graph)


def capabilities():
    return {
        "float64_supported": True,
        "mse_supported": True,
        "sgd_supported": True,
        "reset_supported": True,
        "no_cross_case_state": True,
        "selection_supported": True,
        "fixed_epoch_supported": True,
        "counter_supported": True,
        "independent_verifier_available": True,
        "publisher_requires_t": True,
    }


def test_intent_graph_and_plan_are_transitively_sealed() -> None:
    intent, graph, plan = documents()
    assert plan["intent_sha256"] == intent["intent_sha256"]
    assert plan["requirement_graph_sha256"] == graph["graph_sha256"]
    assert len(plan["decisions"]) == 9
    changed = json.loads(json.dumps(intent))
    changed["training"]["epochs"] = 399
    with pytest.raises(ContractError, match="does not seal"):
        validate_confirmed_intent(changed)


def test_general_t2_pipeline_compiles_all_nine_surfaces(tmp_path: Path) -> None:
    _, _, plan = documents()
    build = compile_training_authority_tcap(plan, tmp_path / "sources", tmp_path / "policy.tcap")
    root, manifest, typed = verify_tcap_v2(build.directory)
    assert root == build.directory
    assert manifest["tcap_hash"] == build.tcap_hash
    assert len(typed["modules"]) == 9
    assert {item["module"] for item in typed["modules"]} == {
        "research.interlocution.dataset",
        "research.interlocution.initialization",
        "research.interlocution.precision",
        "research.interlocution.loss",
        "research.interlocution.update",
        "research.interlocution.optimizer_state",
        "research.interlocution.working_set",
        "research.interlocution.stopping",
        "research.interlocution.judgment",
    }


@pytest.mark.skipif(not RUNTIME.is_file(), reason="real T runtime unavailable")
def test_nine_t_results_are_consumed_without_affirmative_fallback(tmp_path: Path) -> None:
    _, _, plan = documents()
    build = compile_training_authority_tcap(plan, tmp_path / "sources", tmp_path / "policy.tcap")
    authority = TrainingAuthority(RUNTIME, build.directory, tmp_path / "calls")
    grant = authority.authorize(
        dataset_sha256="a" * 64,
        records=1024,
        input_features=8,
        initialization_sha256="b" * 64,
        cases_unique=True,
        nonces_unique=True,
        capabilities=capabilities(),
    )
    assert len(grant.calls) == 9
    assert tuple(item.receipt["surface_id"] for item in grant.calls) == POLICY_SURFACES
    assert grant.config["dtype"] == "float64"
    assert grant.config["epochs"] == "400"
    assert grant.config["dataset_sha256"] == "a" * 64


@pytest.mark.skipif(not RUNTIME.is_file(), reason="real T runtime unavailable")
def test_t_rejects_tampered_dataset_before_foreign_work(tmp_path: Path) -> None:
    _, _, plan = documents()
    build = compile_training_authority_tcap(plan, tmp_path / "sources", tmp_path / "policy.tcap")
    authority = TrainingAuthority(RUNTIME, build.directory, tmp_path / "calls")
    with pytest.raises(InterlocutionAuthorityDenied, match="dataset_hash_mismatch"):
        authority.authorize(
            dataset_sha256="c" * 64,
            records=1024,
            input_features=8,
            initialization_sha256="b" * 64,
            cases_unique=True,
            nonces_unique=True,
            capabilities=capabilities(),
        )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="real T runtime unavailable")
def test_t_judge_fails_closed_on_unknown_or_missing_evidence(tmp_path: Path) -> None:
    _, _, plan = documents()
    build = compile_training_authority_tcap(plan, tmp_path / "sources", tmp_path / "policy.tcap")
    authority = TrainingAuthority(RUNTIME, build.directory, tmp_path / "calls")
    grant = authority.authorize(
        dataset_sha256="a" * 64,
        records=1024,
        input_features=8,
        initialization_sha256="b" * 64,
        cases_unique=True,
        nonces_unique=True,
        capabilities=capabilities(),
    )
    with pytest.raises(InterlocutionAuthorityDenied, match="equivalence_not_pass"):
        authority.judge({}, previous_receipt_hash=grant.receipt_chain[-1])

