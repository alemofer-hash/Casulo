from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any, Mapping


RESULT_HEADER = struct.Struct("<8sII")
RESULT_CASE = struct.Struct("<IIQ32s6Qdd")
PARAMETERS = 81
RECORDS = 1024


class EquivalenceFailure(ValueError):
    pass


def parse_numeric_results(path: str | Path) -> tuple[dict[str, Any], ...]:
    raw = Path(path).read_bytes()
    if len(raw) < RESULT_HEADER.size:
        raise EquivalenceFailure("result is truncated")
    magic, count, records = RESULT_HEADER.unpack_from(raw)
    if magic != b"FWRES1\0\0" or records != RECORDS:
        raise EquivalenceFailure("result header mismatch")
    offset = RESULT_HEADER.size
    result = []
    for _ in range(count):
        if offset + RESULT_CASE.size > len(raw):
            raise EquivalenceFailure("result case header is truncated")
        fields = RESULT_CASE.unpack_from(raw, offset)
        offset += RESULT_CASE.size
        values = struct.unpack_from(f"<{PARAMETERS + RECORDS}d", raw, offset)
        offset += (PARAMETERS + RECORDS) * 8
        result.append(
            {
                "index": fields[0],
                "case_id": fields[1],
                "seed": fields[2],
                "nonce": fields[3].hex(),
                "epochs_completed": fields[4],
                "forward_epochs": fields[5],
                "backward_epochs": fields[6],
                "optimizer_steps": fields[7],
                "records_visited": fields[8],
                "parameter_writes": fields[9],
                "initial_loss": fields[10],
                "final_loss": fields[11],
                "parameters": values[:PARAMETERS],
                "predictions": values[PARAMETERS:],
            }
        )
    if offset != len(raw):
        raise EquivalenceFailure("result has trailing bytes")
    return tuple(result)


def compare_result_files(
    candidate: str | Path, reference: str | Path, *, tolerance: float
) -> dict[str, Any]:
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise EquivalenceFailure("equivalence tolerance is invalid")
    left = parse_numeric_results(candidate)
    right = parse_numeric_results(reference)
    if len(left) != len(right) or not left:
        raise EquivalenceFailure("result counts differ")
    maximum_initial = 0.0
    maximum_final = 0.0
    maximum_parameter = 0.0
    maximum_prediction = 0.0
    cases = []
    expected_counters = {
        "epochs_completed": 400,
        "forward_epochs": 400,
        "backward_epochs": 400,
        "optimizer_steps": 400,
        "records_visited": 409600,
        "parameter_writes": 32400,
    }
    for candidate_case, reference_case in zip(left, right, strict=True):
        identity_equal = all(
            candidate_case[field] == reference_case[field]
            for field in ("index", "case_id", "seed", "nonce")
        )
        counters_equal = all(
            candidate_case[field] == reference_case[field] == expected
            for field, expected in expected_counters.items()
        )
        initial = abs(candidate_case["initial_loss"] - reference_case["initial_loss"])
        final = abs(candidate_case["final_loss"] - reference_case["final_loss"])
        parameter = max(
            abs(a - b)
            for a, b in zip(
                candidate_case["parameters"], reference_case["parameters"], strict=True
            )
        )
        prediction = max(
            abs(a - b)
            for a, b in zip(
                candidate_case["predictions"], reference_case["predictions"], strict=True
            )
        )
        finite = all(
            math.isfinite(value)
            for value in (
                candidate_case["initial_loss"],
                candidate_case["final_loss"],
                *candidate_case["parameters"],
                *candidate_case["predictions"],
            )
        )
        passed = (
            identity_equal
            and counters_equal
            and finite
            and initial <= tolerance
            and final <= tolerance
            and parameter <= tolerance
            and prediction <= tolerance
        )
        cases.append(
            {
                "case_id": candidate_case["case_id"],
                "identity_equal": identity_equal,
                "counters_equal": counters_equal,
                "finite": finite,
                "initial_loss_abs_difference": initial,
                "final_loss_abs_difference": final,
                "parameter_max_abs_difference": parameter,
                "prediction_max_abs_difference": prediction,
                "optimizer_state": "STATELESS_SGD_RESET_EACH_CASE",
                "stopping_reason": "FIXED_EPOCHS_400",
                "pass": passed,
            }
        )
        maximum_initial = max(maximum_initial, initial)
        maximum_final = max(maximum_final, final)
        maximum_parameter = max(maximum_parameter, parameter)
        maximum_prediction = max(maximum_prediction, prediction)
    return {
        "schema": "casulo.interlocution-equivalence/1.0",
        "status": "PASS" if all(item["pass"] for item in cases) else "FAIL",
        "tolerance_frozen_before_execution": tolerance,
        "work_units": len(cases),
        "maximum_initial_loss_abs_difference": maximum_initial,
        "maximum_final_loss_abs_difference": maximum_final,
        "maximum_parameter_abs_difference": maximum_parameter,
        "maximum_prediction_abs_difference": maximum_prediction,
        "optimizer_state_semantics": "SGD_WITHOUT_MOMENTUM_HAS_NO_PERSISTENT_BUFFER_AND_IS_RESET_PER_CASE",
        "cases": cases,
    }

