from __future__ import annotations

from dataclasses import dataclass


CASV_AUDIO_CONTRACT = "casulo.canonical-audio/0.1"
CASV_AUDIO_SAMPLE_FORMAT_BYTES = {
    "PCM_U8": 1,
    "PCM_S16LE": 2,
    "PCM_S32LE": 4,
    "PCM_S64LE": 8,
    "PCM_F32LE": 4,
    "PCM_F64LE": 8,
}
MAX_AUDIO_CHANNELS = 64
MAX_AUDIO_SAMPLE_RATE = 768_000
MAX_AUDIO_SAMPLES_PER_CHANNEL = 2**63 - 1
MAX_CANONICAL_AUDIO_BYTES = 2**64 - 1


class CASVAudioContractError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalAudioSpec:
    """Canonical decoded PCM identity; it is not source-bitstream identity."""

    sample_format: str
    sample_rate: int
    channel_labels: tuple[str, ...]
    samples_per_channel: int
    start_time_numerator: int = 0
    start_time_denominator: int = 1

    def validate(self) -> None:
        if (
            not isinstance(self.sample_format, str)
            or self.sample_format not in CASV_AUDIO_SAMPLE_FORMAT_BYTES
        ):
            raise CASVAudioContractError("canonical audio sample format is unsupported")
        if type(self.sample_rate) is not int or not 1 <= self.sample_rate <= MAX_AUDIO_SAMPLE_RATE:
            raise CASVAudioContractError("canonical audio sample rate is outside bounds")
        if not isinstance(self.channel_labels, tuple):
            raise CASVAudioContractError("canonical audio channel labels must be a tuple")
        if not 1 <= len(self.channel_labels) <= MAX_AUDIO_CHANNELS:
            raise CASVAudioContractError("canonical audio channel count is outside bounds")
        for label in self.channel_labels:
            if (
                not isinstance(label, str)
                or not 1 <= len(label) <= 16
                or not all(
                    character.isascii()
                    and (character.isalnum() or character == "_")
                    for character in label
                )
            ):
                raise CASVAudioContractError("canonical audio channel label is invalid")
        if len(set(self.channel_labels)) != len(self.channel_labels):
            raise CASVAudioContractError("canonical audio channel labels must be unique")
        if (
            type(self.samples_per_channel) is not int
            or not 0 <= self.samples_per_channel <= MAX_AUDIO_SAMPLES_PER_CHANNEL
        ):
            raise CASVAudioContractError("canonical audio sample count is outside bounds")
        if type(self.start_time_numerator) is not int:
            raise CASVAudioContractError("canonical audio start time numerator must be an integer")
        if type(self.start_time_denominator) is not int or self.start_time_denominator <= 0:
            raise CASVAudioContractError("canonical audio start time denominator must be positive")
        if self.expected_bytes > MAX_CANONICAL_AUDIO_BYTES:
            raise CASVAudioContractError("canonical audio payload exceeds format bounds")

    @property
    def channels(self) -> int:
        return len(self.channel_labels)

    @property
    def bytes_per_sample(self) -> int:
        return CASV_AUDIO_SAMPLE_FORMAT_BYTES[self.sample_format]

    @property
    def expected_bytes(self) -> int:
        return self.samples_per_channel * self.channels * self.bytes_per_sample

    def as_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": CASV_AUDIO_CONTRACT,
            "sample_format": self.sample_format,
            "sample_rate": self.sample_rate,
            "channel_labels": list(self.channel_labels),
            "channels": self.channels,
            "samples_per_channel": self.samples_per_channel,
            "layout": "INTERLEAVED_DECLARED_CHANNEL_ORDER",
            "start_time_numerator": self.start_time_numerator,
            "start_time_denominator": self.start_time_denominator,
            "canonical_bytes": self.expected_bytes,
        }


def validate_canonical_audio(payload: bytes, spec: CanonicalAudioSpec) -> None:
    spec.validate()
    if len(payload) != spec.expected_bytes:
        raise CASVAudioContractError(
            "canonical audio payload length differs from its declared sample grid"
        )


__all__ = [
    "CASV_AUDIO_CONTRACT",
    "CASV_AUDIO_SAMPLE_FORMAT_BYTES",
    "CASVAudioContractError",
    "CanonicalAudioSpec",
    "MAX_CANONICAL_AUDIO_BYTES",
    "validate_canonical_audio",
]
