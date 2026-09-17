from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import zipfile

import pytest

from casulo.product.capabilities import Effect
from casulo.product.creation_pipeline import creation_units
from casulo.product.domain import CreationSpec, CreationState
from casulo.product.materializer import (
    ExecutableAgentBundle,
    MaterializationError,
    MaterializedPackageImporter,
    Materializer,
)
from casulo.t.artifact import ArtifactBuilder
from casulo.product.simulation import (
    SimulatedResponse,
    SimulationCapabilityDouble,
    SimulationPlan,
    SimulationRuntime,
    SimulationStep,
)
from casulo.product.t_forge import TForge


def inputs(*, content=None):
    creation = CreationSpec(
        "creation:materializer",
        version=7,
        state=CreationState.AGREEMENT,
        content=content or {"behavior": {"tone": "resiliente"}},
        capabilities=frozenset({Effect.NETWORK_CONNECT.value}),
    )
    forge = TForge().compile(creation_units(creation))
    simulation_creation = CreationSpec(
        creation.creation_id,
        version=creation.version,
        state=CreationState.CONFIRMATION,
        content=creation.content,
        capabilities=creation.capabilities,
    )
    plan = SimulationPlan(
        "simulation:materializer",
        creation.creation_id,
        (
            SimulationStep(
                "virtual-request",
                Effect.NETWORK_CONNECT,
                "preview",
                {"url": "simulation://local"},
                (),
                (("behavior", "tone"),),
                ("voice:simulate",),
            ),
        ),
        ("voice:simulate",),
    )
    simulation = SimulationRuntime(
        {
            Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
                Effect.NETWORK_CONNECT,
                (SimulatedResponse(True, {"status": 202, "virtual": True}),),
            )
        }
    ).run(simulation_creation, plan)
    return creation, forge, simulation


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_materialization_is_complete_hashed_and_reproducible(tmp_path) -> None:
    creation, forge, simulation = inputs()
    first = Materializer(tmp_path / "one").materialize(
        creation, forge_receipt=forge, simulation_receipt=simulation
    )
    second = Materializer(tmp_path / "two").materialize(
        creation, forge_receipt=forge, simulation_receipt=simulation
    )
    assert first.archive_sha256 == second.archive_sha256
    assert sha(first.archive) == first.archive_sha256
    manifest = json.loads((first.directory / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["engine_boundary"] == "engine-agnostic-no-owner-components"
    assert manifest["bind_policy"] == "127.0.0.1-only"
    assert manifest["real_effects_included"] is False
    with zipfile.ZipFile(first.archive) as archive:
        assert set(archive.namelist()) == {name for name, _digest in first.files}
        assert all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist())
    sums = dict(
        line.split("  ", 1)[::-1]
        for line in (first.directory / "SHA256SUMS").read_text().splitlines()
    )
    for name, digest in sums.items():
        assert sha(first.directory / name) == digest


def test_generated_api_binds_loopback_and_serves_sealed_health(tmp_path) -> None:
    creation, forge, simulation = inputs()
    receipt = Materializer(tmp_path).materialize(
        creation, forge_receipt=forge, simulation_receipt=simulation
    )
    process = subprocess.Popen(
        [sys.executable, str(receipt.directory / "api.py"), "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        endpoint = json.loads(process.stdout.readline())
        assert endpoint["bind"] == "127.0.0.1"
        with urllib.request.urlopen(
            f"http://127.0.0.1:{endpoint['port']}/health", timeout=5
        ) as response:
            payload = json.loads(response.read())
        assert payload == {"effects": "simulation-only", "ok": True}
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_secret_fields_and_private_keys_are_rejected_before_export(tmp_path) -> None:
    creation, forge, simulation = inputs(content={"config": {"api_key": "never"}})
    with pytest.raises(MaterializationError, match="campo secreto"):
        Materializer(tmp_path).materialize(
            creation, forge_receipt=forge, simulation_receipt=simulation
        )
    assert list(tmp_path.iterdir()) == []


def test_materializer_requires_agreement_matching_pass_and_refuses_overwrite(tmp_path) -> None:
    creation, forge, simulation = inputs()
    wrong_state = CreationSpec(
        creation.creation_id,
        state=CreationState.CONFIRMATION,
        capabilities=creation.capabilities,
    )
    with pytest.raises(MaterializationError, match="AGREEMENT"):
        Materializer(tmp_path).materialize(
            wrong_state, forge_receipt=forge, simulation_receipt=simulation
        )
    materializer = Materializer(tmp_path)
    materializer.materialize(creation, forge_receipt=forge, simulation_receipt=simulation)
    with pytest.raises(MaterializationError, match="overwrite"):
        materializer.materialize(creation, forge_receipt=forge, simulation_receipt=simulation)


def test_package_contains_no_owner_adapter_or_secrets(tmp_path) -> None:
    creation, forge, simulation = inputs()
    receipt = Materializer(tmp_path).materialize(
        creation, forge_receipt=forge, simulation_receipt=simulation
    )
    combined = b"\n".join(path.read_bytes() for path in receipt.directory.iterdir() if path.is_file())
    lowered = combined.lower()
    assert b"ownerengineadapter" not in lowered
    assert b"private_components" not in lowered
    assert b"api_key" not in lowered


def test_package_round_trip_preserves_identity_version_and_supports_reedit(tmp_path) -> None:
    creation, forge, simulation = inputs()
    receipt = Materializer(tmp_path).materialize(
        creation, forge_receipt=forge, simulation_receipt=simulation
    )
    imported = MaterializedPackageImporter().import_archive(receipt.archive)
    assert imported.archive_sha256 == receipt.archive_sha256
    assert imported.creation.sha256 == creation.sha256
    aggregate = imported.aggregate_for_reedit()
    corrected = aggregate.transition(CreationState.CORRECTION, "import:human-reedit")
    assert corrected.creation_id == creation.creation_id
    assert corrected.version == creation.version + 1
    assert corrected.capabilities == creation.capabilities


def test_materialized_compiled_t_agent_executes_outside_creator_process(tmp_path) -> None:
    source = tmp_path / "generated.t"
    source.write_text(
        """language T/1.1
module generated.external

capability manifest

field Input
  trace value: Text

condense Answer in Input
  effects [manifest]
  emit "resposta materializada"
""",
        encoding="utf-8",
    )
    built = ArtifactBuilder().build(source, tmp_path / "compiled")
    operation = built.manifest["operations"][0]["name"]
    creation, forge, simulation = inputs()
    bundle = ExecutableAgentBundle(
        built.artifact_id,
        operation,
        (built.output_dir / "casulo_artifact.py").read_bytes(),
        built.manifest,
        b"TCAP-test-sealed",
        {"schema": "casulo.generated-project/1.0", "entry_unit": "external"},
        source.read_bytes(),
    )
    receipt = Materializer(tmp_path / "export").materialize(
        creation,
        forge_receipt=forge,
        simulation_receipt=simulation,
        executable_bundle=bundle,
    )
    process = subprocess.run(
        [sys.executable, str(receipt.directory / "agent.py"), operation, "-"],
        input=json.dumps({"value": "olá"}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["result"] == "resposta materializada"
    imported = MaterializedPackageImporter().import_archive(receipt.archive)
    assert imported.creation.sha256 == creation.sha256
    assert imported.agent_artifact_id == built.artifact_id
    assert imported.agent_operation == operation


def test_target_matrix_is_truthful_and_web_surface_has_csp(tmp_path) -> None:
    creation, forge, simulation = inputs()
    without_agent = Materializer(tmp_path / "plain").materialize(
        creation, forge_receipt=forge, simulation_receipt=simulation
    )
    plain_manifest = json.loads((without_agent.directory / "MANIFEST.json").read_text(encoding="utf-8"))
    plain_targets = {item["target"]: item for item in plain_manifest["targets"]}
    assert plain_targets["cli"]["supported"] is False
    assert plain_targets["api-loopback"]["supported"] is True
    assert plain_targets["desktop-web-local"]["entrypoint"] == "index.html"
    assert plain_manifest["secret_slots"] == []
    assert plain_manifest["real_effects_included"] is False

    process = subprocess.Popen(
        [sys.executable, "-I", str(without_agent.directory / "api.py"), "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={"SYSTEMROOT": os.environ["SYSTEMROOT"], "PATH": os.environ.get("PATH", ""), "PYTHONUTF8": "1"},
    )
    try:
        assert process.stdout is not None
        endpoint = json.loads(process.stdout.readline())
        with urllib.request.urlopen(f"http://127.0.0.1:{endpoint['port']}/", timeout=5) as response:
            html = response.read().decode("utf-8")
            csp = response.headers["Content-Security-Policy"]
        assert "Criação Casulo" in html
        assert "script-src 'none'" in csp
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_import_rejects_tamper_and_path_traversal(tmp_path) -> None:
    creation, forge, simulation = inputs()
    receipt = Materializer(tmp_path / "source").materialize(
        creation, forge_receipt=forge, simulation_receipt=simulation
    )
    tampered = tmp_path / "tampered.casulo.zip"
    with zipfile.ZipFile(receipt.archive) as original, zipfile.ZipFile(tampered, "w") as changed:
        for item in original.infolist():
            payload = original.read(item.filename)
            if item.filename == "creation.json":
                payload += b" "
            changed.writestr(item, payload)
    with pytest.raises(MaterializationError, match="hash divergente"):
        MaterializedPackageImporter().import_archive(tampered)

    traversal = tmp_path / "traversal.casulo.zip"
    with zipfile.ZipFile(traversal, "w") as package:
        package.writestr("../creation.json", b"{}")
    with pytest.raises(MaterializationError, match="layout ZIP inseguro"):
        MaterializedPackageImporter().import_archive(traversal)
