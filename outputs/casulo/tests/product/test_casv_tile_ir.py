from __future__ import annotations

import random

from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_tile_ir import (
    MAX_STRIP_CANONICAL_BYTES,
    assemble_strip,
    build_tile_candidates,
    decode_tile_payload,
    extract_tile,
    iter_strip_layouts,
    summarize_layout,
)


def decoder(payload: bytes, expected: int) -> bytes:
    import zlib

    restored = zlib.decompress(payload)
    assert len(restored) == expected
    return restored


def test_full_resolution_8k_yuv10_layout_never_allocates_a_frame() -> None:
    spec = CanonicalVideoSpec(8192, 4320, 1, 30, pixel_format="YUV444P10LE")
    summary = summarize_layout(spec, tile_width=512, strip_height=128)

    assert spec.frame_bytes == 212_336_640
    assert summary["canonical_bytes"] == spec.frame_bytes
    assert summary["record_count"] == 102
    assert summary["tile_count"] == 1_632
    assert summary["maximum_strip_canonical_bytes"] == 2_097_152
    assert summary["maximum_strip_canonical_bytes"] < MAX_STRIP_CANONICAL_BYTES
    assert summary["full_frame_allocation_required"] is False


def test_strip_tiles_round_trip_the_original_row_order() -> None:
    spec = CanonicalVideoSpec(17, 7, 1, 24, pixel_format="RGB8")
    layout = next(iter_strip_layouts(spec, tile_width=5, strip_height=7))
    strip = bytes((index * 37 + 11) & 0xFF for index in range(layout.canonical_bytes))
    tiles = [extract_tile(strip, layout, tile) for tile in layout.tiles]

    assert assemble_strip(layout, tiles) == strip


def test_every_tile_transform_is_reversible_for_incompressible_bytes() -> None:
    canonical = random.Random(20260910).randbytes(41 * 19 * 3)
    candidates = build_tile_candidates(
        canonical,
        width=41,
        height=19,
        bytes_per_pixel=3,
    )

    for mode, payload in candidates.payloads.items():
        assert decode_tile_payload(
            mode,
            payload,
            width=41,
            height=19,
            bytes_per_pixel=3,
            zlib_decoder=decoder,
        ) == canonical


def test_planar_16_bit_samples_remain_byte_exact() -> None:
    canonical = b"".join(
        ((x * 17 + y * 9) % 1024).to_bytes(2, "little")
        for y in range(23)
        for x in range(37)
    )
    candidates = build_tile_candidates(
        canonical,
        width=37,
        height=23,
        bytes_per_pixel=2,
    )

    for mode, payload in candidates.payloads.items():
        assert decode_tile_payload(
            mode,
            payload,
            width=37,
            height=23,
            bytes_per_pixel=2,
            zlib_decoder=decoder,
        ) == canonical
