from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from casulo.product.math_boundary import (
    DenseSignedCosine,
    SparseSignedCosine,
    mathematical_boundary_inventory,
    profile_similarity_kernels,
    verify_similarity_equivalence,
)


def test_sparse_kernel_is_exact_for_empty_collision_and_typical_cases() -> None:
    cases = (
        (set(), set()),
        ({"saturno", "azul"}, {"saturno", "azul"}),
        ({"casulo", "intenção", "engenharia"}, {"casulo", "memória"}),
        ({f"token-{index}" for index in range(128)}, {f"token-{index}" for index in range(64, 192)}),
    )
    receipt = verify_similarity_equivalence(cases)
    assert receipt.passed
    assert receipt.max_absolute_difference == 0.0
    assert len(receipt.receipt_hash) == 64


def test_sparse_kernel_reduces_logical_zero_traffic_and_profile_is_not_science() -> None:
    profile = profile_similarity_kernels(rounds=3, repetitions=10)
    assert profile.classification == "SHORT_PRODUCT_DIAGNOSTIC_NOT_SCIENTIFIC_BENCHMARK"
    assert profile.traffic_reduced
    assert profile.candidate_logical_slots < profile.reference_logical_slots
    assert profile.reference_median_ns > 0 and profile.candidate_median_ns > 0


def test_boundary_inventory_refuses_matrix_replacement_claim() -> None:
    inventory = mathematical_boundary_inventory()
    boundaries = {item["id"]: item for item in inventory["boundaries"]}
    assert boundaries["owner-neural-inference"]["authority"].startswith("FOREIGN_NUMERICAL")
    assert boundaries["historical-tensor-stack"]["authority"] == "RESEARCH_STACK_NOT_OWNER_RUNTIME_PATH"
    assert any("T replaces Qwen" in claim for claim in inventory["forbidden_claims"])


def test_dense_and_sparse_runtime_contracts_reject_mixed_prepared_values() -> None:
    dense, sparse = DenseSignedCosine(), SparseSignedCosine()
    dense_value = dense.prepare({"casulo"})
    sparse_value = sparse.prepare({"casulo"})
    try:
        dense.cosine(dense_value, sparse_value)
    except TypeError:
        pass
    else:
        raise AssertionError("kernel denso aceitou representação esparsa")
    try:
        sparse.cosine(sparse_value, dense_value)
    except TypeError:
        pass
    else:
        raise AssertionError("kernel esparso aceitou representação densa")
