from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

from casulo.product.creation_field import CreationFieldRenderer, CreationPresentation
from casulo.product.domain import CreationSpec, CreationState, creation_spec_from_document
from casulo.product.engine_contracts import CancellationToken, EngineEventKind
from casulo.product.vm_controller import CasuloVMController, VMProfile
from casulo_owner.dialogue_core import GenerativeDialogueCore, RelationalMode
from casulo_owner.generative_agent_probe import run_probe
from casulo_owner.generative_engine import (
    AppendOnlyTraceStore,
    ContextItem,
    ContextTrust,
    OwnerContextStore,
    OwnerGenerativeEngineAdapter,
    make_owner_request,
)
from casulo_owner.generative_model import GenerativeCandidate
from casulo_owner.inspection import OwnerInspectionRecorder
from casulo_owner.local_model_runtime import (
    ChatMessage,
    GenerationRequest,
    LocalModelRuntime,
    ModelStreamKind,
    initial_sampling_policies,
)
try:
    from tools.stark_jobs_vm_probe import forge_receipt
except ModuleNotFoundError:  # execução direta: sys.path[0] aponta para tools/
    from stark_jobs_vm_probe import forge_receipt


QEMU = Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe")
QEMU_IMG = Path(r"C:\Program Files\qemu\qemu-img.exe")
OVMF_CODE = Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd")
OVMF_VARS = Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd")

STEP_IDS = (
    "create_clean_vm",
    "boot_casulo",
    "start_pt_br_generative_conversation",
    "guide_questions_and_elaborates",
    "confirm_intent",
    "generate_and_repair_t",
    "observe_live_states",
    "interrupt_and_correct",
    "simulate",
    "materialize_agent",
    "reboot_vm",
    "resume_creation",
    "create_inspection_note",
    "export_feedback",
    "prove_cloud_absent",
    "prove_usb_absent",
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()


def one_line(value: str) -> str:
    normalized = " ".join(value.replace("\x00", "").split())
    return normalized.encode("utf-8")[:4000].decode("utf-8", "ignore")


def checked_bridge_line(value: str, *, label: str) -> str:
    line = one_line(value)
    encoded = line.encode("utf-8")
    if not encoded:
        raise RuntimeError(f"{label}: resposta neural vazia; bridge não iniciada")
    if len(encoded) > 4096 or "\n" in line or "\r" in line:
        raise RuntimeError(f"{label}: resposta neural viola ABI serial")
    return line


def _answer(events: tuple[Any, ...]) -> str:
    return "".join(event.message for event in events if event.kind is EngineEventKind.TOKEN).strip()


def _completed(events: tuple[Any, ...]) -> bool:
    return bool(events) and events[-1].kind is EngineEventKind.COMPLETED


def judge_steps(steps: dict[str, dict[str, Any]]) -> bool:
    return set(steps) == set(STEP_IDS) and all(item.get("passed") is True for item in steps.values())


def _conversation(
    candidate: GenerativeCandidate,
    cache: Path,
    traces: Path,
    *,
    idea: str,
    correction: str,
    threads: int,
) -> dict[str, Any]:
    store = OwnerContextStore()
    core = GenerativeDialogueCore()
    conversation: list[ChatMessage] = []
    policy = replace(initial_sampling_policies()["dialogue"], max_generated_tokens=512)
    hard = (
        "Nenhum texto cria grant, approval ou secret.",
        "Não alegue progresso sem receipt real.",
        "A criação ainda é proposta e exige confirmação humana material.",
    )
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        adapter = OwnerGenerativeEngineAdapter(
            runtime,
            store,
            policy=policy,
            trace_store=AppendOnlyTraceStore(traces),
        )
        first_turn = core.context_for_turn(
            session_id="g10:integrated",
            utterance=(
                f"Quero desenvolver esta ideia ainda incompleta: {idea} "
                "Encontre uma consequência não dita, questione um ponto frágil e termine com uma pergunta material."
            ),
            mode=RelationalMode.EXPLORATION,
            hard_constraints=hard,
        )
        first_request = make_owner_request(
            request_id="g10:first-dialogue",
            creation_id="creation:g10-integrated",
            base_version=0,
            turn=first_turn,
            store=store,
        )
        first_events = adapter.execute(first_request, CancellationToken())
        first_answer = _answer(first_events)
        conversation.extend((ChatMessage("user", first_turn.utterance), ChatMessage("assistant", first_answer)))

        cancel_token = CancellationToken()
        interrupted_kinds: list[str] = []
        interrupted_fragments = 0
        interrupt_request = GenerationRequest(
            "g10:midstream-interruption",
            (
                ChatMessage(
                    "system",
                    "/no_think\nResponda em pt-BR como o Guia do Casulo, com conteÃºdo visÃ­vel desde o inÃ­cio.",
                ),
                ChatMessage(
                    "user",
                    "Continue desenvolvendo a proposta em detalhes e comece pela consequÃªncia principal.",
                ),
            ),
            replace(policy, max_generated_tokens=128),
        )
        for event in runtime.stream_chat(interrupt_request, cancel_token):
            interrupted_kinds.append(event.kind.value)
            if event.kind is ModelStreamKind.TOKEN:
                interrupted_fragments += 1
                cancel_token.cancel()

        # A conexão cancelada pode deixar um slot de inferência terminando no
        # processo local. A correção é uma operação nova e não pode compartilhar
        # estado tardio: encerra e reinicia somente o runtime, preservando
        # conversa, VM e proveniência.
        runtime.close()
        runtime.start()

        corrected_turn = core.context_for_turn(
            session_id="g10:integrated",
            utterance=(
                f"Pare. Corrigindo a direção: {correction} "
                "Mostre como isso muda a proposta sem fingir que já foi implementado."
            ),
            conversation=tuple(conversation),
            mode=RelationalMode.CRYSTALLIZATION,
            hard_constraints=hard,
        )
        corrected_request = make_owner_request(
            request_id="g10:corrected-dialogue",
            creation_id="creation:g10-integrated",
            base_version=0,
            turn=corrected_turn,
            store=store,
        )
        corrected_events = adapter.execute(corrected_request, CancellationToken())
        corrected_answer = _answer(corrected_events)
        first_trace = adapter.trace_for(first_request.request_id)
        corrected_trace = adapter.trace_for(corrected_request.request_id)

    return {
        "schema": "casulo.g10-conversation/1.0",
        "first": {
            "utterance": first_turn.utterance,
            "answer": first_answer,
            "event_kinds": [event.kind.value for event in first_events],
            "trace": None if first_trace is None else first_trace.to_dict(),
        },
        "interruption": {
            "event_kinds": interrupted_kinds,
            "token_fragments_before_cancel": interrupted_fragments,
            "late_completion_absent": ModelStreamKind.COMPLETED.value not in interrupted_kinds,
            "runtime_restarted_before_correction": True,
        },
        "corrected": {
            "utterance": corrected_turn.utterance,
            "answer": corrected_answer,
            "event_kinds": [event.kind.value for event in corrected_events],
            "trace": None if corrected_trace is None else corrected_trace.to_dict(),
        },
        "checks": {
            "first_completed": _completed(first_events),
            "first_streamed": sum(event.kind is EngineEventKind.TOKEN for event in first_events) > 1,
            "guide_asked_material_question": "?" in first_answer,
            "guide_elaborated": len(first_answer.split()) >= 35,
            "midstream_cancelled": ModelStreamKind.CANCELLED.value in interrupted_kinds and interrupted_fragments >= 1,
            "late_result_not_consolidated": ModelStreamKind.COMPLETED.value not in interrupted_kinds,
            "correction_completed": _completed(corrected_events) and len(corrected_answer.split()) >= 20,
            "stochastic_traces_present": first_trace is not None and corrected_trace is not None,
            "external_ai_api_absent": all(
                trace is not None and not trace.commercial_ai_api_used and not trace.external_network_used
                for trace in (first_trace, corrected_trace)
            ),
        },
    }


def _recall(
    candidate: GenerativeCandidate,
    cache: Path,
    memory_path: Path,
    traces: Path,
    *,
    resume_expectation: str,
    threads: int,
) -> dict[str, Any]:
    remembered = json.loads(memory_path.read_text(encoding="utf-8").splitlines()[-1])
    store = OwnerContextStore()
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        adapter = OwnerGenerativeEngineAdapter(
            runtime,
            store,
            trace_store=AppendOnlyTraceStore(traces),
        )
        turn = GenerativeDialogueCore().context_for_turn(
            session_id="g10:reboot",
            utterance="Lembra daquilo? Retome a criação pelo nome e diga somente o que os receipts provam.",
            hard_constraints=("Não invente progresso além da memória fornecida.",),
            memory_items=(
                ContextItem(
                    "owner:g10:creation",
                    json.dumps(remembered, ensure_ascii=False, sort_keys=True),
                    ContextTrust.LOCAL_DERIVED,
                    str(memory_path),
                    100,
                ),
            ),
        )
        request = make_owner_request(
            request_id="g10:reboot-recall",
            creation_id=str(remembered["creation_id"]),
            base_version=int(remembered["creation_version"]),
            turn=turn,
            store=store,
        )
        events = adapter.execute(request, CancellationToken())
        answer = _answer(events)
        trace = adapter.trace_for(request.request_id)
    return {
        "answer": answer,
        "event_kinds": [event.kind.value for event in events],
        "trace": None if trace is None else trace.to_dict(),
        "completed": _completed(events),
        "expected_identity_recalled": resume_expectation.casefold() in answer.casefold(),
    }


def _render_visuals(creation_root: Path, result: dict[str, Any], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True)
    receipt = forge_receipt(creation_root)
    renderer = CreationFieldRenderer()
    pages: list[dict[str, Any]] = []
    for index, state in enumerate(CreationState):
        formed = state not in {
            CreationState.SILENCE,
            CreationState.FIRST_INTENT,
            CreationState.LISTENING,
            CreationState.CLARIFICATION,
        }
        frame = renderer.project(
            CreationSpec(
                str(result["imported"]["creation_id"]),
                version=int(result["imported"]["creation_version"]),
                state=state,
                content={"identity": {"name": result["agent_name"]}},
            ),
            provenance_event_ids=() if state is CreationState.SILENCE else (f"g10:{index}:{state.value}",),
            forge_receipt=receipt if formed else None,
        )
        page = output / f"{index:02d}-{state.value.casefold()}.html"
        page.write_text(renderer.render_html(frame), encoding="utf-8", newline="\n")
        pages.append({"state": state.value, "path": str(page), "sha256": sha(page), "nodes": len(frame.nodes)})
    write_json(output / "timeline.json", {"schema": "casulo.g10-visual-timeline/1.0", "pages": pages})
    return {
        "design_status": renderer.theme.design_status,
        "states": [item["state"] for item in pages],
        "pages": pages,
        "all_twelve_states": len(pages) == 12 and [item["state"] for item in pages] == [state.value for state in CreationState],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa o cenário final integrado G10 do Casulo owner generativo")
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--holdout-expectation", required=True)
    parser.add_argument("--resume-expectation", required=True)
    parser.add_argument("--correction", required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output G10 já existe; overwrite negado")
    if args.threads <= 0 or not all(value.strip() for value in (args.idea, args.holdout_expectation, args.resume_expectation, args.correction)):
        raise SystemExit("cenário G10 incompleto")
    output.mkdir(parents=True)
    images = output / "images"
    state = output / "state"
    images.mkdir()
    base = images / "casulo-g10-base.img"
    shutil.copyfile(args.source_image.expanduser().resolve(strict=True), base)
    base.chmod(stat.S_IREAD)
    candidate = GenerativeCandidate.load(args.candidate)
    controller = CasuloVMController(VMProfile(QEMU, QEMU_IMG, OVMF_CODE, OVMF_VARS, base, state))
    doctor = controller.doctor()
    created = controller.create()
    clean_snapshot = controller.snapshot("clean-g10-integrated")

    conversation = _conversation(
        candidate,
        args.cache.expanduser().resolve(),
        output / "stochastic-traces.jsonl",
        idea=args.idea,
        correction=args.correction,
        threads=args.threads,
    )
    first_dialogue_boot = controller.bridge_boot(
        checked_bridge_line(conversation["first"]["answer"], label="first-dialogue"),
        acceleration="tcg",
        timeout=60,
    )
    corrected_dialogue_boot = controller.bridge_boot(
        checked_bridge_line(conversation["corrected"]["answer"], label="corrected-dialogue"),
        acceleration="tcg",
        timeout=60,
    )
    job_boot = controller.bridge_boot("owner-job-accepted-after-human-confirmation", acceleration="tcg", timeout=60)

    creation_root = state / "owner-data" / "creation"
    creation = run_probe(
        candidate,
        args.cache.expanduser().resolve(),
        creation_root,
        repo=args.repo.expanduser().resolve(),
        idea=args.idea,
        holdout_expectation=args.holdout_expectation,
        threads=args.threads,
    )
    confirmed_creation_path = creation_root / "confirmed-creation.json"
    confirmed_creation = json.loads(confirmed_creation_path.read_text(encoding="utf-8"))
    agent_name = CreationPresentation.from_creation(
        creation_spec_from_document(confirmed_creation)
    ).display_name
    memory = {
        "schema": "casulo.owner-memory-record/1.0",
        "event_id": "vm:g10:creation",
        "idea": args.idea,
        "creation_id": creation["imported"]["creation_id"],
        "creation_version": creation["imported"]["creation_version"],
        "agent_name": agent_name,
        "project_id": creation["project_id"],
        "materialization_sha256": creation["materialization"]["archive_sha256"],
    }
    memory_path = state / "owner-data" / "memory.jsonl"
    append_jsonl(memory_path, memory)
    write_json(state / "owner-data" / "active-creation.json", memory)
    created_snapshot = controller.snapshot("after-g10-creation")
    creation_for_visual = {**creation, "agent_name": agent_name}
    visual = _render_visuals(creation_root, creation_for_visual, output / "visual")

    recall = _recall(
        candidate,
        args.cache.expanduser().resolve(),
        memory_path,
        output / "stochastic-traces.jsonl",
        resume_expectation=agent_name,
        threads=args.threads,
    )
    recall_boot = controller.bridge_boot(one_line(recall["answer"]), acceleration="tcg", timeout=60)

    before_inspection = controller.snapshot("before-guilherme-inspection")
    recorder = OwnerInspectionRecorder(output / "inspection", session_id="guilherme:g10-integrated")
    note = recorder.record(
        note_id="note:g10:integrated",
        channel="text",
        category="DESIRED_CHANGE",
        text="Avaliar se a pergunta material do Guia chegou cedo demais nesta criação.",
        creation_id=str(creation["imported"]["creation_id"]),
        creation_version=int(creation["imported"]["creation_version"]),
        creation_state="MATERIALIZATION",
        source_event_ids=("g10:human-inspection-note",),
    )
    feedback = recorder.export(
        output / "owner-inspection-feedback",
        environment={
            "vm_profile": "casulo-owner-generative-g10",
            "base_sha256": sha(base),
            "model_id": candidate.candidate_id,
            "network": "denied",
            "cloud": "RELEASE_LOCKED",
            "external_media": "NOT_IN_USE",
        },
    )
    feedback_hash_before = sha(output / "owner-inspection-feedback" / "SHA256SUMS")
    restored = controller.restore("before-guilherme-inspection")
    feedback_hash_after = sha(output / "owner-inspection-feedback" / "SHA256SUMS")

    steps = {
        "create_clean_vm": {"passed": doctor["ready"] and created["base_read_only"] and clean_snapshot["snapshot"] == "clean-g10-integrated"},
        "boot_casulo": {"passed": first_dialogue_boot["passed"], "serial_sha256": first_dialogue_boot["serial_sha256"]},
        "start_pt_br_generative_conversation": {"passed": conversation["checks"]["first_completed"] and conversation["checks"]["first_streamed"]},
        "guide_questions_and_elaborates": {"passed": conversation["checks"]["guide_asked_material_question"] and conversation["checks"]["guide_elaborated"]},
        "confirm_intent": {"passed": job_boot["passed"] and confirmed_creation_path.is_file()},
        "generate_and_repair_t": {"passed": creation["checks"]["neural_t_generated"] and creation["checks"]["bounded_neural_repair_passed"]},
        "observe_live_states": {"passed": visual["all_twelve_states"] and visual["design_status"] == "PROVISIONAL_OWNER_REVIEW_REQUIRED"},
        "interrupt_and_correct": {"passed": conversation["checks"]["midstream_cancelled"] and conversation["checks"]["late_result_not_consolidated"] and conversation["checks"]["correction_completed"] and corrected_dialogue_boot["passed"]},
        "simulate": {"passed": creation["checks"]["simulation_passed"] and creation["checks"]["simulation_real_effects_absent"]},
        "materialize_agent": {"passed": creation["checks"]["external_process_passed"] and Path(creation["materialization"]["archive"]).is_file()},
        "reboot_vm": {"passed": recall_boot["passed"] and recall_boot["base_unchanged"]},
        "resume_creation": {"passed": recall["completed"] and recall["expected_identity_recalled"]},
        "create_inspection_note": {"passed": note.creation_id == creation["imported"]["creation_id"] and note.raw_audio_persisted is False},
        "export_feedback": {"passed": feedback["notes"] == 1 and feedback["raw_audio_persisted"] is False and feedback_hash_before == feedback_hash_after and restored["restored"] == "before-guilherme-inspection"},
        "prove_cloud_absent": {"passed": doctor["cloud"] == "RELEASE_LOCKED" and first_dialogue_boot["network"] == "denied"},
        "prove_usb_absent": {"passed": doctor["external_media"] == "NOT_IN_USE" and doctor["host_block_devices"] is False},
    }
    passed = judge_steps(steps) and all(conversation["checks"].values()) and creation["gate"] == "FIRST_OPEN_ENDED_AGENT_CREATED"
    evidence = {
        "schema": "casulo.generative-vm-handoff-scenario/1.0",
        "gate": "READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION" if passed else "GENERATIVE_VM_HANDOFF_SCENARIO_FAIL",
        "scenario_is_new": creation["checks"]["holdout_absent_before_run"],
        "candidate_id": candidate.candidate_id,
        "model_sha256": candidate.model.sha256,
        "runtime_archive_sha256": candidate.runtime.sha256,
        "sampling_policy_id": initial_sampling_policies()["dialogue"].policy_id,
        "interface": "TEXT_FALLBACK_PT_BR_EXPLICIT; HOSTED_VOICE_AVAILABLE_SEPARATELY",
        "inference_execution_location": "HOST_LOCAL_FIRST_PARTY_BRIDGE",
        "idea": args.idea,
        "correction": args.correction,
        "doctor": doctor,
        "conversation": conversation,
        "vm_dialogue_boots": [first_dialogue_boot, corrected_dialogue_boot],
        "job_boot": job_boot,
        "creation_evidence": str(creation_root / "g5-first-open-ended-agent.json"),
        "creation_evidence_sha256": sha(creation_root / "g5-first-open-ended-agent.json"),
        "visual": visual,
        "created_snapshot": created_snapshot,
        "recall": recall,
        "recall_boot": recall_boot,
        "inspection_note": note.to_dict(),
        "feedback": feedback,
        "feedback_sha256sums_sha256": feedback_hash_after,
        "steps": steps,
        "cloud": "RELEASE_LOCKED",
        "public": "FROZEN",
        "usb": "PROHIBITED",
        "scientific_benchmark": False,
        "fake_engine_used": False,
        "external_ai_api_used": False,
    }
    write_json(output / "g10-integrated-handoff.json", evidence)
    print(json.dumps({"gate": evidence["gate"], "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
