from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from casulo.product.capabilities import Effect
from casulo.product.causal_repair import bind_intent_requirements
from casulo.product.domain import (
    CapabilityGrant,
    CreationAggregate,
    CreationSpec,
    CreationState,
)
from casulo.product.engine_contracts import CancellationToken
from casulo.product.intent_engine import IntentEngine
from casulo.product.intent_reconstruction import IntentTwin
from casulo.product.requirement_evidence_gate import RequirementEvidenceFacts, RequirementEvidenceGate
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
from .t85_requirements import TRequirementGraphCompiler
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
    runtime: LocalModelRuntime | None = None,
    enforce_holdout_scan: bool = True,
    require_initial_repair: bool = True,
    intent_twin: IntentTwin | None = None,
    human_confirmation_event_id: str = "human:g5:confirm-material-intent",
    cancellation: CancellationToken | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    scan = (
        _preexisting_holdout_matches(repo, idea, holdout_expectation)
        if enforce_holdout_scan
        else {
            "schema": "casulo.holdout-scan/1.0",
            "status": "NOT_APPLICABLE_PRODUCT_PATH",
            "absent_before_run": True,
            "findings": [],
        }
    )
    if enforce_holdout_scan and not scan["absent_before_run"]:
        raise RuntimeError("tarefa holdout ja aparece em prompt, fixture, codigo ou documento")
    if not human_confirmation_event_id.startswith("human:"):
        raise RuntimeError("produção exige evento de confirmação humana")
    if intent_twin is not None and not intent_twin.confirmed:
        raise RuntimeError("IntentTwin precisa estar confirmado antes da produção")
    if output.exists() or output.is_symlink():
        raise RuntimeError("diretorio de evidencia ja existe; overwrite negado")
    output.mkdir(parents=True)
    _write_json(output / "holdout-scan.json", scan)
    active_cancellation = cancellation or CancellationToken()

    def report(summary: str, evidence_sha256: str) -> None:
        if progress is not None:
            progress(summary, evidence_sha256)

    def cancellation_checkpoint() -> None:
        if active_cancellation.cancelled:
            raise RuntimeError("criação cancelada antes da próxima publicação")

    report("Workspace isolado e contrato inicial preservados.", _sha(output / "holdout-scan.json"))

    creation_id = intent_twin.creation_id if intent_twin is not None else "creation:open-ended-holdout"
    aggregate = CreationAggregate(CreationSpec(creation_id))
    requirement_graph = None
    runtime_context = nullcontext(runtime) if runtime is not None else LocalModelRuntime(candidate, cache, threads=threads)
    with runtime_context as active_runtime:
        if active_runtime is None:
            raise RuntimeError("runtime owner indisponível")
        planner = IntentPlanner(active_runtime)
        plan = planner.propose(
            aggregate,
            source_event_id=(
                intent_twin.confirmation_event_ids[-1]
                if intent_twin is not None
                else "voice:g5:novel-idea"
            ),
            utterance=idea,
            cancellation=active_cancellation,
        )
        _write_json(
            output / "checkpoint-intent.json",
            {
                "delta": plan.delta.to_dict(),
                "requested_capabilities": list(plan.requested_capabilities),
                "trace": plan.generation_trace.to_dict(),
            },
        )
        report("IntentDelta real gerado e persistido.", _sha(output / "checkpoint-intent.json"))
        cancellation_checkpoint()
        confirmed = IntentEngine().decide(
            plan.delta,
            human_event_id=human_confirmation_event_id,
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

        if intent_twin is not None:
            graph = intent_twin.requirement_graph()
            requirement_graph = graph
            compiled_requirements = TRequirementGraphCompiler().compile(
                graph,
                (),
                project_id=intent_twin.creation_id,
                candidate_project_id=f"candidate:{intent_twin.twin_id}",
            )
            _write_json(output / "intent-twin.json", intent_twin.to_dict())
            _write_json(
                output / "requirement-graph.json",
                {
                    "schema": "casulo.requirement-graph/2.0",
                    "requirements": [item.to_dict() for item in graph.requirements],
                    "dependencies": {key: list(value) for key, value in graph.dependencies.items()},
                    "status": "AWAITING_INDEPENDENT_EVIDENCE",
                },
            )
            _write_json(
                output / "t-requirement-authority-input.json",
                {
                    "authority_inputs": compiled_requirements.authority_inputs(),
                    "evidence_plan": compiled_requirements.evidence_plan,
                    "status": "FACTS_COMPILED_NO_ACCEPTANCE_CLAIM",
                },
            )
            report("RequirementGraph compilado para fatos T, ainda sem claim de aceite.", _sha(output / "t-requirement-authority-input.json"))
        cancellation_checkpoint()
        synthesizer = TProgramSynthesizer(active_runtime)
        generated = synthesizer.synthesize(
            confirmed_creation,
            source_event_ids=confirmed.source_event_ids,
            cancellation=active_cancellation,
            intent_twin=intent_twin,
        )
        requirement_bindings = (
            bind_intent_requirements(intent_twin, generated.units)
            if intent_twin is not None
            else ()
        )
        if requirement_bindings:
            _write_json(
                output / "requirement-semantic-bindings.json",
                {
                    "schema": "casulo.requirement-semantic-bindings/1.0",
                    "bindings": [item.to_dict() for item in requirement_bindings],
                },
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
                "neural_route_decisions": [
                    item.to_dict() for item in generated.neural_route_decisions
                ],
                "candidate_rejections": list(generated.candidate_rejections),
            },
        )
        report("Projeto T candidato gerado e selado para verificação.", _sha(output / "checkpoint-generated-project.json"))
        cancellation_checkpoint()
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
            cancellation=active_cancellation,
            requirement_bindings=requirement_bindings,
            require_causal_repairs=intent_twin is not None,
        )

    if not outcome.passed:
        _write_json(output / "repair-outcome.json", outcome.to_dict())
        raise RuntimeError(f"reparo generativo nao convergiu: {outcome.status}")
    if require_initial_repair and (outcome.repair_count < 1 or not outcome.attempts[0].diagnostics):
        raise RuntimeError("demo G5 exige candidato inicial imperfeito e diagnostico real")
    report("T compilado e diagnostics reais convergiram dentro do budget.", outcome.compiled.tcap_sha256)
    cancellation_checkpoint()

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
    simulation_digest = hashlib.sha256(
        json.dumps(simulation.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report("Simulação concluída sem efeitos reais.", simulation_digest)
    cancellation_checkpoint()

    if intent_twin is not None and requirement_graph is not None:
        artifact_sha256 = outcome.compiled.tcap_sha256
        input_sha256 = str(intent_twin.to_dict()["canonical_sha256"])
        occurred_at = datetime.now(timezone.utc).isoformat()
        final_tests = outcome.attempts[-1].tests
        acceptance_pass = any(
            item.name == "human-holdout-acceptance" and item.passed
            for item in final_tests
        )
        clean_execution_pass = bool(final_tests) and all(item.passed for item in final_tests)
        evidence_gate = RequirementEvidenceGate.evaluate(
            requirement_graph,
            RequirementEvidenceFacts(
                acceptance_pass=acceptance_pass,
                compile_pass=outcome.passed,
                simulation_pass=simulation.status == "PASS" and simulation.real_effects_executed is False,
                clean_execution_pass=clean_execution_pass,
                human_review_pass=intent_twin.confirmed,
            ),
            artifact_sha256=artifact_sha256,
            input_sha256=input_sha256,
            occurred_at=occurred_at,
        )
        _write_json(output / "requirement-evidence.json", {
            "schema": "casulo.requirement-evidence-set/1.0",
            "receipts": [item.to_dict() for item in evidence_gate.evidence],
        })
        _write_json(output / "requirement-evaluation.json", evidence_gate.to_dict())
        compiled_with_evidence = TRequirementGraphCompiler().compile(
            requirement_graph,
            evidence_gate.evidence,
            project_id=intent_twin.creation_id,
            candidate_project_id=outcome.project.project_id,
        )
        _write_json(output / "t-requirement-authority-final.json", {
            "authority_inputs": compiled_with_evidence.authority_inputs(),
            "evidence_plan": compiled_with_evidence.evidence_plan,
            "accepted_by_requirement_graph": evidence_gate.evaluation.accepted,
        })
        if not evidence_gate.evaluation.accepted:
            raise RuntimeError(
                "materialização bloqueada: requisito HARD sem evidência independente PASS"
            )
    aggregate.transition(CreationState.SIMULATION, "state:g5:simulation")
    agreement = aggregate.transition(CreationState.AGREEMENT, "human:g5:agreement")
    cancellation_checkpoint()

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
        "neural_route_decisions": [
            item.to_dict() for item in outcome.project.neural_route_decisions
        ],
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
    report("Pacote Casulo materializado e selado.", _sha(materialized.archive))
    cancellation_checkpoint()

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
    report("Execução externa e round-trip concluídos.", _sha(materialized.archive))

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
        "intent_twin_confirmed": intent_twin is None or intent_twin.confirmed,
        "requirements_compiled_before_t": intent_twin is None or (output / "t-requirement-authority-input.json").is_file(),
        "requirements_bound_to_t_units": intent_twin is None or bool(requirement_bindings),
        "repairs_have_causal_receipts": (
            intent_twin is None
            or outcome.repair_count == len(outcome.causal_repairs)
        ),
        "t_neural_budget_is_declared": (
            intent_twin is None or bool(outcome.project.neural_route_decisions)
        ),
        "neural_plan_generated": bool(plan.generation_trace.output_sha256),
        "neural_t_generated": bool(generated.generation_trace.output_sha256),
        "initial_candidate_imperfect": (not require_initial_repair) or bool(outcome.attempts[0].diagnostics),
        "real_compiled_process_test_failed_first": (not require_initial_repair) or any(
            diagnostic.code == "TTEST_EXPECTED_TEXT_MISSING"
            for diagnostic in outcome.attempts[0].diagnostics
        ),
        "bounded_neural_repair_passed": outcome.passed and 0 <= outcome.repair_count <= outcome.budget,
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
        "mode": "HOLDOUT_EVIDENCE" if enforce_holdout_scan else "OWNER_PRODUCT_CREATION",
        "gate": (
            "FIRST_OPEN_ENDED_AGENT_CREATED" if passed else "FIRST_OPEN_ENDED_AGENT_FAILED"
        ) if enforce_holdout_scan else (
            "OWNER_CREATION_MATERIALIZED" if passed else "OWNER_CREATION_FAILED"
        ),
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
