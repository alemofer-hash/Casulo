from __future__ import annotations

import base64
import io
import json
from array import array
from pathlib import Path

import pytest

from casulo.product.platform_contracts import PlatformError
from casulo.product.whisper_worker import SAMPLE_RATE, WorkerSession, serve


ROOT = Path(__file__).resolve().parents[2]


class FakeBackend:
    def __init__(self) -> None:
        self.sample_counts: list[int] = []
        self.closed = False

    def transcribe(self, samples: array[float]) -> str:
        self.sample_counts.append(len(samples))
        return f"fala com {len(samples)} amostras"

    def close(self) -> None:
        self.closed = True


def command(op: str, **extra: object) -> bytes:
    return (
        json.dumps({"schema": "casulo-asr-command/1.0", "op": op, **extra}).encode("utf-8")
        + b"\n"
    )


def test_worker_emits_partial_and_final_then_closes_backend() -> None:
    pcm = array("h", [1000] * 8).tobytes()
    source = io.BytesIO(
        command(
            "audio",
            sample_rate=SAMPLE_RATE,
            channels=1,
            pcm_s16le_b64=base64.b64encode(pcm).decode("ascii"),
        )
        + command("finalize")
        + command("shutdown")
    )
    destination = io.BytesIO()
    backend = FakeBackend()
    assert serve(source, destination, backend, partial_interval_samples=4) == 0
    events = [json.loads(line) for line in destination.getvalue().splitlines()]
    assert [event["final"] for event in events] == [False, True]
    assert events[0]["transcript_id"] == events[1]["transcript_id"]
    assert backend.sample_counts == [8, 8]
    assert backend.closed


def test_worker_reset_prevents_audio_from_crossing_utterances() -> None:
    backend = FakeBackend()
    session = WorkerSession(backend, partial_interval_samples=100)
    first = array("h", [1] * 8).tobytes()
    session.accept_audio(
        {
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "pcm_s16le_b64": base64.b64encode(first).decode("ascii"),
        }
    )
    session.reset()
    second = array("h", [2] * 4).tobytes()
    session.accept_audio(
        {
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "pcm_s16le_b64": base64.b64encode(second).decode("ascii"),
        }
    )
    final = session.finalize()
    assert final["text"] == "fala com 4 amostras"
    assert backend.sample_counts == [4]


def test_worker_rejects_invalid_base64() -> None:
    session = WorkerSession(FakeBackend())
    with pytest.raises(PlatformError, match="base64"):
        session.accept_audio(
            {
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
                "pcm_s16le_b64": "%%%",
            }
        )


def test_native_bridge_is_narrow_and_upstream_network_features_are_off() -> None:
    cmake = (ROOT / "native/voice/CMakeLists.txt").read_text(encoding="utf-8")
    bridge = (ROOT / "native/voice/casulo_whisper_bridge.cpp").read_text(encoding="utf-8")
    assert "WHISPER_CURL OFF" in cmake
    assert "WHISPER_BUILD_EXAMPLES OFF" in cmake
    assert "GGML_OPENMP OFF" in cmake
    assert "casulo_whisper_transcribe_pt_br" in bridge
    assert 'parameters.language = "pt"' in bridge
    assert "whisper_is_multilingual" in bridge
