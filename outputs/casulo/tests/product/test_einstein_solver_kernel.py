from __future__ import annotations

import pytest

from casulo_owner.einstein_solver_kernel import EinsteinSolverError, solve


def minkowski_problem() -> dict:
    return {
        "coordinates": ["t", "x", "y", "z"],
        "coordinate_point": [0.0, 0.0, 0.0, 0.0],
        "metric": [
            ["-1", "0", "0", "0"],
            ["0", "1", "0", "0"],
            ["0", "0", "1", "0"],
            ["0", "0", "0", "1"],
        ],
        "constants": {"G": 6.67430e-11, "c": 299792458.0, "Lambda": 0.0},
        "energy_momentum_tensor": [[0.0] * 4 for _ in range(4)],
        "initial_conditions": {"hypersurface": "t=0", "metric": "Minkowski"},
        "boundary_conditions": {"type": "asymptotically_flat"},
        "tolerances": {"derivative_step": 1e-5, "residual": 1e-9, "symmetry": 1e-10, "pivot": 1e-12},
        "conventions": {"signature": "-+++", "riemann": "wald", "units": "SI"},
    }


def test_minkowski_constructs_all_tensors_and_zero_residual() -> None:
    result = solve(minkowski_problem())
    assert result["status"] == "PASS"
    assert result["max_abs_residual"] == 0.0
    assert len(result["connection"]) == 4
    assert result["inverse_metric"] == [
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    assert result["ricci_scalar"] == 0.0
    assert result["real_effects_executed"] is False
    assert any("does not integrate" in item for item in result["limitations"])
    assert result["conventions"]["signature"] == "-+++"
    assert result["conventions"]["units"] == "SI"


def test_minkowski_with_lambda_matches_analytic_lambda_times_metric() -> None:
    value = minkowski_problem()
    value["constants"]["Lambda"] = 2.5
    value["tolerances"]["residual"] = 3.0
    result = solve(value)
    assert result["field_equation_residual"] == [
        [-2.5, 0.0, 0.0, 0.0],
        [0.0, 2.5, 0.0, 0.0],
        [0.0, 0.0, 2.5, 0.0],
        [0.0, 0.0, 0.0, 2.5],
    ]
    assert result["max_abs_residual"] == 2.5


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_stress_energy_is_rejected(bad: float) -> None:
    value = minkowski_problem()
    value["energy_momentum_tensor"][0][0] = bad
    with pytest.raises(EinsteinSolverError, match="finite"):
        solve(value)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("tolerances", "derivative_step", 0.0),
        ("tolerances", "derivative_step", -1.0),
        ("tolerances", "residual", 0.0),
        ("conventions", "signature", "+---"),
        ("conventions", "units", "geometric"),
    ],
)
def test_invalid_step_tolerance_or_convention_is_rejected(section, key, value) -> None:
    problem = minkowski_problem()
    problem[section][key] = value
    with pytest.raises(EinsteinSolverError):
        solve(problem)


def test_incompatible_stress_energy_shape_is_rejected() -> None:
    value = minkowski_problem()
    value["energy_momentum_tensor"] = [[0.0] * 3 for _ in range(3)]
    with pytest.raises(EinsteinSolverError, match="4x4"):
        solve(value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(coordinates=["t", "x", "y"]),
        lambda value: value["metric"][1].__setitem__(0, "1"),
        lambda value: value.update(metric=[["0"] * 4 for _ in range(4)]),
        lambda value: value["metric"][0].__setitem__(0, "__import__('os').system('whoami')"),
        lambda value: value.pop("boundary_conditions"),
    ],
)
def test_solver_refuses_unsupported_or_unsafe_inputs(mutation) -> None:
    value = minkowski_problem()
    mutation(value)
    with pytest.raises(EinsteinSolverError):
        solve(value)
