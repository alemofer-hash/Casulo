from __future__ import annotations

import hashlib
import math
import re
import struct
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterator


SAMPLE_RATE = 16_000
FRAME_SAMPLES = 320


class FirstPartyTTSError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    profile_id: str = "casulo-formant-ptbr-v1"
    backend: str = "casulo-first-party-formant"
    voice_id: str = "casulo-provisional-robotic-ptbr"
    locale: str = "pt-BR"
    speed: float = 1.0
    energy: float = 0.72
    pause_policy: str = "punctuation-aware"
    sentence_chunking: bool = True
    design_status: str = "PROVISIONAL_OWNER_REVIEW_REQUIRED"

    def __post_init__(self) -> None:
        if self.locale != "pt-BR" or not 0.6 <= self.speed <= 1.6 or not 0.1 <= self.energy <= 1.0:
            raise FirstPartyTTSError("VoiceProfile fora do envelope")


@dataclass(frozen=True, slots=True)
class TTSReceipt:
    text_sha256: str
    pcm_sha256: str
    sample_rate: int
    samples: int
    frames: int
    cancelled: bool
    backend: str
    license: str


_VOWELS = {
    "a": (780.0, 1150.0, 2850.0),
    "e": (520.0, 1800.0, 2500.0),
    "i": (300.0, 2250.0, 3000.0),
    "o": (500.0, 900.0, 2400.0),
    "u": (350.0, 650.0, 2350.0),
}


def ptbr_graphemes(text: str) -> tuple[str, ...]:
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise FirstPartyTTSError("texto vazio ou acima do limite")
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-z0-9 .,;:!?-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # Ordered pt-BR grapheme groups. This is deliberately a small, auditable
    # frontend, not a claim of complete linguistic coverage.
    groups = ("nh", "lh", "ch", "rr", "ss", "qu", "gu")
    result: list[str] = []
    index = 0
    while index < len(normalized):
        pair = normalized[index:index + 2]
        if pair in groups:
            result.append(pair)
            index += 2
        else:
            result.append(normalized[index])
            index += 1
    return tuple(result)


class FirstPartyFormantTTS:
    """Tiny source-filter-like pt-BR fallback with no external model or data."""

    def __init__(self, profile: VoiceProfile | None = None) -> None:
        self.profile = profile or VoiceProfile()

    def synthesize(self, text: str) -> tuple[bytes, TTSReceipt]:
        chunks = list(self.stream(text))
        pcm = b"".join(chunks)
        return pcm, TTSReceipt(
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            hashlib.sha256(pcm).hexdigest(), SAMPLE_RATE, len(pcm) // 2,
            len(chunks), False, self.profile.backend, "MIT-first-party-no-model",
        )

    def stream(self, text: str, *, cancelled: Callable[[], bool] = lambda: False) -> Iterator[bytes]:
        samples: list[int] = []
        phase = 0
        for grapheme in ptbr_graphemes(text):
            if cancelled():
                return
            duration = self._duration(grapheme)
            count = max(1, int(SAMPLE_RATE * duration / self.profile.speed))
            for offset in range(count):
                envelope = min(1.0, offset / 80.0, (count - offset) / 80.0)
                value = self._sample(grapheme, phase + offset) * envelope * self.profile.energy
                samples.append(max(-32767, min(32767, int(value))))
                if len(samples) == FRAME_SAMPLES:
                    yield struct.pack("<" + "h" * len(samples), *samples)
                    samples.clear()
            phase += count
        if samples and not cancelled():
            yield struct.pack("<" + "h" * len(samples), *samples)

    @staticmethod
    def _duration(grapheme: str) -> float:
        if grapheme == " ":
            return 0.035
        if grapheme in ".!?":
            return 0.12
        if grapheme in ",;:":
            return 0.075
        return 0.055

    @staticmethod
    def _sample(grapheme: str, index: int) -> float:
        base = grapheme[0] if grapheme else " "
        if base in _VOWELS:
            f1, f2, f3 = _VOWELS[base]
            t = index / SAMPLE_RATE
            fundamental = 125.0
            return 9500 * math.sin(2 * math.pi * fundamental * t) + 2600 * math.sin(2 * math.pi * f1 * t) + 1600 * math.sin(2 * math.pi * f2 * t) + 900 * math.sin(2 * math.pi * f3 * t)
        if base in " .,!?:;-0123456789":
            return 0.0
        # Deterministic unvoiced excitation; no random state or recorded unit.
        noise = ((index * 1103515245 + ord(base) * 12345) & 0xFFFF) - 32768
        if grapheme in {"m", "n", "nh"}:
            t = index / SAMPLE_RATE
            return 5000 * math.sin(2 * math.pi * 180 * t) + noise * 0.04
        if grapheme in {"l", "lh", "r", "rr"}:
            t = index / SAMPLE_RATE
            return 4200 * math.sin(2 * math.pi * 240 * t) + noise * 0.06
        return noise * 0.18
