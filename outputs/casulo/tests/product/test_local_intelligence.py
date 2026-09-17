from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from casulo.product.local_intelligence import (
    ContextItem,
    LocalGuidePolicy,
    LocalIntelligenceError,
    LocalModelRegistry,
    load_local_intelligence,
    select_context,
)


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "models/registry.json"


def test_first_party_registry_and_models_are_hash_verified_and_offline() -> None:
    registry, guide, embedding = load_local_intelligence(REGISTRY)
    report = registry.report()
    assert report["ready"] == {"guide": True, "embeddings": True}
    assert report["third_party_ai_api_required"] is False
    assert all(model["owner"] == "Guilherme Moura Fernandes" for model in report["models"])
    response = guide.respond("Quero criar um agente cotidiano")
    assert response["network_used"] is False
    assert response["third_party_ai_api_used"] is False
    vector = embedding.embed("lembretes gentis")
    assert len(vector) == 64
    assert math.isclose(sum(item * item for item in vector), 1.0)


def test_context_selection_never_drops_mandatory_restrictions() -> None:
    items = (
        ContextItem("constraint", "Nunca enviar sem confirmar.", ("voice:1",)),
        ContextItem("history", "O usuario prefere respostas curtas.", ("memory:2",)),
    )
    selected = select_context(items, mandatory_ids=frozenset({"constraint"}), max_chars=30)
    assert [item.context_id for item in selected] == ["constraint"]
    with pytest.raises(LocalIntelligenceError, match="truncamento negado"):
        select_context(items, mandatory_ids=frozenset({"constraint"}), max_chars=5)


def test_hash_mismatch_and_malformed_registry_fail_closed(tmp_path) -> None:
    source = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source["models"][0]["sha256"] = "0" * 64
    (tmp_path / "first-party").mkdir()
    for artifact in (ROOT / "models/first-party").iterdir():
        (tmp_path / "first-party" / artifact.name).write_bytes(artifact.read_bytes())
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(LocalIntelligenceError, match="hash"):
        LocalModelRegistry(registry)
    registry.write_text("not-json", encoding="utf-8")
    with pytest.raises(LocalIntelligenceError, match="JSON local invalido"):
        LocalModelRegistry(registry)


def test_guide_policy_preserves_constraint_semantics() -> None:
    registry = LocalModelRegistry(REGISTRY)
    policy = LocalGuidePolicy(registry.require("casulo-guide-policy-v1"))
    response = policy.respond("Nao pode enviar sem permissao")
    assert response["act"] == "CONSTRAINT"
    assert "restricao" in response["text"].casefold()
