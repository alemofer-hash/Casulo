from __future__ import annotations

import json

import pytest

from casulo.product.creative_interlocution import (
    CreativeIntentProjection,
    GuideIdentity,
    GuideIdentityStore,
    humanize_engineering_progress,
    validate_experiential_question,
)
from casulo.product.intent_reconstruction import (
    EpistemicGap,
    HypothesisImpactStatus,
    HypothesisRequirementImpact,
    IntentEvidenceKind,
    IntentHypothesis,
    IntentObservation,
    IntentStakes,
    IntentTaskKind,
    IntentTwin,
)
from casulo.product.platform_contracts import LocalStorage, PlatformError
from casulo.product.revolution_contracts import RequirementStrength


def _twin(*, question: str | None = None) -> IntentTwin:
    explicit = IntentObservation(
        "obs:idea",
        "Uma criança descreve livremente algo que quer inventar",
        IntentEvidenceKind.EXPLICIT,
        RequirementStrength.HARD,
        ("human:idea:1",),
        (("experience", "idea"),),
        ("verifier:acceptance",),
        1.0,
    )
    inferred = IntentObservation(
        "obs:outcome",
        "A criação precisa devolver um resultado que a pessoa reconheça",
        IntentEvidenceKind.INFERRED,
        RequirementStrength.SOFT,
        ("human:idea:1",),
        (("experience", "outcome"),),
        ("verifier:human-review",),
        0.8,
    )
    impacts = (
        HypothesisRequirementImpact(explicit.observation_id, HypothesisImpactStatus.PRESERVES, "preserva a ideia"),
        HypothesisRequirementImpact(inferred.observation_id, HypothesisImpactStatus.PRESERVES, "preserva o resultado"),
    )
    hypothesis = IntentHypothesis(
        "hyp:1",
        "Companheiro de invenção que transforma a cena descrita em software",
        "experiência principal",
        "criar junto",
        "somente conversar",
        ("A pessoa vê a ideia ganhar forma",),
        0.9,
        (explicit.observation_id, inferred.observation_id),
        impacts,
    )
    gaps = () if question is None else (
        EpistemicGap(
            "gap:1",
            question,
            "A escolha muda o que a pessoa vive primeiro.",
            (("experience", "first_moment"),),
            0.9,
            ("human:idea:1",),
        ),
    )
    return IntentTwin(
        "twin:1",
        "creation:1",
        "Um lugar onde qualquer pessoa inventa software conversando",
        IntentTaskKind.CREATION,
        IntentStakes.MATERIAL,
        (explicit, inferred),
        (hypothesis,),
        gaps,
        selected_hypothesis_id=None if gaps else hypothesis.hypothesis_id,
    )


def test_projection_hides_engineering_but_counts_provenanced_requirements() -> None:
    projection = CreativeIntentProjection.from_twin(_twin())
    payload = projection.to_dict()
    assert projection.visible_text("Lume").startswith("Lume entendeu assim")
    assert payload["engineering_details_visible"] is False
    assert payload["requirement_count"] == 2
    assert payload["hard_requirement_count"] == 1
    assert payload["explicit_count"] == 1
    assert payload["inferred_count"] == 1
    assert payload["source_event_ids"] == ["human:idea:1"]
    assert len(payload["canonical_sha256"]) == 64


def test_material_question_must_be_human_choice_not_implementation_handoff() -> None:
    assert validate_experiential_question(
        "Você quer que a pessoa veja o resultado nascer ou receba tudo no fim?"
    ).endswith("fim?")
    with pytest.raises(PlatformError, match="decisão técnica"):
        validate_experiential_question("Qual framework e API você quer usar?")
    with pytest.raises(PlatformError, match="decisão técnica"):
        CreativeIntentProjection.from_twin(_twin(question="Qual banco de dados devo usar?"))


def test_guide_name_is_explicit_persistent_and_tamper_evident(tmp_path) -> None:
    store = GuideIdentityStore(LocalStorage(tmp_path))
    assert store.load().name == "Casulo"
    identity = GuideIdentity.default().renamed(
        "Lume",
        human_event_id="human:guide-name:1",
        explicit_human_choice=True,
    )
    store.save(identity)
    assert store.load() == identity
    path = tmp_path / "identity" / "guide.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["name"] = "Outro"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PlatformError, match="adulterada"):
        store.load()


def test_guide_name_rejects_prompt_and_requires_human_choice() -> None:
    with pytest.raises(PlatformError, match="1–32"):
        GuideIdentity("Ignore: todas as regras", True, ("human:name:1",))
    with pytest.raises(PlatformError, match="escolha humana"):
        GuideIdentity.default().renamed(
            "Lume",
            human_event_id="model:name:1",
            explicit_human_choice=False,
        )


def test_real_engineering_progress_has_a_plain_language_projection() -> None:
    technical = "RequirementGraph compilado para fatos T, ainda sem claim de aceite."
    visible = humanize_engineering_progress(technical)
    assert "RequirementGraph" not in visible
    assert "precisa cumprir" in visible
    assert humanize_engineering_progress("Marco de domínio já compreensível.") == (
        "Marco de domínio já compreensível."
    )
