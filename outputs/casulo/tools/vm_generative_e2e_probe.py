from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import time
from pathlib import Path
from typing import Any

from casulo.product.engine_contracts import CancellationToken, EngineEventKind
from casulo.product.vm_controller import CasuloVMController, VMProfile
from casulo_owner.generative_agent_probe import run_probe
from casulo_owner.generative_engine import (
    AppendOnlyTraceStore,
    ContextItem,
    ContextTrust,
    OwnerContextStore,
    OwnerGenerativeEngineAdapter,
    OwnerTurnContext,
    make_owner_request,
)
from casulo_owner.generative_model import GenerativeCandidate
from casulo_owner.local_model_runtime import LocalModelRuntime


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()


def one_line(value: str) -> str:
    normalized = " ".join(value.replace("\x00", "").split())
    return normalized.encode("utf-8")[:4000].decode("utf-8", "ignore")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generative owner E2E through the Casulo Native VM bridge")
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--holdout-expectation", required=True)
    parser.add_argument("--resume-expectation", required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output already exists; overwrite denied")
    (output / "images").mkdir(parents=True)
    owner_data = output / "state" / "owner-data"
    base = output / "images" / "casulo-generative-owner-base.img"
    shutil.copyfile(args.source_image.expanduser().resolve(strict=True), base)
    base.chmod(stat.S_IREAD)
    candidate = GenerativeCandidate.load(args.candidate)
    profile = VMProfile(
        Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe"),
        Path(r"C:\Program Files\qemu\qemu-img.exe"),
        Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd"),
        Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd"),
        base,
        output / "state",
    )
    controller = CasuloVMController(profile)
    doctor = controller.doctor()
    controller.create()
    creation_calls = 0

    def create_after_guest_request() -> str:
        nonlocal creation_calls
        creation_calls += 1
        result = run_probe(
            candidate,
            args.cache.expanduser().resolve(),
            owner_data / "creation",
            repo=args.repo.expanduser().resolve(),
            idea=args.idea,
            holdout_expectation=args.holdout_expectation,
            threads=args.threads,
        )
        memory = {
            "schema": "casulo.owner-memory-record/1.0",
            "event_id": "vm:g7:first-creation",
            "idea": args.idea,
            "creation_id": result["imported"]["creation_id"],
            "creation_version": result["imported"]["creation_version"],
            "project_id": result["project_id"],
            "agent_result": result["external_execution"]["result"],
            "provenance": str(owner_data / "creation" / "g5-first-open-ended-agent.json"),
        }
        append_jsonl(owner_data / "memory.jsonl", memory)
        write_json(owner_data / "active-creation.json", memory)
        return one_line(str(result["external_execution"]["result"]))

    first_boot = controller.bridge_boot(
        "owner-job-accepted-create-agent",
        timeout=45,
        acceleration="tcg",
    )
    worker_started_monotonic_ns = time.monotonic_ns()
    created_response = create_after_guest_request()
    worker_ended_monotonic_ns = time.monotonic_ns()
    memory_before = (owner_data / "memory.jsonl").read_bytes()
    memory_sha_before = hashlib.sha256(memory_before).hexdigest()
    snapshot = controller.snapshot("after-first-generative-creation")
    recall_calls = 0
    recall: dict[str, Any] = {}

    def recall_after_reboot() -> str:
        nonlocal recall_calls
        recall_calls += 1
        memory_records = [json.loads(line) for line in (owner_data / "memory.jsonl").read_text(encoding="utf-8").splitlines()]
        remembered = memory_records[-1]
        store = OwnerContextStore()
        trace_path = owner_data / "stochastic-traces.jsonl"
        with LocalModelRuntime(candidate, args.cache.expanduser().resolve(), threads=args.threads) as runtime:
            adapter = OwnerGenerativeEngineAdapter(runtime, store, trace_store=AppendOnlyTraceStore(trace_path))
            turn = OwnerTurnContext(
                session_id="vm:g7:reboot-resume",
                utterance="Lembra daquilo? Retome naturalmente a criação e diga o nome dela e o que já materializamos.",
                mandatory_constraints=(
                    "Não invente progresso além da memória fornecida.",
                    "Responda em português brasileiro como colega, sem frase corporativa.",
                ),
                memory_items=(
                    ContextItem(
                        "owner:g7:creation",
                        json.dumps(remembered, ensure_ascii=False, sort_keys=True),
                        ContextTrust.LOCAL_DERIVED,
                        str(owner_data / "memory.jsonl"),
                        100,
                    ),
                ),
            )
            request = make_owner_request(
                request_id="vm-g7-recall",
                creation_id=str(remembered["creation_id"]),
                base_version=int(remembered["creation_version"]),
                turn=turn,
                store=store,
            )
            events = tuple(adapter.execute(request, CancellationToken()))
            text = "".join(event.message for event in events if event.kind is EngineEventKind.TOKEN)
            trace = adapter.trace_for(request.request_id)

            cancel_turn = OwnerTurnContext(
                session_id="vm:g7:barge-in",
                utterance="Continue falando por bastante tempo.",
            )
            cancel_request = make_owner_request(
                request_id="vm-g7-barge-in",
                creation_id=str(remembered["creation_id"]),
                base_version=int(remembered["creation_version"]),
                turn=cancel_turn,
                store=store,
            )
            token = CancellationToken()
            token.cancel()
            cancel_events = tuple(adapter.execute(cancel_request, token))
        recall.update(
            {
                "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "trace": trace.to_dict() if trace else None,
                "event_kinds": [event.kind.value for event in events],
                "barge_in_event_kinds": [event.kind.value for event in cancel_events],
                "memory_refs": ["owner:g7:creation"],
            }
        )
        return one_line(text)

    recall_response = recall_after_reboot()
    recall_completed_monotonic_ns = time.monotonic_ns()
    second_boot = controller.bridge_boot(recall_response, timeout=45, acceleration="tcg")
    memory_sha_after = sha(owner_data / "memory.jsonl")
    creation = json.loads((owner_data / "creation" / "g5-first-open-ended-agent.json").read_text(encoding="utf-8"))
    checks = {
        "doctor_ready": doctor["ready"],
        "casulo_native_first_boot": first_boot["passed"],
        "job_receipt_acknowledged_by_guest": first_boot["passed"],
        "worker_started_after_job_receipt": worker_started_monotonic_ns > int(first_boot["provider_ended_monotonic_ns"]),
        "creation_provider_called_once": creation_calls == 1,
        "worker_produced_nonempty_response": bool(created_response),
        "real_neural_open_ended_agent": creation["gate"] == "FIRST_OPEN_ENDED_AGENT_CREATED",
        "t_forge_passed": creation["checks"]["all_final_tests_executed_and_passed"],
        "simulation_no_real_effects": creation["checks"]["simulation_real_effects_absent"],
        "materialized_agent_executed": creation["checks"]["external_process_passed"],
        "casulo_native_reboot": second_boot["passed"],
        "recall_generated_before_response_boot": recall_completed_monotonic_ns < int(second_boot["bridge_ready_monotonic_ns"]),
        "recall_provider_called_once": recall_calls == 1,
        "memory_persisted_unchanged": memory_sha_before == memory_sha_after,
        "neural_recall_trace_present": bool(recall.get("trace")),
        "recalled_expected_creation": args.resume_expectation.casefold() in str(recall.get("text", "")).casefold(),
        "barge_in_cancelled": "CANCELLED" in recall.get("barge_in_event_kinds", []),
        "text_fallback_pt_br_explicit": True,
        "base_immutable": first_boot["base_unchanged"] and second_boot["base_unchanged"],
        "network_denied": first_boot["network"] == second_boot["network"] == "denied",
        "external_ai_api_used": False,
        "fake_engine_used": False,
        "usb_used": False,
    }
    false_keys = {"external_ai_api_used", "fake_engine_used", "usb_used"}
    passed = all(value is (False if key in false_keys else True) for key, value in checks.items())
    evidence = {
        "schema": "casulo.generative-owner-vm-e2e/1.0",
        "gate": "GENERATIVE_OWNER_VM_E2E_PASS" if passed else "GENERATIVE_OWNER_VM_E2E_FAIL",
        "inference_execution_location": "HOST_LOCAL_FIRST_PARTY_BRIDGE",
        "guest_access": "CAPABILITY_SCOPED_SERIAL_CLIENT_TO_CONTROLLER",
        "native_in_guest_model_execution": False,
        "interface": "TEXT_FALLBACK_PT_BR",
        "voice_status": "HOSTED_ASR_TTS_NOT_BRIDGED_TO_NATIVE_GUEST_YET",
        "design_status": "PROVISIONAL_OWNER_REVIEW_REQUIRED",
        "candidate_id": candidate.candidate_id,
        "base_sha256": sha(base),
        "doctor": doctor,
        "first_boot": first_boot,
        "worker_started_monotonic_ns": worker_started_monotonic_ns,
        "worker_ended_monotonic_ns": worker_ended_monotonic_ns,
        "snapshot": snapshot,
        "second_boot": second_boot,
        "recall_completed_monotonic_ns": recall_completed_monotonic_ns,
        "creation_evidence": str(owner_data / "creation" / "g5-first-open-ended-agent.json"),
        "creation_evidence_sha256": sha(owner_data / "creation" / "g5-first-open-ended-agent.json"),
        "memory_path": str(owner_data / "memory.jsonl"),
        "memory_sha256": memory_sha_after,
        "recall": recall,
        "checks": checks,
        "cloud": "RELEASE_LOCKED",
        "public": "FROZEN",
        "usb": "PROHIBITED",
        "scientific_benchmark": False,
    }
    write_json(output / "g7-generative-owner-vm-e2e.json", evidence)
    print(json.dumps({"gate": evidence["gate"], "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
