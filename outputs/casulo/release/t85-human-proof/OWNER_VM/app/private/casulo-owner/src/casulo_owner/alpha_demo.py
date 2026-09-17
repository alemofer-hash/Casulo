from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from casulo.product.capabilities import Effect
from casulo.product.creation_field import CreationFieldRenderer
from casulo.product.domain import (
    CapabilityGrant,
    CreationAggregate,
    CreationSpec,
    CreationState,
    canonical_sha256,
)
from casulo.product.engine_contracts import CancellationToken, EngineRequest
from casulo.product.guide_presence import GuidePresence
from casulo.product.intent_engine import IntentEngine
from casulo.product.living_memory import DpapiSecretBox, LivingMemory, TestSecretBox
from casulo.product.local_intelligence import load_local_intelligence
from casulo.product.materializer import MaterializedPackageImporter, Materializer
from casulo.product.platform_contracts import LocalStorage, SystemClock
from casulo.product.simulation import (
    SimulatedResponse,
    SimulationCapabilityDouble,
    SimulationPlan,
    SimulationRuntime,
    SimulationStep,
)

from .adapter import OwnerEngineAdapter
from .motor import AuthorizedIntent, LocalOwnerMotor


def _intent(aggregate: CreationAggregate, event_id: str, utterance: str):
    interpreted = IntentEngine().interpret(
        aggregate,
        source_event_id=event_id,
        utterance=utterance,
    )
    if interpreted.delta is None:
        raise RuntimeError("demo exige IntentDelta exato")
    return interpreted.delta


def _execute_owner(
    motor: LocalOwnerMotor,
    aggregate: CreationAggregate,
    delta,
    event_id: str,
):
    authorization = AuthorizedIntent(delta, event_id, True)
    digest = canonical_sha256(delta.to_dict())
    if not motor.has_intent(digest):
        motor.register_intent(authorization)
    request = EngineRequest(
        f"request:{event_id}",
        aggregate.current.creation_id,
        aggregate.current.version,
        digest,
    )
    return OwnerEngineAdapter(motor).execute(request, CancellationToken())


def _plan(creation_id: str, simulation_id: str) -> SimulationPlan:
    return SimulationPlan(
        simulation_id,
        creation_id,
        (
            SimulationStep(
                "daily-reminder-preview",
                Effect.NETWORK_CONNECT,
                "preview",
                {"endpoint": "simulation://daily-reminder"},
                (),
                (("behavior", "retry"),),
                ("voice:simulate",),
            ),
        ),
        ("voice:simulate",),
    )


def run(output: Path, *, test_encryption: bool = False) -> dict[str, object]:
    target = output.expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise RuntimeError("demo output precisa estar vazio")
    target.mkdir(parents=True, exist_ok=True)
    clock = SystemClock()
    box = TestSecretBox() if test_encryption else DpapiSecretBox()
    storage = LocalStorage(target / "profile")
    memory = LivingMemory(
        storage=storage,
        clock=clock,
        secret_box=box,
        allow_test_encryption=test_encryption,
    )
    guide = GuidePresence(clock=clock, memory=memory)
    repository = Path(__file__).resolve().parents[4]
    model_registry, local_guide, local_embedding = load_local_intelligence(
        repository / "models/registry.json"
    )
    first_turn = guide.respond(
        event_id="voice:first-contact",
        text="Quero criar um agente cotidiano de lembretes gentis.",
    )
    local_model_turn = local_guide.respond(
        "Quero criar um agente cotidiano de lembretes gentis."
    )
    intent_vector = local_embedding.embed("agente cotidiano de lembretes gentis")

    aggregate = CreationAggregate(
        CreationSpec(
            "creation:daily-guide",
            content={"identity": {"name": "Guia Diario"}},
        )
    )
    aggregate.grant(
        CapabilityGrant(
            Effect.NETWORK_CONNECT.value,
            "human",
            "voice:grant-simulation",
            True,
        )
    )
    aggregate.transition(CreationState.FIRST_INTENT, "voice:first-contact")
    first_delta = _intent(
        aggregate,
        "voice:tone-proposal",
        "defina behavior.tone como gentil",
    )
    first_digest = canonical_sha256(first_delta.to_dict())
    motor = LocalOwnerMotor(
        aggregate,
        {first_digest: AuthorizedIntent(first_delta, "voice:tone-confirm", True)},
    )
    first_events = _execute_owner(motor, aggregate, first_delta, "voice:tone-confirm")
    assert motor.last_decision is not None and motor.last_decision.forge_receipt is not None
    first_forge = motor.last_decision.forge_receipt
    permission_snapshot = aggregate.current.capabilities
    aggregate.transition(CreationState.FIRST_FORM, "forge:first-form")
    aggregate.transition(CreationState.CONFIRMATION, "voice:form-confirm")
    aggregate.transition(CreationState.PERSONALITY, "voice:personality")

    # Barge-in is represented as a domain interruption; the physical latency and
    # ASR evidence remain in Sprint 5 and are not fabricated here.
    aggregate.transition(CreationState.INTERRUPTION, "voice:barge-in")
    aggregate.transition(CreationState.CORRECTION, "voice:correction-start")
    aggregate.transition(CreationState.FIRST_FORM, "forge:resume-form")
    aggregate.transition(CreationState.CONFIRMATION, "voice:resume-confirm")
    aggregate.transition(CreationState.PERSONALITY, "voice:resume-personality")
    aggregate.transition(CreationState.SIMULATION, "voice:simulate")

    failed_simulation = SimulationRuntime(
        {
            Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
                Effect.NETWORK_CONNECT,
                (SimulatedResponse(False, error="policy denied in simulation"),),
            )
        }
    ).run(aggregate.current, _plan(aggregate.current.creation_id, "simulation:denied"))
    aggregate.transition(CreationState.CORRECTION, "simulation:denied")
    correction_delta = _intent(
        aggregate,
        "voice:policy-correction",
        "defina behavior.retry como conservador",
    )
    correction_events = _execute_owner(
        motor,
        aggregate,
        correction_delta,
        "voice:policy-confirm",
    )
    assert motor.last_decision is not None and motor.last_decision.forge_receipt is not None
    corrected_forge = motor.last_decision.forge_receipt
    if aggregate.current.capabilities != permission_snapshot:
        raise RuntimeError("correcao alterou permissions")
    aggregate.transition(CreationState.SIMULATION, "voice:retry-simulation")
    successful_simulation = SimulationRuntime(
        {
            Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
                Effect.NETWORK_CONNECT,
                (SimulatedResponse(True, {"accepted": True, "virtual": True}),),
            )
        }
    ).run(aggregate.current, _plan(aggregate.current.creation_id, "simulation:approved"))
    aggregate.transition(CreationState.AGREEMENT, "voice:agreement")

    memory.append(
        event_id="memory:daily-guide",
        kind="CREATION",
        subject_id=aggregate.current.creation_id,
        text="Agente cotidiano de lembretes gentis; politica corrigida e simulada.",
        payload={"version": aggregate.current.version, "state": aggregate.current.state.value},
        source_ids=("voice:first-contact", "voice:agreement"),
    )
    reopened = LivingMemory(
        storage=LocalStorage(target / "profile"),
        clock=clock,
        secret_box=box,
        allow_test_encryption=test_encryption,
    )
    recall = reopened.recall("lembra daquilo agente cotidiano")

    renderer = CreationFieldRenderer()
    field_root = target / "field"
    field_root.mkdir()
    rendered_states: list[str] = []
    for state in CreationState:
        intent_state = state in {
            CreationState.FIRST_INTENT,
            CreationState.LISTENING,
            CreationState.CLARIFICATION,
        }
        view = CreationSpec(
            aggregate.current.creation_id,
            version=aggregate.current.version,
            state=state,
            content=aggregate.current.content,
            capabilities=aggregate.current.capabilities,
        )
        frame = renderer.project(
            view,
            provenance_event_ids=() if state is CreationState.SILENCE else (f"alpha:{state.value}",),
            pending_delta=first_delta if intent_state else None,
            forge_receipt=None if state is CreationState.SILENCE or intent_state else corrected_forge,
        )
        (field_root / f"{state.value.casefold()}.html").write_text(
            renderer.render_html(frame), encoding="utf-8"
        )
        rendered_states.append(state.value)

    materialized = Materializer(target / "materialized").materialize(
        aggregate.current,
        forge_receipt=corrected_forge,
        simulation_receipt=successful_simulation,
    )
    process = subprocess.Popen(
        [sys.executable, str(materialized.directory / "api.py"), "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        endpoint = json.loads(process.stdout.readline())
        with urllib.request.urlopen(
            f"http://127.0.0.1:{endpoint['port']}/creation", timeout=5
        ) as response:
            external_creation = json.loads(response.read())
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    imported = MaterializedPackageImporter().import_archive(materialized.archive)
    imported_aggregate = imported.aggregate_for_reedit()
    imported_correction = imported_aggregate.transition(
        CreationState.CORRECTION,
        "import:reedit",
    )

    report: dict[str, object] = {
        "schema": "casulo-product-alpha-demo/1.0",
        "edition": "casulo-owner",
        "engine_boundary": "owner-direct-first-party",
        "cloud_used": False,
        "third_party_ai_api_used": False,
        "first_guide_turn": first_turn.to_dict(),
        "local_model_turn": local_model_turn,
        "local_model_registry": model_registry.report(),
        "local_embedding_dimensions": len(intent_vector),
        "owner_events": [event.kind.value for event in (*first_events, *correction_events)],
        "creation_id": aggregate.current.creation_id,
        "creation_version": aggregate.current.version,
        "permissions_preserved_during_correction": aggregate.current.capabilities == permission_snapshot,
        "failed_simulation_status": failed_simulation.status,
        "successful_simulation_status": successful_simulation.status,
        "real_effects_executed": successful_simulation.real_effects_executed,
        "recall_status": recall.status,
        "rendered_states": rendered_states,
        "forge_rebuilt_after_correction": list(corrected_forge.rebuilt_units),
        "forge_identity_hash_preserved": {
            item.unit_id: item.artifact_sha256 for item in first_forge.artifacts
        }["identity"] == {
            item.unit_id: item.artifact_sha256 for item in corrected_forge.artifacts
        }["identity"],
        "materialized_archive": str(materialized.archive),
        "materialized_archive_sha256": materialized.archive_sha256,
        "external_api_identity_matches": external_creation["creation_id"] == aggregate.current.creation_id,
        "import_identity_matches": imported.creation.sha256 == aggregate.current.sha256,
        "imported_reedit_version": imported_correction.version,
        "memory_encryption": "TEST_ONLY" if test_encryption else "WINDOWS_DPAPI",
        "physical_voice_evidence_reused_not_replayed": True,
    }
    report_path = target / "alpha-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums = []
    for path in sorted(item for item in target.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        sums.append(f"{digest}  {path.relative_to(target).as_posix()}\n")
    (target / "SHA256SUMS").write_text("".join(sums), encoding="ascii", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo owner Product Alpha vertical slice")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test-encryption", action="store_true")
    args = parser.parse_args()
    report = run(args.output, test_encryption=args.test_encryption)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
