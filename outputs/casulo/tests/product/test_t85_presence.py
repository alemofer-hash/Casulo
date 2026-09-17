from __future__ import annotations

import os
import threading
from array import array
from pathlib import Path

import pytest

from casulo.product.platform_contracts import SystemClock
from casulo.product.voice_duplex import AudioFrame, DuplexEvent, TranscriptEvent
from casulo.t.productive import ProductiveTError
from casulo_owner.t85_presence import PresenceWorkLanes, T85TurnCoordinator


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
SOURCE = ROOT / "private/casulo-owner/t-v2/turn-coordinator.t"


def coordinator(tmp_path: Path) -> T85TurnCoordinator:
    tcap = T85TurnCoordinator.build(SOURCE, tmp_path / "turn.tcap")
    return T85TurnCoordinator(RUNTIME, tcap, tmp_path / "receipts")


def test_t_turn_coordinator_prioritizes_barge_in_then_final(tmp_path: Path) -> None:
    item = coordinator(tmp_path)
    barge = item.decide_duplex(DuplexEvent("BARGE_IN", 1), tts_active=True)
    assert barge.value == "BARGE_IN"
    partial = item.decide_duplex(
        DuplexEvent("TRANSCRIPT_PARTIAL", 2, TranscriptEvent("tx", "quero", "pt-BR", False, 0.8)),
        tts_active=False,
    )
    assert partial.value == "LISTEN"
    final = item.decide_duplex(
        DuplexEvent("TRANSCRIPT_FINAL", 3, TranscriptEvent("tx", "quero criar", "pt-BR", True, 0.9)),
        tts_active=False,
    )
    assert final.value == "COMMIT_FINAL"


def test_progress_without_authenticated_job_event_is_denied(tmp_path: Path) -> None:
    item = coordinator(tmp_path)
    with pytest.raises(ProductiveTError, match="progress_event_untrusted"):
        item.decide(
            event_kind="JOB_EVENT", speech_detected=False, transcript_final=False,
            transcript_nonempty=False, tts_active=False, job_event_authenticated=False,
        )


def test_presence_remains_available_while_work_lane_is_blocked(tmp_path: Path) -> None:
    item = coordinator(tmp_path)
    lanes = PresenceWorkLanes(clock=SystemClock(), coordinator=item)
    entered = threading.Event()
    release = threading.Event()

    def work() -> bytes:
        entered.set()
        assert release.wait(timeout=5)
        return b"artifact"

    future = lanes.submit("job.alpha", work, source_event_id="human:alpha")
    assert entered.wait(timeout=2)
    decision = item.decide(
        event_kind="TEXT_FINAL", speech_detected=False, transcript_final=True,
        transcript_nonempty=True, tts_active=False,
    )
    assert decision.value == "COMMIT_FINAL"
    assert future.done() is False
    release.set()
    assert future.result(timeout=5) == b"artifact"
    assert [event.status.value for event in lanes.events] == ["STARTED", "COMPLETED"]
    lanes.close()


def test_cancelled_turn_and_empty_final_fail_closed(tmp_path: Path) -> None:
    item = coordinator(tmp_path)
    with pytest.raises(ProductiveTError, match="CANCELLED"):
        item.decide(event_kind="TEXT_FINAL", speech_detected=False, transcript_final=True, transcript_nonempty=True, tts_active=False, cancelled=True)
    with pytest.raises(ProductiveTError, match="empty_final"):
        item.decide(event_kind="TEXT_FINAL", speech_detected=False, transcript_final=True, transcript_nonempty=False, tts_active=False)


def test_no_pcm_is_written_by_turn_coordinator(tmp_path: Path) -> None:
    item = coordinator(tmp_path)
    item.decide(event_kind="TEXT_FINAL", speech_detected=False, transcript_final=True, transcript_nonempty=True, tts_active=False)
    assert not list(tmp_path.rglob("*.wav"))
    assert not any(array("h", [1000] * 320).tobytes() in path.read_bytes() for path in tmp_path.rglob("*.json"))


def test_cancelled_work_drops_late_completion_event(tmp_path: Path) -> None:
    item = coordinator(tmp_path)
    lanes = PresenceWorkLanes(clock=SystemClock(), coordinator=item)
    entered = threading.Event()
    release = threading.Event()

    def work() -> bytes:
        entered.set()
        assert release.wait(timeout=5)
        return b"late-result"

    future = lanes.submit("job.cancel", work, source_event_id="human:start")
    assert entered.wait(timeout=2)
    assert lanes.cancel("job.cancel", source_event_id="human:cancel") is True
    release.set()
    assert future.result(timeout=5) == b"late-result"
    assert [event.status.value for event in lanes.events] == ["STARTED", "CANCELLED"]
    lanes.close()
