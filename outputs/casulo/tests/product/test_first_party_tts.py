from __future__ import annotations

import hashlib
import math
import struct

from casulo.product.audio_frontend import AudioFrontend
from casulo.product.first_party_tts import FirstPartyFormantTTS, SAMPLE_RATE, VoiceProfile, ptbr_graphemes


def sine(frequency: float, amplitude: float, samples: int = 320) -> bytes:
    values = [int(amplitude * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)) for index in range(samples)]
    return struct.pack("<" + "h" * samples, *values)


def test_first_party_ptbr_tts_streams_nonempty_pcm_and_is_reproducible() -> None:
    tts = FirstPartyFormantTTS()
    pcm, receipt = tts.synthesize("Olá, Casulo. Vamos construir com segurança.")
    second, _ = tts.synthesize("Olá, Casulo. Vamos construir com segurança.")
    assert pcm == second and len(pcm) > 3200 and len(pcm) % 2 == 0
    assert receipt.sample_rate == 16000
    assert receipt.pcm_sha256 == hashlib.sha256(pcm).hexdigest()
    assert receipt.license == "MIT-first-party-no-model"
    assert "lh" in ptbr_graphemes("trabalho")


def test_tts_cancellation_stops_before_full_utterance() -> None:
    calls = 0
    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls > 3
    frames = list(FirstPartyFormantTTS().stream("uma frase bastante longa para cancelar", cancelled=cancelled))
    assert 0 < len(frames) < 20


def test_voice_profile_is_explicit_and_provisional() -> None:
    profile = VoiceProfile(speed=1.1, energy=0.6)
    assert profile.locale == "pt-BR"
    assert profile.design_status == "PROVISIONAL_OWNER_REVIEW_REQUIRED"


def test_audio_frontend_reduces_known_echo_and_applies_bounded_agc() -> None:
    reference = sine(440, 6000)
    microphone = sine(440, 4200)
    output, receipt = AudioFrontend(noise_floor=20).process(microphone, reference)
    assert len(output) == len(microphone)
    assert 0.6 < receipt.echo_scale < 0.8
    assert receipt.residual_rms < receipt.input_rms * 0.05
    assert 0.5 <= receipt.agc_gain <= 4.0


def test_audio_frontend_rejects_truncated_pcm() -> None:
    try:
        AudioFrontend().process(b"x", b"x")
    except ValueError as error:
        assert "truncado" in str(error)
    else:
        raise AssertionError("PCM truncado foi aceito")
