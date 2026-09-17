from __future__ import annotations

from pathlib import Path

import pytest

from casulo.product.platform_contracts import PlatformError
from casulo.product.voice_candidate import VoiceCandidate
from casulo.product.voice_duplex import AudioFrame, TranscriptEvent
from casulo.product.voice_physical import (
    BARGE_IN_CONSENT,
    CAPTURE_CONSENT,
    PLAYBACK_CONSENT,
    capture_microphone_smoke,
    barge_in_smoke,
    playback_cancel_smoke,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "release/voice-candidates/whisper-cpp-base-q5_1-v1.9.2.json"


class FakeCapture:
    def __init__(self, **_kwargs):
        self.frames = [AudioFrame(b"\xe8\x03" * 320)]
        self.started = False
        self.closed = False

    def start(self): self.started = True
    def poll(self): return self.frames.pop() if self.frames else None
    def close(self): self.closed = True


class FakeAsr:
    def __init__(self): self.closed = False
    def accept(self, _frame): return None
    def finalize(self): return TranscriptEvent("physical:1", "olá casulo", "pt-BR", True, None)
    def close(self): self.closed = True


def test_capture_requires_exact_consent_before_device_factory(tmp_path) -> None:
    called = False
    def factory(**_kwargs):
        nonlocal called
        called = True
        return FakeCapture()
    with pytest.raises(PlatformError, match="consentimento ausente"):
        capture_microphone_smoke(
            VoiceCandidate.load(MANIFEST), tmp_path, consent="sim", capture_factory=factory
        )
    assert not called


def test_capture_never_persists_pcm_and_closes_resources(tmp_path) -> None:
    capture = FakeCapture()
    asr = FakeAsr()
    captured_options = {}

    def capture_factory(**options):
        captured_options.update(options)
        return capture

    ticks = iter([0.0, 0.0, 9.0, 9.1])
    report = capture_microphone_smoke(
        VoiceCandidate.load(MANIFEST),
        tmp_path,
        consent=CAPTURE_CONSENT,
        device=5,
        capture_factory=capture_factory,
        asr_factory=lambda *_args, **_kwargs: asr,
        clock=lambda: next(ticks),
        sleeper=lambda _seconds: None,
    )
    assert report["passed"] is True
    assert report["raw_audio_persisted"] is False
    assert report["input_device"] == 5
    assert captured_options["device"] == 5
    assert report["frames"] == 1
    assert capture.closed and asr.closed


class FakeSession:
    def __init__(self): self.active = True
    def cancel(self): self.active = False


class FakeTts:
    streaming_playback = True
    streaming_pcm = False
    redistributed = False
    def __init__(self): self.session = FakeSession()
    def speak(self, _text): return self.session


def test_playback_cancel_is_bounded_and_reported() -> None:
    ticks = iter([1_000, 1_250])
    report = playback_cancel_smoke(
        consent=PLAYBACK_CONSENT,
        tts_factory=FakeTts,
        sleeper=lambda _seconds: None,
        clock_ns=lambda: next(ticks),
    )
    assert report["passed"] is True
    assert report["cancel_latency_ns"] == 250
    assert report["streaming_playback"] is True


def test_barge_in_requires_voice_cancel_and_human_sentinel(tmp_path) -> None:
    capture = FakeCapture()
    asr = FakeAsr()
    asr.finalize = lambda: TranscriptEvent("physical:2", "Pare, Casulo", "pt-BR", True, None)
    tts = FakeTts()
    wall_ticks = iter([0.0, 0.0, 0.1, 0.2, 16.0])
    nano_ticks = iter([1_000, 1_125])
    report = barge_in_smoke(
        VoiceCandidate.load(MANIFEST),
        tmp_path,
        consent=BARGE_IN_CONSENT,
        device=1,
        capture_factory=lambda **_kwargs: capture,
        asr_factory=lambda *_args, **_kwargs: asr,
        tts_factory=lambda: tts,
        clock=lambda: next(wall_ticks),
        clock_ns=lambda: next(nano_ticks),
        sleeper=lambda _seconds: None,
    )
    assert report["passed"] is True
    assert report["sentinel_heard"] is True
    assert report["cancel_latency_ns"] == 125
    assert report["raw_audio_persisted"] is False
