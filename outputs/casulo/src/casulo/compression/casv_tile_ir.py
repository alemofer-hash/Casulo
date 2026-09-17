from __future__ import annotations

import zlib
from collections.abc import Callable
from collections import Counter
from dataclasses import dataclass
from typing import Iterator, Mapping

from .casv_ir import CanonicalVideoSpec


DEFAULT_TILE_WIDTH = 512
DEFAULT_STRIP_HEIGHT = 128
MAX_TILE_CANONICAL_BYTES = 8 * 1024 * 1024
MAX_STRIP_CANONICAL_BYTES = 64 * 1024 * 1024
TILE_MODES = ("DC_XOR_ZLIB", "PAETH_ZLIB", "CANONICAL_ZLIB", "CANONICAL_RAW")


class CASVTileIRError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TileLayout:
    tile_index: int
    x: int
    width: int
    bytes_per_pixel: int
    canonical_bytes: int


@dataclass(frozen=True, slots=True)
class StripLayout:
    record_index: int
    frame_index: int
    plane_index: int
    y: int
    width: int
    height: int
    bytes_per_pixel: int
    canonical_offset: int
    canonical_bytes: int
    tiles: tuple[TileLayout, ...]


@dataclass(frozen=True, slots=True)
class TileCandidates:
    canonical: bytes
    payloads: Mapping[str, bytes]
    dc_sample: bytes
    dc_exact_bytes: int
    paeth_zero_bytes: int

    def validate(self) -> None:
        if not self.canonical:
            raise CASVTileIRError("tile canonical payload is empty")
        if set(self.payloads) != set(TILE_MODES):
            raise CASVTileIRError("tile candidate family is incomplete")
        if self.payloads["CANONICAL_RAW"] != self.canonical:
            raise CASVTileIRError("raw tile candidate differs from canonical bytes")


def _plane_geometry(spec: CanonicalVideoSpec) -> tuple[int, int]:
    if spec.pixel_format == "RGB8":
        return 1, 3
    if spec.pixel_format == "YUV444P10LE":
        return 3, 2
    raise CASVTileIRError("CASV/0.4 pixel format is unsupported")


def iter_strip_layouts(
    spec: CanonicalVideoSpec,
    *,
    tile_width: int = DEFAULT_TILE_WIDTH,
    strip_height: int = DEFAULT_STRIP_HEIGHT,
) -> Iterator[StripLayout]:
    """Yield canonical-order, bounded strip layouts without allocating a frame."""

    spec.validate(enforce_memory_limit=False)
    if type(tile_width) is not int or not 1 <= tile_width <= spec.width:
        raise CASVTileIRError("tile width is outside frame bounds")
    if type(strip_height) is not int or not 1 <= strip_height <= spec.height:
        raise CASVTileIRError("strip height is outside frame bounds")
    plane_count, bytes_per_pixel = _plane_geometry(spec)
    canonical_offset = 0
    record_index = 0
    tile_index = 0
    for frame_index in range(spec.frame_count):
        for plane_index in range(plane_count):
            for y in range(0, spec.height, strip_height):
                height = min(strip_height, spec.height - y)
                strip_bytes = spec.width * height * bytes_per_pixel
                if strip_bytes > MAX_STRIP_CANONICAL_BYTES:
                    raise CASVTileIRError("strip exceeds the CASV/0.4 memory bound")
                tiles: list[TileLayout] = []
                for x in range(0, spec.width, tile_width):
                    width = min(tile_width, spec.width - x)
                    tile_bytes = width * height * bytes_per_pixel
                    if tile_bytes > MAX_TILE_CANONICAL_BYTES:
                        raise CASVTileIRError("tile exceeds the CASV/0.4 memory bound")
                    tiles.append(
                        TileLayout(
                            tile_index=tile_index,
                            x=x,
                            width=width,
                            bytes_per_pixel=bytes_per_pixel,
                            canonical_bytes=tile_bytes,
                        )
                    )
                    tile_index += 1
                yield StripLayout(
                    record_index=record_index,
                    frame_index=frame_index,
                    plane_index=plane_index,
                    y=y,
                    width=spec.width,
                    height=height,
                    bytes_per_pixel=bytes_per_pixel,
                    canonical_offset=canonical_offset,
                    canonical_bytes=strip_bytes,
                    tiles=tuple(tiles),
                )
                record_index += 1
                canonical_offset += strip_bytes


def summarize_layout(
    spec: CanonicalVideoSpec,
    *,
    tile_width: int = DEFAULT_TILE_WIDTH,
    strip_height: int = DEFAULT_STRIP_HEIGHT,
) -> dict[str, int | str | bool]:
    record_count = 0
    tile_count = 0
    maximum_strip = 0
    maximum_tile = 0
    final_offset = 0
    for strip in iter_strip_layouts(
        spec,
        tile_width=tile_width,
        strip_height=strip_height,
    ):
        record_count += 1
        tile_count += len(strip.tiles)
        maximum_strip = max(maximum_strip, strip.canonical_bytes)
        maximum_tile = max(maximum_tile, *(tile.canonical_bytes for tile in strip.tiles))
        final_offset = strip.canonical_offset + strip.canonical_bytes
    return {
        "schema": "casulo.casv-tile-layout/0.4",
        "pixel_format": spec.pixel_format,
        "record_count": record_count,
        "tile_count": tile_count,
        "canonical_bytes": final_offset,
        "maximum_strip_canonical_bytes": maximum_strip,
        "maximum_tile_canonical_bytes": maximum_tile,
        "strip_bound_bytes": MAX_STRIP_CANONICAL_BYTES,
        "tile_bound_bytes": MAX_TILE_CANONICAL_BYTES,
        "full_frame_allocation_required": False,
    }


def extract_tile(strip: bytes, layout: StripLayout, tile: TileLayout) -> bytes:
    if len(strip) != layout.canonical_bytes:
        raise CASVTileIRError("strip payload differs from its layout")
    if tile not in layout.tiles:
        raise CASVTileIRError("tile does not belong to strip")
    row_bytes = layout.width * layout.bytes_per_pixel
    start_x = tile.x * layout.bytes_per_pixel
    tile_row_bytes = tile.width * layout.bytes_per_pixel
    result = bytearray(tile.canonical_bytes)
    destination = 0
    for row in range(layout.height):
        source = row * row_bytes + start_x
        result[destination : destination + tile_row_bytes] = strip[
            source : source + tile_row_bytes
        ]
        destination += tile_row_bytes
    return bytes(result)


def assemble_strip(
    layout: StripLayout,
    tiles: tuple[bytes, ...] | list[bytes],
) -> bytes:
    if len(tiles) != len(layout.tiles):
        raise CASVTileIRError("tile cardinality differs from strip layout")
    result = bytearray(layout.canonical_bytes)
    strip_row_bytes = layout.width * layout.bytes_per_pixel
    for tile_layout, tile in zip(layout.tiles, tiles, strict=True):
        if len(tile) != tile_layout.canonical_bytes:
            raise CASVTileIRError("decoded tile length differs")
        tile_row_bytes = tile_layout.width * layout.bytes_per_pixel
        source = 0
        start_x = tile_layout.x * layout.bytes_per_pixel
        for row in range(layout.height):
            destination = row * strip_row_bytes + start_x
            result[destination : destination + tile_row_bytes] = tile[
                source : source + tile_row_bytes
            ]
            source += tile_row_bytes
    return bytes(result)


def _modal_sample(payload: bytes, bytes_per_pixel: int) -> bytes:
    samples = Counter(
        payload[offset : offset + bytes_per_pixel]
        for offset in range(0, len(payload), bytes_per_pixel)
    )
    maximum = max(samples.values())
    return min(sample for sample, count in samples.items() if count == maximum)


def _xor_with_sample(payload: bytes, sample: bytes) -> bytes:
    width = len(sample)
    return bytes(value ^ sample[index % width] for index, value in enumerate(payload))


def _paeth(left: int, above: int, upper_left: int) -> int:
    prediction = left + above - upper_left
    distance_left = abs(prediction - left)
    distance_above = abs(prediction - above)
    distance_upper_left = abs(prediction - upper_left)
    if distance_left <= distance_above and distance_left <= distance_upper_left:
        return left
    if distance_above <= distance_upper_left:
        return above
    return upper_left


def paeth_residual(
    payload: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
) -> bytes:
    expected = width * height * bytes_per_pixel
    if len(payload) != expected:
        raise CASVTileIRError("Paeth input length differs")
    row_bytes = width * bytes_per_pixel
    residual = bytearray(expected)
    for row in range(height):
        row_start = row * row_bytes
        for offset in range(row_bytes):
            index = row_start + offset
            left = payload[index - bytes_per_pixel] if offset >= bytes_per_pixel else 0
            above = payload[index - row_bytes] if row else 0
            upper_left = (
                payload[index - row_bytes - bytes_per_pixel]
                if row and offset >= bytes_per_pixel
                else 0
            )
            residual[index] = (payload[index] - _paeth(left, above, upper_left)) & 0xFF
    return bytes(residual)


def reverse_paeth(
    residual: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
) -> bytes:
    expected = width * height * bytes_per_pixel
    if len(residual) != expected:
        raise CASVTileIRError("Paeth residual length differs")
    row_bytes = width * bytes_per_pixel
    restored = bytearray(expected)
    for row in range(height):
        row_start = row * row_bytes
        for offset in range(row_bytes):
            index = row_start + offset
            left = restored[index - bytes_per_pixel] if offset >= bytes_per_pixel else 0
            above = restored[index - row_bytes] if row else 0
            upper_left = (
                restored[index - row_bytes - bytes_per_pixel]
                if row and offset >= bytes_per_pixel
                else 0
            )
            restored[index] = (residual[index] + _paeth(left, above, upper_left)) & 0xFF
    return bytes(restored)


def build_tile_candidates(
    canonical: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
) -> TileCandidates:
    expected = width * height * bytes_per_pixel
    if len(canonical) != expected or expected > MAX_TILE_CANONICAL_BYTES:
        raise CASVTileIRError("tile payload is outside bounded layout")
    dc_sample = _modal_sample(canonical, bytes_per_pixel)
    dc_residual = _xor_with_sample(canonical, dc_sample)
    paeth = paeth_residual(
        canonical,
        width=width,
        height=height,
        bytes_per_pixel=bytes_per_pixel,
    )
    candidates = TileCandidates(
        canonical=canonical,
        payloads={
            "DC_XOR_ZLIB": dc_sample + zlib.compress(dc_residual, level=9),
            "PAETH_ZLIB": zlib.compress(paeth, level=9),
            "CANONICAL_ZLIB": zlib.compress(canonical, level=9),
            "CANONICAL_RAW": canonical,
        },
        dc_sample=dc_sample,
        dc_exact_bytes=sum(value == 0 for value in dc_residual),
        paeth_zero_bytes=sum(value == 0 for value in paeth),
    )
    candidates.validate()
    return candidates


def decode_tile_payload(
    mode: str,
    stored: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
    zlib_decoder: Callable[[bytes, int], bytes],
) -> bytes:
    expected = width * height * bytes_per_pixel
    if mode == "CANONICAL_RAW":
        if len(stored) != expected:
            raise CASVTileIRError("raw tile length differs")
        return stored
    if mode == "CANONICAL_ZLIB":
        return zlib_decoder(stored, expected)
    if mode == "DC_XOR_ZLIB":
        if len(stored) <= bytes_per_pixel:
            raise CASVTileIRError("DC tile payload is truncated")
        sample = stored[:bytes_per_pixel]
        residual = zlib_decoder(stored[bytes_per_pixel:], expected)
        return _xor_with_sample(residual, sample)
    if mode == "PAETH_ZLIB":
        residual = zlib_decoder(stored, expected)
        return reverse_paeth(
            residual,
            width=width,
            height=height,
            bytes_per_pixel=bytes_per_pixel,
        )
    raise CASVTileIRError("unknown tile storage mode")


__all__ = [
    "CASVTileIRError",
    "DEFAULT_STRIP_HEIGHT",
    "DEFAULT_TILE_WIDTH",
    "MAX_STRIP_CANONICAL_BYTES",
    "MAX_TILE_CANONICAL_BYTES",
    "StripLayout",
    "TILE_MODES",
    "TileCandidates",
    "TileLayout",
    "assemble_strip",
    "build_tile_candidates",
    "decode_tile_payload",
    "extract_tile",
    "iter_strip_layouts",
    "paeth_residual",
    "reverse_paeth",
    "summarize_layout",
]
