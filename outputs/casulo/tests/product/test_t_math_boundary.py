from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from casulo.product.math_boundary import (
    DenseSignedCosine,
    SparseSignedCosine,
    profile_similarity_kernels,
    verify_similarity_equivalence,
)
from casulo_owner.math_boundary import OwnerMathBoundary, select_safe_reference_when_t_unavailable


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
POLICY = ROOT / "private/casulo-owner/t-v2/math-boundary-policy.t"


def _boundary(tmp_path: Path, source: Path = POLICY) -> OwnerMathBoundary:
    tcap = OwnerMathBoundary.build_policy(source, tmp_path / "policy.tcap")
    return OwnerMathBoundary(RUNTIME, tcap, tmp_path / "receipts")


def test_t_is_the_adoption_authority_and_candidate_result_is_consumed(tmp_path: Path) -> None:
    profile = replace(profile_similarity_kernels(rounds=3, repetitions=5), candidate_wins=True)
    selection = _boundary(tmp_path).decide(verify_similarity_equivalence(), profile)
    assert selection.specialized_adopted
    assert selection.selected_kernel == SparseSignedCosine.kernel_id
    assert isinstance(selection.kernel(), SparseSignedCosine)
    assert selection.t_call is not None
    assert selection.t_call.receipt["foreign_calls"] == []
    assert (tmp_path / "receipts/math.boundary.00000001.selection.json").is_file()


def test_t_denial_preserves_reference_without_affirmative_recomputation(tmp_path: Path) -> None:
    profile = replace(profile_similarity_kernels(rounds=3, repetitions=5), candidate_wins=False)
    selection = _boundary(tmp_path).decide(verify_similarity_equivalence(), profile)
    assert not selection.specialized_adopted
    assert selection.selected_kernel == DenseSignedCosine.kernel_id
    assert "candidate_did_not_win" in selection.reason
    assert selection.t_call is not None and not selection.t_call.passed


def test_mutating_t_policy_changes_the_product_decision(tmp_path: Path) -> None:
    source = POLICY.read_text(encoding="utf-8").replace(
        'return ok "ADOPT_SPECIALIZED"',
        'return error "mutated_policy_denied"',
    )
    mutated = tmp_path / "mutated-policy.t"
    mutated.write_text(source, encoding="utf-8")
    profile = replace(profile_similarity_kernels(rounds=3, repetitions=5), candidate_wins=True)
    selection = _boundary(tmp_path / "mutated", mutated).decide(verify_similarity_equivalence(), profile)
    assert not selection.specialized_adopted
    assert selection.selected_kernel == DenseSignedCosine.kernel_id
    assert selection.reason == "T_DENIED:mutated_policy_denied"


def test_missing_t_never_grants_specialized_kernel() -> None:
    selection = select_safe_reference_when_t_unavailable(FileNotFoundError("runtime"))
    assert not selection.specialized_adopted
    assert selection.selected_kernel == DenseSignedCosine.kernel_id
    assert selection.t_call is None
    assert selection.reason.startswith("T_UNAVAILABLE_REFERENCE_FALLBACK")


def test_owner_launcher_qualifies_math_kernel_without_starting_model_or_vm(tmp_path: Path) -> None:
    from tools.casulo_semantic_multiverse_vm_inspect import prepare_owner_math_kernel

    selection = prepare_owner_math_kernel(ROOT, tmp_path)
    assert selection.selected_kernel in {DenseSignedCosine.kernel_id, SparseSignedCosine.kernel_id}
    assert selection.equivalence["passed"] is True
    assert selection.profile["classification"] == "SHORT_PRODUCT_DIAGNOSTIC_NOT_SCIENTIFIC_BENCHMARK"
    if selection.specialized_adopted:
        assert selection.t_call is not None and selection.t_call.passed
