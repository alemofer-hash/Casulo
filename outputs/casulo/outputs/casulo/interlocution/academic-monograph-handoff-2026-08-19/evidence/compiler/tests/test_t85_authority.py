from __future__ import annotations

from pathlib import Path

import pytest

from casulo.t.authority import (
    AuthorityAudit,
    AuthorityError,
    AuthoritySurface,
    DecisionTrace,
    TDecisionReceipt,
    canonical_sha256,
)


ZERO = "0" * 64


def trace(**changes: object) -> DecisionTrace:
    values: dict[str, object] = {
        "surface_id": "publish_commit",
        "decision_id": "decision:1",
        "t_runtime_executed": True,
        "t_result_consumed": True,
        "foreign_recomputed": False,
        "productive_fallback": False,
        "clean_release_trace": True,
        "mutation_changes_decision": True,
        "bypass_fails_closed": True,
        "execution_is_nontrivial_t": True,
    }
    values.update(changes)
    return DecisionTrace(**values)  # type: ignore[arg-type]


def test_degree_one_requires_causal_mutation_and_bypass() -> None:
    assert trace().degree() == 1.0
    assert trace(mutation_changes_decision=False).degree() == 0.75
    assert trace(bypass_fails_closed=False).degree() == 0.75


def test_decorative_shadow_and_foreign_recomputation_never_count_as_authority() -> None:
    assert trace(t_runtime_executed=False).degree() == 0.0
    assert trace(t_result_consumed=False).degree() == 0.25
    assert trace(foreign_recomputed=True).degree() == 0.5


def test_empty_ret_or_emit_literal_gets_no_execution_credit() -> None:
    assert trace(execution_is_nontrivial_t=False).execution_credit == 0.0


def test_audit_uses_frozen_weights_and_critical_coverage() -> None:
    surfaces = (
        AuthoritySurface("publish_commit", 8, True),
        AuthoritySurface("interface_state", 2, False),
    )
    audit = AuthorityAudit(
        surfaces,
        (trace(), trace(surface_id="interface_state", decision_id="decision:2", t_runtime_executed=False)),
    )
    assert audit.authority_score == pytest.approx(0.8)
    assert audit.execution_score == pytest.approx(0.8)
    assert audit.critical_coverage == 1.0


def test_receipt_is_hashed_inside_identified_t_runtime() -> None:
    receipt = TDecisionReceipt(
        decision_id="decision:1",
        surface_id="publish_commit",
        scope_id="creation:1",
        t_source_hash=ZERO,
        t_ir_hash=ZERO,
        tcap_hash=ZERO,
        runtime_function="publish::decide",
        canonical_input_hash=canonical_sha256({"ready": True}),
        canonical_output_hash=canonical_sha256({"result": "PUBLISH"}),
        effects_requested=("manifest",),
        grants_consumed=(),
        foreign_calls=(),
        result="PUBLISH",
        previous_receipt_hash=ZERO,
        monotonic_timestamp_ns=1,
        runtime_id="t-runtime/reference-2.0",
    )
    assert receipt.to_dict()["receipt_hash"] == receipt.receipt_hash
    assert len(receipt.receipt_hash) == 64


def test_receipt_rejects_posthoc_python_identity() -> None:
    with pytest.raises(AuthorityError):
        TDecisionReceipt(
            "d", "publish_commit", "c", ZERO, ZERO, ZERO, "publish::decide",
            ZERO, ZERO, (), (), (), "PUBLISH", ZERO, 1, "python-wrapper/1.0"
        )
