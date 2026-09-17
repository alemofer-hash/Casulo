from __future__ import annotations

import argparse
import hashlib
import json
import time
import webbrowser
from pathlib import Path

from casulo.product.engine_contracts import CancellationToken as EngineCancellationToken
from casulo.product.guide_continuity import RecordKind
from casulo.product.living_memory import DpapiSecretBox
from casulo.product.platform_contracts import SystemClock
from casulo.product.semantic_multiverse import CancellationToken as SemanticCancellationToken
from casulo.product.vm_controller import CasuloVMController, VMProfile
from casulo_owner.generative_agent_probe import run_probe
from casulo_owner.generative_engine import AppendOnlyTraceStore
from casulo_owner.generative_model import GenerativeCandidate
from casulo_owner.inspection import OwnerInspectionRecorder
from casulo_owner.local_model_runtime import LocalModelRuntime
from casulo_owner.semantic_multiverse import GenerativeUniversePlanner, OwnerSemanticMultiverse
from casulo_owner.t85_continuity import T85ContinuityService
from casulo_owner.t85_presence import T85TurnCoordinator
from casulo_owner.t85_physical_multiverse import T85PhysicalMultiverse, build_physical_universe_bundles

try:
    from tools.casulo_owner_vm_inspect import QEMU, QEMU_IMG, OVMF_CODE, OVMF_VARS, dialogue_turn, recoverable_error, render_creation_timeline
except ModuleNotFoundError:
    from casulo_owner_vm_inspect import QEMU, QEMU_IMG, OVMF_CODE, OVMF_VARS, dialogue_turn, recoverable_error, render_creation_timeline


def prepare_semantic_controller(source_image: Path, vm_root: Path) -> CasuloVMController:
    """Create only a sparse overlay; the immutable G10 base is never copied."""
    vm_root.mkdir(parents=True, exist_ok=True)
    controller = CasuloVMController(
        VMProfile(QEMU, QEMU_IMG, OVMF_CODE, OVMF_VARS, source_image.resolve(strict=True), vm_root / "state")
    )
    if not controller.overlay_path.exists():
        controller.create()
        controller.snapshot("clean-semantic-multiverse")
    return controller


def prepare_owner_semantic(repo: Path, vm_root: Path) -> OwnerSemanticMultiverse:
    semantic = OwnerSemanticMultiverse(vm_root / "owner-data" / "semantic-multiverse")
    policy = repo / "private/casulo-owner/t-v2/universe-lifecycle-policy.t"
    physical_root = semantic.root / "physical-universe-store"
    build_physical_universe_bundles(physical_root, semantic.manifests, policy_source=policy)
    policy_hash = hashlib.sha256(policy.read_bytes()).hexdigest()[:16]
    tcap = T85PhysicalMultiverse.build_policy(
        policy, vm_root / "owner-data" / f"t85-universe-lifecycle-{policy_hash}.tcap",
    )
    physical = T85PhysicalMultiverse(
        repo / "t-runtime/target/release/casulo-t-runtime.exe", tcap, physical_root,
        vm_root / "owner-data/physical-lifecycle-receipts" / f"session-{time.time_ns()}",
        minimum_residence_ns=1_000_000,
    )
    semantic.attach_physical_runtime(physical)
    return semantic


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspeção Casulo owner Semantic Multiverse na VM")
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--vm-root", type=Path, required=True)
    parser.add_argument("--feedback-root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    vm_root, feedback_root = args.vm_root.resolve(), args.feedback_root.resolve()
    controller = prepare_semantic_controller(args.source_image, vm_root)
    doctor = controller.doctor()
    if not doctor["ready"]:
        raise SystemExit("VM doctor reprovou; nenhuma sessão iniciada")
    candidate = GenerativeCandidate.load(args.candidate)
    semantic = prepare_owner_semantic(args.repo.resolve(), vm_root)
    reboot = semantic.reboot()
    policy_tcap = T85ContinuityService.build_policy(
        args.repo.resolve() / "private/casulo-owner/t-v2/guide-context-policy.t",
        vm_root / "owner-data/t85-guide-context.tcap",
    )
    continuity = T85ContinuityService(
        vm_root / "owner-data/guide-continuity",
        clock=SystemClock(), secret_box=DpapiSecretBox(),
        t_runtime=args.repo.resolve() / "t-runtime/target/release/casulo-t-runtime.exe",
        tcap=policy_tcap,
    )
    turn_tcap = T85TurnCoordinator.build(
        args.repo.resolve() / "private/casulo-owner/t-v2/turn-coordinator.t",
        vm_root / "owner-data/t85-turn-coordinator.tcap",
    )
    turn_coordinator = T85TurnCoordinator(
        args.repo.resolve() / "t-runtime/target/release/casulo-t-runtime.exe",
        turn_tcap,
        vm_root / "owner-data/turn-coordinator-receipts",
    )
    project_id = "guilherme:semantic-live"
    if project_id not in continuity.kernel.snapshot()["projects"]:
        continuity.open_project(project_id, source_event_id="human:semantic-live:open")
    recorder = OwnerInspectionRecorder(feedback_root / "active-session", session_id="guilherme:semantic-live")
    trace_store = AppendOnlyTraceStore(feedback_root / "active-session" / "stochastic-traces.jsonl")
    conversation = []
    last_route: dict[str, object] | None = None
    print("Casulo owner · Semantic Multiverse · pt-BR · Cloud OFF · rede guest OFF")
    print(f"Catálogo retomado: {reboot['sessions']} sessão(ões); HOT reiniciado corretamente como vazio.")
    print("Comandos: :criar, :universos, :rota, :memoria, :nota, :snapshot, :restore, :export, :sair.")
    with LocalModelRuntime(candidate, args.cache.resolve(), threads=args.threads) as runtime:
        while True:
            try:
                text = input("\nVocê › ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSessão encerrada; bases e deltas confirmados permanecem.")
                break
            if not text:
                continue
            if text == ":sair":
                break
            if text == ":universos":
                print(json.dumps(semantic.inspect(), ensure_ascii=False, indent=2))
                continue
            if text == ":rota":
                print(json.dumps(last_route or {"status": "nenhuma rota nesta sessão"}, ensure_ascii=False, indent=2))
                continue
            if text == ":memoria":
                print(json.dumps({"runtime": semantic.inspect(), "gc_dry_run": semantic.gc_plan(), "living_memory_events": len(continuity.memory.events), "continuity_state_sha256": continuity.kernel.state_sha256}, ensure_ascii=False, indent=2))
                continue
            if text == ":snapshot":
                try:
                    print(json.dumps(controller.snapshot("guilherme-semantic-live"), ensure_ascii=False))
                except Exception as error:
                    print(json.dumps(recoverable_error("snapshot", error), ensure_ascii=False))
                continue
            if text == ":restore":
                try:
                    semantic.shutdown_physical()
                    print(json.dumps(controller.restore("guilherme-semantic-live"), ensure_ascii=False))
                    semantic = prepare_owner_semantic(args.repo.resolve(), vm_root)
                    print(json.dumps(semantic.reboot(), ensure_ascii=False))
                except Exception as error:
                    print(json.dumps(recoverable_error("restore", error), ensure_ascii=False))
                continue
            if text == ":nota":
                note = input("Nota › ").strip()
                recorder.record(note_id=f"note:semantic:{recorder.note_count + 1}", channel="text", category="DESIRED_CHANGE", text=note, creation_id="creation:semantic-live", creation_version=0, creation_state="LISTENING", source_event_ids=("human:semantic-note",))
                print("Nota preservada; ela não altera rotas nem capabilities.")
                continue
            if text == ":export":
                result = recorder.export(feedback_root / "semantic-multiverse-feedback", environment={"cloud": "RELEASE_LOCKED", "network": "denied", "usb": "prohibited"})
                print(json.dumps(result, ensure_ascii=False))
                continue
            if text == ":criar":
                idea = input("Ideia inédita multiuniverso › ").strip()
                expectation = input("Frase/comportamento que precisa aparecer › ").strip()
                route_cancellation = EngineCancellationToken()
                proposal = GenerativeUniversePlanner(runtime).propose(idea, operation_id=f"semantic-route-{semantic.catalog.snapshot.version}-{len(list((semantic.root / 'sessions').glob('*.json'))) if (semantic.root / 'sessions').exists() else 0}", cancellation=route_cancellation)
                print("Rota neural proposta: " + " → ".join(proposal.route))
                print(proposal.rationale)
                if input("Digite CONFIRMO para validar a rota, gerar/reparar T e materializar › ").strip() != "CONFIRMO":
                    print("Rota rejeitada; nenhum delta, criação ou sessão foi publicado.")
                    continue
                controller.bridge_boot("owner-job-accepted-semantic-multiverse", acceleration="tcg", timeout=60)
                owner_data = vm_root / "owner-data"
                owner_data.mkdir(parents=True, exist_ok=True)
                destination = owner_data / f"semantic-creation-{len(list(owner_data.glob('semantic-creation-*'))) + 1}"
                try:
                    creation = run_probe(candidate, args.cache.resolve(), destination, repo=args.repo.resolve(), idea=idea, holdout_expectation=expectation, threads=args.threads)
                    print(f"Artifact materializado: {creation['materialization']['archive']}")
                    last_route = semantic.execute(proposal, idea=idea, constraints=("sem API externa", "capabilities deny-by-default", "somente efeitos simulados antes do acordo"), confirmed=True, cancellation=SemanticCancellationToken())
                    (destination / "semantic-session.json").write_text(json.dumps(last_route, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
                    semantic_visual = semantic.render(last_route, destination / "semantic-visual")
                    continuity.record(
                        record_id=f"{project_id}:{destination.name}", project_id=project_id,
                        kind=RecordKind.DECISION, text=idea,
                        source_event_ids=(f"artifact:{creation['materialization']['archive']}",), criticality=9,
                    )
                    print("Universos: " + " → ".join(last_route["universes_visited"]))
                    print(f"Mapa semântico: {semantic_visual}")
                    try:
                        creation_visual = render_creation_timeline(destination, creation, destination / "visual")
                        print(f"Forma da criação: {creation_visual['index']}")
                        webbrowser.open(semantic_visual.as_uri())
                    except Exception as error:
                        print(json.dumps(recoverable_error("visualization", error, destination), ensure_ascii=False))
                except Exception as error:
                    print(json.dumps(recoverable_error("creation", error, destination), ensure_ascii=False))
                continue
            print("Casulo › ", end="", flush=True)
            try:
                turn = turn_coordinator.decide(
                    event_kind="TEXT_FINAL", speech_detected=False,
                    transcript_final=True, transcript_nonempty=bool(text.strip()),
                    tts_active=False,
                )
                if turn.value != "COMMIT_FINAL":
                    raise RuntimeError("T TurnCoordinator não consolidou o turno final")
                controller.bridge_boot(lambda: " ".join(dialogue_turn(runtime, trace_store, conversation, text, continuity=continuity, project_id=project_id).split()), acceleration="tcg", timeout=900)
            except KeyboardInterrupt:
                continue
    semantic.shutdown_physical()
    continuity.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps(recoverable_error("launcher", error), ensure_ascii=False))
        raise SystemExit(2)
