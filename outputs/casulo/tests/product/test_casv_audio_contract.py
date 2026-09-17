from __future__ import annotations

import pytest

from casulo.compression.casv_audio import (
    CASVAudioContractError,
    CanonicalAudioSpec,
    validate_canonical_audio,
)


def test_canonical_audio_contract_accounts_interleaved_pcm_exactly() -> None:
    spec = CanonicalAudioSpec(
        sample_format="PCM_F32LE",
        sample_rate=48_000,
        channel_labels=("FL", "FR"),
        samples_per_channel=48_000,
        start_time_numerator=-1,
        start_time_denominator=2,
    )
    payload = bytes(spec.expected_bytes)
    validate_canonical_audio(payload, spec)
    assert spec.expected_bytes == 384_000
    assert spec.as_dict() == {
        "schema": "casulo.canonical-audio/0.1",
        "sample_format": "PCM_F32LE",
        "sample_rate": 48_000,
        "channel_labels": ["FL", "FR"],
        "channels": 2,
        "samples_per_channel": 48_000,
        "layout": "INTERLEAVED_DECLARED_CHANNEL_ORDER",
        "start_time_numerator": -1,
        "start_time_denominator": 2,
        "canonical_bytes": 384_000,
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sample_format": "AAC"}, "format"),
        ({"sample_format": []}, "format"),
        ({"sample_rate": 0}, "sample rate"),
        ({"sample_rate": "48000"}, "sample rate"),
        ({"channel_labels": ()}, "channel count"),
        ({"channel_labels": ["FL", "FR"]}, "must be a tuple"),
        ({"channel_labels": ("FL", "FL")}, "unique"),
        ({"channel_labels": ("FL", "R;DROP")}, "label"),
        ({"samples_per_channel": -1}, "sample count"),
        ({"samples_per_channel": True}, "sample count"),
        ({"start_time_numerator": "0"}, "numerator"),
        ({"start_time_denominator": 0}, "denominator"),
    ],
)
def test_canonical_audio_contract_fails_closed(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "sample_format": "PCM_S16LE",
        "sample_rate": 48_000,
        "channel_labels": ("FL", "FR"),
        "samples_per_channel": 1,
        "start_time_numerator": 0,
        "start_time_denominator": 1,
    }
    values.update(changes)
    spec = CanonicalAudioSpec(**values)  # type: ignore[arg-type]
    with pytest.raises(CASVAudioContractError, match=message):
        spec.validate()


def test_canonical_audio_payload_length_is_not_inferred_or_padded() -> None:
    spec = CanonicalAudioSpec(
        sample_format="PCM_S16LE",
        sample_rate=48_000,
        channel_labels=("MONO",),
        samples_per_channel=4,
    )
    with pytest.raises(CASVAudioContractError, match="payload length differs"):
        validate_canonical_audio(b"\x00" * 7, spec)
