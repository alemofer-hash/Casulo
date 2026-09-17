from __future__ import annotations

from dataclasses import replace

import pytest

from casulo.livelab.workload_adapters import (
    AdapterStatus,
    compare_equivalence,
    run_smoke_adapter,
)
from casulo.livelab.workloads import (
    canonical_catalog_bytes,
    catalog_sha256,
    generate_workload,
    get_workload,
    workload_specs,
)


SPEC_HASHES = {
    "flood-surrogate-historical": "778dfcba2eb0c12aefa4bfa9241c045e9d42e5e00f6c5510b9c37f8895e4a46f",
    "mlp-small": "bf3a61f47f836ff7ce1fdfc90fe0d2e7af7eae557cc6c2e5f103dbe1962d67db",
    "mlp-medium": "c5cb302fce78fd3c1e421ac13d22779c16f8e9c3cc64d7fe3a384a3e8bc184ab",
    "mlp-large": "ab8b33756203f4d8ef39582519d0876b9bacd2c1f5a05be417554ed77abe5afe",
    "cnn-small": "ba0ff782dc08147794e331e81d1a11c31712c4fe4ea4de22ed6559debf26c8dd",
    "attention-compact": "9e21609f3c3fe14f9ee780b02c3c24bc844226525fdcb46fa4954e9b8129dfcf",
    "dynamic-length": "1a7126e26e65e940eee4bda42a4cc9530cbf54815dcbb9aa9097baece3b300c9",
    "t-unfavorable-opaque-branch": "730ea0e5ead94f7291ecdfc309e1e81fd626932bca185b949edae9e57314376a",
    "flow-residual-interference": "ef4ef435c527dfca4f16b37b5d3f4f44703269e7f913b39ff6a6aa21afc717be",
}

SMOKE_DATA_HASHES = {
    "flood-surrogate-historical": "c91e16aefa15a8473c24eab1f803c9853d351232140ca15d0b00f3d4e1806cec",
    "mlp-small": "194b978410595595b032404b2f021cae152aa3b81e4012aa310a84512a5e35c9",
    "mlp-medium": "54aef959e246743e0ccdf750de34e4602ce9c8e673bc9becb939d66b42aaa3d4",
    "mlp-large": "43c5f80e3972daaa93e2f2af56d847753df4f5417726e02ff7aca33e62b6b0fc",
    "cnn-small": "58f7b8dcf2b1be21ddc35d75ba57b65ef923450a69e27a17065681dff5e67b37",
    "attention-compact": "d63e51f8392ddd453cd599923b6c8180e92adcbbdb08a32e923b35458f1aab5a",
    "dynamic-length": "80b7120b8e2cf2968cae511ae6912832300fbf1d5abccf2583f0e16f3c5f8238",
    "t-unfavorable-opaque-branch": "44e1aa06f8d1a53c6ab0d984d5f37d975720f571cfdee760ab7337fc91f35325",
    "flow-residual-interference": "f65650331595d8c7af36e01679a8e33fb560a09000657acfca0eeb5ea78cf746",
}


def test_registry_freezes_all_declared_workloads_and_golden_hashes() -> None:
    specs = workload_specs()
    assert {item.workload_id for item in specs} == set(SPEC_HASHES)
    assert {item.workload_id: item.sha256 for item in specs} == SPEC_HASHES
    assert {
        item.workload_id: generate_workload(item).sha256 for item in specs
    } == SMOKE_DATA_HASHES
    assert catalog_sha256() == "405b98f3caf3045e74bd301c0f00250d9f3ff1f330ae9b1d4399c466e895dc5b"
    assert canonical_catalog_bytes().startswith(
        b'{"protocol":"casulo-livelab-workload-catalog/1.0"'
    )


def test_generation_is_repeatable_and_does_not_mutate_specs() -> None:
    for spec in workload_specs():
        first = generate_workload(spec)
        second = generate_workload(spec)
        assert first == second
        assert first.profile == "smoke"
        assert spec.smoke["not_a_performance_campaign"] is True


@pytest.mark.parametrize("workload", tuple(SPEC_HASHES))
def test_numpy_semantic_smoke_is_bounded_and_executable(workload: str) -> None:
    result = run_smoke_adapter("numpy-semantic", workload)
    assert result.status is AdapterStatus.PASS
    assert result.output_count > 0
    assert result.output_sha256 is not None
    assert result.details["performance_measured"] is False
    assert result.details["profile"] == "bounded-smoke"


def test_pytorch_full_step_matches_numpy_for_frozen_dense_scope() -> None:
    pytest.importorskip("torch")
    spec = get_workload("mlp-small")
    reference = run_smoke_adapter("numpy-semantic", spec)
    candidate = run_smoke_adapter("pytorch-eager", spec)
    comparison = compare_equivalence(reference, candidate, spec)
    assert candidate.status is AdapterStatus.PASS
    assert comparison.status is AdapterStatus.PASS
    assert comparison.maximum_absolute_error is not None


def test_adapters_fail_closed_on_different_semantic_scope() -> None:
    spec = get_workload("cnn-small")
    reference = run_smoke_adapter("numpy-semantic", spec)
    candidate = replace(reference, semantic_scope=("forward", "backward"))
    comparison = compare_equivalence(reference, candidate, spec)
    assert comparison.status is AdapterStatus.FAIL
    assert "scope" in comparison.reason


@pytest.mark.parametrize(
    "adapter",
    ("pytorch-compile", "native-c-no-t", "historical-t-c99", "t-general-ir-tcap"),
)
def test_toolchain_adapters_require_explicit_opt_in(adapter: str) -> None:
    result = run_smoke_adapter(adapter, "flood-surrogate-historical")
    assert result.status is AdapterStatus.UNAVAILABLE
    assert result.output_sha256 is None
    assert result.details["performance_measured"] is False


def test_unsupported_backend_is_unavailable_not_silently_substituted() -> None:
    result = run_smoke_adapter("historical-t-c99", "attention-compact", allow_toolchain=True)
    assert result.status is AdapterStatus.UNAVAILABLE
    assert "only equivalent" in result.details["reason"]


def test_historical_campaign_delegates_to_original_dataset_generator() -> None:
    pytest.importorskip("numpy")
    spec = get_workload("flood-surrogate-historical")
    data = generate_workload(spec, profile="campaign")
    assert data.seed == 20260730
    assert data.shape("inputs") == (1024, 8)
    assert data.value("inputs")[:3] == pytest.approx(
        (1.3463107566844281, 1.170108066319003, -0.05259633448885206),
        rel=0,
        abs=0,
    )
