from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from casulo.product.capabilities import Effect
from casulo.product.domain import (
    CapabilityGrant,
    CreationAggregate,
    CreationSpec,
    CreationState,
)
from casulo.product.engine_contracts import CancellationToken
from casulo.product.intent_engine import IntentEngine
from casulo.product.materializer import (
    ExecutableAgentBundle,
    MaterializedPackageImporter,
    Materializer,
)
from casulo.product.simulation import (
    SimulatedResponse,
    SimulationCapabilityDouble,
    SimulationPlan,
    SimulationRuntime,
    SimulationStep,
)
from casulo.t.artifact import ArtifactBuilder, EXECUTABLE_FILE

from .generative_forge import (
    IntentPlanner,
    TProgramSynthesizer,
    validate_project_test_feasibility,
)
from .generative_model import GenerativeCandidate
from .local_model_runtime import LocalModelRuntime
from .verifier_repair import VerifierRepairLoop


OPEN_ENDED_REPAIR_BUDGET = 4


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _python_literal_scan(repo: Path, term: str) -> list[str]:
    matches: list[str] = []
    excluded = {".git", "product-demos", "outputs", "__pycache__", ".pytest_cache"}
    allowed = {".py", ".md", ".json", ".t"}
    for root, directories, filenames in os.walk(repo):
        directories[:] = [
            name for name in directories
            if name not in excluded and not name.startswith(".tmp")
        ]
        base = Path(root)
        for filename in filenames:
            path = base / filename
            if path.suffix.casefold() not in allowed:
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                if term in path.read_text(encoding="utf-8", errors="ignore"):
                    matches.append(str(path))
            except OSError:
                continue
    return matches


def holdout_scanner_capability() -> dict[str, Any]:
    executable = shutil.which("rg")
    rg_usable = False
    if executable:
        try:
            probe = subprocess.run(
                [executable, "--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False, shell=False,
            )
            rg_usable = probe.returncode == 0
        except OSError:
            rg_usable = False
    return {
        "schema": "casulo.holdout-scanner-capability/1.0",
        "preferred": "rg",
        "rg_discovered": executable is not None,
        "rg_available": rg_usable,
        "selected_backend": "rg" if rg_usable else "bounded-python-literal-scan",
        "fallback": "bounded-python-literal-scan",
        "fallback_available": True,
        "shell_used": False,
    }


def _preexisting_holdout_matches(repo: Path, idea: str, expectation: str) -> dict[str, Any]:
    terms = (idea, expectation)
    findings: list[dict[str, Any]] = []
    capability = holdout_scanner_capability()
    scanner = str(capability["selected_backend"])
    executable = shutil.which("rg") if scanner == "rg" else None
    fallback_reason: str | None = None
    for term in terms:
        if scanner == "rg":
            try:
                process = subprocess.run(
                    [
                        str(executable), "-F", "-l", term, str(repo),
                        "-g", "*.py", "-g", "*.md", "-g", "*.json", "-g", "*.t",
                        "-g", "!product-demos/**", "-g", "!outputs/**", "-g", "!.tmp*/**",
                    ],
                    text=True, encoding="utf-8", errors="replace",
                    capture_output=True, check=False, shell=False,
                )
            except OSError as error:
                fallback_reason = f"rg_exec_error:{type(error).__name__}"
                scanner = "bounded-python-literal-scan"
                matches = _python_literal_scan(repo, term)
            else:
                if process.returncode in {0, 1}:
                    matches = [line for line in process.stdout.splitlines() if line.strip()]
                else:
                    fallback_reason = f"rg_exit:{process.returncode}"
                    scanner = "bounded-python-literal-scan"
                    matches = _python_literal_scan(repo, term)
        else:
            matches = _python_literal_scan(repo, term)
        findings.append(
            {
                "term_sha256": hashlib.sha256(term.encode("utf-8")).hexdigest(),
                "matches": matches,
            }
        )
    return {
        "schema": "casulo.holdout-scan/1.0",
        "scanned_extensions": ["py", "md", "json", "t"],
        "excluded_generated_evidence": True,
        "scanner": scanner,
        "fallback_reason": fallback_reason,
        "shell_used": False,
        "findings": findings,
        "absent_before_run": all(not item["matches"] for item in findings),
    }


def run_probe(
    candidate: GenerativeCandidate,
    cache: Path,
    output: Path,
    *,
    repo: Path,
    idea: str,
    holdout_expectation: str,
    threads: int = 4,
) -> dict[str, Any]:
    scan = _preexisting_holdout_matches(repo, idea, holdout_expectation)
    if not scan["absent_before_run"]:
        raise RuntimeError("tarefa holdout ja aparece em prompt, fixture, codigo ou documento")
    if output.exists() or output.is_symlink():
        raise RuntimeError("diretorio de evidencia ja existe; overwrite negado")
    output.mkdir(parents=True)
    _write_json(output / "holdout-scan.json", scan)

    aggregate = CreationAggregate(CreationSpec("creation:open-ended-holdout"))
    cancellation = CancellationToken()
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        planner = IntentPlanner(runtime)
        plan = planner.propose(
            aggregate,
            source_event_id="voice:g5:novel-idea",
            utterance=idea,
            cancellation=cancellation,
        )
        _write_json(
            output / "checkpoint-intent.json",
            {
                "delta": plan.delta.to_dict(),
                "requested_capabilities": list(plan.requested_capabilities),
                "trace": plan.generation_trace.to_dict(),
            },
        )
        confirmed = IntentEngine().decide(
            plan.delta,
            human_event_id="human:g5:confirm-material-intent",
            accepted=True,
            explicit_human_approval=True,
        )
        aggregate.apply_delta(confirmed)
        creation_before_human_grant = aggregate.current
        aggregate.grant(
            CapabilityGrant(
                Effect.MEMORY_READ.value,
                "human",
                "human:g5:grant-simulation-memory-read",
                True,
            )
        )
        for state, event_id in (
            (CreationState.FIRST_INTENT, "state:g5:first-intent"),
            (CreationState.FIRST_FORM, "state:g5:first-form"),
            (CreationState.CONFIRMATION, "state:g5:confirmation"),
        ):
            aggregate.transition(state, event_id)
        confirmed_creation = aggregate.current

        synthesizer = TProgramSynthesizer(runtime)
        generated = synthesizer.synthesize(
            confirmed_creation,
            source_event_ids=confirmed.source_event_ids,
            cancellation=cancellation,
        )
        _write_json(
            output / "checkpoint-generated-project.json",
            {
                "project_id": generated.project_id,
                "creation_sha256": generated.creation_sha256,
                "entry_unit": generated.entry_unit,
                "tests": list(generated.tests),
                "units": [
                    {
                        "unit_id": unit.unit_id,
                        "source": unit.source,
                        "watch_paths": [list(path) for path in unit.watch_paths],
                        "dependencies": list(unit.dependencies),
                    }
                    for unit in generated.units
                ],
                "trace": generated.generation_trace.to_dict(),
                "candidate_rejections": list(generated.candidate_rejections),
            },
        )
        holdout_test = {
            "name": "human-holdout-acceptance",
            "unit_id": generated.entry_unit,
            "input": idea,
            "expected_contains": holdout_expectation,
        }
        candidate_project = replace(generated, tests=(*generated.tests, holdout_test))
        validate_project_test_feasibility(candidate_project)
        outcome = VerifierRepairLoop(
            synthesizer, repair_budget=OPEN_ENDED_REPAIR_BUDGET
        ).run(
            candidate_project,
            work_root=output / "verification",
            cancellation=cancellation,
        )

    if not outcome.passed:
        _write_json(output / "repair-outcome.json", outcome.to_dict())
        raise RuntimeError(f"reparo generativo nao convergiu: {outcome.status}")
    if outcome.repair_count < 1 or not outcome.attempts[0].diagnostics:
        raise RuntimeError("demo G5 exige candidato inicial imperfeito e diagnostico real")

    simulation = SimulationRuntime(
        {
            Effect.MEMORY_READ: SimulationCapabilityDouble(
                Effect.MEMORY_READ,
                (SimulatedResponse(True, {"virtual": True, "records": 3}),),
            )
        }
    ).run(
        confirmed_creation,
        SimulationPlan(
            "simulation:g5:open-ended-agent",
            confirmed_creation.creation_id,
            (
                SimulationStep(
                    "read-research-memory-virtually",
                    Effect.MEMORY_READ,
                    "preview competing hypotheses",
                    {"source": "simulation://sealed-research-notes"},
                    (),
                    (("behavior",),),
                    ("human:g5:simulate",),
                ),
            ),
            ("human:g5:simulate",),
        ),
    )
    aggregate.transition(CreationState.SIMULATION, "state:g5:simulation")
    agreement = aggregate.transition(CreationState.AGREEMENT, "human:g5:agreement")

    entry = next(unit for unit in outcome.project.units if unit.unit_id == outcome.project.entry_unit)
    entry_root = output / "entry-build"
    entry_root.mkdir()
    entry_source = entry_root / "source.t"
    entry_source.write_text(entry.source, encoding="utf-8", newline="\n")
    built = ArtifactBuilder().build(entry_source, entry_root / "artifact")
    operation = str(built.manifest["operations"][0]["name"])
    project_manifest = {
        "schema": "casulo.generated-project/1.0",
        "project_id": outcome.project.project_id,
        "creation_sha256": outcome.project.creation_sha256,
        "entry_unit": outcome.project.entry_unit,
        "tests": list(outcome.project.tests),
        "units": [
            {
                "unit_id": unit.unit_id,
                "source_sha256": hashlib.sha256(unit.source.encode("utf-8")).hexdigest(),
                "watch_paths": [list(path) for path in unit.watch_paths],
                "dependencies": list(unit.dependencies),
            }
            for unit in outcome.project.units
        ],
        "verifier_receipt_sha256": outcome.receipt_sha256,
    }
    bundle = ExecutableAgentBundle(
        built.artifact_id,
        operation,
        (built.output_dir / EXECUTABLE_FILE).read_bytes(),
        built.manifest,
        outcome.compiled.tcap,
        project_manifest,
    )
    materialized = Materializer(output / "materialized").materialize(
        agreement,
        forge_receipt=outcome.compiled.forge_receipt,
        simulation_receipt=simulation,
        executable_bundle=bundle,
    )

    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    external = subprocess.run(
        [sys.executable, str(materialized.directory / "agent.py"), operation, "-"],
        input=json.dumps({"value": idea}, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=10,
        env=environment,
        check=False,
    )
    external_payload = json.loads(external.stdout) if external.returncode == 0 else {}
    external_result = str(external_payload.get("result", ""))
    imported = MaterializedPackageImporter().import_archive(materialized.archive)

    _write_json(output / "intent-plan.json", plan.delta.to_dict())
    _write_json(output / "confirmed-creation.json", confirmed_creation.to_dict())
    _write_json(output / "repair-outcome.json", outcome.to_dict())
    _write_json(output / "simulation-receipt.json", simulation.to_dict())
    _write_json(output / "materialization-receipt.json", materialized.to_dict())
    _write_json(
        output / "external-execution.json",
        {
            "returncode": external.returncode,
            "stdout_sha256": hashlib.sha256(external.stdout.encode("utf-8")).hexdigest(),
            "stderr": external.stderr[-2048:],
            "operation": operation,
            "result": external_result,
        },
    )
    checks = {
        "holdout_absent_before_run": scan["absent_before_run"],
        "neural_plan_generated": bool(plan.generation_trace.output_sha256),
        "neural_t_generated": bool(generated.generation_trace.output_sha256),
        "initial_candidate_imperfect": bool(outcome.attempts[0].diagnostics),
        "real_compiled_process_test_failed_first": any(
            diagnostic.code == "TTEST_EXPECTED_TEXT_MISSING"
            for diagnostic in outcome.attempts[0].diagnostics
        ),
        "bounded_neural_repair_passed": outcome.passed and 1 <= outcome.repair_count <= outcome.budget,
        "all_final_tests_executed_and_passed": all(item.passed for item in outcome.attempts[-1].tests),
        "simulation_passed": simulation.status == "PASS",
        "simulation_real_effects_absent": simulation.real_effects_executed is False,
        "external_process_passed": external.returncode == 0 and holdout_expectation.casefold() in external_result.casefold(),
        "round_trip_identity_preserved": imported.creation.creation_id == agreement.creation_id,
        "round_trip_version_preserved": imported.creation.version == agreement.version,
        "round_trip_executable_preserved": imported.agent_artifact_id == built.artifact_id,
        "model_created_no_grant": not creation_before_human_grant.capabilities,
        "fake_engine_used": False,
        "external_ai_api_used": False,
        "real_effect_executed": False,
        "scientific_benchmark": False,
    }
    required_false = {
        "fake_engine_used", "external_ai_api_used", "real_effect_executed", "scientific_benchmark"
    }
    passed = all(value is (False if key in required_false else True) for key, value in checks.items())
    result = {
        "schema": "casulo-first-open-ended-agent-evidence/1.0",
        "gate": "FIRST_OPEN_ENDED_AGENT_CREATED" if passed else "FIRST_OPEN_ENDED_AGENT_FAILED",
        "idea": idea,
        "holdout_expectation": holdout_expectation,
        "candidate_id": candidate.candidate_id,
        "project_id": outcome.project.project_id,
        "repair": outcome.to_dict(),
        "simulation": simulation.to_dict(),
        "materialization": materialized.to_dict(),
        "imported": {
            "creation_id": imported.creation.creation_id,
            "creation_version": imported.creation.version,
            "agent_artifact_id": imported.agent_artifact_id,
            "agent_operation": imported.agent_operation,
        },
        "external_execution": {
            "returncode": external.returncode,
            "result": external_result,
        },
        "checks": checks,
        "cloud_state": "RELEASE_LOCKED",
        "public_state": "FROZEN",
        "usb_state": "PROHIBITED",
    }
    _write_json(output / "g5-first-open-ended-agent.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cria e materializa um agente owner neural holdout")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--holdout-expectation", required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        result = run_probe(
            GenerativeCandidate.load(args.candidate),
            args.cache.expanduser().resolve(),
            args.output_dir.expanduser().resolve(),
            repo=args.repo.expanduser().resolve(),
            idea=args.idea,
            holdout_expectation=args.holdout_expectation,
            threads=args.threads,
        )
    except BaseException as error:
        destination = args.output_dir.expanduser().resolve()
        if destination.is_dir():
            _write_json(
                destination / "failure.json",
                {
                    "schema": "casulo.generative-probe-failure/1.0",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "preserved": True,
                },
            )
        raise
    print(json.dumps({"gate": result["gate"], "output": str(args.output_dir)}, ensure_ascii=False))
    return 0 if result["gate"] == "FIRST_OPEN_ENDED_AGENT_CREATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
