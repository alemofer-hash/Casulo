from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))


def _load_packaged_app(app: Path) -> None:
    app = app.resolve(strict=True)
    allowed = (app / "src", app / "private/casulo-owner/src")
    if not all(path.is_dir() for path in allowed):
        raise RuntimeError("release owner não contém as duas raízes Python esperadas")
    cwd = Path.cwd().resolve()
    sys.path[:] = [item for item in sys.path if item and not _is_relative(Path(item), cwd)]
    sys.path[:0] = [str(path) for path in allowed]


def _is_relative(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _verify_release(release: Path) -> dict[str, object]:
    manifest_path = release / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for item in manifest.get("files", []):
        path = release / str(item["path"])
        if not path.is_file() or path.stat().st_size != int(item["bytes"]) or _sha_file(path) != item["sha256"]:
            mismatches.append(str(item["path"]))
    return {
        "manifest_sha256": _sha_file(manifest_path),
        "files": len(manifest.get("files", [])),
        "mismatches": mismatches,
        "valid": not mismatches,
        "checkout_dependency": manifest.get("checkout_dependency"),
        "boundaries": manifest.get("boundaries"),
    }


def _request_absent(app: Path, request: str, requirements: tuple[str, ...]) -> dict[str, object]:
    needles = (request, *requirements)
    hits: dict[str, list[str]] = {needle: [] for needle in needles}
    examined = 0
    for path in app.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {".py", ".t", ".json", ".md", ".txt"}:
            continue
        examined += 1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for needle in needles:
            if needle in text:
                hits[needle].append(path.relative_to(app).as_posix())
    return {"files_examined": examined, "hits": hits, "absent": all(not value for value in hits.values())}


class StepLedger:
    def __init__(self, root: Path) -> None:
        self.path = root / "step-receipts.jsonl"
        self.previous = "0" * 64
        self.count = 0

    def add(self, step: str, facts: Mapping[str, Any], evidence: tuple[Path, ...] = ()) -> dict[str, Any]:
        self.count += 1
        base = {
            "schema": "casulo.t85-integrated-step/1.0",
            "sequence": self.count,
            "step": step,
            "facts": dict(facts),
            "evidence": [
                {"path": str(path), "sha256": _sha_file(path)} for path in evidence if path.is_file()
            ],
            "previous_receipt_hash": self.previous,
        }
        receipt = {**base, "receipt_hash": _sha_bytes(_canonical(base))}
        with self.path.open("ab") as stream:
            stream.write(_canonical(receipt))
        self.previous = receipt["receipt_hash"]
        return receipt


def _stream_dialogue(runtime: Any, cancellation: Any, idea: str) -> tuple[str, dict[str, Any]]:
    from casulo_owner.local_model_runtime import ChatMessage, GenerationRequest, ModelStreamKind, initial_sampling_policies

    request = GenerationRequest(
        "ts14-dialogue-during-job",
        (
            ChatMessage("system", "Converse em pt-BR como colega técnico. Desenvolva a ideia sem fingir conclusão e responda em até 90 palavras."),
            ChatMessage("user", f"Enquanto verificamos o release, qual é o risco conceitual mais importante nesta ideia? {idea}"),
        ),
        initial_sampling_policies()["dialogue"],
    )
    chunks: list[str] = []
    trace = None
    for event in runtime.stream_chat(request, cancellation):
        if event.kind is ModelStreamKind.TOKEN:
            chunks.append(event.content)
        elif event.kind is ModelStreamKind.COMPLETED:
            trace = event.trace
    if trace is None or not chunks:
        raise RuntimeError("diálogo neural não concluiu")
    return "".join(chunks).strip(), trace.to_dict()


def _simulation(creation: Any) -> Any:
    from casulo.product.capabilities import Effect
    from casulo.product.domain import CreationSpec, CreationState
    from casulo.product.simulation import SimulatedResponse, SimulationCapabilityDouble, SimulationPlan, SimulationRuntime, SimulationStep

    confirmation = CreationSpec(
        creation.creation_id, creation.version, CreationState.CONFIRMATION,
        creation.content, creation.capabilities, creation.rejected_delta_ids,
    )
    plan = SimulationPlan(
        f"simulation:{creation.creation_id}:{creation.version}", creation.creation_id,
        (
            SimulationStep(
                "protocol-preview", Effect.NETWORK_CONNECT, "preview",
                {"url": "simulation://replication-protocol"}, (),
                (("interface",),), (f"human:agreement:{creation.version}",),
            ),
        ),
        (f"human:agreement:{creation.version}",),
    )
    runtime = SimulationRuntime({
        Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
            Effect.NETWORK_CONNECT, (SimulatedResponse(True, {"virtual": True, "external_effect": False}),),
        )
    })
    return runtime.run(confirmation, plan)


def _graph_dict(graph: Any) -> dict[str, object]:
    return {
        "schema": "casulo.requirement-graph/2.0",
        "requirements": [item.to_dict() for item in graph.requirements],
        "dependencies": {key: list(value) for key, value in graph.dependencies.items()},
    }


def _clean_execute(imported: Any, payload: dict[str, object], root: Path) -> dict[str, object]:
    package_root = imported.extract_to(root / "package")
    env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT") if name in os.environ}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    command = [sys.executable, "-I", str(package_root / "agent.py")]
    completed = subprocess.run(
        command, input=json.dumps(payload), text=True, encoding="utf-8", capture_output=True,
        cwd=package_root, env=env, timeout=60, check=False,
    )
    server = subprocess.Popen(
        [sys.executable, "-I", str(package_root / "api.py"), "--port", "0"],
        text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=package_root, env=env,
    )
    health: dict[str, object] = {}
    try:
        if server.stdout is None:
            raise RuntimeError("stdout da API ausente")
        endpoint = json.loads(server.stdout.readline())
        with urllib.request.urlopen(f"http://127.0.0.1:{endpoint['port']}/", timeout=5) as response:
            health = json.loads(response.read())
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=5)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "api_health": health,
        "pythonpath_present": "PYTHONPATH" in env,
        "package_root_outside_checkout": not _is_relative(package_root, Path.cwd()),
        "command_contains_checkout": str(Path.cwd()).casefold() in " ".join(command).casefold(),
        "service_stopped": server.poll() is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="TS14: rehearsal integrada inédita do release T85")
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--requirement", action="append", required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if len(args.requirement) != 3 or len(set(args.requirement)) != 3:
        raise SystemExit("TS14 exige exatamente três requisitos HARD distintos")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("output existente; overwrite negado")
    output.mkdir(parents=True)
    release = args.release.resolve(strict=True)
    app = release / "OWNER_VM/app"
    release_check = _verify_release(release)
    if not release_check["valid"]:
        _dump(output / "failure.json", {"gate": "TS14_FAIL", "cause": "release diverged", "release": release_check})
        return 2
    novelty = _request_absent(app, args.idea, tuple(args.requirement))
    if not novelty["absent"]:
        _dump(output / "failure.json", {"gate": "TS14_FAIL", "cause": "holdout known by packaged app", "novelty": novelty})
        return 2

    _load_packaged_app(app)
    import casulo
    import casulo_owner
    from casulo.product.capabilities import Effect
    from casulo.product.creation_pipeline import creation_units
    from casulo.product.domain import CreationSpec, CreationState
    from casulo.product.engine_contracts import CancellationToken
    from casulo.product.guide_continuity import ConstraintStrength, RecordKind
    from casulo.product.living_memory import DpapiSecretBox
    from casulo.product.platform_contracts import SystemClock
    from casulo.product.revolution_contracts import EvidenceClass, EvidenceReceipt, Requirement, RequirementGraph, RequirementStrength, Verdict
    from casulo.product.semantic_multiverse import CancellationToken as SemanticCancellationToken
    from casulo.product.sovereign_materializer import SovereignPackageImporter, SovereignTAgentBundle
    from casulo.product.t_forge import TForge
    from casulo.t.productive import ProductiveTExecutor
    from casulo.t.v2_tcap import TcapV2Builder, verify_tcap_v2
    from casulo_owner.generative_model import GenerativeCandidate
    from casulo_owner.local_model_runtime import LocalModelRuntime
    from casulo_owner.semantic_multiverse import GenerativeUniversePlanner, OwnerSemanticMultiverse
    from casulo_owner.t85_agent_synthesis import T85AgentSynthesizer, execute_agent
    from casulo_owner.t85_authority import T85AuthorityDenied, T85OwnerCriticalAuthority
    from casulo_owner.t85_continuity import T85ContinuityService
    from casulo_owner.t85_materialization import T85SovereignMaterializer
    from casulo_owner.t85_physical_multiverse import T85PhysicalMultiverse, build_physical_universe_bundles
    from casulo_owner.t85_presence import PresenceWorkLanes, T85TurnCoordinator
    from casulo_owner.t85_requirements import TRequirementGraphCompiler

    ledger = StepLedger(output)
    protocol = {
        "schema": "casulo.t85-integrated-rehearsal-protocol/1.0",
        "idea_sha256": _sha_bytes(args.idea.encode("utf-8")),
        "requirements": list(args.requirement),
        "release": str(release),
        "release_check": release_check,
        "novelty": novelty,
        "module_roots": {"casulo": str(Path(casulo.__file__).resolve()), "casulo_owner": str(Path(casulo_owner.__file__).resolve())},
        "no_checkout_module_import": _is_relative(Path(casulo.__file__), app) and _is_relative(Path(casulo_owner.__file__), app),
        "locks": {"cloud": "RELEASE_LOCKED", "guest_network": "OFF", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
    }
    _dump(output / "protocol.json", protocol)
    ledger.add("PACKAGED_RELEASE_VERIFIED", {"manifest": release_check["manifest_sha256"], "holdout_absent": novelty["absent"], "packaged_modules": protocol["no_checkout_module_import"]}, (output / "protocol.json",))

    runtime_path = app / "t-runtime/target/release/casulo-t-runtime.exe"
    t_source_root = app / "private/casulo-owner/t-v2"
    candidate_path = app / "registry/qwen3-4b-q4km-llamacpp-b10362.json"
    candidate = GenerativeCandidate.load(candidate_path)
    continuity_tcap = T85ContinuityService.build_policy(t_source_root / "guide-context-policy.t", output / "policies/guide-context.tcap")
    continuity_root = output / "owner-data/guide-continuity"
    project_id = "ts14:mycelium-lab-replication"
    continuity = T85ContinuityService(
        continuity_root, clock=SystemClock(), secret_box=DpapiSecretBox(),
        t_runtime=runtime_path, tcap=continuity_tcap,
    )
    continuity.open_project(project_id, source_event_id="automated-acceptance:ts14:project-open")
    continuity.add_constraint(
        constraint_id="ts14:immutable-notebooks", project_id=project_id, key="source-integrity",
        statement="Os bytes dos cadernos originais nunca podem ser alterados.",
        strength=ConstraintStrength.HARD, source_event_ids=("human-contract:ts14",),
    )
    continuity.record(
        record_id="ts14:initial-intent", project_id=project_id, kind=RecordKind.DECISION,
        text=args.idea, source_event_ids=("human:ts14:idea",), criticality=9,
    )
    selection = continuity.select_context(project_id=project_id, query="micélio protocolo réplica", budget_chars=12000)
    continuity.close()
    continuity = T85ContinuityService(
        continuity_root, clock=SystemClock(), secret_box=DpapiSecretBox(),
        t_runtime=runtime_path, tcap=continuity_tcap,
    )
    resumed = continuity.recall("micélio protocolo réplica", project_id=project_id)
    ledger.add("PROJECT_RESUMED", {"context_decision": selection.decision, "recall_status": resumed.status, "provenance": list(resumed.provenance_event_ids), "t_receipt": selection.t_call.receipt["receipt_hash"]})

    turn_tcap = T85TurnCoordinator.build(t_source_root / "turn-coordinator.t", output / "policies/turn-coordinator.tcap")
    coordinator = T85TurnCoordinator(runtime_path, turn_tcap, output / "owner-data/turn-receipts")
    lanes = PresenceWorkLanes(clock=SystemClock(), coordinator=coordinator)
    release_job_gate = threading.Event()
    release_job_done = threading.Event()

    def release_integrity_job() -> bytes:
        release_job_gate.wait(timeout=180)
        result = _canonical(_verify_release(release))
        release_job_done.set()
        return result

    future = lanes.submit("ts14-release-integrity", release_integrity_job, source_event_id="ts14:rehearsal")
    candidate_trace: dict[str, Any]
    with LocalModelRuntime(candidate, args.cache.resolve(strict=True), threads=args.threads) as neural:
        reply, dialogue_trace = _stream_dialogue(neural, CancellationToken(), args.idea)
        release_job_gate.set()
        job_payload = json.loads(future.result(timeout=180))
        if not release_job_done.is_set() or not job_payload["valid"]:
            raise RuntimeError("job de integridade não concluiu de forma válida")
        job_events = [
            {"event_id": item.event_id, "status": item.status.value, "evidence_sha256": item.evidence_sha256}
            for item in lanes.events
        ]
        ledger.add("DIALOGUE_DURING_REAL_JOB", {"reply_sha256": _sha_bytes(reply.encode("utf-8")), "trace": dialogue_trace, "job_events": job_events})

        synthesizer = T85AgentSynthesizer(neural)
        plan = synthesizer.propose(
            case_id="ts14-mycelium-holdout", request=args.idea,
            hard_requirements=tuple(args.requirement), cancellation=CancellationToken(),
        )
        build = synthesizer.build(plan, output / "generated-agent")
        execution = execute_agent(build, runtime_path, output / "generated-agent/hosted-calls")
        candidate_trace = plan.trace.to_dict()
        _dump(output / "neural-dialogue.json", {"reply": reply, "trace": dialogue_trace})
        _dump(output / "agent-plan.json", {
            "case_id": plan.case_id, "request": plan.request, "agent_id": plan.agent_id,
            "summary": plan.summary, "module_suffixes": list(plan.module_suffixes),
            "constraints": [dict(item) for item in plan.constraints], "trace": candidate_trace,
            "raw_sha256": plan.raw_sha256, "rejected_candidates": [dict(item) for item in plan.rejected_candidates],
        })
        _dump(output / "agent-runtime-receipts.json", [dict(item.receipt) for item in execution.calls])
        _root, tcap_manifest, typed = verify_tcap_v2(build.tcap.directory)
        ledger.add("NOVEL_T_AGENT_EXECUTED", {
            "agent_id": plan.agent_id, "modules": len(typed["modules"]),
            "functions": sum(len(module["functions"]) for module in typed["modules"]),
            "runtime_receipts": len(execution.calls), "final": execution.final_value,
            "tcap_hash": tcap_manifest["tcap_hash"], "neural_trace": candidate_trace,
        }, (output / "agent-plan.json", output / "agent-runtime-receipts.json"))

        planner = GenerativeUniversePlanner(neural)
        route_errors: list[str] = []
        proposal = None
        for attempt in range(1, 4):
            try:
                proposal = planner.propose(args.idea, operation_id=f"ts14-route-{attempt}", cancellation=CancellationToken())
                break
            except RuntimeError as error:
                route_errors.append(str(error))
        if proposal is None:
            raise RuntimeError(f"rota neural falhou após três candidatos: {route_errors}")
    lanes.close()

    graph = RequirementGraph(tuple(
        Requirement(
            f"ts14:{requirement}", requirement.replace("_", " "), RequirementStrength.HARD,
            1.0, ("human:ts14:idea",), (f"agent-runtime:{requirement}",), project_id,
        )
        for requirement in args.requirement
    ))
    evidence = tuple(
        EvidenceReceipt(
            f"evidence:ts14:{requirement}", f"ts14:{requirement}", f"agent-runtime:{requirement}",
            Verdict.PASS, EvidenceClass.CLEAN_EXECUTION, build.tcap.tcap_hash,
            "t-runtime/rust-2.0", (execution.calls[index].receipt["canonical_output_hash"],),
            "2026-08-15T00:00:00Z", "função T dedicada produziu o evento canônico do requisito",
        )
        for index, requirement in enumerate(args.requirement)
    )
    compiler = TRequirementGraphCompiler()
    partial = compiler.compile(graph, evidence[:2], project_id=project_id, candidate_project_id=project_id)
    critical_sources = tuple(sorted(t_source_root.glob("critical-*.t")))
    critical_tcap = TcapV2Builder().build(
        critical_sources, output / "policies/critical.tcap",
        entry_module="owner.critical.intent", entry_function="decide",
    ).directory
    denied_reason = ""
    try:
        T85OwnerCriticalAuthority(runtime_path, critical_tcap, output / "semantic-failure").decide(
            decision_id="ts14.failure", creation_id=project_id,
            model_proposed=True, human_confirmed=True, material=True,
            requested_capabilities=("simulation", "manifest"), granted_capabilities=("simulation", "manifest"),
            consent_valid=True, **partial.authority_inputs(), safety_pass=True, unsupported_claims=(),
            simulation_status="PASS", human_publish_approval=True,
        )
    except T85AuthorityDenied as error:
        denied_reason = str(error)
    if not denied_reason:
        raise RuntimeError("evidência HARD incompleta foi aceita")
    repaired = compiler.compile(graph, evidence, project_id=project_id, candidate_project_id=project_id)
    decisions = T85OwnerCriticalAuthority(runtime_path, critical_tcap, output / "semantic-repair").decide(
        decision_id="ts14.repair", creation_id=project_id,
        model_proposed=True, human_confirmed=True, material=True,
        requested_capabilities=("simulation", "manifest"), granted_capabilities=("simulation", "manifest"),
        consent_valid=True, **repaired.authority_inputs(), safety_pass=True, unsupported_claims=(),
        simulation_status="PASS", human_publish_approval=True,
    )
    _dump(output / "semantic-repair.json", {
        "initial_failure": denied_reason,
        "repair": "missing independent runtime evidence attached",
        "evidence_plan_hash": repaired.evidence_plan_hash,
        "decision_receipts": list(decisions.receipt_chain), "committed": decisions.committed,
    })
    ledger.add("SEMANTIC_FAILURE_REPAIRED", {"failure": denied_reason, "commit": decisions.committed, "T_receipts": list(decisions.receipt_chain)}, (output / "semantic-repair.json",))

    sentinel = output / "forbidden-effect-sentinel"
    publish_module = f"owner.agent.{plan.agent_id}.{plan.module_suffixes[2]}"
    denied_call = ProductiveTExecutor(runtime_path, build.tcap.directory, output / "capability-denial").execute(
        publish_module, "simulate",
        {"previous": "WORKFLOW_READY", "simulated": True, "approved": False, "cancelled": False},
        call_id="ts14.capability.denied", surface_id="agent_behavior", scope_id=f"agent:{project_id}",
    )
    denied_result = denied_call.observable.get("result")
    if denied_result != {"kind": "error", "value": "CAPABILITY_DENIED:simulation"} or sentinel.exists():
        raise RuntimeError("capability denial não permaneceu fail-closed")
    ledger.add("CAPABILITY_DENIED_NO_EFFECT", {"result": denied_result, "sentinel_absent": not sentinel.exists(), "T_receipt": denied_call.receipt["receipt_hash"]})

    semantic = OwnerSemanticMultiverse(output / "owner-data/semantic-multiverse")
    physical_root = semantic.root / "physical-universe-store"
    build_physical_universe_bundles(physical_root, semantic.manifests, policy_source=t_source_root / "universe-lifecycle-policy.t")
    lifecycle_tcap = T85PhysicalMultiverse.build_policy(t_source_root / "universe-lifecycle-policy.t", output / "policies/universe-lifecycle.tcap")
    physical = T85PhysicalMultiverse(runtime_path, lifecycle_tcap, physical_root, output / "owner-data/physical-receipts", minimum_residence_ns=1_000_000)
    semantic.attach_physical_runtime(physical)
    session = semantic.execute(
        proposal, idea=args.idea, constraints=tuple(args.requirement), confirmed=True,
        cancellation=SemanticCancellationToken(), confirmation_source="AUTOMATED_ACCEPTANCE_SCENARIO",
    )
    _dump(output / "semantic-session.json", session)
    ledger.add("PHYSICAL_UNIVERSES_ACTIVATED", {
        "route": list(proposal.route), "route_errors": route_errors,
        "lifecycle_receipts": len(session["lifecycle_receipts"]),
        "transition_receipts": len(session["transition_receipts"]),
        "physical_receipts": len(session["physical_lifecycle_receipts"]),
        "hot": session["hot_at_completion"], "strict_hot_subset": session["strict_hot_subset"],
    }, (output / "semantic-session.json",))

    content = {
        "identity": {"name": "Guardião Micelial", "purpose": plan.summary},
        "behavior": {"tone": "científico, rastreável e explícito sobre incerteza"},
        "interface": {"channel": "voice-first com fallback textual"},
        "constraints": list(args.requirement),
        "provenance": ["human:ts14:idea", plan.trace.output_sha256, session["confirmed_delta_hash"]],
    }
    creation_v1 = CreationSpec(
        "creation:ts14-mycelium-replication", 1, CreationState.AGREEMENT,
        content, frozenset({Effect.NETWORK_CONNECT.value}),
    )
    simulation_v1 = _simulation(creation_v1)
    if simulation_v1.status != "PASS" or simulation_v1.real_effects_executed:
        raise RuntimeError("simulação não permaneceu sem efeitos reais")
    ledger.add("SIMULATION_PASS", {"status": simulation_v1.status, "events": len(simulation_v1.events), "real_effects": simulation_v1.real_effects_executed, "head_hash": simulation_v1.head_hash})

    agent = SovereignTAgentBundle(
        build.tcap.directory, runtime_path,
        f"owner.agent.{plan.agent_id}.{plan.module_suffixes[0]}", "decide",
        f"owner.agent.{plan.agent_id}",
        {"schema": "casulo.generated-project/2.0", "neural_trace_sha256": _sha_bytes(_canonical(candidate_trace)), "holdout": True},
    )
    graph_payload = _graph_dict(graph)
    evidence_payload = {"schema": "casulo.evidence-set/1.0", "receipts": [item.to_dict() for item in evidence]}

    def materialize(root: Path, creation: Any, simulation_receipt: Any) -> Any:
        policy = T85SovereignMaterializer.build_policy(t_source_root / "materialization-lifecycle.t", root / "materialization-policy.tcap")
        authority = T85SovereignMaterializer(runtime_path, policy, root / "exports", root / "authority")
        return authority.materialize(
            creation, forge_receipt=TForge().compile(creation_units(creation)),
            simulation_receipt=simulation_receipt, agent=agent,
            requirement_graph=graph_payload, evidence_receipts=evidence_payload,
            previous_fulfillment="FULFILLED", human_approved=True,
        )

    v1 = materialize(output / "materialization/v1", creation_v1, simulation_v1)
    importer = SovereignPackageImporter()
    imported_v1 = importer.import_archive(v1.receipt.archive)
    content_v2 = json.loads(json.dumps(dict(imported_v1.creation.content), ensure_ascii=False))
    content_v2["behavior"]["tone"] = "científico, conciso e explícito sobre incerteza e unidades"
    content_v2["provenance"] = [*content_v2["provenance"], f"archive:{v1.receipt.archive_sha256}"]
    creation_v2 = CreationSpec(
        imported_v1.creation.creation_id, 2, CreationState.AGREEMENT, content_v2,
        imported_v1.creation.capabilities, imported_v1.creation.rejected_delta_ids,
    )
    v2 = materialize(output / "materialization/v2", creation_v2, _simulation(creation_v2))
    imported_v2 = importer.import_archive(v2.receipt.archive)
    payload = {
        "confirmed": True, "project_match": True, "evidence_statuses": ["PASS"] * 3,
        **{item["field_name"]: True for item in plan.constraints}, "cancelled": False,
    }
    with tempfile.TemporaryDirectory(prefix="casulo-ts14-clean-") as temporary:
        clean = _clean_execute(imported_v2, payload, Path(temporary))
    clean_document = json.loads(str(clean["stdout"])) if clean["returncode"] == 0 else {}
    round_trip = {
        "v1_exact": imported_v1.creation.sha256 == creation_v1.sha256,
        "v2_exact": imported_v2.creation.sha256 == creation_v2.sha256,
        "identity_preserved": imported_v2.creation.creation_id == imported_v1.creation.creation_id,
        "edit_applied": imported_v2.creation.content["behavior"]["tone"] == content_v2["behavior"]["tone"],
        "provenance_superseded": imported_v2.creation.content["provenance"][:-1] == imported_v1.creation.content["provenance"],
    }
    _dump(output / "materialization.json", {
        "v1": {"archive": str(v1.receipt.archive), "sha256": v1.receipt.archive_sha256},
        "v2": {"archive": str(v2.receipt.archive), "sha256": v2.receipt.archive_sha256},
        "clean": clean, "round_trip": round_trip,
    })
    ledger.add("MATERIALIZED_EXECUTED_REIMPORTED_EDITED", {
        "clean_returncode": clean["returncode"],
        "runtime_result": clean_document.get("observable", {}).get("result"),
        "api_health": clean["api_health"], "round_trip": round_trip,
        "v2_archive_sha256": v2.receipt.archive_sha256,
    }, (output / "materialization.json", v2.receipt.archive))

    continuity.record(
        record_id="ts14:materialized", project_id=project_id, kind=RecordKind.DECISION,
        text=f"Pacote materializado e reeditado: {v2.receipt.archive_sha256}",
        source_event_ids=(v2.receipt.archive_sha256,), criticality=10,
    )
    continuity.close()
    reboot = semantic.reboot()
    continuity = T85ContinuityService(
        continuity_root, clock=SystemClock(), secret_box=DpapiSecretBox(),
        t_runtime=runtime_path, tcap=continuity_tcap,
    )
    recall = continuity.recall("pacote materializado reeditado", project_id=project_id)
    continuity.close()
    ledger.add("REBOOT_AND_RECALL", {"hot_after_reboot": reboot["hot_after_reboot"], "false_hot_persistence": reboot["false_hot_persistence"], "recall_status": recall.status, "provenance": list(recall.provenance_event_ids)})

    checks = {
        "packaged_release_verified": release_check["valid"] and protocol["no_checkout_module_import"],
        "novel_request_absent_from_package": novelty["absent"],
        "real_qwen_stochastic": candidate_trace["model_sha256"] == candidate.model.sha256 and candidate_trace["seed_if_available"] is None and not candidate_trace["external_network_used"],
        "dialogue_during_job": len(job_events) == 2 and job_events[0]["status"] == "STARTED" and job_events[1]["status"] == "COMPLETED",
        "nontrivial_t_agent": len(typed["modules"]) >= 3 and sum(len(module["functions"]) for module in typed["modules"]) >= 10 and execution.final_value == "AUDITED",
        "semantic_failure_then_repair": bool(denied_reason) and decisions.committed,
        "physical_multiverse": len(session["physical_lifecycle_receipts"]) >= len(proposal.route) and session["strict_hot_subset"],
        "simulation_no_real_effect": simulation_v1.status == "PASS" and not simulation_v1.real_effects_executed,
        "materialization_clean_execution": clean["returncode"] == 0 and clean_document.get("observable", {}).get("result") == {"kind": "ok", "value": "READY"} and not clean["pythonpath_present"] and not clean["command_contains_checkout"],
        "round_trip_edit": all(round_trip.values()),
        "reboot_recall": reboot["hot_after_reboot"] == [] and recall.status == "FOUND",
        "capability_denied_without_effect": denied_result == {"kind": "error", "value": "CAPABILITY_DENIED:simulation"} and not sentinel.exists(),
        "no_fake_replay_template": candidate_trace["model_id"] == candidate.candidate_id and plan.raw_sha256 == candidate_trace["output_sha256"],
        "receipt_chain": ledger.count >= 10,
    }
    result = {
        "schema": "casulo.t85-integrated-rehearsal/1.0",
        "gate": "TS14_INTEGRATED_REHEARSAL_PASS" if all(checks.values()) else "TS14_FAIL",
        "checks": checks, "steps": ledger.count, "step_chain_head": ledger.previous,
        "model": {"candidate_id": candidate.candidate_id, "sha256": candidate.model.sha256, "runtime": "llama.cpp-local-loopback"},
        "agent": {"agent_id": plan.agent_id, "tcap_hash": build.tcap.tcap_hash, "modules": len(typed["modules"]), "functions": sum(len(module["functions"]) for module in typed["modules"])},
        "semantic_route": list(proposal.route), "materialized_archive_sha256": v2.receipt.archive_sha256,
        "claims": ["automated owner rehearsal over one novel request", "packaged app plus verified cached Qwen3-4B and llama.cpp", "T decisions and Rust runtime receipts retained"],
        "limitations": ["automated acceptance is not Guilherme human proof", "semantic repair attaches missing independent evidence; it is not neural source repair", "host Python remains a declared compatibility dependency"],
        "locks": protocol["locks"],
    }
    _dump(output / "integrated-rehearsal.json", result)
    ledger.add("GATE_EVALUATED", {"gate": result["gate"], "checks": checks}, (output / "integrated-rehearsal.json",))
    result["steps"] = ledger.count
    result["step_chain_head"] = ledger.previous
    _dump(output / "gate.json", result)
    print(json.dumps({"gate": result["gate"], "agent": plan.agent_id, "route": list(proposal.route), "steps": ledger.count}, ensure_ascii=False, indent=2))
    return 0 if result["gate"].endswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
