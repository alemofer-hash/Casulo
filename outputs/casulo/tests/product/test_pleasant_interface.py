from __future__ import annotations

import hashlib
import threading

import pytest

from casulo.product.pleasant_interface import (
    HonestBackgroundJob,
    JobEvidence,
    UxEvent,
    UxEventKind,
    UxStreamValidator,
    decode_ux_event,
    encode_ux_event,
)


def event(event_id: str, kind: UxEventKind, payload: dict[str, object]) -> UxEvent:
    return UxEvent.create(
        event_id=event_id,
        kind=kind,
        payload=payload,
        source_event_ids=("runtime:test",),
        occurred_at="2026-08-18T12:00:00Z",
    )


def test_stream_round_trip_is_hash_bound_and_preserves_token_whitespace() -> None:
    original = event(
        "ux:1",
        UxEventKind.ASSISTANT_TOKEN,
        {"turn_id": "turn:1", "sequence": 1, "text": "Oi,\nGuilherme. "},
    )
    decoded = decode_ux_event(encode_ux_event(original))
    assert decoded == original
    assert decoded is not None and decoded.payload["text"] == "Oi,\nGuilherme. "


def test_validator_rejects_late_or_out_of_order_tokens() -> None:
    validator = UxStreamValidator()
    validator.accept(event("ux:1", UxEventKind.ASSISTANT_START, {"turn_id": "turn:1"}))
    with pytest.raises(ValueError, match="ordem"):
        validator.accept(event("ux:2", UxEventKind.ASSISTANT_TOKEN, {"turn_id": "turn:1", "sequence": 2, "text": "x"}))
    validator.accept(event("ux:3", UxEventKind.ASSISTANT_TOKEN, {"turn_id": "turn:1", "sequence": 1, "text": "x"}))
    validator.accept(event("ux:4", UxEventKind.ASSISTANT_END, {"turn_id": "turn:1", "finish_reason": "stop"}))
    with pytest.raises(ValueError, match="ativo"):
        validator.accept(event("ux:5", UxEventKind.ASSISTANT_TOKEN, {"turn_id": "turn:1", "sequence": 2, "text": "tardio"}))


def test_progress_percentage_without_evidence_is_forbidden() -> None:
    with pytest.raises(ValueError, match="inventado"):
        event(
            "ux:job",
            UxEventKind.JOB_MILESTONE,
            {"job_id": "job:1", "summary": "quase", "evidence_sha256": "a" * 64, "progress_percent": 90},
        )
    with pytest.raises(ValueError, match="evidência"):
        event("ux:job2", UxEventKind.JOB_STARTED, {"job_id": "job:1", "summary": "começou"})


def test_zero_digest_is_not_job_evidence() -> None:
    with pytest.raises(ValueError, match="evidência real"):
        event(
            "ux:zero",
            UxEventKind.JOB_STARTED,
            {"job_id": "job:zero", "summary": "sem prova", "evidence_sha256": "0" * 64},
        )


def test_background_job_emits_only_real_milestones_and_completion() -> None:
    events = []
    coordinator = HonestBackgroundJob(events.append)

    def worker(_token, report):
        report("T compilado.", "b" * 64)
        return JobEvidence("c" * 64, "Pacote materializado.", {"archive": "sealed"})

    coordinator.start("creation:1", worker, start_evidence_sha256="a" * 64)
    coordinator.join(2)
    assert [item.status for item in events] == ["STARTED", "MILESTONE", "COMPLETED"]
    assert [item.evidence_sha256 for item in events] == ["a" * 64, "b" * 64, "c" * 64]
    assert coordinator.snapshot()["status"] == "COMPLETED"


def test_cancelled_job_discards_late_completion() -> None:
    entered = threading.Event()
    release = threading.Event()
    events = []
    coordinator = HonestBackgroundJob(events.append)

    def worker(_token, _report):
        entered.set()
        release.wait(2)
        return JobEvidence("d" * 64, "resultado tardio", {})

    coordinator.start("creation:cancel", worker, start_evidence_sha256="a" * 64)
    assert entered.wait(1)
    assert coordinator.cancel()
    release.set()
    coordinator.join(2)
    assert [item.status for item in events] == ["STARTED", "CANCELLED"]
    assert coordinator.snapshot()["status"] == "CANCELLED"


def test_non_protocol_line_remains_outside_structured_surface() -> None:
    assert decode_ux_event("traceback técnico") is None
