from __future__ import annotations

import json
from pathlib import Path

import pytest

from casulo.product.learned_router import LearnedRouterError, LearnedRouterModel, train_router


ROOT = Path(__file__).resolve().parents[2]


def dataset() -> dict:
    return json.loads((ROOT / "models/training/router-rc5-v1.json").read_text(encoding="utf-8"))


def test_training_is_real_reproducible_and_split_by_family(tmp_path: Path) -> None:
    first, lineage = train_router(dataset())
    second, _ = train_router(dataset())
    assert first == second
    assert lineage["dedup_exact"] is True
    assert not (set(lineage["split_families"]["train"]) & set(lineage["split_families"]["test"]))
    path = tmp_path / "model.json"
    path.write_text(json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    model = LearnedRouterModel.load(path)
    assert model.predict("investigue a falha e explique a causa").universe_id == "diagnostico"
    assert model.predict("empacotar aplicação com sbom e hashes").universe_id == "materializacao"


def test_allowed_universes_never_expand_capabilities(tmp_path: Path) -> None:
    model_payload, _ = train_router(dataset())
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    model = LearnedRouterModel.load(path)
    prediction = model.predict("execute e compile os componentes", allowed_universes={"intencao", "diagnostico"})
    assert prediction.universe_id in {"intencao", "diagnostico"}
    with pytest.raises(LearnedRouterError):
        model.predict("qualquer coisa", allowed_universes=set())


def test_tampered_model_is_rejected(tmp_path: Path) -> None:
    model_payload, _ = train_router(dataset())
    model_payload["log_priors"]["intencao"] = 999
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(LearnedRouterError, match="hash"):
        LearnedRouterModel.load(path)
