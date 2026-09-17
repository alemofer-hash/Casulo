from __future__ import annotations

import pytest

from casulo.t.resource import ResourceContract, SemanticClass


def valid_contract() -> ResourceContract:
    return ResourceContract(
        memory_limit_bytes=1 << 20,
        arena_bytes=1 << 18,
        max_threads=2,
        semantic_class=SemanticClass.FLOW,
        deterministic=True,
        numerical_precision="float64",
        permissions=("memory", "console"),
        quality_definition={"protocol": "casulo-equivalence/1", "max_abs": 1e-12},
        residual_routing={"audit": "ATTRACTOR_AUDIT", "invalid": "QUARANTINE"},
    )


def test_resource_contract_round_trip() -> None:
    contract = valid_contract()
    assert ResourceContract.from_dict(contract.to_dict()) == contract


@pytest.mark.parametrize(
    "field,value",
    [("memory_limit_bytes", 0), ("arena_bytes", 2 << 20), ("max_threads", 0), ("numerical_precision", "magic")],
)
def test_invalid_bounds_are_rejected(field: str, value: object) -> None:
    data = valid_contract().to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        ResourceContract.from_dict(data)


def test_unknown_permission_is_rejected() -> None:
    data = valid_contract().to_dict()
    data["permissions"] = ["memory", "host-disk"]
    with pytest.raises(ValueError, match="unknown permissions"):
        ResourceContract.from_dict(data)

