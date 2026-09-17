from __future__ import annotations

import os
from pathlib import Path

import pytest

from casulo.t.productive import ProductiveTError
from casulo.t.v2_tcap import TcapV2Builder
from casulo_owner.t85_authority import T85AuthorityDenied, T85OwnerCriticalAuthority


ROOT = Path(__file__).resolve().parents[2]
SOURCES = tuple(sorted((ROOT / "private/casulo-owner/t-v2").glob("critical-*.t")))
RUNTIME = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")


def build(tmp_path: Path, sources: tuple[Path, ...] = SOURCES) -> Path:
    return TcapV2Builder().build(
        sources,
        tmp_path / "owner-critical.tcap",
        entry_module="owner.critical.intent",
        entry_function="decide",
        tests={"properties": ["critical_T_only", "hard_unknown_blocks", "publish_requires_human"]},
        foreign_boundaries=({"name": "manifest_writer", "kind": "foreign_primitive", "decision_authority": False},),
    ).directory


def valid() -> dict:
    return {
        "decision_id": "case01",
        "creation_id": "holdout01",
        "model_proposed": True,
        "human_confirmed": True,
        "material": True,
        "requested_capabilities": ("manifest",),
        "granted_capabilities": ("manifest",),
        "consent_valid": True,
        "graph_schema": "casulo.requirement-graph/2.0",
        "graph_version": 1,
        "project_id": "project01",
        "candidate_project_id": "project01",
        "hard_requirement_ids": ("hard01", "hard02"),
        "expected_evidence_tokens": ("a" * 64, "b" * 64),
        "observed_evidence_tokens": ("a" * 64, "b" * 64),
        "evidence_plan_hash": "c" * 64,
        "safety_pass": True,
        "unsupported_claims": (),
        "simulation_status": "PASS",
        "human_publish_approval": True,
    }


def authority(tmp_path: Path, sources: tuple[Path, ...] = SOURCES) -> T85OwnerCriticalAuthority:
    return T85OwnerCriticalAuthority(RUNTIME, build(tmp_path, sources), tmp_path / "calls")


def test_four_critical_surfaces_are_decided_by_t_and_consumed(tmp_path: Path) -> None:
    called: list[str] = []
    result = authority(tmp_path).authorize_and_execute(
        lambda decisions: called.append(decisions.publish.receipt["receipt_hash"]) or "published",
        **valid(),
    )
    assert result.value == "published"
    assert called == [result.decisions.receipt_chain[-1]]
    assert result.decisions.committed
    assert [
        result.decisions.intent.receipt["surface_id"],
        result.decisions.capabilities.receipt["surface_id"],
        result.decisions.fulfillment.receipt["surface_id"],
        result.decisions.publish.receipt["surface_id"],
    ] == ["material_intent", "capabilities_effects", "hard_requirement_fulfillment", "publish_commit"]
    assert all(item.receipt["runtime_id"] == "t-runtime/rust-2.0" for item in (
        result.decisions.intent, result.decisions.capabilities,
        result.decisions.fulfillment, result.decisions.publish,
    ))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"human_confirmed": False}, "human_confirmation_required"),
        ({"granted_capabilities": ()}, "capability_not_granted"),
        ({"observed_evidence_tokens": ("a" * 64, "d" * 64)}, "hard_requirement_not_pass"),
        ({"candidate_project_id": "project02"}, "project_scope_mismatch"),
        ({"safety_pass": False}, "safety_gate_failed"),
        ({"unsupported_claims": ("solver geral",)}, "unsupported_claim_present"),
        ({"simulation_status": "FAIL"}, "simulation_pass_required"),
        ({"human_publish_approval": False}, "publish_human_approval_required"),
        ({"cancelled": True}, "CANCELLED"),
    ],
)
def test_each_negative_decision_fails_before_foreign_effect(tmp_path: Path, change: dict, message: str) -> None:
    inputs = {**valid(), **change}
    called = False

    def primitive(_decisions):
        nonlocal called
        called = True

    with pytest.raises(T85AuthorityDenied, match=message):
        authority(tmp_path).authorize_and_execute(primitive, **inputs)
    assert called is False


def test_mutating_t_source_changes_the_product_decision(tmp_path: Path) -> None:
    changed: list[Path] = []
    for source in SOURCES:
        destination = tmp_path / source.name
        text = source.read_text(encoding="utf-8")
        if source.name == "critical-intent.t":
            text = text.replace('return ok "MATERIAL"', 'return error "mutated_policy_denied"')
        destination.write_text(text, encoding="utf-8", newline="\n")
        changed.append(destination)
    with pytest.raises(T85AuthorityDenied, match="mutated_policy_denied"):
        authority(tmp_path / "mutated", tuple(changed)).decide(**valid())


def test_missing_runtime_or_tcap_has_no_python_fallback(tmp_path: Path) -> None:
    with pytest.raises(ProductiveTError, match="runtime T"):
        T85OwnerCriticalAuthority(tmp_path / "missing-runtime", tmp_path / "missing-tcap", tmp_path / "calls")
    with pytest.raises(Exception):
        T85OwnerCriticalAuthority(RUNTIME, tmp_path / "missing-tcap", tmp_path / "calls2")


def test_critical_sources_are_not_decorative_or_literal_emitters() -> None:
    joined = "\n".join(source.read_text(encoding="utf-8") for source in SOURCES)
    assert "emit_literal" not in joined
    assert "emit " not in joined
    assert "return ok" in joined
    assert joined.count("requires ") >= 12
    assert "request effect manifest" in joined
