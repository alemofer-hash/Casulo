from __future__ import annotations

import json
import sys
from array import array
from pathlib import Path

import pytest

from casulo.product.platform_contracts import PlatformError
from casulo.product.voice_bridge import (
    JsonLineAsrBridge,
    WhisperBridgeAsr,
    create_cached_whisper_asr,
)
from casulo.product.voice_candidate import VoiceCandidate
from casulo.product.voice_duplex import AudioFrame


FAKE_BRIDGE = r'''
import json, sys
for line in sys.stdin.buffer:
    command = json.loads(line)
    op = command["op"]
    if op == "audio":
        event = {"schema":"casulo-asr-event/1.0","transcript_id":"tx:bridge","text":"quero criar","locale":"pt-BR","final":False,"confidence":0.75}
        print(json.dumps(event), flush=True)
    elif op == "finalize":
        event = {"schema":"casulo-asr-event/1.0","transcript_id":"tx:bridge","text":"quero criar um guia","locale":"pt-BR","final":True,"confidence":0.91}
        print(json.dumps(event), flush=True)
    elif op == "shutdown":
        break
'''


def test_process_boundary_delivers_partial_and_final() -> None:
    bridge = JsonLineAsrBridge([sys.executable, "-u", "-c", FAKE_BRIDGE])
    asr = WhisperBridgeAsr(bridge, final_timeout_s=2.0)
    try:
        frame = AudioFrame(array("h", [1000] * 320).tobytes())
        assert asr.accept(frame) is None
        partial = asr.poll_partial(timeout_s=1.0)
        assert partial is not None
        assert not partial.final
        final = asr.finalize()
        assert final is not None
        assert final.final
        assert final.text == "quero criar um guia"
    finally:
        asr.close()


def test_bridge_rejects_wrong_locale() -> None:
    script = r'''
import json, sys
for line in sys.stdin:
    print(json.dumps({"schema":"casulo-asr-event/1.0","transcript_id":"x","text":"hello","locale":"en-US","final":False,"confidence":1}), flush=True)
'''
    bridge = JsonLineAsrBridge([sys.executable, "-u", "-c", script])
    try:
        frame = AudioFrame(array("h", [1] * 320).tobytes())
        bridge.send_frame(frame)
        with pytest.raises(PlatformError, match="locale"):
            bridge.receive(timeout=1.0)
    finally:
        bridge.close()


def test_cached_factory_is_fail_closed_before_starting_process(tmp_path) -> None:
    manifest = Path(__file__).resolve().parents[2] / "release/voice-candidates/whisper-cpp-v1.9.2.json"
    candidate = VoiceCandidate.load(manifest)
    with pytest.raises(PlatformError, match="verification"):
        create_cached_whisper_asr(candidate, str(tmp_path / "missing"))
