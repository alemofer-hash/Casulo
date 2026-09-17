from __future__ import annotations

import math
import queue
import sys
from array import array
from dataclasses import dataclass
from typing import Protocol

from .platform_contracts import Clock, PlatformError


@dataclass(frozen=True, slots=True)
class AudioFrame:
    pcm_s16le: bytes
    sample_rate: int = 16_000
    channels: int = 1

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.channels != 1 or len(self.pcm_s16le) % 2:
            raise PlatformError("frame PCM precisa ser mono s16le válido")

    @property
    def duration_ms(self) -> float:
        samples = len(self.pcm_s16le) // 2
        return samples / self.sample_rate * 1000.0


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    transcript_id: str
    text: str
    locale: str
    final: bool
    confidence: float | None


@dataclass(frozen=True, slots=True)
class DuplexEvent:
    kind: str
    timestamp_ns: int
    transcript: TranscriptEvent | None = None
    cancel_latency_ns: int | None = None


class VadEngine(Protocol):
    def is_speech(self, frame: AudioFrame) -> bool: ...


class StreamingAsr(Protocol):
    locale: str

    def accept(self, frame: AudioFrame) -> TranscriptEvent | None: ...

    def finalize(self) -> TranscriptEvent | None: ...

    def reset(self) -> None: ...


class TtsSession(Protocol):
    def cancel(self) -> None: ...

    @property
    def active(self) -> bool: ...


class TtsEngine(Protocol):
    locale: str
    streaming_pcm: bool

    def speak(self, text: str) -> TtsSession: ...


class EnergyVad:
    """VAD local mínimo; limiar configurado antes da conversa."""

    def __init__(self, rms_threshold: float = 500.0) -> None:
        if rms_threshold <= 0:
            raise ValueError("rms_threshold precisa ser positivo")
        self.rms_threshold = rms_threshold

    def is_speech(self, frame: AudioFrame) -> bool:
        samples = array("h")
        samples.frombytes(frame.pcm_s16le)
        if sys.byteorder != "little":
            samples.byteswap()
        if not samples:
            return False
        rms = math.sqrt(sum(value * value for value in samples) / len(samples))
        return rms >= self.rms_threshold


class VoiceDuplex:
    def __init__(
        self,
        *,
        clock: Clock,
        vad: VadEngine,
        asr: StreamingAsr,
        tts: TtsEngine,
        endpoint_silence_ms: float = 500.0,
    ) -> None:
        if asr.locale != "pt-BR" or tts.locale != "pt-BR":
            raise PlatformError("Voice Duplex inicial exige ASR/TTS pt-BR")
        if endpoint_silence_ms <= 0:
            raise ValueError("endpoint precisa ser positivo")
        self.clock = clock
        self.vad = vad
        self.asr = asr
        self.tts = tts
        self.endpoint_silence_ms = endpoint_silence_ms
        self._silence_ms = 0.0
        self._heard_speech = False
        self._tts_session: TtsSession | None = None

    def speak(self, text: str) -> DuplexEvent:
        self.cancel_speech()
        self._tts_session = self.tts.speak(text)
        return DuplexEvent("TTS_STARTED", self.clock.monotonic_ns())

    def submit_text(self, text: str, *, transcript_id: str) -> DuplexEvent:
        """Fallback explícito/acessível; não é apresentado como reconhecimento."""
        normalized = text.strip()
        if not normalized or not transcript_id:
            raise PlatformError("fallback texto exige conteúdo e identidade")
        self.cancel_speech()
        return DuplexEvent(
            "TEXT_FINAL",
            self.clock.monotonic_ns(),
            transcript=TranscriptEvent(
                transcript_id=transcript_id,
                text=normalized,
                locale="pt-BR",
                final=True,
                confidence=None,
            ),
        )

    def cancel_speech(self) -> int | None:
        if self._tts_session is None or not self._tts_session.active:
            self._tts_session = None
            return None
        started = self.clock.monotonic_ns()
        self._tts_session.cancel()
        latency = self.clock.monotonic_ns() - started
        self._tts_session = None
        return latency

    def ingest(self, frame: AudioFrame) -> tuple[DuplexEvent, ...]:
        events: list[DuplexEvent] = []
        voiced = self.vad.is_speech(frame)
        if voiced:
            latency = self.cancel_speech()
            if latency is not None:
                events.append(
                    DuplexEvent(
                        "BARGE_IN",
                        self.clock.monotonic_ns(),
                        cancel_latency_ns=latency,
                    )
                )
            self._heard_speech = True
            self._silence_ms = 0.0
        elif self._heard_speech:
            self._silence_ms += frame.duration_ms

        partial = self.asr.accept(frame)
        if partial is not None:
            if partial.final:
                raise PlatformError("accept deve emitir somente transcript parcial")
            events.append(DuplexEvent("TRANSCRIPT_PARTIAL", self.clock.monotonic_ns(), partial))

        if self._heard_speech and self._silence_ms >= self.endpoint_silence_ms:
            final = self.asr.finalize()
            if final is not None:
                if not final.final:
                    raise PlatformError("finalize precisa marcar transcript final")
                if final.text.strip():
                    events.append(DuplexEvent("TRANSCRIPT_FINAL", self.clock.monotonic_ns(), final))
            self.asr.reset()
            self._heard_speech = False
            self._silence_ms = 0.0
        return tuple(events)


class UnavailablePtBrAsr:
    locale = "pt-BR"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def accept(self, frame: AudioFrame) -> TranscriptEvent | None:
        raise PlatformError(f"ASR pt-BR local indisponível: {self.reason}")

    def finalize(self) -> TranscriptEvent | None:
        raise PlatformError(f"ASR pt-BR local indisponível: {self.reason}")

    def reset(self) -> None:
        return None


class SoundDevicePcmCapture:
    """Adapter opcional; importa sounddevice somente quando ativado."""

    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        block_ms: int = 20,
        device: int | str | None = None,
    ) -> None:
        import sounddevice  # type: ignore[import-not-found]

        self._sounddevice = sounddevice
        self.sample_rate = sample_rate
        self.blocksize = sample_rate * block_ms // 1000
        self.device = device
        self._frames: queue.SimpleQueue[AudioFrame] = queue.SimpleQueue()
        self._stream = None

    def start(self) -> None:
        if self._stream is not None:
            return

        def callback(data, frames, time_info, status) -> None:
            del frames, time_info
            if status:
                return
            self._frames.put(AudioFrame(bytes(data), self.sample_rate, 1))

        try:
            self._stream = self._sounddevice.RawInputStream(
                device=self.device,
                samplerate=self.sample_rate,
                blocksize=self.blocksize,
                channels=1,
                dtype="int16",
                callback=callback,
            )
            self._stream.start()
        except Exception as error:
            self._stream = None
            selected = "padrão" if self.device is None else repr(self.device)
            raise PlatformError(
                f"não foi possível abrir dispositivo de entrada {selected}: {error}"
            ) from error

    def poll(self) -> AudioFrame | None:
        try:
            return self._frames.get_nowait()
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
