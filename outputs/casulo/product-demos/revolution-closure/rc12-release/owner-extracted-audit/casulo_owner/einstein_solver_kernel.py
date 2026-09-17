"""Pure-Python local Einstein tensor/residual evaluator.

This is deliberately a bounded local differential-geometry kernel, not a claim
to solve arbitrary global Einstein PDEs.  It evaluates a user-declared 4D
metric and stress-energy tensor at one coordinate point using central finite
differences, then constructs Christoffel symbols, Ricci, scalar curvature,
Einstein tensor and the field-equation residual.
"""

from __future__ import annotations

import ast
import json
import math
import sys
from dataclasses import dataclass
from typing import Any, Callable


class EinsteinSolverError(ValueError):
    pass


_FUNCTIONS: dict[str, Callable[..., float]] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "exp": math.exp,
    "log": math.log,
    "sqrt": math.sqrt,
    "sinh": math.sinh,
    "cosh": math.cosh,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}
_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}


def _expression(source: str, variables: dict[str, float]) -> float:
    if not isinstance(source, str) or not 1 <= len(source) <= 512:
        raise EinsteinSolverError("metric expression must be a bounded string")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as error:
        raise EinsteinSolverError("invalid metric expression") from error

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in variables:
                return float(variables[node.id])
            if node.id in _CONSTANTS:
                return _CONSTANTS[node.id]
            raise EinsteinSolverError(f"unknown symbol: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return float(_BINARY[type(node.op)](evaluate(node.left), evaluate(node.right)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
            if node.keywords or len(node.args) != 1:
                raise EinsteinSolverError("functions accept one positional argument")
            return float(_FUNCTIONS[node.func.id](evaluate(node.args[0])))
        raise EinsteinSolverError(f"expression operation denied: {type(node).__name__}")

    value = evaluate(tree)
    if not math.isfinite(value):
        raise EinsteinSolverError("metric expression produced non-finite value")
    return value


def _matrix_inverse(matrix: list[list[float]], pivot_tolerance: float) -> list[list[float]]:
    size = len(matrix)
    augmented = [row[:] + [1.0 if i == j else 0.0 for j in range(size)] for i, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= pivot_tolerance:
            raise EinsteinSolverError("metric is singular or numerically degenerate")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column], strict=True)
            ]
    return [row[size:] for row in augmented]


@dataclass(frozen=True, slots=True)
class EinsteinProblem:
    coordinates: tuple[str, str, str, str]
    point: tuple[float, float, float, float]
    metric: tuple[tuple[str, ...], ...]
    stress_energy: tuple[tuple[float, ...], ...]
    gravitational_constant: float
    speed_of_light: float
    cosmological_constant: float
    derivative_step: float
    residual_tolerance: float
    symmetry_tolerance: float
    pivot_tolerance: float
    initial_conditions: dict[str, Any]
    boundary_conditions: dict[str, Any]
    signature_convention: str
    riemann_convention: str
    units: str

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> "EinsteinProblem":
        required = {
            "coordinates", "coordinate_point", "metric", "constants", "energy_momentum_tensor",
            "initial_conditions", "boundary_conditions", "tolerances",
            "conventions",
        }
        if not isinstance(value, dict) or not required.issubset(value):
            raise EinsteinSolverError("missing required Einstein problem inputs")
        coordinates = value["coordinates"]
        point = value["coordinate_point"]
        metric = value["metric"]
        tensor = value["energy_momentum_tensor"]
        if (
            not isinstance(coordinates, list) or len(coordinates) != 4
            or any(not isinstance(item, str) or not item.isidentifier() for item in coordinates)
            or len(set(coordinates)) != 4
        ):
            raise EinsteinSolverError("exactly four distinct coordinate identifiers are required")
        if not isinstance(point, list) or len(point) != 4:
            raise EinsteinSolverError("coordinate_point must contain four numbers")
        if (
            not isinstance(metric, list) or len(metric) != 4
            or any(not isinstance(row, list) or len(row) != 4 for row in metric)
        ):
            raise EinsteinSolverError("metric must be a 4x4 expression matrix")
        if (
            not isinstance(tensor, list) or len(tensor) != 4
            or any(not isinstance(row, list) or len(row) != 4 for row in tensor)
        ):
            raise EinsteinSolverError("energy_momentum_tensor must be 4x4")
        constants = value["constants"]
        tolerances = value["tolerances"]
        conventions = value["conventions"]
        if not isinstance(conventions, dict):
            raise EinsteinSolverError("conventions must be a declared object")
        if conventions.get("signature") != "-+++":
            raise EinsteinSolverError("only the -+++ metric signature is supported")
        if conventions.get("riemann") != "wald":
            raise EinsteinSolverError("only the declared Wald-sign Riemann convention is supported")
        if conventions.get("units") != "SI":
            raise EinsteinSolverError("only SI units are supported")
        try:
            G = float(constants["G"])
            c = float(constants["c"])
            cosmological = float(constants.get("Lambda", 0.0))
            derivative_step = float(tolerances["derivative_step"])
            residual_tolerance = float(tolerances["residual"])
            symmetry_tolerance = float(tolerances.get("symmetry", 1e-10))
            pivot_tolerance = float(tolerances.get("pivot", 1e-12))
            parsed_point = tuple(float(item) for item in point)
            parsed_tensor = tuple(tuple(float(item) for item in row) for row in tensor)
        except (KeyError, TypeError, ValueError) as error:
            raise EinsteinSolverError("constants, tensors or tolerances are malformed") from error
        scalars = (
            G, c, cosmological, derivative_step, residual_tolerance,
            symmetry_tolerance, pivot_tolerance, *parsed_point,
            *(item for row in parsed_tensor for item in row),
        )
        if any(not math.isfinite(item) for item in scalars) or G <= 0 or c <= 0:
            raise EinsteinSolverError("physical constants and coordinates must be finite; G and c positive")
        if not 1e-9 <= derivative_step <= 1e-1 or min(residual_tolerance, symmetry_tolerance, pivot_tolerance) <= 0:
            raise EinsteinSolverError("tolerances are outside the supported numerical envelope")
        if (
            not isinstance(value["initial_conditions"], dict)
            or not value["initial_conditions"]
            or not isinstance(value["boundary_conditions"], dict)
            or not value["boundary_conditions"]
        ):
            raise EinsteinSolverError("initial and boundary conditions must be declared objects")
        return cls(
            tuple(coordinates), parsed_point, tuple(tuple(str(item) for item in row) for row in metric),
            parsed_tensor, G, c, cosmological, derivative_step, residual_tolerance,
            symmetry_tolerance, pivot_tolerance, dict(value["initial_conditions"]),
            dict(value["boundary_conditions"]), "-+++", "wald", "SI",
        )


def solve(payload: dict[str, Any]) -> dict[str, Any]:
    problem = EinsteinProblem.from_payload(payload)
    n, h = 4, problem.derivative_step

    def metric_at(point: tuple[float, ...]) -> list[list[float]]:
        variables = dict(zip(problem.coordinates, point, strict=True))
        value = [[_expression(problem.metric[i][j], variables) for j in range(n)] for i in range(n)]
        for i in range(n):
            for j in range(n):
                if abs(value[i][j] - value[j][i]) > problem.symmetry_tolerance:
                    raise EinsteinSolverError("metric is not symmetric within tolerance")
        return value

    def shifted(point: tuple[float, ...], axis: int, delta: float) -> tuple[float, ...]:
        result = list(point)
        result[axis] += delta
        return tuple(result)

    def connection_at(point: tuple[float, ...]) -> list[list[list[float]]]:
        metric = metric_at(point)
        inverse = _matrix_inverse(metric, problem.pivot_tolerance)
        derivatives = []
        for axis in range(n):
            plus, minus = metric_at(shifted(point, axis, h)), metric_at(shifted(point, axis, -h))
            derivatives.append([[(plus[i][j] - minus[i][j]) / (2.0 * h) for j in range(n)] for i in range(n)])
        gamma = [[[0.0 for _ in range(n)] for _ in range(n)] for _ in range(n)]
        for rho in range(n):
            for mu in range(n):
                for nu in range(n):
                    gamma[rho][mu][nu] = 0.5 * sum(
                        inverse[rho][sigma]
                        * (derivatives[mu][sigma][nu] + derivatives[nu][sigma][mu] - derivatives[sigma][mu][nu])
                        for sigma in range(n)
                    )
        return gamma

    point = problem.point
    metric = metric_at(point)
    inverse = _matrix_inverse(metric, problem.pivot_tolerance)
    gamma = connection_at(point)
    gamma_derivative = []
    for axis in range(n):
        plus = connection_at(shifted(point, axis, h))
        minus = connection_at(shifted(point, axis, -h))
        gamma_derivative.append(
            [[[(plus[rho][mu][nu] - minus[rho][mu][nu]) / (2.0 * h) for nu in range(n)] for mu in range(n)] for rho in range(n)]
        )
    ricci = [[0.0 for _ in range(n)] for _ in range(n)]
    for mu in range(n):
        for nu in range(n):
            ricci[mu][nu] = sum(
                gamma_derivative[rho][rho][mu][nu]
                - gamma_derivative[nu][rho][mu][rho]
                + sum(
                    gamma[rho][rho][lam] * gamma[lam][mu][nu]
                    - gamma[rho][nu][lam] * gamma[lam][mu][rho]
                    for lam in range(n)
                )
                for rho in range(n)
            )
    scalar = sum(inverse[mu][nu] * ricci[mu][nu] for mu in range(n) for nu in range(n))
    einstein = [[ricci[i][j] - 0.5 * metric[i][j] * scalar for j in range(n)] for i in range(n)]
    coupling = 8.0 * math.pi * problem.gravitational_constant / problem.speed_of_light**4
    residual = [
        [einstein[i][j] + problem.cosmological_constant * metric[i][j] - coupling * problem.stress_energy[i][j] for j in range(n)]
        for i in range(n)
    ]
    max_abs = max(abs(item) for row in residual for item in row)
    return {
        "schema": "casulo.einstein-local-residual/1.0",
        "status": "PASS" if max_abs <= problem.residual_tolerance else "RESIDUAL_ABOVE_TOLERANCE",
        "coordinates": list(problem.coordinates),
        "coordinate_point": list(problem.point),
        "inverse_metric": inverse,
        "connection": gamma,
        "ricci_tensor": ricci,
        "ricci_scalar": scalar,
        "einstein_tensor": einstein,
        "field_equation_residual": residual,
        "max_abs_residual": max_abs,
        "residual_tolerance": problem.residual_tolerance,
        "initial_conditions_declared": problem.initial_conditions,
        "boundary_conditions_declared": problem.boundary_conditions,
        "conditions_usage": "declared for provenance only; this local evaluator does not evolve an initial-boundary-value problem",
        "conventions": {
            "signature": problem.signature_convention,
            "riemann": problem.riemann_convention,
            "units": problem.units,
            "stress_energy_indices": "covariant T_mu_nu",
            "field_equation": "G_mu_nu + Lambda*g_mu_nu = (8*pi*G/c^4)*T_mu_nu",
        },
        "scope": "local 4D residual evaluation for a user-declared differentiable metric",
        "limitations": [
            "finite-difference derivatives; result depends on derivative_step",
            "does not integrate the global nonlinear Einstein initial-boundary-value problem",
            "does not prove physical validity, stability, convergence or uniqueness",
            "refuses non-4D, non-symmetric, singular or unsafe metric expressions",
        ],
        "real_effects_executed": False,
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(solve(payload), ensure_ascii=False, sort_keys=True))
        return 0
    except (EinsteinSolverError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "REFUSED", "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
