"""Independent, standard-library-only decoder for the CASV/0.4 tiled stream."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, BinaryIO


CASV_TILED_STREAM_MAGIC = b"CASV\x00\x04\r\n"
CASV_TILED_FOOTER_MAGIC = b"CV4IDX\r\n"
CASV_TILED_FOOTER = struct.Struct(">8sQ32s")
CASV_TILED_STRIP_MAGIC = b"CVT4"
CASV_TILED_STRIP_HEADER = struct.Struct(">4s10I32s")
CASV_TILED_TILE_ENTRY = struct.Struct(">HHB3xII")
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 100_000
MAX_TILES_PER_RECORD = 65_536
MAX_STRIP_CANONICAL_BYTES = 64 * 1024 * 1024
MAX_TILE_CANONICAL_BYTES = 8 * 1024 * 1024
PIXEL_FORMAT_GEOMETRY = {"RGB8": (1, 3), "YUV444P10LE": (3, 2)}
MODE_IDS = {
    "CANONICAL_RAW": 0,
    "CANONICAL_ZLIB": 1,
    "DC_XOR_ZLIB": 2,
    "PAETH_ZLIB": 3,
}
ID_MODES = {value: key for key, value in MODE_IDS.items()}


class IndependentCASVTiledStreamError(RuntimeError):
    pass


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_exact(stream: BinaryIO, length: int, label: str) -> bytes:
    payload = stream.read(length)
    if len(payload) != length:
        raise IndependentCASVTiledStreamError(f"CASV/0.4 {label} is truncated")
    return payload


def _bounded_zlib(payload: bytes, expected_bytes: int) -> bytes:
    decoder = zlib.decompressobj()
    restored = decoder.decompress(payload, expected_bytes + 1)
    if len(restored) > expected_bytes or decoder.unconsumed_tail:
        raise IndependentCASVTiledStreamError("CASV/0.4 zlib output exceeds bounds")
    restored += decoder.flush(expected_bytes - len(restored) + 1)
    if len(restored) > expected_bytes:
        raise IndependentCASVTiledStreamError("CASV/0.4 zlib output exceeds bounds")
    if not decoder.eof or decoder.unused_data or len(restored) != expected_bytes:
        raise IndependentCASVTiledStreamError("CASV/0.4 zlib stream is not exact")
    return restored


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


def _reverse_paeth(
    residual: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
) -> bytes:
    expected = width * height * bytes_per_pixel
    if len(residual) != expected:
        raise IndependentCASVTiledStreamError("CASV/0.4 Paeth residual length differs")
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


def _decode_tile(
    mode: str,
    stored: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
) -> bytes:
    expected = width * height * bytes_per_pixel
    if mode == "CANONICAL_RAW":
        if len(stored) != expected:
            raise IndependentCASVTiledStreamError("CASV/0.4 raw tile length differs")
        return stored
    if mode == "CANONICAL_ZLIB":
        return _bounded_zlib(stored, expected)
    if mode == "DC_XOR_ZLIB":
        if len(stored) <= bytes_per_pixel:
            raise IndependentCASVTiledStreamError("CASV/0.4 DC tile is truncated")
        sample = stored[:bytes_per_pixel]
        residual = _bounded_zlib(stored[bytes_per_pixel:], expected)
        return bytes(
            value ^ sample[index % bytes_per_pixel]
            for index, value in enumerate(residual)
        )
    if mode == "PAETH_ZLIB":
        return _reverse_paeth(
            _bounded_zlib(stored, expected),
            width=width,
            height=height,
            bytes_per_pixel=bytes_per_pixel,
        )
    raise IndependentCASVTiledStreamError("CASV/0.4 tile mode is unknown")


def _validate_media(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], int, int]:
    media = manifest.get("canonical_media")
    if not isinstance(media, dict):
        raise IndependentCASVTiledStreamError("CASV/0.4 canonical media is missing")
    fields = ("width", "height", "frame_count", "fps_numerator", "fps_denominator")
    if any(type(media.get(field)) is not int or media[field] <= 0 for field in fields):
        raise IndependentCASVTiledStreamError("CASV/0.4 media dimensions are invalid")
    if media["width"] > 16_384 or media["height"] > 16_384 or media["frame_count"] > 1_000_000:
        raise IndependentCASVTiledStreamError("CASV/0.4 media exceeds bounds")
    geometry = PIXEL_FORMAT_GEOMETRY.get(media.get("pixel_format"))
    if geometry is None:
        raise IndependentCASVTiledStreamError("CASV/0.4 pixel format is unsupported")
    plane_count, bytes_per_pixel = geometry
    canonical_bytes = (
        media["width"]
        * media["height"]
        * plane_count
        * bytes_per_pixel
        * media["frame_count"]
    )
    if media.get("canonical_bytes") != canonical_bytes:
        raise IndependentCASVTiledStreamError("CASV/0.4 media byte accounting differs")
    return media, plane_count, bytes_per_pixel


def _parse_record(
    encoded: bytes,
    expected: Mapping[str, Any],
) -> tuple[dict[str, Any], list[tuple[int, int, str, int, bytes]]]:
    if len(encoded) < CASV_TILED_STRIP_HEADER.size:
        raise IndependentCASVTiledStreamError("CASV/0.4 strip header is truncated")
    unpacked = CASV_TILED_STRIP_HEADER.unpack_from(encoded)
    (
        magic,
        record_index,
        frame_index,
        plane_index,
        y,
        width,
        height,
        bytes_per_pixel,
        tile_count,
        canonical_length,
        payload_length,
        canonical_hash,
    ) = unpacked
    if magic != CASV_TILED_STRIP_MAGIC:
        raise IndependentCASVTiledStreamError("CASV/0.4 strip magic differs")
    fields = {
        "index": record_index,
        "frame_index": frame_index,
        "plane_index": plane_index,
        "y": y,
        "width": width,
        "height": height,
        "bytes_per_pixel": bytes_per_pixel,
        "tile_count": tile_count,
        "canonical_length": canonical_length,
    }
    if any(expected.get(key) != value for key, value in fields.items()):
        raise IndependentCASVTiledStreamError("CASV/0.4 strip header differs from manifest")
    if not 1 <= tile_count <= MAX_TILES_PER_RECORD:
        raise IndependentCASVTiledStreamError("CASV/0.4 tile count is invalid")
    table_length = tile_count * CASV_TILED_TILE_ENTRY.size
    expected_length = CASV_TILED_STRIP_HEADER.size + table_length + payload_length
    if len(encoded) != expected_length:
        raise IndependentCASVTiledStreamError("CASV/0.4 strip payload length differs")
    if canonical_hash.hex() != expected.get("canonical_sha256"):
        raise IndependentCASVTiledStreamError("CASV/0.4 strip canonical hash differs")
    table_offset = CASV_TILED_STRIP_HEADER.size
    payload_offset = table_offset + table_length
    cursor = payload_offset
    expected_x = 0
    tiles: list[tuple[int, int, str, int, bytes]] = []
    for tile_index in range(tile_count):
        entry_offset = table_offset + tile_index * CASV_TILED_TILE_ENTRY.size
        x, tile_width, mode_id, tile_canonical, stored_length = (
            CASV_TILED_TILE_ENTRY.unpack_from(encoded, entry_offset)
        )
        mode = ID_MODES.get(mode_id)
        if (
            mode is None
            or x != expected_x
            or tile_width <= 0
            or x + tile_width > width
            or tile_canonical != tile_width * height * bytes_per_pixel
            or not 1 <= tile_canonical <= MAX_TILE_CANONICAL_BYTES
            or stored_length <= 0
            or cursor + stored_length > len(encoded)
        ):
            raise IndependentCASVTiledStreamError("CASV/0.4 tile table is invalid")
        stored = encoded[cursor : cursor + stored_length]
        if mode == "CANONICAL_RAW" and stored_length != tile_canonical:
            raise IndependentCASVTiledStreamError("CASV/0.4 raw tile accounting differs")
        tiles.append((x, tile_width, mode, tile_canonical, stored))
        cursor += stored_length
        expected_x += tile_width
    if expected_x != width or cursor != len(encoded):
        raise IndependentCASVTiledStreamError("CASV/0.4 tile partition is not exact")
    if sum(item[3] for item in tiles) != canonical_length:
        raise IndependentCASVTiledStreamError("CASV/0.4 tile canonical sum differs")
    return fields, tiles


def inspect_casv_tiled_stream(
    archive: str | Path,
    *,
    compute_archive_sha256: bool = True,
) -> dict[str, Any]:
    path = Path(archive).resolve()
    if not path.is_file():
        raise IndependentCASVTiledStreamError(f"CASV/0.4 archive not found: {path}")
    archive_bytes = path.stat().st_size
    minimum = len(CASV_TILED_STREAM_MAGIC) + CASV_TILED_FOOTER.size + 2
    if archive_bytes < minimum:
        raise IndependentCASVTiledStreamError("CASV/0.4 archive is truncated")
    with path.open("rb") as stream:
        if _read_exact(stream, len(CASV_TILED_STREAM_MAGIC), "header") != CASV_TILED_STREAM_MAGIC:
            raise IndependentCASVTiledStreamError("CASV/0.4 magic differs")
        stream.seek(-CASV_TILED_FOOTER.size, os.SEEK_END)
        footer = _read_exact(stream, CASV_TILED_FOOTER.size, "footer")
        footer_magic, manifest_length, manifest_hash = CASV_TILED_FOOTER.unpack(footer)
        if footer_magic != CASV_TILED_FOOTER_MAGIC:
            raise IndependentCASVTiledStreamError("CASV/0.4 footer magic differs")
        if not 1 <= manifest_length <= MAX_MANIFEST_BYTES:
            raise IndependentCASVTiledStreamError("CASV/0.4 manifest length is invalid")
        manifest_offset = archive_bytes - CASV_TILED_FOOTER.size - manifest_length
        if manifest_offset < len(CASV_TILED_STREAM_MAGIC):
            raise IndependentCASVTiledStreamError("CASV/0.4 manifest overlaps header")
        stream.seek(manifest_offset)
        manifest_bytes = _read_exact(stream, manifest_length, "manifest")
    if hashlib.sha256(manifest_bytes).digest() != manifest_hash:
        raise IndependentCASVTiledStreamError("CASV/0.4 manifest hash differs")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndependentCASVTiledStreamError("CASV/0.4 manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or _canonical_json(manifest) != manifest_bytes:
        raise IndependentCASVTiledStreamError("CASV/0.4 manifest is not canonical")
    if manifest.get("schema") != "casulo.casv/0.4":
        raise IndependentCASVTiledStreamError("unsupported CASV/0.4 schema")
    if manifest.get("equivalence_contract") != "EXACT_MEDIA":
        raise IndependentCASVTiledStreamError("CASV/0.4 requires EXACT_MEDIA")
    if manifest.get("foreign_bitstreams_embedded") is not False:
        raise IndependentCASVTiledStreamError("CASV/0.4 embeds a foreign bitstream")
    if manifest.get("audio_included") is not False:
        raise IndependentCASVTiledStreamError("CASV/0.4 audio is not implemented")
    media, plane_count, bytes_per_pixel = _validate_media(manifest)
    source = manifest.get("source")
    if (
        not isinstance(source, dict)
        or source.get("canonical_bytes") != media["canonical_bytes"]
        or not _is_sha256(source.get("canonical_sha256"))
    ):
        raise IndependentCASVTiledStreamError("CASV/0.4 source identity is invalid")
    representation = manifest.get("representation")
    if not isinstance(representation, dict):
        raise IndependentCASVTiledStreamError("CASV/0.4 representation is missing")
    tile_width = representation.get("tile_width")
    strip_height = representation.get("strip_height")
    if (
        type(tile_width) is not int
        or not 1 <= tile_width <= media["width"]
        or type(strip_height) is not int
        or not 1 <= strip_height <= media["height"]
    ):
        raise IndependentCASVTiledStreamError("CASV/0.4 tile geometry is invalid")
    records = manifest.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise IndependentCASVTiledStreamError("CASV/0.4 record index is invalid")

    expected_records = (
        media["frame_count"]
        * plane_count
        * ((media["height"] + strip_height - 1) // strip_height)
    )
    if len(records) != expected_records:
        raise IndependentCASVTiledStreamError("CASV/0.4 record cardinality differs")
    expected_stored_offset = len(CASV_TILED_STREAM_MAGIC)
    expected_canonical_offset = 0
    mode_counts: Counter[str] = Counter()
    record_index = 0
    with path.open("rb") as stream:
        for frame_index in range(media["frame_count"]):
            for plane_index in range(plane_count):
                for y in range(0, media["height"], strip_height):
                    record = records[record_index]
                    height = min(strip_height, media["height"] - y)
                    canonical_length = media["width"] * height * bytes_per_pixel
                    expected = {
                        "index": record_index,
                        "frame_index": frame_index,
                        "plane_index": plane_index,
                        "y": y,
                        "width": media["width"],
                        "height": height,
                        "bytes_per_pixel": bytes_per_pixel,
                        "tile_count": (media["width"] + tile_width - 1) // tile_width,
                        "canonical_length": canonical_length,
                    }
                    if not isinstance(record, dict) or any(
                        record.get(key) != value for key, value in expected.items()
                    ):
                        raise IndependentCASVTiledStreamError("CASV/0.4 record order differs")
                    stored_offset = record.get("stored_offset")
                    stored_length = record.get("stored_length")
                    if (
                        stored_offset != expected_stored_offset
                        or type(stored_length) is not int
                        or stored_length <= 0
                        or stored_offset + stored_length > manifest_offset
                        or record.get("canonical_offset") != expected_canonical_offset
                        or not _is_sha256(record.get("canonical_sha256"))
                        or not _is_sha256(record.get("stored_sha256"))
                        or not _is_sha256(record.get("selection_receipt_chain_start"))
                        or not _is_sha256(record.get("selection_receipt_chain_end"))
                        or record.get("selection_receipt_count") != expected["tile_count"]
                    ):
                        raise IndependentCASVTiledStreamError("CASV/0.4 record bounds differ")
                    stream.seek(stored_offset)
                    encoded = _read_exact(stream, stored_length, "strip record")
                    if hashlib.sha256(encoded).hexdigest() != record["stored_sha256"]:
                        raise IndependentCASVTiledStreamError("CASV/0.4 strip hash differs")
                    _fields, tiles = _parse_record(encoded, record)
                    mode_counts.update(tile[2] for tile in tiles)
                    expected_stored_offset += stored_length
                    expected_canonical_offset += canonical_length
                    record_index += 1
    if expected_stored_offset != manifest_offset:
        raise IndependentCASVTiledStreamError("CASV/0.4 payload has gaps or trailing bytes")
    if expected_canonical_offset != source["canonical_bytes"]:
        raise IndependentCASVTiledStreamError("CASV/0.4 canonical partition differs")
    return {
        "path": str(path),
        "archive_bytes": archive_bytes,
        "archive_sha256": _sha256_file(path) if compute_archive_sha256 else None,
        "archive_sha256_computed": compute_archive_sha256,
        "manifest": manifest,
        "manifest_offset": manifest_offset,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "canonical_media": media,
        "record_count": len(records),
        "tile_count": sum(mode_counts.values()),
        "storage_modes": dict(mode_counts),
    }


def _decode_record(encoded: bytes, record: Mapping[str, Any]) -> bytes:
    fields, encoded_tiles = _parse_record(encoded, record)
    strip = bytearray(fields["canonical_length"])
    strip_row_bytes = fields["width"] * fields["bytes_per_pixel"]
    for x, tile_width, mode, _canonical_length, stored in encoded_tiles:
        tile = _decode_tile(
            mode,
            stored,
            width=tile_width,
            height=fields["height"],
            bytes_per_pixel=fields["bytes_per_pixel"],
        )
        tile_row_bytes = tile_width * fields["bytes_per_pixel"]
        source_offset = 0
        x_offset = x * fields["bytes_per_pixel"]
        for row in range(fields["height"]):
            destination = row * strip_row_bytes + x_offset
            strip[destination : destination + tile_row_bytes] = tile[
                source_offset : source_offset + tile_row_bytes
            ]
            source_offset += tile_row_bytes
    restored = bytes(strip)
    if hashlib.sha256(restored).hexdigest() != record["canonical_sha256"]:
        raise IndependentCASVTiledStreamError("CASV/0.4 decoded strip hash differs")
    return restored


def iter_casv_tiled_canonical(archive: str | Path) -> Iterator[bytes]:
    inspected = inspect_casv_tiled_stream(archive, compute_archive_sha256=False)
    path = Path(inspected["path"])
    with path.open("rb") as stream:
        for record in inspected["manifest"]["records"]:
            stream.seek(record["stored_offset"])
            encoded = _read_exact(stream, record["stored_length"], "strip record")
            yield _decode_record(encoded, record)


def verify_casv_tiled_stream(archive: str | Path) -> dict[str, Any]:
    inspected = inspect_casv_tiled_stream(archive)
    digest = hashlib.sha256()
    canonical_bytes = 0
    maximum_decoded_strip_bytes = 0
    for strip in iter_casv_tiled_canonical(archive):
        digest.update(strip)
        canonical_bytes += len(strip)
        maximum_decoded_strip_bytes = max(maximum_decoded_strip_bytes, len(strip))
    source = inspected["manifest"]["source"]
    if canonical_bytes != source["canonical_bytes"] or digest.hexdigest() != source["canonical_sha256"]:
        raise IndependentCASVTiledStreamError("CASV/0.4 canonical media hash differs")
    return {
        "schema": "casulo.casv-independent-verification/0.4",
        "status": "PASS",
        "archive": inspected["path"],
        "archive_bytes": inspected["archive_bytes"],
        "archive_sha256": inspected["archive_sha256"],
        "canonical_bytes": canonical_bytes,
        "canonical_sha256": digest.hexdigest(),
        "record_count": inspected["record_count"],
        "tile_count": inspected["tile_count"],
        "storage_modes": inspected["storage_modes"],
        "maximum_decoded_strip_bytes": maximum_decoded_strip_bytes,
        "full_frame_allocation_required": False,
        "foreign_bitstreams_embedded": False,
    }


def unpack_casv_tiled_stream(archive: str | Path, output: str | Path) -> dict[str, Any]:
    output_path = Path(output).resolve()
    if output_path.exists():
        raise IndependentCASVTiledStreamError(f"output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    temporary = output_path.with_name(output_path.name + ".casv-part")
    try:
        with temporary.open("xb") as stream:
            for strip in iter_casv_tiled_canonical(archive):
                stream.write(strip)
                digest.update(strip)
                written += len(strip)
            stream.flush()
            os.fsync(stream.fileno())
        inspected = inspect_casv_tiled_stream(archive, compute_archive_sha256=False)
        source = inspected["manifest"]["source"]
        if written != source["canonical_bytes"] or digest.hexdigest() != source["canonical_sha256"]:
            raise IndependentCASVTiledStreamError("unpacked CASV/0.4 media differs")
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema": "casulo.casv-unpack/0.4",
        "status": "PASS",
        "output": str(output_path),
        "bytes": written,
        "sha256": digest.hexdigest(),
    }


__all__ = [
    "CASV_TILED_FOOTER",
    "CASV_TILED_FOOTER_MAGIC",
    "CASV_TILED_STREAM_MAGIC",
    "CASV_TILED_STRIP_HEADER",
    "CASV_TILED_STRIP_MAGIC",
    "CASV_TILED_TILE_ENTRY",
    "ID_MODES",
    "IndependentCASVTiledStreamError",
    "MAX_MANIFEST_BYTES",
    "MAX_RECORDS",
    "MODE_IDS",
    "inspect_casv_tiled_stream",
    "iter_casv_tiled_canonical",
    "unpack_casv_tiled_stream",
    "verify_casv_tiled_stream",
]
