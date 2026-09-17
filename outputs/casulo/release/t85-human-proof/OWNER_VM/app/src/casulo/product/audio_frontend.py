from __future__ import annotations

import math
import struct
from dataclasses import dataclass


class AudioFrontendError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AudioFrontendReceipt:
    samples: int
    echo_scale: float
    input_rms: float
    residual_rms: float
    output_rms: float
    agc_gain: float
    double_talk: bool


class AudioFrontend:
    """Bounded PCM16 high-pass, echo subtraction, gate and AGC reference."""

    def __init__(self, *, noise_floor: float = 120.0, target_rms: float = 3200.0) -> None:
        if noise_floor < 0 or not 500 <= target_rms <= 8000:
            raise AudioFrontendError("calibração de áudio inválida")
        self.noise_floor = noise_floor
        self.target_rms = target_rms
        self._previous_input = 0.0
        self._previous_highpass = 0.0

    def process(self, microphone_pcm: bytes, render_reference_pcm: bytes) -> tuple[bytes, AudioFrontendReceipt]:
        microphone = self._decode(microphone_pcm)
        reference = self._decode(render_reference_pcm)
        if len(microphone) != len(reference) or not microphone:
            raise AudioFrontendError("microfone e referência precisam ter o mesmo frame não vazio")
        ref_energy = sum(value * value for value in reference)
        cross = sum(mic * ref for mic, ref in zip(microphone, reference, strict=True))
        scale = max(0.0, min(1.2, cross / ref_energy)) if ref_energy else 0.0
        residual = [mic - scale * ref for mic, ref in zip(microphone, reference, strict=True)]
        input_rms = self._rms(microphone)
        residual_rms = self._rms(residual)
        double_talk = residual_rms > max(self.noise_floor * 3, input_rms * 0.35)
        highpassed: list[float] = []
        for value in residual:
            filtered = value - self._previous_input + 0.97 * self._previous_highpass
            self._previous_input, self._previous_highpass = value, filtered
            highpassed.append(0.0 if abs(filtered) < self.noise_floor else filtered)
        rms = self._rms(highpassed)
        gain = 1.0 if rms == 0 else max(0.5, min(4.0, self.target_rms / rms))
        output_values = [max(-32767, min(32767, int(value * gain))) for value in highpassed]
        output = struct.pack("<" + "h" * len(output_values), *output_values)
        return output, AudioFrontendReceipt(len(output_values), scale, input_rms, residual_rms, self._rms(output_values), gain, double_talk)

    @staticmethod
    def _decode(pcm: bytes) -> tuple[int, ...]:
        if len(pcm) % 2:
            raise AudioFrontendError("PCM16 truncado")
        return struct.unpack("<" + "h" * (len(pcm) // 2), pcm)

    @staticmethod
    def _rms(values) -> float:
        sequence = tuple(values)
        return math.sqrt(sum(value * value for value in sequence) / len(sequence)) if sequence else 0.0
