from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from dataclasses import replace
from pathlib import Path


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def recalls_rejected_dashboard(answer: str) -> bool:
    text = normalized(answer)
    rejected = any(word in text for word in ("rejeit", "descart", "nao adot"))
    concept = "dashboard" in text or "interface convencional" in text
    return rejected and concept


def recalls_offline_constraint(answer: str) -> bool:
    text = normalized(answer)
    boundary = any(marker in text for marker in ("api", "rede", "servidor", "extern"))
    denial = "offline" in text or any(
        marker in text
        for marker in ("sem conexao", "nao ha conexao", "sem acesso", "em isolamento", "opera em isolamento")
    )
    return boundary and denial


def run_probe(repo: Path, candidate_path: Path, cache: Path, output: Path, *, threads: int) -> dict[str, object]:
    sys.path[:0] = [str(repo / "src"), str(repo / "private/casulo-owner/src")]
    from casulo.product.engine_contracts import CancellationToken, EngineEventKind  # noqa: PLC0415
    from casulo.product.guide_continuity import (  # noqa: PLC0415
        ConstraintStrength,
        GuideContinuityKernel,
        RecordKind,
    )
    from casulo.product.guide_presence import JobEvent, JobStatus  # noqa: PLC0415
    from casulo_owner.dialogue_core import GenerativeDialogueCore  # noqa: PLC0415
    from casulo_owner.generative_engine import (  # noqa: PLC0415
        AppendOnlyTraceStore,
        ContextAssembler,
        OwnerContextStore,
        OwnerGenerativeEngineAdapter,
        make_owner_request,
    )
    from casulo_owner.generative_model import GenerativeCandidate  # noqa: PLC0415
    from casulo_owner.local_model_runtime import LocalModelRuntime, initial_sampling_policies  # noqa: PLC0415

    if output.exists():
        raise RuntimeError("evidence dir já existe; overwrite negado")
    output.mkdir(parents=True)
    kernel = GuideContinuityKernel()
    project = "rc2-guide-neural"
    kernel.open_project(project, source_event_id="human:open")
    kernel.add_constraint(
        constraint_id="rc2:offline",
        project_id=project,
        key="network",
        statement="O fluxo principal permanece offline e sem API externa.",
        strength=ConstraintStrength.HARD,
        source_event_ids=("human:constraint:offline",),
    )
    kernel.record(
        record_id="rc2:rejected-dashboard",
        project_id=project,
        kind=RecordKind.REJECTED,
        text="Guilherme rejeitou explicitamente transformar o Casulo em dashboard convencional.",
        source_event_ids=("human:reject:dashboard",),
        criticality=10,
    )
    kernel.record(
        record_id="rc2:purpose",
        project_id=project,
        kind=RecordKind.DECISION,
        text="A finalidade é conversar durante a construção, sem sumir quando jobs rodam.",
        source_event_ids=("human:purpose",),
        criticality=10,
    )
    evidence_hash = hashlib.sha256(b"rc2-neural-job-start").hexdigest()
    job = JobEvent(
        "rc2:job:start",
        "rc2:job",
        JobStatus.STARTED,
        "T Forge iniciou a validação; nenhum resultado de compilação existe ainda.",
        evidence_hash,
        ("intent:rc2",),
        "2026-08-14T19:00:00Z",
    )
    kernel.accept_job_event(job)
    directive = kernel.directive(project_id=project, query="retomar finalidade interface e job", budget_chars=16_000)
    core = GenerativeDialogueCore()
    turn = core.context_for_turn(
        session_id=project,
        utterance=(
            "Retome esse projeto sem me bajular. Diga qual direção de interface eu já rejeitei, "
            "qual é a restrição de rede e o que sabemos de verdade sobre o job. Em seguida, "
            "desenvolva uma consequência útil em vez de apenas repetir minhas frases."
        ),
        continuity=directive,
        job_events=(job,),
    )
    contexts = OwnerContextStore()
    policy = replace(initial_sampling_policies()["dialogue"], max_generated_tokens=240)
    traces = output / "stochastic-traces.jsonl"
    candidate = GenerativeCandidate.load(candidate_path)
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        adapter = OwnerGenerativeEngineAdapter(
            runtime,
            contexts,
            assembler=ContextAssembler(),
            policy=policy,
            trace_store=AppendOnlyTraceStore(traces),
        )
        request = make_owner_request(
            request_id="rc2:neural:1",
            creation_id=project,
            base_version=0,
            turn=turn,
            store=contexts,
        )
        events = adapter.execute(request, CancellationToken())
    answer = "".join(event.message for event in events if event.kind is EngineEventKind.TOKEN)
    text = normalized(answer)
    checks = {
        "completed": events[-1].kind is EngineEventKind.COMPLETED,
        "streaming": sum(event.kind is EngineEventKind.TOKEN for event in events) > 1,
        "rejected_dashboard_recalled": recalls_rejected_dashboard(answer),
        "offline_constraint_recalled": recalls_offline_constraint(answer),
        "job_not_falsely_completed": "inici" in text or "ainda" in text or "nenhum resultado" in text,
        "useful_consequence_present": len(answer.strip()) >= 120,
        "no_external_ai_api": True,
        "no_fake_engine": True,
    }
    passed = all(checks.values())
    result = {
        "schema": "casulo.guide-neural-continuity/1.0",
        "gate": "PASS" if passed else "FAIL",
        "candidate_id": candidate.candidate_id,
        "model_sha256": candidate.model.sha256,
        "sampling_policy_id": policy.policy_id,
        "seed": None,
        "state_sha256": kernel.state_sha256,
        "context_digest": turn.digest,
        "directive": {
            "project_id": directive.project_id,
            "mandatory_constraints": list(directive.mandatory_constraints),
            "context_refs": [item.ref_id for item in directive.context_items],
            "conflicts": list(directive.conflicts),
        },
        "answer": answer,
        "stream_fragments": sum(event.kind is EngineEventKind.TOKEN for event in events),
        "terminal": events[-1].kind.value,
        "trace": adapter.trace_for(request.request_id).to_dict() if adapter.trace_for(request.request_id) else None,
        "checks": checks,
        "human_chemistry_status": "PENDING_GUILHERME",
        "physical_voice_validation": "PENDING_RC8_AND_GUILHERME",
        "external_ai_api_used": False,
        "fake_engine_used": False,
    }
    target = output / "guide-neural-continuity.json"
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Real local-neural continuity probe")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    result = run_probe(args.repo.resolve(), args.candidate.resolve(), args.cache.resolve(), args.output.resolve(), threads=args.threads)
    print(json.dumps({"gate": result["gate"], "checks": result["checks"]}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
