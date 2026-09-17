from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from casulo.product.capabilities import Effect
from casulo.product.creation_pipeline import creation_units
from casulo.product.domain import CreationSpec, CreationState
from casulo.product.materializer import MaterializationError
from casulo.product.simulation import SimulatedResponse, SimulationCapabilityDouble, SimulationPlan, SimulationRuntime, SimulationStep
from casulo.product.sovereign_materializer import SovereignPackageImporter, SovereignTAgentBundle
from casulo.product.t_forge import TForge
from casulo_owner.t85_materialization import T85MaterializationDenied, T85SovereignMaterializer
from casulo_owner.t85_physical_multiverse import T85PhysicalMultiverse


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release/casulo-t-runtime.exe"
AGENT_POLICY = ROOT / "private/casulo-owner/t-v2/universe-lifecycle-policy.t"
MATERIALIZATION_POLICY = ROOT / "private/casulo-owner/t-v2/materialization-lifecycle.t"


def inputs(tmp_path: Path, *, secret: bool = False):
    content = {"identity": {"purpose": "agente T portátil"}, "constraints": ["sem rede"]}
    if secret:
        content["config"] = {"api_key": "denied"}
    creation = CreationSpec("creation:t85-portable", 2, CreationState.AGREEMENT, content, frozenset({Effect.NETWORK_CONNECT.value}))
    forge = TForge().compile(creation_units(creation))
    confirmation = CreationSpec(creation.creation_id, creation.version, CreationState.CONFIRMATION, creation.content, creation.capabilities)
    simulation = SimulationRuntime({
        Effect.NETWORK_CONNECT: SimulationCapabilityDouble(Effect.NETWORK_CONNECT, (SimulatedResponse(True, {"virtual": True}),)),
    }).run(confirmation, SimulationPlan(
        "simulation:t85", creation.creation_id,
        (SimulationStep("preview", Effect.NETWORK_CONNECT, "preview", {"url": "simulation://local"}, (), (("identity", "purpose"),), ("human:agreement",)),),
        ("human:agreement",),
    ))
    agent_tcap = T85PhysicalMultiverse.build_policy(AGENT_POLICY, tmp_path / "agent.tcap")
    agent = SovereignTAgentBundle(
        agent_tcap, RUNTIME, "owner.multiverse.lifecycle_policy", "decide",
        "owner.agent.test_portable", {"schema": "casulo.generated-project/2.0", "nontrivial": True},
    )
    materialization_tcap = T85SovereignMaterializer.build_policy(MATERIALIZATION_POLICY, tmp_path / "materialization.tcap")
    service = T85SovereignMaterializer(RUNTIME, materialization_tcap, tmp_path / "exports", tmp_path / "authority")
    return creation, forge, simulation, agent, service


def authority_args() -> dict[str, object]:
    return {
        "requirement_graph": {
            "schema": "casulo.requirement-graph/1.0",
            "requirements": [{"id": "portable", "strength": "HARD", "statement": "executar T fora do checkout"}],
            "dependencies": {},
        },
        "evidence_receipts": {
            "schema": "casulo.evidence-set/1.0",
            "receipts": [{"requirement_id": "portable", "verdict": "PASS", "producer": "clean-room-verifier"}],
        },
    }


def test_t_policy_denies_unapproved_or_secret_before_publication(tmp_path: Path) -> None:
    creation, forge, simulation, agent, service = inputs(tmp_path / "approval")
    with pytest.raises(T85MaterializationDenied, match="publish_human_approval_required"):
        service.materialize(creation, forge_receipt=forge, simulation_receipt=simulation, agent=agent, previous_fulfillment="FULFILLED", human_approved=False, **authority_args())
    assert not (tmp_path / "approval/exports").exists()

    creation, forge, simulation, agent, service = inputs(tmp_path / "secret", secret=True)
    with pytest.raises(T85MaterializationDenied, match="real_effect_or_secret_denied"):
        service.materialize(creation, forge_receipt=forge, simulation_receipt=simulation, agent=agent, previous_fulfillment="FULFILLED", human_approved=True, **authority_args())
    assert not (tmp_path / "secret/exports").exists()


def test_v2_package_executes_t_runtime_clean_and_round_trips(tmp_path: Path) -> None:
    creation, forge, simulation, agent, service = inputs(tmp_path)
    result = service.materialize(
        creation, forge_receipt=forge, simulation_receipt=simulation, agent=agent,
        previous_fulfillment="FULFILLED", human_approved=True, **authority_args(),
    )
    imported = SovereignPackageImporter().import_archive(result.receipt.archive)
    assert imported.creation.sha256 == creation.sha256
    assert len(imported.manifest["targets"]) == 5
    assert all(item["supported"] for item in imported.manifest["targets"])
    assert imported.manifest["real_effects_included"] is False
    assert imported.manifest["signature_class"] == "DEVELOPMENT_NOT_COMMERCIAL"
    clean = imported.extract_to(tmp_path / "clean-room")
    env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT") if name in os.environ}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    payload = {
        "action": "ACTIVATE", "trusted_route": True, "bundle_valid": True,
        "capability_safe": True, "can_hibernate": False,
        "sufficient_state_valid": True, "cancelled": False,
    }
    completed = subprocess.run(
        [sys.executable, "-I", str(clean / "agent.py")], input=json.dumps(payload),
        text=True, encoding="utf-8", capture_output=True, cwd=clean, env=env,
        timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["observable"]["result"] == {"kind": "ok", "value": "ACTIVATE"}
    assert document["runtime_receipt"]["runtime_id"] == "t-runtime/rust-2.0"
    assert "PYTHONPATH" not in env and not (clean / ".git").exists()
    edited = imported.aggregate_for_reedit().transition(CreationState.CORRECTION, "human:reedit")
    assert edited.creation_id == creation.creation_id and edited.version == creation.version + 1


def test_v2_import_rejects_tamper_and_nested_traversal(tmp_path: Path) -> None:
    creation, forge, simulation, agent, service = inputs(tmp_path / "source")
    result = service.materialize(creation, forge_receipt=forge, simulation_receipt=simulation, agent=agent, previous_fulfillment="FULFILLED", human_approved=True, **authority_args())
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(result.receipt.archive) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "creation.json":
                payload += b" "
            target.writestr(info, payload)
    with pytest.raises(MaterializationError, match="hash mismatch"):
        SovereignPackageImporter().import_archive(tampered)
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as package:
        package.writestr("tcap/../../escape", b"x")
    with pytest.raises(MaterializationError, match="unsafe package path"):
        SovereignPackageImporter().import_archive(traversal)
