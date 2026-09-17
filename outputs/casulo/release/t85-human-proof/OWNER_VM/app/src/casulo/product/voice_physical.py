from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .platform_contracts import PlatformError
from .tts_streaming import WindowsDirectStreamingTts
from .voice_bridge import WhisperBridgeAsr, create_cached_whisper_asr
from .voice_candidate import VoiceCandidate
from .voice_duplex import EnergyVad, SoundDevicePcmCapture


CAPTURE_CONSENT = "CAPTURE_MICROPHONE_8_SECONDS_NO_STORAGE"
PLAYBACK_CONSENT = "PLAY_TTS_AND_CANCEL_2_SECONDS"
BARGE_IN_CONSENT = "BARGE_IN_MICROPHONE_15_SECONDS_NO_STORAGE"


def capture_microphone_smoke(
    candidate: VoiceCandidate,
    cache_root: str | Path,
    *,
    consent: str,
    duration_s: float = 8.0,
    threads: int = 4,
    device: int | str | None = None,
    capture_factory: Callable[..., Any] = SoundDevicePcmCapture,
    asr_factory: Callable[..., WhisperBridgeAsr] = create_cached_whisper_asr,
    clock: Callable[[], float] = time.perf_counter,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if consent != CAPTURE_CONSENT:
        raise PlatformError(f"consentimento ausente; use exatamente {CAPTURE_CONSENT}")
    if not 1.0 <= duration_s <= 15.0:
        raise PlatformError("captura física precisa durar entre 1 e 15 segundos")
    if threads <= 0:
        raise PlatformError("threads da captura precisam ser positivas")

    capture = capture_factory(sample_rate=16_000, block_ms=20, device=device)
    asr = asr_factory(
        candidate,
        str(Path(cache_root).expanduser().resolve()),
        threads=threads,
        partial_ms=2000,
        use_gpu=False,
        final_timeout_s=60.0,
    )
    vad = EnergyVad(rms_threshold=500.0)
    frames = 0
    voiced_frames = 0
    partials: list[str] = []
    started = clock()
    try:
        capture.start()
        deadline = started + duration_s
        while clock() < deadline:
            frame = capture.poll()
            if frame is None:
                sleeper(0.005)
                continue
            frames += 1
            if vad.is_speech(frame):
                voiced_frames += 1
            partial = asr.accept(frame)
            if partial is not None and partial.text.strip():
                partials.append(partial.text.strip())
        final = asr.finalize()
    finally:
        capture.close()
        asr.close()
    finished = clock()
    if frames == 0:
        raise PlatformError("microfone não entregou frames")
    if final is None or not final.final or final.locale != "pt-BR":
        raise PlatformError("captura não produziu transcript final pt-BR")
    return {
        "schema": "casulo-physical-capture-smoke/1.0",
        "passed": bool(final.text.strip()) and voiced_frames > 0,
        "consent_recorded": True,
        "raw_audio_persisted": False,
        "duration_requested_s": duration_s,
        "elapsed_s": round(finished - started, 3),
        "frames": frames,
        "voiced_frames": voiced_frames,
        "partials": partials[-5:],
        "transcript": final.text.strip(),
        "locale": final.locale,
        "threads": threads,
        "input_device": device,
    }


def playback_cancel_smoke(
    *,
    consent: str,
    text: str = "Olá. Eu sou o Guia do Casulo e esta fala será interrompida agora.",
    audible_s: float = 2.0,
    tts_factory: Callable[..., Any] = WindowsDirectStreamingTts,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if consent != PLAYBACK_CONSENT:
        raise PlatformError(f"consentimento ausente; use exatamente {PLAYBACK_CONSENT}")
    if not 0.25 <= audible_s <= 3.0:
        raise PlatformError("playback físico precisa durar entre 0.25 e 3 segundos")
    tts = tts_factory()
    session = tts.speak(text)
    sleeper(audible_s)
    started = clock_ns()
    session.cancel()
    cancel_latency_ns = clock_ns() - started
    return {
        "schema": "casulo-physical-playback-smoke/1.0",
        "passed": not session.active,
        "consent_recorded": True,
        "text_persisted": False,
        "audible_s_requested": audible_s,
        "cancel_latency_ns": cancel_latency_ns,
        "streaming_playback": bool(getattr(tts, "streaming_playback", False)),
        "streaming_pcm": bool(getattr(tts, "streaming_pcm", False)),
        "redistributed": bool(getattr(tts, "redistributed", False)),
    }


def barge_in_smoke(
    candidate: VoiceCandidate,
    cache_root: str | Path,
    *,
    consent: str,
    duration_s: float = 15.0,
    threads: int = 4,
    device: int | str | None = None,
    capture_factory: Callable[..., Any] = SoundDevicePcmCapture,
    asr_factory: Callable[..., WhisperBridgeAsr] = create_cached_whisper_asr,
    tts_factory: Callable[..., Any] = WindowsDirectStreamingTts,
    clock: Callable[[], float] = time.perf_counter,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if consent != BARGE_IN_CONSENT:
        raise PlatformError(f"consentimento ausente; use exatamente {BARGE_IN_CONSENT}")
    if not 3.0 <= duration_s <= 20.0:
        raise PlatformError("barge-in físico precisa durar entre 3 e 20 segundos")

    capture = capture_factory(sample_rate=16_000, block_ms=20, device=device)
    asr = asr_factory(
        candidate,
        str(Path(cache_root).expanduser().resolve()),
        threads=threads,
        partial_ms=1000,
        use_gpu=False,
        final_timeout_s=60.0,
    )
    tts = tts_factory()
    vad = EnergyVad(rms_threshold=500.0)
    session = None
    frames = 0
    voiced_frames = 0
    first_voice_s: float | None = None
    cancel_latency_ns: int | None = None
    partials: list[str] = []
    started = clock()
    try:
        capture.start()
        session = tts.speak(
            "Eu sou o Guia do Casulo. Continuarei explicando enquanto você pensa, "
            "mas a sua voz sempre terá prioridade para me interromper."
        )
        deadline = started + duration_s
        while clock() < deadline:
            frame = capture.poll()
            if frame is None:
                sleeper(0.005)
                continue
            frames += 1
            if vad.is_speech(frame):
                voiced_frames += 1
                if first_voice_s is None:
                    first_voice_s = clock() - started
                    cancel_started = clock_ns()
                    session.cancel()
                    cancel_latency_ns = clock_ns() - cancel_started
            partial = asr.accept(frame)
            if partial is not None and partial.text.strip():
                partials.append(partial.text.strip())
        final = asr.finalize()
    finally:
        if session is not None and session.active:
            session.cancel()
        capture.close()
        asr.close()
    transcript = "" if final is None else final.text.strip()
    normalized = transcript.casefold()
    sentinel_heard = "pare" in normalized and "casul" in normalized
    return {
        "schema": "casulo-physical-barge-in-smoke/1.0",
        "passed": bool(
            frames > 0
            and voiced_frames > 0
            and cancel_latency_ns is not None
            and session is not None
            and not session.active
            and sentinel_heard
        ),
        "consent_recorded": True,
        "raw_audio_persisted": False,
        "duration_requested_s": duration_s,
        "input_device": device,
        "frames": frames,
        "voiced_frames": voiced_frames,
        "first_voice_s": first_voice_s,
        "cancel_latency_ns": cancel_latency_ns,
        "partials": partials[-5:],
        "transcript": transcript,
        "sentinel_heard": sentinel_heard,
        "streaming_playback": bool(getattr(tts, "streaming_playback", False)),
    }
