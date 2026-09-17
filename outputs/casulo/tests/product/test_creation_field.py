from __future__ import annotations

from casulo.product.creation_field import CreationFieldRenderer, CreationFieldTheme
from casulo.product.creation_pipeline import CreationPipeline
from casulo.product.domain import CreationAggregate, CreationSpec, CreationState


def formed_creation(tone: str = "direto"):
    aggregate = CreationAggregate(CreationSpec("creation:field"))
    pipeline = CreationPipeline(aggregate)
    pipeline.bootstrap()
    aggregate.transition(CreationState.FIRST_INTENT, "voice:seed")
    interpretation = pipeline.propose(
        source_event_id="voice:proposal",
        utterance=f"defina behavior.tone como {tone}",
    )
    decision = pipeline.decide(
        human_event_id="voice:confirm",
        accepted=True,
        explicit_human_approval=True,
    )
    aggregate.transition(CreationState.FIRST_FORM, "voice:confirm")
    return aggregate, pipeline, interpretation.delta, decision.forge_receipt


def node_map(frame):
    return {node.node_id: node for node in frame.nodes}


def test_silence_is_empty_and_never_fakes_progress() -> None:
    frame = CreationFieldRenderer().project(
        CreationSpec("creation:silence"),
        provenance_event_ids=(),
    )
    assert frame.state is CreationState.SILENCE
    assert frame.nodes == () and frame.edges == ()
    assert "silêncio" in frame.summary


def test_first_intent_is_provisional_and_bound_to_delta() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:field"))
    pipeline = CreationPipeline(aggregate)
    pipeline.bootstrap()
    aggregate.transition(CreationState.FIRST_INTENT, "voice:seed")
    delta = pipeline.propose(
        source_event_id="voice:proposal",
        utterance="defina behavior.tone como direto",
    ).delta
    frame = CreationFieldRenderer().project(
        aggregate.current,
        provenance_event_ids=("voice:seed",),
        pending_delta=delta,
    )
    assert frame.nodes[0].kind == "intent-seed"
    assert frame.nodes[0].certainty == "proposed"
    assert frame.nodes[0].artifact_sha256 is not None


def test_first_form_uses_real_forge_artifacts_and_edges() -> None:
    aggregate, _pipeline, _delta, receipt = formed_creation()
    assert receipt is not None
    frame = CreationFieldRenderer().project(
        aggregate.current,
        provenance_event_ids=("voice:proposal", "voice:confirm"),
        forge_receipt=receipt,
    )
    assert frame.state is CreationState.FIRST_FORM
    assert {node.node_id for node in frame.nodes} == {"identity", "behavior", "interface"}
    assert set(frame.edges) == {("identity", "interface"), ("behavior", "interface")}
    assert all(node.artifact_sha256 for node in frame.nodes)


def test_correction_preserves_unaffected_manifestation_fingerprint() -> None:
    aggregate, pipeline, _delta, receipt = formed_creation()
    assert receipt is not None
    renderer = CreationFieldRenderer()
    before = renderer.project(
        aggregate.current,
        provenance_event_ids=("voice:1",),
        forge_receipt=receipt,
    )
    pipeline.propose(
        source_event_id="voice:correction",
        utterance="defina behavior.tone como conciso",
    )
    corrected = pipeline.decide(
        human_event_id="voice:correction-confirm",
        accepted=True,
        explicit_human_approval=True,
    )
    assert corrected.forge_receipt is not None
    after = renderer.project(
        aggregate.current,
        provenance_event_ids=("voice:correction", "voice:correction-confirm"),
        forge_receipt=corrected.forge_receipt,
    )
    old, new = node_map(before), node_map(after)
    assert old["identity"].fingerprint == new["identity"].fingerprint
    assert (old["identity"].x, old["identity"].y) == (new["identity"].x, new["identity"].y)
    assert old["behavior"].fingerprint != new["behavior"].fingerprint


def test_confirmation_has_explicit_ring_and_provenance() -> None:
    aggregate, _pipeline, _delta, receipt = formed_creation()
    aggregate.transition(CreationState.CONFIRMATION, "voice:review")
    frame = CreationFieldRenderer().project(
        aggregate.current,
        provenance_event_ids=("voice:review",),
        forge_receipt=receipt,
    )
    assert frame.confirmation_ring is True
    assert frame.phase == "confirmation"


def test_all_twelve_creation_states_are_renderable_without_fake_work() -> None:
    aggregate, _pipeline, delta, receipt = formed_creation()
    renderer = CreationFieldRenderer()
    observed = []
    for state in CreationState:
        creation = CreationSpec(
            aggregate.current.creation_id,
            version=aggregate.current.version,
            state=state,
            content=aggregate.current.content,
        )
        intent_state = state in {
            CreationState.FIRST_INTENT,
            CreationState.LISTENING,
            CreationState.CLARIFICATION,
        }
        frame = renderer.project(
            creation,
            provenance_event_ids=() if state is CreationState.SILENCE else (f"event:{state.value}",),
            pending_delta=delta if intent_state else None,
            forge_receipt=None if state is CreationState.SILENCE or intent_state else receipt,
        )
        observed.append(frame.state)
        assert frame.phase and frame.summary
        if state is CreationState.SILENCE:
            assert frame.nodes == ()
    assert tuple(observed) == tuple(CreationState)


def test_html_is_self_contained_accessible_and_escapes_untrusted_identity() -> None:
    frame = CreationFieldRenderer().project(
        CreationSpec("<script>alert(1)</script>"),
        provenance_event_ids=(),
    )
    document = CreationFieldRenderer().render_html(frame)
    assert "default-src 'none'" in document
    assert "<script>" not in document
    assert "&lt;script&gt;" in document
    assert "role=\"img\"" in document
    assert "prefers-reduced-motion" in document
    assert "drag" not in document.casefold()
    assert 'data-design-status="PROVISIONAL_OWNER_REVIEW_REQUIRED"' in document


def test_visual_tokens_are_externalized_and_never_claim_final_approval() -> None:
    theme = CreationFieldTheme.load()
    assert theme.theme_id == "stark-jobs-provisional-v1"
    assert theme.design_status == "PROVISIONAL_OWNER_REVIEW_REQUIRED"
    assert set(theme.colors) == {"ink", "ivory", "amber", "cobalt", "mist", "deep_blue"}
