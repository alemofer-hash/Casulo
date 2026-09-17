from __future__ import annotations

from array import array
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from casulo.product.platform_contracts import PlatformError
from casulo.product.hosted_shell import HostedShell
from casulo.product.platform_contracts import (
    BufferedAudioPlayback,
    ConsoleDisplay,
    SyntheticAudioCapture,
)
from casulo.product.voice_duplex import (
    AudioFrame,
    EnergyVad,
    SoundDevicePcmCapture,
    TranscriptEvent,
    UnavailablePtBrAsr,
    VoiceDuplex,
)


def test_sounddevice_capture_turns_driver_rejection_into_platform_error(monkeypatch) -> None:
    def reject_stream(**_kwargs):
        raise RuntimeError("Invalid device")

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(RawInputStream=reject_stream),
    )
    capture = SoundDevicePcmCapture(device=5)
    with pytest.raises(PlatformError, match="dispositivo de entrada 5"):
        capture.start()


class StepClock:
    def __init__(self) -> None:
        self.value = 0

    def monotonic_ns(self) -> int:
        self.value += 1_000_000
        return self.value

    def utc_timestamp(self) -> str:
        return "2026-08-11T00:00:00Z"


class FakeAsr:
    locale = "pt-BR"

    def __init__(self) -> None:
        self.count = 0
        self.resets = 0

    def accept(self, frame: AudioFrame):
        self.count += 1
        if max(array("h", frame.pcm_s16le), default=0) > 0:
            return TranscriptEvent("tx:1", "quero um guia", "pt-BR", False, 0.8)
        return None

    def finalize(self):
        return TranscriptEvent("tx:1", "quero um guia", "pt-BR", True, 0.9)

    def reset(self) -> None:
        self.resets += 1


class FakeSession:
    def __init__(self) -> None:
        self.cancelled = False

    @property
    def active(self) -> bool:
        return not self.cancelled

    def cancel(self) -> None:
        self.cancelled = True


class FakeTts:
    locale = "pt-BR"
    streaming_pcm = True

    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def speak(self, text: str) -> FakeSession:
        assert text
        session = FakeSession()
        self.sessions.append(session)
        return session


def frame(amplitude: int) -> AudioFrame:
    return AudioFrame(array("h", [amplitude] * 320).tobytes())


def make_duplex(endpoint_ms: float = 60.0):
    tts = FakeTts()
    asr = FakeAsr()
    duplex = VoiceDuplex(
        clock=StepClock(),
        vad=EnergyVad(500),
        asr=asr,
        tts=tts,
        endpoint_silence_ms=endpoint_ms,
    )
    return duplex, asr, tts


def test_partial_then_final_after_configured_endpoint() -> None:
    duplex, asr, _ = make_duplex()
    partial = duplex.ingest(frame(1000))
    assert [event.kind for event in partial] == ["TRANSCRIPT_PARTIAL"]
    assert not partial[0].transcript.final
    duplex.ingest(frame(0))
    duplex.ingest(frame(0))
    final = duplex.ingest(frame(0))
    assert [event.kind for event in final] == ["TRANSCRIPT_FINAL"]
    assert final[0].transcript.final
    assert asr.resets == 1


def test_barge_in_cancels_guide_before_accepting_partial() -> None:
    duplex, _, tts = make_duplex()
    duplex.speak("Posso explicar melhor.")
    events = duplex.ingest(frame(1200))
    assert [event.kind for event in events] == ["BARGE_IN", "TRANSCRIPT_PARTIAL"]
    assert tts.sessions[0].cancelled
    assert events[0].cancel_latency_ns == 1_000_000


def test_silence_without_prior_speech_does_not_finalize() -> None:
    duplex, asr, _ = make_duplex()
    for _ in range(10):
        assert duplex.ingest(frame(0)) == ()
    assert asr.resets == 0


def test_empty_final_is_not_committed_as_intent() -> None:
    duplex, asr, _ = make_duplex()
    asr.finalize = lambda: TranscriptEvent("tx:empty", "  ", "pt-BR", True, None)
    duplex.ingest(frame(1000))
    duplex.ingest(frame(0))
    duplex.ingest(frame(0))
    assert duplex.ingest(frame(0)) == ()
    assert asr.resets == 1


def test_unavailable_ptbr_asr_fails_honestly() -> None:
    duplex = VoiceDuplex(
        clock=StepClock(),
        vad=EnergyVad(),
        asr=UnavailablePtBrAsr("nenhum modelo consentido"),
        tts=FakeTts(),
    )
    with pytest.raises(PlatformError, match="indisponível"):
        duplex.ingest(frame(1000))


def test_duplex_rejects_non_ptbr_engine() -> None:
    tts = FakeTts()
    tts.locale = "en-US"
    with pytest.raises(PlatformError, match="pt-BR"):
        VoiceDuplex(clock=StepClock(), vad=EnergyVad(), asr=FakeAsr(), tts=tts)


def test_final_duplex_event_enters_hosted_shell_as_presence() -> None:
    duplex, _, _ = make_duplex()
    shell = HostedShell(
        clock=StepClock(),
        capture=SyntheticAudioCapture(),
        playback=BufferedAudioPlayback(),
        display=ConsoleDisplay(emit_ansi=False),
    )
    duplex.ingest(frame(1000))
    duplex.ingest(frame(0))
    duplex.ingest(frame(0))
    final = duplex.ingest(frame(0))[0]
    assert shell.accept_duplex_event(final)
    assert shell.run_one() == "VOICE"
    assert shell.creation.current.state.value == "FIRST_INTENT"


def test_accessible_text_fallback_is_explicit_final_and_cancels_speech() -> None:
    duplex, _, tts = make_duplex()
    duplex.speak("Estou falando")
    event = duplex.submit_text("  Quero criar por texto  ", transcript_id="text:1")
    assert event.kind == "TEXT_FINAL"
    assert event.transcript is not None
    assert event.transcript.final
    assert event.transcript.confidence is None
    assert event.transcript.text == "Quero criar por texto"
    assert tts.sessions[0].cancelled


def test_asr_candidate_is_pinned_but_not_downloaded_or_enabled() -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = json.loads(
        (root / "release/voice-candidates/whisper-cpp-v1.9.2.json").read_text(
            encoding="utf-8"
        )
    )
    assert candidate["status"] == "PROPOSED_NOT_DOWNLOADED"
    assert candidate["engine"]["commit"] == "306c88f4d1286aec1bf96e544632897886af5501"
    assert candidate["model"]["sha256"] == (
        "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb"
    )
    assert candidate["downloaded"] is False
    assert candidate["enabled_by_default"] is False
