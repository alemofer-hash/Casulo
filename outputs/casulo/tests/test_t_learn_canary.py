from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from casulo.t import check_file
from casulo.t.learn_canary import (
    CANARY_HEADER,
    LearnCanaryError,
    build_flood_canary,
    execute_audit,
    execute_scalar,
    parse_flood_canary,
    verify_canary_oracle,
)
from casulo.t.learn_native import lower_learn_native


EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "t"
    / "flood_surrogate_training.t"
)


def _canary():
    checked = check_file(EXAMPLE)
    assert checked.ir is not None and checked.graph is not None
    return build_flood_canary(lower_learn_native(checked.ir, checked.graph))


def test_canary_is_byte_deterministic_and_round_trips() -> None:
    first = _canary().to_bytes()
    second = _canary().to_bytes()
    assert first == second
    assert len(first) == 1952
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    parsed = parse_flood_canary(first)
    assert parsed.to_bytes() == first
    assert parsed.records == 8
    assert parsed.input_features == parsed.hidden_features == 8
    assert parsed.parameter_count == 81


def test_independent_oracle_matches_declared_float64_loop_order() -> None:
    canary = _canary()
    literal = execute_scalar(
        inputs=canary.inputs,
        targets=canary.targets,
        initial_parameters=canary.initial_parameters,
        records=canary.records,
        input_features=canary.input_features,
        hidden_features=canary.hidden_features,
        epochs=canary.epochs,
        learning_rate=canary.learning_rate,
    )
    audit = execute_audit(canary)
    assert struct.pack("<d", literal.initial_loss) == struct.pack("<d", audit.initial_loss)
    assert struct.pack("<d", literal.final_loss) == struct.pack("<d", audit.final_loss)
    assert b"".join(struct.pack("<d", x) for x in literal.parameters) == b"".join(
        struct.pack("<d", x) for x in audit.parameters
    )
    result = verify_canary_oracle(canary)
    assert result["max_abs_parameter_difference"] == 0.0
    assert result["initial_loss"] > result["target_loss"]
    assert result["final_loss"] <= result["target_loss"]


@pytest.mark.parametrize("cut", [0, CANARY_HEADER.size - 1, CANARY_HEADER.size, -1])
def test_canary_truncation_is_rejected(cut: int) -> None:
    raw = _canary().to_bytes()
    with pytest.raises(LearnCanaryError):
        parse_flood_canary(raw[:cut])


def test_canary_tampered_expectation_is_rejected_by_oracle() -> None:
    raw = bytearray(_canary().to_bytes())
    # The last scalar is an expected final parameter; TCAP integrity protects
    # this in production, while the oracle independently protects semantics.
    raw[-1] ^= 1
    tampered = parse_flood_canary(bytes(raw))
    with pytest.raises(LearnCanaryError, match="audit oracle differs"):
        verify_canary_oracle(tampered)
