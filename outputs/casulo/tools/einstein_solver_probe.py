from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from casulo.product.domain import canonical_sha256
from casulo.product.engine_contracts import CancellationToken
from casulo.product.semantic_multiverse import CancellationToken as SemanticCancellationToken
from casulo.product.t_forge import ForgeUnit
from casulo_owner.einstein_solver_kernel import solve
from casulo_owner.generative_agent_probe import run_probe
from casulo_owner.generative_forge import GeneratedTProject, compile_generated_project, lower_generated_unit_to_t
from casulo_owner.generative_model import GenerativeCandidate
from casulo_owner.local_model_runtime import LocalModelRuntime
from casulo_owner.scientific_solver import ScientificSolverPlanner
from casulo_owner.semantic_multiverse import GenerativeUniversePlanner, OwnerSemanticMultiverse

try:
    from tools.casulo_owner_vm_inspect import render_creation_timeline
except ModuleNotFoundError:
    from casulo_owner_vm_inspect import render_creation_timeline


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _minkowski() -> dict:
    return {
        "schema": "casulo.einstein-problem/1.0",
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


def _reproducible_zip(root: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(path.name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, path.read_bytes())


def run(
    candidate: GenerativeCandidate,
    cache: Path,
    output: Path,
    *,
    repo: Path,
    semantic_root: Path,
    idea: str,
    expectation: str,
    threads: int,
) -> dict:
    if output.exists() or output.is_symlink():
        raise RuntimeError("einstein probe output already exists; overwrite denied")
    output.mkdir(parents=True)
    base = run_probe(
        candidate, cache, output / "creation", repo=repo, idea=idea,
        holdout_expectation=expectation, threads=threads,
    )
    cancellation = CancellationToken()
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        scientific = ScientificSolverPlanner(runtime).propose(idea, cancellation=cancellation)
        route = GenerativeUniversePlanner(runtime).propose(
            idea, operation_id="einstein-semantic-route", cancellation=cancellation
        )
    semantic = OwnerSemanticMultiverse(semantic_root)
    semantic_session = semantic.execute(
        route,
        idea=idea,
        constraints=("sem API externa", "somente resíduo local 4D", "efeitos reais negados"),
        confirmed=True,
        confirmation_source="AUTOMATED_ACCEPTANCE_SCENARIO",
        cancellation=SemanticCancellationToken(),
    )

    emit = f"Einstein local residual {scientific.payload_sha256[:16]}"
    source = lower_generated_unit_to_t(
        "casulo.science.einstein", "EinsteinProblem", "EvaluateResidual", emit
    )
    unit = ForgeUnit(
        "einstein-local-residual",
        source,
        (("identity", "purpose"), ("data", "requirements"), ("constraints", "precision")),
        (),
    )
    project = GeneratedTProject(
        f"t-project:einstein:{scientific.payload_sha256[:20]}",
        canonical_sha256(scientific.payload),
        (unit,),
        ({"name": "scientific-contract", "unit_id": unit.unit_id, "input": "Minkowski", "expected_contains": "Einstein local residual"},),
        unit.unit_id,
        scientific.trace,
        scientific.payload_sha256,
    )
    compiled = compile_generated_project(project)

    example = _minkowski()
    simulated = solve(example)
    if simulated["status"] != "PASS" or simulated["max_abs_residual"] != 0.0:
        raise RuntimeError("Minkowski validation failed")

    materialized = output / "materialized-einstein-solver"
    materialized.mkdir()
    kernel_source = Path(__file__).parents[1] / "private/casulo-owner/src/casulo_owner/einstein_solver_kernel.py"
    payloads: dict[str, bytes] = {
        "einstein_solver.py": kernel_source.read_bytes(),
        "solver-spec.json": _json_bytes(scientific.payload),
        "solver-plan-repair.json": _json_bytes({"attempts": scientific.attempts, "history": scientific.diagnostics, "trace": scientific.trace.to_dict()}),
        "example-input.json": _json_bytes(example),
        "example-output.json": _json_bytes(simulated),
        "solver-contract.t": source.encode("utf-8"),
        "solver-contract.tcap": compiled.tcap,
        "forge-receipt.json": _json_bytes(compiled.forge_receipt.to_dict()),
        "semantic-session.json": _json_bytes(semantic_session),
        "base-creation-evidence.json": _json_bytes({"gate": base["gate"], "archive": base["materialization"]["archive"], "archive_sha256": base["materialization"]["archive_sha256"]}),
    }
    for name, payload in payloads.items():
        (materialized / name).write_bytes(payload)
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    external = subprocess.run(
        [sys.executable, str(materialized / "einstein_solver.py")],
        input=json.dumps(example), text=True, encoding="utf-8", capture_output=True,
        timeout=30, env=environment, check=False,
    )
    external_payload = json.loads(external.stdout) if external.stdout else {}
    if external.returncode != 0 or external_payload != simulated:
        raise RuntimeError("external scientific solver execution diverged")
    (materialized / "external-execution.json").write_bytes(
        _json_bytes({"returncode": external.returncode, "stdout_sha256": _sha(external.stdout.encode("utf-8")), "equivalent": True})
    )
    payload_hashes = {path.name: _sha(path.read_bytes()) for path in materialized.iterdir() if path.is_file()}
    manifest = {
        "schema": "casulo.einstein-solver-package/1.0",
        "profile": "owner-local-scientific-sandbox",
        "scientific_claim": "local 4D Einstein field-equation residual evaluator",
        "global_einstein_solver_claim": False,
        "inputs": scientific.payload["inputs"],
        "outputs": scientific.payload["outputs"],
        "files": payload_hashes,
        "t_generated": True,
        "t_compiled": True,
        "tcap_sha256": compiled.tcap_sha256,
        "simulation_real_effects": False,
        "external_ai_api": False,
        "fake_engine": False,
        "cloud": "RELEASE_LOCKED",
        "usb": "PROHIBITED",
    }
    (materialized / "MANIFEST.json").write_bytes(_json_bytes(manifest))
    sums = "".join(
        f"{_sha(path.read_bytes())}  {path.name}\n"
        for path in sorted(materialized.iterdir(), key=lambda item: item.name)
        if path.is_file()
    )
    (materialized / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")
    archive = output / "casulo-owner-einstein-local-solver.casulo.zip"
    _reproducible_zip(materialized, archive)
    semantic_visual = semantic.render(semantic_session, output / "semantic-visual")
    creation_visual = render_creation_timeline(output / "creation", base, output / "creation-visual")
    reboot = semantic.reboot()
    result = {
        "schema": "casulo.einstein-solver-probe/1.0",
        "state": "PASS_REAL_LOCAL_EINSTEIN_RESIDUAL_SOLVER",
        "idea": idea,
        "neural_plan": scientific.payload,
        "neural_plan_trace": scientific.trace.to_dict(),
        "diagnostic_repair": {"attempts": scientific.attempts, "history": scientific.diagnostics},
        "t": {"source_sha256": _sha(source.encode("utf-8")), "tcap_sha256": compiled.tcap_sha256, "forge": compiled.forge_receipt.to_dict()},
        "simulation": simulated,
        "external_execution": {"returncode": external.returncode, "equivalent": True},
        "materialization": {"directory": str(materialized), "archive": str(archive), "archive_sha256": _sha(archive.read_bytes())},
        "visualization": {"creation": creation_visual, "semantic": str(semantic_visual)},
        "semantic": semantic_session,
        "reboot": reboot,
        "claims": {"global_einstein_solver": False, "local_residual_evaluator": True},
    }
    (output / "einstein-solver-evidence.json").write_bytes(_json_bytes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--semantic-root", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--expectation", required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    result = run(
        GenerativeCandidate.load(args.candidate), args.cache.resolve(), args.output.resolve(),
        repo=args.repo.resolve(), semantic_root=args.semantic_root.resolve(), idea=args.idea,
        expectation=args.expectation, threads=args.threads,
    )
    print(json.dumps({"state": result["state"], "evidence": str(args.output / "einstein-solver-evidence.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
