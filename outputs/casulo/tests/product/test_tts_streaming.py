from __future__ import annotations

import threading
import io
import subprocess

from casulo.product.tts_streaming import WindowsBufferedPcmTts, WindowsDirectStreamingTts


class BlockingStdout:
    def __init__(self) -> None:
        self.released = threading.Event()

    def read(self, size: int) -> bytes:
        self.released.wait(timeout=2.0)
        return b""


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = BlockingStdout()
        self.stderr = io.BytesIO()
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0
        self.stdout.released.set()

    def kill(self) -> None:
        self.returncode = -9
        self.stdout.released.set()

    def wait(self, timeout=None):
        self.stdout.released.set()
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


class FakeOutputSession:
    def __init__(self) -> None:
        self.cancelled = False
        self.closed = False
        self.writes: list[bytes] = []

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    def cancel(self) -> None:
        self.cancelled = True

    def close(self) -> None:
        self.closed = True


class FakeOutput:
    def __init__(self) -> None:
        self.session = FakeOutputSession()
        self.opened = None

    def open(self, *, sample_rate: int, channels: int):
        self.opened = (sample_rate, channels)
        return self.session


def test_system_tts_buffer_is_local_cancelable_and_text_is_not_shell_code() -> None:
    captured = {}
    process = FakeProcess()

    def factory(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return process

    output = FakeOutput()
    tts = WindowsBufferedPcmTts(output=output, process_factory=factory)
    session = tts.speak("Olá; $(não executar)")
    assert not tts.streaming_pcm
    assert output.opened == (16_000, 1)
    assert "Olá" not in " ".join(captured["argv"])
    assert captured["env"]["CASULO_TTS_TEXT"] == "Olá; $(não executar)"
    assert session.active
    session.cancel()
    assert output.session.cancelled
    assert process.terminated
    assert not session.active


def test_system_voice_card_is_explicitly_non_redistributed() -> None:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    card = json.loads(
        (root / "release/voice-candidates/microsoft-maria-system.json").read_text(
            encoding="utf-8"
        )
    )
    assert card["status"] == "HOST_SYSTEM_FALLBACK_NOT_REDISTRIBUTED"
    assert card["redistributed"] is False
    assert card["model_hash"] is None
    assert card["streaming"] is False


def test_sink_open_failure_terminates_synthesizer() -> None:
    process = FakeProcess()

    class BrokenOutput:
        def open(self, **kwargs):
            raise RuntimeError("device unavailable")

    tts = WindowsBufferedPcmTts(
        output=BrokenOutput(),
        process_factory=lambda *args, **kwargs: process,
    )
    try:
        tts.speak("Teste")
    except RuntimeError as error:
        assert "device unavailable" in str(error)
    else:
        raise AssertionError("falha do sink precisa ser propagada")
    assert process.terminated


def test_direct_sapi_streams_playback_and_barge_in_terminates_process() -> None:
    captured = {}
    process = FakeProcess()

    def factory(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        captured["stdout"] = kwargs["stdout"]
        return process

    tts = WindowsDirectStreamingTts(process_factory=factory)
    session = tts.speak("Resposta local; $(não executar)")
    assert tts.streaming_playback is True
    assert tts.streaming_pcm is False
    assert tts.redistributed is False
    assert captured["stdout"] is not subprocess.PIPE
    assert "Resposta local" not in " ".join(captured["argv"])
    assert captured["env"]["CASULO_TTS_TEXT"] == "Resposta local; $(não executar)"
    session.cancel()
    assert process.terminated
    assert not session.active
