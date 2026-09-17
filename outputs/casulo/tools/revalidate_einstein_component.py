from __future__ import annotations

import hashlib
import json
import math
import zipfile
from pathlib import Path
from typing import Any, Callable

from casulo.product.domain import canonical_sha256
from casulo.product.t_forge import ForgeUnit
from casulo_owner.einstein_solver_kernel import EinsteinSolverError, solve
from casulo_owner.generative_forge import GeneratedTProject, compile_generated_project, lower_generated_unit_to_t
from casulo_owner.local_model_runtime import StochasticTrace
from casulo_owner.scientific_solver import validate_solver_plan


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def trace_from(value: dict[str, Any]) -> StochasticTrace:
    return StochasticTrace(
        value["operation_id"], value["model_id"], value["model_sha256"],
        value["sampling_policy_id"], value["seed_if_available"], value["context_digest"],
        value["output_sha256"], value["stream_events"], value["finish_reason"],
        value["started_monotonic_ns"], value["ended_monotonic_ns"],
        value["external_network_used"], value["commercial_ai_api_used"],
    )


def minkowski() -> dict[str, Any]:
    return {
        "schema": "casulo.einstein-problem/1.1",
        "coordinates": ["t", "x", "y", "z"],
        "coordinate_point": [0.0, 0.0, 0.0, 0.0],
        "metric": [["-1", "0", "0", "0"], ["0", "1", "0", "0"], ["0", "0", "1", "0"], ["0", "0", "0", "1"]],
        "constants": {"G": 6.67430e-11, "c": 299792458.0, "Lambda": 0.0},
        "energy_momentum_tensor": [[0.0] * 4 for _ in range(4)],
        "initial_conditions": {"hypersurface": "t=0", "metric": "Minkowski"},
        "boundary_conditions": {"type": "asymptotically_flat"},
        "tolerances": {"derivative_step": 1e-5, "residual": 1e-9, "symmetry": 1e-10, "pivot": 1e-12},
        "conventions": {"signature": "-+++", "riemann": "wald", "units": "SI"},
    }


def rejected(mutator: Callable[[dict[str, Any]], None]) -> str:
    value = minkowski()
    mutator(value)
    try:
        solve(value)
    except EinsteinSolverError as error:
        return str(error)
    raise RuntimeError("mandatory refusal case was accepted")


def reproducible_zip(root: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(path.name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, path.read_bytes())


def main(source_evidence: Path, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise SystemExit("Einstein revalidation output exists; overwrite denied")
    output.mkdir(parents=True)
    historical = json.loads(source_evidence.read_text(encoding="utf-8"))
    plan = dict(historical["neural_plan"])
    plan["inputs"] = sorted(set(plan["inputs"]) | {"conventions"})
    plan["outputs"] = sorted(set(plan["outputs"]) | {"inverse_metric"})
    diagnostics = validate_solver_plan(plan)
    if diagnostics:
        raise SystemExit(f"amended scientific plan failed: {diagnostics}")
    plan_sha = sha(canonical(plan))
    source = lower_generated_unit_to_t(
        "casulo.science.einstein", "EinsteinProblem", "EvaluateResidual",
        f"Einstein local residual {plan_sha[:16]}",
    )
    unit = ForgeUnit(
        "einstein-local-residual", source,
        (("identity", "purpose"), ("data", "requirements"), ("constraints", "precision")), (),
    )
    inherited_trace = trace_from(historical["neural_plan_trace"])
    project = GeneratedTProject(
        f"t-project:einstein-reseal:{plan_sha[:20]}", canonical_sha256(plan), (unit,),
        ({"name": "scientific-contract", "unit_id": unit.unit_id, "input": "Minkowski", "expected_contains": "Einstein local residual"},),
        unit.unit_id, inherited_trace, plan_sha,
    )
    compiled = compile_generated_project(project)
    vacuum = minkowski()
    vacuum_result = solve(vacuum)
    lambda_problem = minkowski()
    lambda_problem["constants"]["Lambda"] = 2.5
    lambda_problem["tolerances"]["residual"] = 3.0
    lambda_result = solve(lambda_problem)
    expected_lambda = [[-2.5, 0.0, 0.0, 0.0], [0.0, 2.5, 0.0, 0.0], [0.0, 0.0, 2.5, 0.0], [0.0, 0.0, 0.0, 2.5]]
    refusals = {
        "non_symmetric": rejected(lambda value: value["metric"][1].__setitem__(0, "1")),
        "singular": rejected(lambda value: value.update(metric=[["0"] * 4 for _ in range(4)])),
        "wrong_metric_dimensions": rejected(lambda value: value.update(metric=[["1"] * 3 for _ in range(3)])),
        "insufficient_coordinates": rejected(lambda value: value.update(coordinates=["t", "x", "y"])),
        "nonpositive_step": rejected(lambda value: value["tolerances"].update(derivative_step=0.0)),
        "nan_tensor": rejected(lambda value: value["energy_momentum_tensor"][0].__setitem__(0, math.nan)),
        "infinite_tensor": rejected(lambda value: value["energy_momentum_tensor"][0].__setitem__(0, math.inf)),
        "invalid_tolerance": rejected(lambda value: value["tolerances"].update(residual=0.0)),
        "incompatible_stress_energy": rejected(lambda value: value.update(energy_momentum_tensor=[[0.0] * 3 for _ in range(3)])),
    }
    checks = {
        "minkowski_vacuum_zero": vacuum_result["max_abs_residual"] == 0.0,
        "minkowski_lambda_analytic": lambda_result["field_equation_residual"] == expected_lambda,
        "inverse_metric_exposed": "inverse_metric" in vacuum_result,
        "christoffel_exposed": "connection" in vacuum_result,
        "ricci_exposed": "ricci_tensor" in vacuum_result and "ricci_scalar" in vacuum_result,
        "einstein_tensor_exposed": "einstein_tensor" in vacuum_result,
        "field_residual_exposed": "field_equation_residual" in vacuum_result,
        "cosmological_term": lambda_result["max_abs_residual"] == 2.5,
        "coupling_declared": "8*pi*G/c^4" in vacuum_result["conventions"]["field_equation"],
        "si_and_signature_declared": vacuum_result["conventions"]["units"] == "SI" and vacuum_result["conventions"]["signature"] == "-+++",
        "conditions_declared_not_falsely_evolved": vacuum_result["conditions_usage"].startswith("declared for provenance only"),
        "all_refusals": len(refusals) == 9 and all(refusals.values()),
        "global_claim_refused": any("does not integrate the global" in item for item in vacuum_result["limitations"]),
        "t_generated_and_compiled": bool(compiled.tcap_sha256 and compiled.forge_receipt.artifacts),
        "historical_neural_trace_preserved": inherited_trace.output_sha256 == historical["neural_plan_trace"]["output_sha256"],
        "external_api_absent": not inherited_trace.external_network_used and not inherited_trace.commercial_ai_api_used,
    }
    if not all(checks.values()):
        raise SystemExit(f"Einstein revalidation checks failed: {checks}")
    package = output / "package"
    package.mkdir()
    kernel = Path(__file__).parents[1] / "private/casulo-owner/src/casulo_owner/einstein_solver_kernel.py"
    files = {
        "einstein_solver.py": kernel.read_bytes(),
        "solver-spec.json": canonical(plan),
        "solver-contract.t": source.encode("utf-8"),
        "solver-contract.tcap": compiled.tcap,
        "forge-receipt.json": canonical(compiled.forge_receipt.to_dict()),
        "minkowski-input.json": canonical(vacuum),
        "minkowski-output.json": canonical(vacuum_result),
        "minkowski-lambda-output.json": canonical(lambda_result),
        "refusal-cases.json": canonical(refusals),
        "historical-neural-trace.json": canonical(inherited_trace.to_dict()),
    }
    for name, payload in files.items():
        (package / name).write_bytes(payload)
    manifest = {
        "schema": "casulo.einstein-local-evaluator/1.1",
        "claim": "avaliador tensorial local 4D das equações de campo, parametrizável e validado para Minkowski no vácuo",
        "global_solver": False,
        "scientific_validation_complete": False,
        "tcap_sha256": compiled.tcap_sha256,
        "checks": checks,
        "files": {name: sha(payload) for name, payload in files.items()},
        "source_evidence": {"path": str(source_evidence), "sha256": sha(source_evidence.read_bytes())},
        "contract_amendment": ["conventions input", "inverse_metric output", "finite T_mu_nu"],
        "cloud": "RELEASE_LOCKED", "usb": "PROHIBITED", "fake_engine": False,
    }
    (package / "MANIFEST.json").write_bytes(canonical(manifest))
    (package / "SHA256SUMS").write_text(
        "".join(f"{sha(path.read_bytes())}  {path.name}\n" for path in sorted(package.iterdir(), key=lambda item: item.name) if path.is_file()),
        encoding="ascii", newline="\n",
    )
    archive = output / "casulo-owner-einstein-local-evaluator-v1.1.casulo.zip"
    reproducible_zip(package, archive)
    evidence = {
        "schema": "casulo.einstein-component-revalidation/1.0",
        "state": "PASS_DELIMITED_LOCAL_EVALUATOR",
        "checks": checks, "refusals": refusals,
        "vacuum_result": vacuum_result, "lambda_result": lambda_result,
        "tcap_sha256": compiled.tcap_sha256,
        "archive": str(archive), "archive_sha256": sha(archive.read_bytes()),
        "historical_package_preserved": True,
    }
    (output / "einstein-component-audit.json").write_bytes(canonical(evidence))
    print(json.dumps({"state": evidence["state"], "tcap_sha256": compiled.tcap_sha256, "archive_sha256": evidence["archive_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.source_evidence.resolve(strict=True), args.output.resolve())
