from __future__ import annotations

import hashlib

import pytest

from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_probe import (
    make_noise_probe_video,
    make_structured_probe_video,
)
from casulo.compression.casv_segment_ir import (
    CASVSegmentIRError,
    encode_segment_candidate,
    infer_segment_program,
    render_segment_program,
)


def _structured_yuv444p10le(spec: CanonicalVideoSpec) -> bytes:
    output = bytearray()
    pixels = spec.width * spec.height
    for frame_index in range(spec.frame_count):
        planes = [
            bytearray(value.to_bytes(2, "little") * pixels)
            for value in (128, 512, 512)
        ]
        x = 4 + frame_index
        y = 6
        width = 12
        height = 8
        for plane, value in zip(planes, (800, 300, 700), strict=True):
            row = value.to_bytes(2, "little") * width
            for offset_y in range(height):
                start = ((y + offset_y) * spec.width + x) * 2
                plane[start : start + len(row)] = row
        output.extend(b"".join(planes))
    return bytes(output)


def _close_exact(source: bytes, rendered: bytes, residual: bytes) -> bytes:
    return bytes(
        predicted ^ delta
        for predicted, delta in zip(rendered, residual, strict=True)
    )


def test_rgb8_segment_program_finds_motion_and_closes_exactly() -> None:
    spec = CanonicalVideoSpec(64, 36, 6, 24)
    source = make_structured_probe_video(spec)
    inferred = infer_segment_program(source, spec)
    encoded, metadata = encode_segment_candidate(inferred)

    assert render_segment_program(inferred.program) == inferred.rendered
    assert _close_exact(source, inferred.rendered, inferred.residual_xor) == source
    assert inferred.detected_tracks == 2
    assert inferred.residual_nonzero_bytes == 0
    assert inferred.exact_predicted_pixels == inferred.total_pixels
    assert metadata["residual_encoding"] == "ZERO"
    assert len(encoded) < len(source)


def test_yuv444p10le_planar_segment_program_is_native_and_exact() -> None:
    spec = CanonicalVideoSpec(
        64,
        36,
        6,
        24,
        pixel_format="YUV444P10LE",
    )
    source = _structured_yuv444p10le(spec)
    inferred = infer_segment_program(source, spec)
    encoded, metadata = encode_segment_candidate(inferred)

    assert _close_exact(source, inferred.rendered, inferred.residual_xor) == source
    assert inferred.detected_tracks == 1
    assert inferred.residual_nonzero_bytes == 0
    assert inferred.exact_predicted_pixels == inferred.total_pixels
    assert metadata["renderer"].endswith("/0.3")
    assert len(encoded) < len(source)


def test_unexplained_bytes_are_preserved_only_by_exact_residual() -> None:
    spec = CanonicalVideoSpec(64, 36, 2, 24)
    source = make_noise_probe_video(spec)
    inferred = infer_segment_program(source, spec)
    encoded, metadata = encode_segment_candidate(inferred)

    restored = _close_exact(source, inferred.rendered, inferred.residual_xor)
    assert hashlib.sha256(restored).digest() == hashlib.sha256(source).digest()
    assert inferred.residual_nonzero_bytes > 0
    assert metadata["residual_encoding"] == "XOR_ZLIB"
    assert len(encoded) > 0


def test_segment_proposer_fails_closed_above_pixel_budget() -> None:
    spec = CanonicalVideoSpec(1024, 1024, 1, 24)
    with pytest.raises(CASVSegmentIRError, match="bounded visual proposer"):
        infer_segment_program(bytes(spec.expected_bytes), spec)
