from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from casulo.product.engine_contracts import CancellationToken as EngineCancellationToken
from casulo.product.creative_interlocution import (
    CreativeIntentProjection,
    GuideIdentityStore,
    humanize_engineering_progress,
)
from casulo.product.discovery_transport import DIALOGUE_TRANSPORTS, deliver_dialogue
from casulo.product.guide_continuity import RecordKind
from casulo.product.intent_reconstruction import IntentTaskKind, IntentTwinRenderer
from casulo.product.living_memory import DpapiSecretBox
from casulo.product.math_boundary import profile_similarity_kernels, verify_similarity_equivalence
from casulo.product.platform_contracts import LocalStorage, SystemClock
from casulo.product.pleasant_interface import (
    HonestBackgroundJob,
    JobEvidence,
    UxEvent,
    UxEventKind,
    encode_ux_event,
)
from casulo.product.semantic_multiverse import CancellationToken as SemanticCancellationToken
from casulo.product.vm_controller import CasuloVMController, VMProfile
from casulo_owner.generative_agent_probe import run_probe
from casulo_owner.generative_engine import AppendOnlyTraceStore
from casulo_owner.generative_model import GenerativeCandidate
from casulo_owner.inspection import OwnerInspectionRecorder
from casulo_owner.intent_reconstruction import IntentReconstructionEngine
from casulo_owner.local_model_runtime import LocalModelRuntime
from casulo_owner.math_boundary import OwnerMathBoundary, select_safe_reference_when_t_unavailable
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


def prepare_owner_math_kernel(repo: Path, vm_root: Path):
    """Qualify one bounded kernel; losing or unavailable T keeps the reference."""

    policy = repo / "private/casulo-owner/t-v2/math-boundary-policy.t"
    policy_hash = hashlib.sha256(policy.read_bytes()).hexdigest()[:16]
    try:
        tcap = OwnerMathBoundary.build_policy(
            policy,
            vm_root / "owner-data" / f"t85-math-boundary-{policy_hash}.tcap",
        )
        boundary = OwnerMathBoundary(
            repo / "t-runtime/target/release/casulo-t-runtime.exe",
            tcap,
            vm_root / "owner-data/math-boundary-receipts" / f"session-{time.time_ns()}",
        )
        selection = boundary.decide(
            verify_similarity_equivalence(),
            profile_similarity_kernels(rounds=5, repetitions=100),
        )
    except Exception as error:
        selection = select_safe_reference_when_t_unavailable(error)
    return selection


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspeção Casulo owner Semantic Multiverse na VM")
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--vm-root", type=Path, required=True)
    parser.add_argument("--feedback-root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument(
        "--dialogue-transport",
        choices=DIALOGUE_TRANSPORTS,
        default="vm-bridge",
        help="vm-bridge preserva a prova selada; host-direct serve apenas à descoberta UX",
    )
    parser.add_argument(
        "--ui-mode",
        choices=("terminal", "gui-stream", "arc-stream"),
        default="terminal",
        help="arc-stream usa eventos estruturados incrementais; gui-stream preserva o transporte legado",
    )
    args = parser.parse_args()
    ux_lock = threading.RLock()
    ux_sequence = 0

    def emit_ux(kind: UxEventKind, payload: dict[str, object], *source_event_ids: str) -> None:
        nonlocal ux_sequence
        if args.ui_mode != "arc-stream":
            return
        with ux_lock:
            ux_sequence += 1
            event = UxEvent.create(
                event_id=f"ux:{ux_sequence:08d}",
                kind=kind,
                payload=payload,
                source_event_ids=tuple(source_event_ids) or ("owner:runtime",),
                occurred_at=datetime.now(timezone.utc).isoformat(),
            )
            print(encode_ux_event(event), flush=True)

    def ask_user(prompt: str, *, input_kind: str) -> str:
        if args.ui_mode == "arc-stream":
            emit_ux(
                UxEventKind.INPUT_REQUEST,
                {"prompt": prompt, "input_kind": input_kind},
                "owner:input-request",
            )
            return input().strip()
        return input(prompt).strip()

    def show(text: str, *, code: str = "NOTICE") -> None:
        visible = text if len(text) <= 16_000 else text[:16_000] + "\n[saída visual limitada; artifact integral preservado]"
        if args.ui_mode == "arc-stream":
            emit_ux(UxEventKind.NOTICE, {"code": code, "text": visible}, "owner:visible-notice")
        else:
            print(visible, flush=True)

    def file_sha256(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    vm_root, feedback_root = args.vm_root.resolve(), args.feedback_root.resolve()
    guide_identity_store = GuideIdentityStore(LocalStorage(vm_root / "owner-data" / "guide-profile"))
    guide_identity = guide_identity_store.load()
    controller = prepare_semantic_controller(args.source_image, vm_root)
    doctor = controller.doctor()
    if not doctor["ready"]:
        raise SystemExit("VM doctor reprovou; nenhuma sessão iniciada")
    candidate = GenerativeCandidate.load(args.candidate)
    semantic = prepare_owner_semantic(args.repo.resolve(), vm_root)
    reboot = semantic.reboot()
    math_selection = prepare_owner_math_kernel(args.repo.resolve(), vm_root)
    policy_tcap = T85ContinuityService.build_policy(
        args.repo.resolve() / "private/casulo-owner/t-v2/guide-context-policy.t",
        vm_root / "owner-data/t85-guide-context.tcap",
    )
    continuity = T85ContinuityService(
        vm_root / "owner-data/guide-continuity",
        clock=SystemClock(), secret_box=DpapiSecretBox(),
        t_runtime=args.repo.resolve() / "t-runtime/target/release/casulo-t-runtime.exe",
        tcap=policy_tcap,
        similarity_kernel=math_selection.kernel(),
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
    state_lock = threading.RLock()
    if args.ui_mode != "arc-stream":
        print(f"{guide_identity.name} · criação local · pt-BR · Cloud OFF · rede guest OFF")
        print(f"Catálogo retomado: {reboot['sessions']} sessão(ões); HOT reiniciado corretamente como vazio.")
        print(f"Álgebra da memória: {math_selection.selected_kernel} · {math_selection.reason}")
        print("Comandos: :criar, :nome, :universos, :rota, :memoria, :nota, :snapshot, :restore, :export, :cancelar, :sair.")
    emit_ux(
        UxEventKind.PRESENCE_READY,
        {"text": "Estou aqui. Você já pode começar; o motor local termina de acordar em paralelo."},
        "owner:presence-ready",
    )
    if args.dialogue_transport == "host-direct":
        print("Perfil de interação: DISCOVERY_FAST_HOST_DIALOGUE · ponte VM preservada para criação · não é selo de release.")
    if args.ui_mode != "arc-stream":
        print("Casulo status · MODEL_LOADING")
    emit_ux(UxEventKind.MODEL_LOADING, {"text": "Acordando o motor local…"}, "owner:model-loading")
    with LocalModelRuntime(candidate, args.cache.resolve(), threads=args.threads) as runtime:
        if args.ui_mode != "arc-stream":
            print("Casulo status · MODEL_READY")
        emit_ux(UxEventKind.MODEL_READY, {"text": "Pronto."}, "owner:model-ready")

        def on_job_event(event) -> None:
            kind = {
                "STARTED": UxEventKind.JOB_STARTED,
                "MILESTONE": UxEventKind.JOB_MILESTONE,
                "COMPLETED": UxEventKind.JOB_COMPLETED,
                "FAILED": UxEventKind.JOB_FAILED,
                "CANCELLED": UxEventKind.JOB_CANCELLED,
            }[event.status]
            visible_summary = humanize_engineering_progress(event.summary)
            emit_ux(
                kind,
                {
                    "job_id": event.job_id,
                    "summary": visible_summary,
                    "engineering_summary": event.summary,
                    "evidence_sha256": event.evidence_sha256,
                    "sequence": event.sequence,
                },
                f"job:{event.job_id}",
            )
            if args.ui_mode != "arc-stream":
                print(f"{guide_identity.name} · {visible_summary}", flush=True)

        creation_job = HonestBackgroundJob(on_job_event)
        while True:
            try:
                text = input("" if args.ui_mode == "gui-stream" else "\nVocê › ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSessão encerrada; bases e deltas confirmados permanecem.")
                break
            if not text:
                continue
            if text == ":sair":
                if creation_job.active:
                    creation_job.cancel()
                    creation_job.join(15)
                break
            if text == ":cancelar":
                cancelled = creation_job.cancel()
                message = "Cancelamento solicitado; nenhum resultado tardio será publicado." if cancelled else "Não há criação ativa para cancelar."
                emit_ux(UxEventKind.NOTICE, {"code": "CANCEL_REQUEST", "text": message}, "human:cancel")
                if args.ui_mode != "arc-stream":
                    print(message)
                continue
            if text == ":nome":
                chosen_name = ask_user(
                    "Como você quer chamar quem vai criar com você? ",
                    input_kind="GUIDE_NAME",
                )
                try:
                    guide_identity = guide_identity.renamed(
                        chosen_name,
                        human_event_id=f"human:guide-name:{time.time_ns()}",
                        explicit_human_choice=True,
                    )
                    guide_identity_store.save(guide_identity)
                    show(
                        f"Fechado. A partir de agora, pode me chamar de {guide_identity.name}.",
                        code="GUIDE_NAMED",
                    )
                except Exception as error:
                    show(
                        json.dumps(recoverable_error("guide-name", error), ensure_ascii=False),
                        code="RECOVERABLE_ERROR",
                    )
                continue
            if text == ":universos":
                show(json.dumps(semantic.inspect(), ensure_ascii=False, indent=2), code="UNIVERSES")
                continue
            if text == ":rota":
                with state_lock:
                    route_snapshot = last_route
                show(json.dumps(route_snapshot or {"status": "nenhuma rota nesta sessão", "job": creation_job.snapshot()}, ensure_ascii=False, indent=2), code="ROUTE")
                continue
            if text == ":memoria":
                show(json.dumps({"runtime": semantic.inspect(), "gc_dry_run": semantic.gc_plan(), "living_memory_events": len(continuity.memory.events), "continuity_state_sha256": continuity.kernel.state_sha256, "math_kernel": math_selection.selected_kernel, "math_selection_hash": math_selection.selection_hash}, ensure_ascii=False, indent=2), code="MEMORY")
                continue
            if text == ":snapshot":
                if creation_job.active:
                    show("Snapshot recusado enquanto a criação está ativa; aguarde o receipt terminal.", code="SNAPSHOT_DENIED_ACTIVE_JOB")
                    continue
                try:
                    show(json.dumps(controller.snapshot("guilherme-semantic-live"), ensure_ascii=False), code="SNAPSHOT")
                except Exception as error:
                    show(json.dumps(recoverable_error("snapshot", error), ensure_ascii=False), code="RECOVERABLE_ERROR")
                continue
            if text == ":restore":
                if creation_job.active:
                    show("Restore recusado enquanto a criação está ativa; use :cancelar ou aguarde o receipt terminal.", code="RESTORE_DENIED_ACTIVE_JOB")
                    continue
                try:
                    semantic.shutdown_physical()
                    show(json.dumps(controller.restore("guilherme-semantic-live"), ensure_ascii=False), code="RESTORE")
                    semantic = prepare_owner_semantic(args.repo.resolve(), vm_root)
                    show(json.dumps(semantic.reboot(), ensure_ascii=False), code="REBOOT")
                except Exception as error:
                    show(json.dumps(recoverable_error("restore", error), ensure_ascii=False), code="RECOVERABLE_ERROR")
                continue
            if text == ":nota":
                note = ask_user("O que você quer preservar como nota?", input_kind="NOTE")
                recorder.record(note_id=f"note:semantic:{recorder.note_count + 1}", channel="text", category="DESIRED_CHANGE", text=note, creation_id="creation:semantic-live", creation_version=0, creation_state="LISTENING", source_event_ids=("human:semantic-note",))
                show("Nota preservada; ela não altera rotas nem capabilities.", code="NOTE_SAVED")
                continue
            if text == ":export":
                result = recorder.export(feedback_root / "semantic-multiverse-feedback", environment={"cloud": "RELEASE_LOCKED", "network": "denied", "usb": "prohibited"})
                show(json.dumps(result, ensure_ascii=False), code="EXPORT")
                continue
            if text == ":criar":
                if creation_job.active:
                    snapshot = creation_job.snapshot()
                    show(f"Já existe uma criação ativa: {snapshot['last_summary']}", code="JOB_ALREADY_ACTIVE")
                    continue
                idea = ask_user(
                    "Me conta a ideia do jeito que ela apareceu na sua cabeça. Não precisa explicar como fazer: ",
                    input_kind="CREATION_IDEA",
                )
                if not idea:
                    show("Pode voltar quando a primeira imagem aparecer; nada foi criado ainda.", code="CREATION_INPUT_REQUIRED")
                    continue
                expectation = ""
                owner_data = vm_root / "owner-data"
                owner_data.mkdir(parents=True, exist_ok=True)
                creation_number = len(list(owner_data.glob("semantic-creation-*"))) + 1
                destination = owner_data / f"semantic-creation-{creation_number}"
                preview_root = owner_data / "intent-previews" / f"intent-{time.time_ns()}"
                try:
                    source_event = f"human:intent:{time.time_ns()}"
                    reconstruction_engine = IntentReconstructionEngine(runtime)
                    reconstruction = reconstruction_engine.propose(
                        creation_id=f"creation:semantic:{creation_number}",
                        source_event_id=source_event,
                        utterance=idea,
                        expected_behavior=expectation,
                        cancellation=EngineCancellationToken(),
                        task_kind_hint=IntentTaskKind.CREATION,
                    )
                    preview_root.mkdir(parents=True, exist_ok=False)
                    (preview_root / "intent-twin-proposed.json").write_text(
                        json.dumps(reconstruction.twin.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n",
                    )
                    (preview_root / "intent-reconstruction-receipt.json").write_text(
                        json.dumps(
                            {
                                "schema": "casulo.intent-reconstruction-receipt/1.0",
                                "model_task_kind": reconstruction.model_task_kind.value,
                                "deterministic_overrides": list(reconstruction.deterministic_overrides),
                                "candidate_rejections": list(reconstruction.candidate_rejections),
                                "raw_sha256": reconstruction.raw_sha256,
                                "trace": reconstruction.trace.to_dict(),
                                "neural_route_decisions": [
                                    item.to_dict()
                                    for item in reconstruction.route_decisions
                                ],
                            },
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ) + "\n",
                        encoding="utf-8", newline="\n",
                    )
                    creative_projection = CreativeIntentProjection.from_twin(reconstruction.twin)
                    (preview_root / "creative-interlocution.json").write_text(
                        json.dumps(
                            creative_projection.to_dict(),
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    show(
                        creative_projection.visible_text(guide_identity.name),
                        code="CREATIVE_MIRROR",
                    )
                    if reconstruction.twin.open_gaps:
                        gap = reconstruction.twin.open_gaps[0]
                        answer = ask_user(
                            f"Só uma escolha sua muda a experiência: {creative_projection.visible_question} ",
                            input_kind="HUMAN_EXPERIENCE_CHOICE",
                        )
                        reconstruction = reconstruction_engine.refine(
                            reconstruction,
                            answer=answer,
                            source_event_id=f"human:intent-answer:{time.time_ns()}",
                            cancellation=EngineCancellationToken(),
                        )
                        (preview_root / "intent-twin-refined.json").write_text(
                            json.dumps(reconstruction.twin.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8", newline="\n",
                        )
                        (preview_root / "intent-refinement-neural-budget.json").write_text(
                            json.dumps(
                                reconstruction.route_decisions[-1].to_dict(),
                                ensure_ascii=False,
                                indent=2,
                                sort_keys=True,
                            ) + "\n",
                            encoding="utf-8",
                            newline="\n",
                        )
                        creative_projection = CreativeIntentProjection.from_twin(reconstruction.twin)
                        (preview_root / "creative-interlocution-refined.json").write_text(
                            json.dumps(
                                creative_projection.to_dict(),
                                ensure_ascii=False,
                                indent=2,
                                sort_keys=True,
                            ) + "\n",
                            encoding="utf-8",
                            newline="\n",
                        )
                    twin = reconstruction.twin
                    if twin.task_kind is not IntentTaskKind.CREATION or not twin.production_ready:
                        show("A intenção ainda não está pronta para produção. Nada foi compilado ou materializado.", code="INTENT_NOT_READY")
                        continue
                    visual = IntentTwinRenderer.render(twin, preview_root / "visual")
                    show(
                        f"A ideia ganhou forma: {twin.summary}\nOs detalhes de engenharia já estão registrados por baixo.",
                        code="INTENT_TWIN_READY",
                    )
                    webbrowser.open(visual.as_uri())
                    route_cancellation = EngineCancellationToken()
                    route_seed = twin.summary
                    proposal = GenerativeUniversePlanner(runtime).propose(
                        route_seed,
                        operation_id=f"semantic-route-{semantic.catalog.snapshot.version}-{creation_number}",
                        cancellation=route_cancellation,
                    )
                    (preview_root / "semantic-route-neural-budget.json").write_text(
                        json.dumps(
                            proposal.route_decision.to_dict(),
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    if ask_user(
                        "É isso que você imaginou? Se for, diga CONFIRMO. Se não for, diga qualquer outra coisa e nada será fabricado: ",
                        input_kind="MATERIAL_CONFIRMATION",
                    ).casefold() != "confirmo":
                        show("Entendido. Preservei a leitura, mas não fabriquei nada.", code="INTENT_REJECTED")
                        continue
                    human_confirmation = f"human:intent-confirm:{time.time_ns()}"
                    twin = twin.confirm(
                        human_event_id=human_confirmation,
                        explicit_human_approval=True,
                    )
                    (preview_root / "intent-twin-confirmed.json").write_text(
                        json.dumps(twin.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n",
                    )
                    production_brief = twin.production_brief()
                    selected_hypothesis = next(
                        item for item in twin.hypotheses
                        if item.hypothesis_id == twin.selected_hypothesis_id
                    )
                    expectation = selected_hypothesis.consequences[0]
                    start_evidence = hashlib.sha256(
                        json.dumps(twin.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()

                    def create_in_background(token, report):
                        nonlocal last_route
                        controller.bridge_boot("owner-job-accepted-semantic-multiverse", acceleration="tcg", timeout=60)
                        creation = run_probe(
                            candidate,
                            args.cache.resolve(),
                            destination,
                            repo=args.repo.resolve(),
                            idea=production_brief,
                            holdout_expectation=expectation,
                            threads=args.threads,
                            runtime=runtime,
                            enforce_holdout_scan=False,
                            require_initial_repair=False,
                            intent_twin=twin,
                            human_confirmation_event_id=human_confirmation,
                            cancellation=token,
                            progress=report,
                        )
                        if token.cancelled:
                            return JobEvidence(start_evidence, "Criação cancelada; materialização não publicada na memória.", {})
                        archive = str(creation["materialization"]["archive"])
                        route = semantic.execute(
                            proposal,
                            idea=production_brief,
                            constraints=("sem API externa", "capabilities deny-by-default", "somente efeitos simulados antes do acordo"),
                            confirmed=True,
                            cancellation=SemanticCancellationToken(),
                        )
                        (destination / "semantic-session.json").write_text(json.dumps(route, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
                        semantic_visual = semantic.render(route, destination / "semantic-visual")
                        continuity.record(
                            record_id=f"{project_id}:{destination.name}", project_id=project_id,
                            kind=RecordKind.DECISION, text=twin.summary,
                            source_event_ids=(f"artifact:{archive}",), criticality=9,
                        )
                        with state_lock:
                            last_route = route
                        show(f"Artifact materializado: {archive}", code="ARTIFACT_MATERIALIZED")
                        show("Universos: " + " → ".join(route["universes_visited"]), code="UNIVERSES_VISITED")
                        show(f"Mapa semântico: {semantic_visual}", code="SEMANTIC_VISUAL")
                        try:
                            creation_visual = render_creation_timeline(destination, creation, destination / "visual")
                            show(f"Forma da criação: {creation_visual['index']}", code="CREATION_VISUAL")
                            webbrowser.open(semantic_visual.as_uri())
                        except Exception as error:
                            show(json.dumps(recoverable_error("visualization", error, destination), ensure_ascii=False), code="RECOVERABLE_ERROR")
                        return JobEvidence(file_sha256(archive), "Criação materializada, verificada e pronta para inspeção.", {"archive": archive})

                    creation_job.start(
                        f"creation-{creation_number}",
                        create_in_background,
                        start_evidence_sha256=start_evidence,
                    )
                    emit_ux(
                        UxEventKind.NOTICE,
                        {"code": "BACKGROUND_JOB_ACCEPTED", "text": "Vou construir isso em background. Você pode continuar falando comigo."},
                        human_confirmation,
                    )
                except Exception as error:
                    show(json.dumps(recoverable_error("creation", error, destination), ensure_ascii=False), code="RECOVERABLE_ERROR")
                continue
            if creation_job.active:
                snapshot = creation_job.snapshot()
                answer = f"Continuo aqui. {snapshot['last_summary']} Posso registrar outra decisão ou cancelar sem inventar progresso."
                if args.ui_mode == "arc-stream":
                    turn_id = f"presence:{time.time_ns()}"
                    emit_ux(UxEventKind.ASSISTANT_START, {"turn_id": turn_id}, "guide:background-presence")
                    emit_ux(UxEventKind.ASSISTANT_TOKEN, {"turn_id": turn_id, "sequence": 1, "text": answer}, "guide:background-presence")
                    emit_ux(UxEventKind.ASSISTANT_END, {"turn_id": turn_id, "finish_reason": "real_job_status", "status": "COMPLETED", "response_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(), "response_chars": len(answer)}, "guide:background-presence")
                else:
                    print(f"Casulo › {answer}")
                continue
            if args.ui_mode != "arc-stream":
                print("Casulo › ", end="", flush=True)
            try:
                turn = turn_coordinator.decide(
                    event_kind="TEXT_FINAL", speech_detected=False,
                    transcript_final=True, transcript_nonempty=bool(text.strip()),
                    tts_active=False,
                )
                if turn.value != "COMMIT_FINAL":
                    raise RuntimeError("T TurnCoordinator não consolidou o turno final")
                deliver_dialogue(
                    transport=args.dialogue_transport,
                    controller=controller,
                    provider=lambda: " ".join(
                        dialogue_turn(
                            runtime,
                            trace_store,
                            conversation,
                            text,
                            continuity=continuity,
                            project_id=project_id,
                            guide_name=guide_identity.name,
                            turn_id=f"dialogue:{time.time_ns()}",
                            stream_sink=(
                                (lambda kind, payload: emit_ux(UxEventKind(kind), dict(payload), "owner:dialogue-stream"))
                                if args.ui_mode == "arc-stream"
                                else None
                            ),
                        ).split()
                    ),
                )
            except KeyboardInterrupt:
                continue
    if creation_job.active:
        creation_job.cancel()
        creation_job.join(15)
    semantic.shutdown_physical()
    continuity.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps(recoverable_error("launcher", error), ensure_ascii=False))
        raise SystemExit(2)
