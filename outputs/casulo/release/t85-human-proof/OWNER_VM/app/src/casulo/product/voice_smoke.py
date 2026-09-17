from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .platform_contracts import PlatformError
from .voice_bridge import WhisperBridgeAsr, create_cached_whisper_asr
from .voice_candidate import VoiceCandidate
from .voice_duplex import AudioFrame


AsrFactory = Callable[..., WhisperBridgeAsr]


def smoke_cached_whisper(
    candidate: VoiceCandidate,
    cache_root: str | Path,
    *,
    seconds: float = 1.0,
    threads: int = 1,
    factory: AsrFactory = create_cached_whisper_asr,
) -> dict[str, Any]:
    """Exercise the real process boundary with synthetic silence and no device."""
    if not 0.1 <= seconds <= 5.0:
        raise PlatformError("smoke ASR aceita entre 0.1 e 5 segundos")
    if threads <= 0:
        raise PlatformError("threads do smoke ASR precisam ser positivas")
    sample_count = round(16_000 * seconds)
    frame = AudioFrame(
        pcm_s16le=b"\x00\x00" * sample_count,
        sample_rate=16_000,
        channels=1,
    )

    started = time.perf_counter()
    asr = factory(
        candidate,
        str(Path(cache_root).expanduser().resolve()),
        threads=threads,
        partial_ms=6000,
        use_gpu=False,
        final_timeout_s=30.0,
    )
    created = time.perf_counter()
    try:
        partial = asr.accept(frame)
        final = asr.finalize()
    finally:
        asr.close()
    finished = time.perf_counter()
    if partial is not None:
        raise PlatformError("smoke curto emitiu parcial inesperada")
    if final is None or not final.final or final.locale != "pt-BR":
        raise PlatformError("worker não devolveu transcript final pt-BR")
    return {
        "schema": "casulo-asr-smoke/1.0",
        "passed": True,
        "device_capture": False,
        "speaker_output": False,
        "synthetic_silence": True,
        "sample_rate": frame.sample_rate,
        "samples": sample_count,
        "threads": threads,
        "transcript": final.text,
        "locale": final.locale,
        "process_start_ms": round((created - started) * 1000, 3),
        "finalize_and_shutdown_ms": round((finished - created) * 1000, 3),
    }
