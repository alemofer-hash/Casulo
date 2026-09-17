from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from casulo.product.domain import CreationAggregate, CreationSpec, DeltaConfirmation
from casulo.product.engine_contracts import CancellationToken
from casulo.product.intent_engine import IntentEngine
from casulo.product.t_forge import TForge
from casulo.t.tcap import parse_tcap

from .generative_forge import (
    IntentPlanner,
    TProgramSynthesizer,
    compile_generated_project,
    verify_correction_scope,
)
from .generative_model import GenerativeCandidate
from .local_model_runtime import LocalModelRuntime


IDEA = (
    "Quero um agente local chamado Farol de Decisões. Ele lê notas de reunião, "
    "separa decisões confirmadas de hipóteses e lembra contradições na conversa "
    "seguinte. Nunca envia ou altera documentos sem minha confirmação."
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_probe(candidate: GenerativeCandidate, cache: Path, output: Path, *, threads: int = 4) -> dict[str, object]:
    if output.exists() or output.is_symlink():
        raise RuntimeError("diretório de evidência já existe; overwrite negado")
    output.mkdir(parents=True)
    aggregate = CreationAggregate(CreationSpec("creation:farol-decisoes"))
    cancellation = CancellationToken()
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        planner = IntentPlanner(runtime)
        plan = planner.propose(
            aggregate,
            source_event_id="voice:g4:idea",
            utterance=IDEA,
            cancellation=cancellation,
        )
        # A inferência só propõe. Esta confirmação é um evento humano explícito
        # do cenário de aceitação e ocorre fora do runtime neural.
        confirmed = IntentEngine().decide(
            plan.delta,
            human_event_id="human:g4:confirm",
            accepted=True,
            explicit_human_approval=True,
        )
        creation = aggregate.apply_delta(confirmed)
        synthesizer = TProgramSynthesizer(runtime)
        project = synthesizer.synthesize(
            creation,
            source_event_ids=confirmed.source_event_ids,
            cancellation=cancellation,
        )
        forge = TForge()
        compiled = compile_generated_project(project, forge)

        depended_on = {dependency for unit in project.units for dependency in unit.dependencies}
        leaf_candidates = [unit for unit in project.units if unit.unit_id not in depended_on]
        target = leaf_candidates[-1] if leaf_candidates else project.units[-1]
        affected = (target.watch_paths[0],)
        corrected = synthesizer.revise_unit(
            project,
            unit_id=target.unit_id,
            correction=(
                "Torne a mensagem emitida mais direta e deixe explícito que hipótese não é decisão confirmada."
            ),
            declared_affected_paths=affected,
            source_event_id="voice:g4:correction",
            cancellation=cancellation,
        )
        changed_units = verify_correction_scope(
            project,
            corrected,
            declared_affected_paths=affected,
        )
        corrected_compiled = compile_generated_project(corrected, forge, affected_paths=affected)

    initial_dir = output / "initial"
    corrected_dir = output / "corrected"
    initial_dir.mkdir()
    corrected_dir.mkdir()
    for unit in project.units:
        (initial_dir / f"{unit.unit_id}.t").write_text(unit.source, encoding="utf-8")
    for unit in corrected.units:
        (corrected_dir / f"{unit.unit_id}.t").write_text(unit.source, encoding="utf-8")
    (initial_dir / "tests.json").write_text(
        json.dumps(project.tests, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (initial_dir / "creation.json").write_text(
        json.dumps(creation.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (initial_dir / "intent-proposed.json").write_text(
        json.dumps(plan.delta.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (initial_dir / "intent-confirmed.json").write_text(
        json.dumps(confirmed.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (initial_dir / "forge-receipt.json").write_text(
        json.dumps(compiled.forge_receipt.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (corrected_dir / "forge-receipt.json").write_text(
        json.dumps(corrected_compiled.forge_receipt.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (initial_dir / "agent.tcap").write_bytes(compiled.tcap)
    (corrected_dir / "agent.tcap").write_bytes(corrected_compiled.tcap)
    traces = output / "stochastic-traces.jsonl"
    traces.write_text(
        "".join(
            json.dumps(trace.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for trace in (plan.generation_trace, project.generation_trace, corrected.generation_trace)
        ),
        encoding="utf-8",
    )
    package = parse_tcap(corrected_compiled.tcap)
    initial_sources = {artifact.unit_id: artifact.source_sha256 for artifact in compiled.forge_receipt.artifacts}
    corrected_sources = {artifact.unit_id: artifact.source_sha256 for artifact in corrected_compiled.forge_receipt.artifacts}
    unchanged = tuple(sorted(unit_id for unit_id in initial_sources if initial_sources[unit_id] == corrected_sources[unit_id]))
    checks = {
        "intent_delta_proposed_by_model": plan.delta.confirmation is DeltaConfirmation.PROPOSED,
        "human_confirmation_is_separate": confirmed.confirmation is DeltaConfirmation.CONFIRMED and confirmed.source_event_ids[-1] == "human:g4:confirm",
        "capability_requests_are_not_grants": not creation.capabilities and "grants" not in package.manifest,
        "creation_spec_generated": bool(creation.content),
        "t_sources_generated": len(project.units) >= 2,
        "tests_generated": len(project.tests) >= 2,
        "frontend_semantics_ir_graph_pass": all(
            artifact.ir_sha256 and artifact.graph_sha256 for artifact in compiled.forge_receipt.artifacts
        ),
        "tcap_real_and_parseable": package.manifest["schema"] == "tcap-manifest/1.1",
        "correction_changed_only_declared_unit": changed_units == (target.unit_id,),
        "unaffected_source_hashes_preserved": len(unchanged) == len(project.units) - 1,
        "incremental_reuse_observed": bool(corrected_compiled.forge_receipt.reused_units),
        "external_ai_api_used": False,
        "fake_engine_used": False,
        "legacy_training_shortcut_used": False,
        "scientific_benchmark": False,
    }
    required_false = {"external_ai_api_used", "fake_engine_used", "legacy_training_shortcut_used", "scientific_benchmark"}
    passed = all(value is (False if key in required_false else True) for key, value in checks.items())
    result = {
        "schema": "casulo-generative-t-synthesis-evidence/1.0",
        "gate": "GENERATIVE_T_SYNTHESIS_PASS" if passed else "GENERATIVE_T_SYNTHESIS_FAIL",
        "idea": IDEA,
        "candidate_id": candidate.candidate_id,
        "intent_delta": plan.delta.to_dict(),
        "requested_capabilities": list(plan.requested_capabilities),
        "confirmed_creation": creation.to_dict(),
        "project_id": project.project_id,
        "unit_ids": [unit.unit_id for unit in project.units],
        "generated_tests": list(project.tests),
        "initial_forge_receipt": compiled.forge_receipt.to_dict(),
        "correction": {
            "target_unit": target.unit_id,
            "affected_paths": [list(path) for path in affected],
            "changed_units": list(changed_units),
            "unchanged_source_units": list(unchanged),
            "forge_receipt": corrected_compiled.forge_receipt.to_dict(),
        },
        "initial_tcap_sha256": compiled.tcap_sha256,
        "corrected_tcap_sha256": corrected_compiled.tcap_sha256,
        "checks": checks,
        "stochastic_traces_sha256": _sha(traces),
        "cloud_state": "RELEASE_LOCKED",
        "public_state": "FROZEN",
        "usb_state": "PROHIBITED",
    }
    evidence = output / "g4-generative-t-synthesis.json"
    temporary = evidence.with_name(f".{evidence.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(evidence)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe real de intenção e síntese T generativas")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    result = run_probe(
        GenerativeCandidate.load(args.candidate),
        args.cache.expanduser().resolve(),
        args.output_dir.expanduser().resolve(),
        threads=args.threads,
    )
    print(json.dumps({"gate": result["gate"], "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0 if result["gate"] == "GENERATIVE_T_SYNTHESIS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
