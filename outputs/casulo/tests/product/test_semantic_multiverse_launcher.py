from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_semantic_launcher_is_separate_and_preserves_locked_boundaries() -> None:
    old = (ROOT / "release" / "CASULO_OWNER_VM_INSPECT.ps1").read_text(encoding="utf-8")
    new = (ROOT / "release" / "CASULO_SEMANTIC_MULTIVERSE_VM_INSPECT.ps1").read_text(encoding="utf-8")
    tool = (ROOT / "tools" / "casulo_semantic_multiverse_vm_inspect.py").read_text(encoding="utf-8")
    assert "casulo_owner_vm_inspect.py" in old
    assert "casulo_semantic_multiverse_vm_inspect.py" in new
    assert "network" in tool and "denied" in tool
    assert "RELEASE_LOCKED" in tool and "prohibited" in tool
    assert "clean-semantic-multiverse" in tool
    assert "vm_root.mkdir(parents=True, exist_ok=True)" in tool
    assert "copyfile" not in tool
    assert "block-device" not in new and "-drive" not in new and "usb" not in new.casefold()


def test_human_launcher_uses_encrypted_t_governed_continuity() -> None:
    semantic = (ROOT / "tools" / "casulo_semantic_multiverse_vm_inspect.py").read_text(encoding="utf-8")
    dialogue = (ROOT / "tools" / "casulo_owner_vm_inspect.py").read_text(encoding="utf-8")
    assert "T85ContinuityService" in semantic
    assert "DpapiSecretBox" in semantic
    assert "continuity=continuity" in semantic
    assert "continuity.select_context" in dialogue
    assert "continuity.record_turn" in dialogue
    assert "conversation=tuple(conversation[-16:])" in dialogue  # legacy fallback remains explicit
    assert "if continuity is not None" in dialogue
    assert "T85PhysicalMultiverse" in semantic
    assert "build_physical_universe_bundles" in semantic
    assert "attach_physical_runtime" in semantic
    assert "minimum_residence_ns=1_000_000" in semantic


def test_creation_entry_is_one_free_idea_and_engineering_stays_background() -> None:
    semantic = (ROOT / "tools" / "casulo_semantic_multiverse_vm_inspect.py").read_text(encoding="utf-8")
    assert "Me conta a ideia do jeito que ela apareceu na sua cabeça" in semantic
    assert 'input_kind="OBSERVABLE_EXPECTATION"' not in semantic
    assert "CreativeIntentProjection.from_twin" in semantic
    assert "creative-interlocution.json" in semantic
    assert "Os detalhes de engenharia já estão registrados por baixo" in semantic
    assert "Rota neural proposta:" not in semantic
    assert 'if text == ":nome"' in semantic
