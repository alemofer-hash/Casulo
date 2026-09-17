from __future__ import annotations

from pathlib import Path

import pytest

from casulo.product.platform_contracts import PlatformError
from casulo.product.voice_candidate import VoiceCandidate
from casulo.product.voice_duplex import TranscriptEvent
from casulo.product.voice_smoke import smoke_cached_whisper


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "release/voice-candidates/whisper-cpp-v1.9.2.json"


class FakeAsr:
    def __init__(self) -> None:
        self.frames = []
        self.closed = False

    def accept(self, frame):
        self.frames.append(frame)
        return None

    def finalize(self):
        return TranscriptEvent("smoke:1", "", "pt-BR", True, None)

    def close(self):
        self.closed = True


def test_smoke_is_bounded_and_never_requests_a_device(tmp_path) -> None:
    fake = FakeAsr()
    calls = []

    def factory(candidate, cache, **options):
        calls.append((candidate, cache, options))
        return fake

    report = smoke_cached_whisper(
        VoiceCandidate.load(MANIFEST),
        tmp_path,
        seconds=0.25,
        threads=1,
        factory=factory,
    )
    assert report["passed"] is True
    assert report["device_capture"] is False
    assert report["speaker_output"] is False
    assert report["samples"] == 4000
    assert fake.frames[0].pcm_s16le == b"\x00\x00" * 4000
    assert fake.closed
    assert calls[0][2]["use_gpu"] is False


@pytest.mark.parametrize("seconds", [0.0, 5.1])
def test_smoke_rejects_unbounded_duration(seconds, tmp_path) -> None:
    with pytest.raises(PlatformError, match="entre 0.1 e 5"):
        smoke_cached_whisper(
            VoiceCandidate.load(MANIFEST),
            tmp_path,
            seconds=seconds,
        )
