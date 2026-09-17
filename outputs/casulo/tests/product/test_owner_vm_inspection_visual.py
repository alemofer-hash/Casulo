from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from casulo.product.creation_field import CreationPresentation
from casulo.product.domain import (
    CreationSpec,
    CreationState,
    DomainError,
    creation_spec_from_document,
)
from casulo.product.t_forge import ForgeArtifact, ForgeReceipt
from tools import casulo_owner_vm_inspect


@pytest.mark.parametrize(
    ("content", "expected", "diagnostic"),
    [
        ({"identity": {"name": {"type": "string", "value": "Agente Teste"}}}, "Agente Teste", None),
        ({"identity": {}}, "creation:test", "identity_name_missing"),
        ({"identity": {"name": {"type": "string"}}}, "creation:test", "identity_name_value_missing"),
        ({}, "creation:test", "identity_missing"),
    ],
)
def test_creation_presentation_is_total_for_every_valid_identity_variant(
    content, expected, diagnostic
) -> None:
    projection = CreationPresentation.from_creation(CreationSpec("creation:test", content=content))
    assert projection.display_name == expected
    if diagnostic:
        assert diagnostic in projection.diagnostics


@pytest.mark.parametrize(
    "content",
    [
        {"identity": {"name": {"value": 42}}},
        {"identity": "quebrada"},
        {"identity": {"name": 42}},
    ],
)
def test_wrong_identity_types_are_rejected_before_render(content) -> None:
    with pytest.raises(Exception, match="identity"):
        CreationPresentation.from_creation(CreationSpec("creation:test", content=content))


def test_old_creation_schema_is_migrated_and_future_schema_is_rejected() -> None:
    old = creation_spec_from_document(
        {"schema": "casulo.creation/0.1", "id": "creation:old", "title": "Legado"}
    )
    assert CreationPresentation.from_creation(old).display_name == "Legado"
    with pytest.raises(DomainError, match="schema"):
        creation_spec_from_document(
            {"schema": "casulo.creation/9.9", "creation_id": "creation:future"}
        )


def test_partial_creation_document_is_rejected_without_keyerror() -> None:
    with pytest.raises(DomainError, match="incompleto"):
        creation_spec_from_document({"schema": "casulo.creation/1.0", "content": {}})


def test_invalid_identity_does_not_create_visual_directory(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "creation"
    root.mkdir()
    creation = CreationSpec(
        "creation:invalid-identity", version=1,
        state=CreationState.CONFIRMATION, content={"identity": "invalid"},
    )
    (root / "confirmed-creation.json").write_text(json.dumps(creation.to_dict()), encoding="utf-8")
    monkeypatch.setattr(
        casulo_owner_vm_inspect.MaterializedPackageImporter,
        "import_archive",
        lambda _self, _archive: SimpleNamespace(creation=creation),
    )
    output = root / "visual"
    with pytest.raises(Exception, match="identity"):
        casulo_owner_vm_inspect.render_creation_timeline(
            root, {"materialization": {"archive": str(tmp_path / "x.zip")}}, output
        )
    assert not output.exists()


def test_materialized_owner_creation_without_name_gets_browsable_timeline(
    tmp_path: Path, monkeypatch
) -> None:
    creation_root = tmp_path / "creation"
    creation_root.mkdir()
    confirmed = CreationSpec(
        "creation:test",
        version=3,
        state=CreationState.CONFIRMATION,
        content={"identity": {"purpose": {"value": "solver"}}},
    )
    (creation_root / "confirmed-creation.json").write_text(
        json.dumps(confirmed.to_dict()), encoding="utf-8"
    )
    receipt = ForgeReceipt(
        "forge:test",
        (),
        ("unit",),
        (),
        (ForgeArtifact("unit", "a" * 64, "b" * 64, "c" * 64, (), "d" * 64),),
    )
    monkeypatch.setattr(casulo_owner_vm_inspect, "forge_receipt", lambda _root: receipt)
    monkeypatch.setattr(
        casulo_owner_vm_inspect.MaterializedPackageImporter,
        "import_archive",
        lambda _self, _archive: SimpleNamespace(creation=confirmed),
    )
    rendered = casulo_owner_vm_inspect.render_creation_timeline(
        creation_root,
        {"materialization": {"archive": str(tmp_path / "agent.casulo.zip")}},
        creation_root / "visual",
    )
    assert rendered["pages"] == 12
    assert rendered["agent_name"] == "creation:test"
    assert rendered["identity_source"] == "creation_id"
    assert "identity_name_missing" in rendered["projection_diagnostics"]
    index = Path(str(rendered["index"]))
    assert "creation:test" in index.read_text(encoding="utf-8")
    timeline = json.loads((creation_root / "visual" / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["pages"][-1]["state"] == "MATERIALIZATION"


def test_preserved_creation_roundtrips_into_reedit_aggregate() -> None:
    original = CreationSpec(
        "creation:einstein-preserved",
        version=7,
        state=CreationState.AGREEMENT,
        content={"identity": {"purpose": {"value": "equacoes de campo"}}},
    )
    restored = creation_spec_from_document(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert restored.creation_id == "creation:einstein-preserved"
