"""Independent, standard-library-only decoder for temporal CASV/0.6."""

from __future__ import annotations

import hashlib
import os
import struct
import tempfile
import zlib
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO


CASV_TEMPORAL_MAGIC = b"CASV\x00\x06\r\n"
CASV_TEMPORAL_RECORD_MAGIC = b"CVT6"
CASV_TEMPORAL_FOOTER_MAGIC = b"CV6END\r\n"
CASV_TEMPORAL_HEADER = struct.Struct(">BBH8IQ32s")
CASV_TEMPORAL_RECORD_HEADER = struct.Struct(">4sII32s")
CASV_TEMPORAL_TILE_ENTRY = struct.Struct(">BI")
CASV_TEMPORAL_FOOTER = struct.Struct(">8sI32s32s")

PIXEL_FORMAT_IDS = {"RGB8": 1, "YUV444P10LE": 2}
ID_PIXEL_FORMATS = {value: key for key, value in PIXEL_FORMAT_IDS.items()}
MODE_IDS = {
    "CANONICAL_RAW": 0,
    "CANONICAL_ZLIB": 1,
    "DC_XOR_ZLIB": 2,
    "PAETH_ZLIB": 3,
    "TEMPORAL_XOR_ZLIB": 4,
    "TEMPORAL_SUB_ZLIB": 5,
}
ID_MODES = {value: key for key, value in MODE_IDS.items()}
PIXEL_FORMAT_GEOMETRY = {"RGB8": (1, 3), "YUV444P10LE": (3, 2)}
TEMPORAL_MODES = frozenset({"TEMPORAL_XOR_ZLIB", "TEMPORAL_SUB_ZLIB"})

MAX_RECORDS = 100_000
MAX_TILES_PER_RECORD = 65_536
MAX_TILE_CANONICAL_BYTES = 8 * 1024 * 1024
MAX_STRIP_CANONICAL_BYTES = 64 * 1024 * 1024
MAX_STORED_TILE_BYTES = MAX_TILE_CANONICAL_BYTES + 1024 * 1024
MAX_KEYFRAME_INTERVAL = 1024


class IndependentCASVTemporalStreamError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _read_exact(stream: BinaryIO, length: int, label: str) -> bytes:
    payload = stream.read(length)
    if len(payload) != length:
        raise IndependentCASVTemporalStreamError(f"CASV/0.6 {label} is truncated")
    return payload


def _read_hashed(
    stream: BinaryIO,
    length: int,
    label: str,
    digest: Any,
) -> bytes:
    payload = _read_exact(stream, length, label)
    digest.update(payload)
    return payload


def _hash_stream_bytes(stream: BinaryIO, length: int, digest: Any) -> None:
    remaining = length
    while remaining:
        block = _read_exact(stream, min(remaining, 1024 * 1024), "record payload")
        digest.update(block)
        remaining -= len(block)


def _bounded_zlib(payload: bytes, expected_bytes: int) -> bytes:
    decoder = zlib.decompressobj()
    restored = decoder.decompress(payload, expected_bytes + 1)
    if len(restored) > expected_bytes or decoder.unconsumed_tail:
        raise IndependentCASVTemporalStreamError("CASV/0.6 zlib output exceeds bounds")
    restored += decoder.flush(expected_bytes - len(restored) + 1)
    if len(restored) > expected_bytes:
        raise IndependentCASVTemporalStreamError("CASV/0.6 zlib output exceeds bounds")
    if not decoder.eof or decoder.unused_data or len(restored) != expected_bytes:
        raise IndependentCASVTemporalStreamError("CASV/0.6 zlib stream is not exact")
    return restored


def _paeth(left: int, above: int, upper_left: int) -> int:
    prediction = left + above - upper_left
    dl = abs(prediction - left)
    da = abs(prediction - above)
    dul = abs(prediction - upper_left)
    if dl <= da and dl <= dul:
        return left
    if da <= dul:
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
        raise IndependentCASVTemporalStreamError("CASV/0.6 Paeth residual differs")
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


def _extract_tile(
    strip: bytes,
    *,
    full_width: int,
    x: int,
    width: int,
    height: int,
    bytes_per_pixel: int,
) -> bytes:
    expected_strip = full_width * height * bytes_per_pixel
    if len(strip) != expected_strip:
        raise IndependentCASVTemporalStreamError("CASV/0.6 reference strip differs")
    row_bytes = full_width * bytes_per_pixel
    tile_row_bytes = width * bytes_per_pixel
    x_offset = x * bytes_per_pixel
    result = bytearray(tile_row_bytes * height)
    cursor = 0
    for row in range(height):
        source = row * row_bytes + x_offset
        result[cursor : cursor + tile_row_bytes] = strip[
            source : source + tile_row_bytes
        ]
        cursor += tile_row_bytes
    return bytes(result)


def _decode_tile(
    mode: str,
    stored: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
    previous: bytes | None,
) -> bytes:
    expected = width * height * bytes_per_pixel
    if mode == "CANONICAL_RAW":
        if len(stored) != expected:
            raise IndependentCASVTemporalStreamError("CASV/0.6 raw tile differs")
        return stored
    if mode == "CANONICAL_ZLIB":
        return _bounded_zlib(stored, expected)
    if mode == "DC_XOR_ZLIB":
        if len(stored) <= bytes_per_pixel:
            raise IndependentCASVTemporalStreamError("CASV/0.6 DC tile is truncated")
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
    if mode in TEMPORAL_MODES:
        if previous is None or len(previous) != expected:
            raise IndependentCASVTemporalStreamError(
                "CASV/0.6 temporal reference is unavailable"
            )
        residual = _bounded_zlib(stored, expected)
        if mode == "TEMPORAL_XOR_ZLIB":
            return bytes(
                left ^ right for left, right in zip(residual, previous, strict=True)
            )
        return bytes(
            (left + right) & 0xFF
            for left, right in zip(residual, previous, strict=True)
        )
    raise IndependentCASVTemporalStreamError("CASV/0.6 tile mode is unknown")


def _validate_header(values: tuple[Any, ...]) -> dict[str, Any]:
    (
        pixel_format_id,
        flags,
        header_size,
        width,
        height,
        frame_count,
        fps_numerator,
        fps_denominator,
        tile_width,
        strip_height,
        keyframe_interval,
        canonical_bytes,
        canonical_hash,
    ) = values
    pixel_format = ID_PIXEL_FORMATS.get(pixel_format_id)
    if pixel_format is None or flags != 0 or header_size != CASV_TEMPORAL_HEADER.size:
        raise IndependentCASVTemporalStreamError("CASV/0.6 header contract differs")
    fields = (
        width,
        height,
        frame_count,
        fps_numerator,
        fps_denominator,
        tile_width,
        strip_height,
        keyframe_interval,
    )
    if any(type(value) is not int or value <= 0 for value in fields):
        raise IndependentCASVTemporalStreamError("CASV/0.6 dimensions are invalid")
    if width > 16_384 or height > 16_384 or frame_count > 1_000_000:
        raise IndependentCASVTemporalStreamError("CASV/0.6 media exceeds bounds")
    if tile_width > width or strip_height > height:
        raise IndependentCASVTemporalStreamError("CASV/0.6 tile geometry exceeds media")
    if keyframe_interval > MAX_KEYFRAME_INTERVAL:
        raise IndependentCASVTemporalStreamError(
            "CASV/0.6 keyframe interval exceeds bounds"
        )
    plane_count, bytes_per_pixel = PIXEL_FORMAT_GEOMETRY[pixel_format]
    frame_bytes = width * height * plane_count * bytes_per_pixel
    expected_bytes = frame_bytes * frame_count
    if canonical_bytes != expected_bytes:
        raise IndependentCASVTemporalStreamError(
            "CASV/0.6 canonical byte count differs"
        )
    strips_per_plane = (height + strip_height - 1) // strip_height
    records_per_frame = plane_count * strips_per_plane
    expected_records = frame_count * records_per_frame
    if not 1 <= expected_records <= MAX_RECORDS:
        raise IndependentCASVTemporalStreamError("CASV/0.6 record count exceeds bounds")
    return {
        "width": width,
        "height": height,
        "frame_count": frame_count,
        "fps_numerator": fps_numerator,
        "fps_denominator": fps_denominator,
        "pixel_format": pixel_format,
        "canonical_bytes": canonical_bytes,
        "canonical_sha256": canonical_hash.hex(),
        "tile_width": tile_width,
        "strip_height": strip_height,
        "keyframe_interval": keyframe_interval,
        "plane_count": plane_count,
        "bytes_per_pixel": bytes_per_pixel,
        "frame_bytes": frame_bytes,
        "records_per_frame": records_per_frame,
        "record_count": expected_records,
    }


def _iter_expected_records(media: dict[str, Any]) -> Iterator[dict[str, int]]:
    index = 0
    canonical_offset = 0
    for frame_index in range(media["frame_count"]):
        frame_offset = 0
        for plane_index in range(media["plane_count"]):
            for y in range(0, media["height"], media["strip_height"]):
                height = min(media["strip_height"], media["height"] - y)
                canonical_length = media["width"] * height * media["bytes_per_pixel"]
                tile_count = (media["width"] + media["tile_width"] - 1) // media[
                    "tile_width"
                ]
                if (
                    canonical_length > MAX_STRIP_CANONICAL_BYTES
                    or not 1 <= tile_count <= MAX_TILES_PER_RECORD
                ):
                    raise IndependentCASVTemporalStreamError(
                        "CASV/0.6 derived record exceeds bounds"
                    )
                yield {
                    "index": index,
                    "frame_index": frame_index,
                    "plane_index": plane_index,
                    "y": y,
                    "height": height,
                    "canonical_offset": canonical_offset,
                    "frame_offset": frame_offset,
                    "canonical_length": canonical_length,
                    "tile_count": tile_count,
                    "is_keyframe": frame_index % media["keyframe_interval"] == 0,
                }
                index += 1
                canonical_offset += canonical_length
                frame_offset += canonical_length


def inspect_casv_temporal_stream(
    archive: str | Path,
    *,
    compute_archive_sha256: bool = True,
) -> dict[str, Any]:
    path = Path(archive).resolve()
    if not path.is_file():
        raise IndependentCASVTemporalStreamError(f"CASV/0.6 archive not found: {path}")
    archive_bytes = path.stat().st_size
    minimum = (
        len(CASV_TEMPORAL_MAGIC)
        + CASV_TEMPORAL_HEADER.size
        + CASV_TEMPORAL_RECORD_HEADER.size
        + CASV_TEMPORAL_TILE_ENTRY.size
        + CASV_TEMPORAL_FOOTER.size
    )
    if archive_bytes < minimum:
        raise IndependentCASVTemporalStreamError("CASV/0.6 archive is truncated")

    content_digest = hashlib.sha256()
    records: list[dict[str, Any]] = []
    modes: Counter[str] = Counter()
    with path.open("rb") as stream:
        magic = _read_hashed(stream, len(CASV_TEMPORAL_MAGIC), "magic", content_digest)
        if magic != CASV_TEMPORAL_MAGIC:
            raise IndependentCASVTemporalStreamError("CASV/0.6 magic differs")
        packed_header = _read_hashed(
            stream, CASV_TEMPORAL_HEADER.size, "header", content_digest
        )
        media = _validate_header(CASV_TEMPORAL_HEADER.unpack(packed_header))
        for expected in _iter_expected_records(media):
            record_offset = stream.tell()
            packed_record = _read_hashed(
                stream,
                CASV_TEMPORAL_RECORD_HEADER.size,
                "record header",
                content_digest,
            )
            record_magic, index, payload_length, canonical_hash = (
                CASV_TEMPORAL_RECORD_HEADER.unpack(packed_record)
            )
            if record_magic != CASV_TEMPORAL_RECORD_MAGIC or index != expected["index"]:
                raise IndependentCASVTemporalStreamError(
                    "CASV/0.6 record order differs"
                )
            table_length = expected["tile_count"] * CASV_TEMPORAL_TILE_ENTRY.size
            table = _read_hashed(stream, table_length, "tile table", content_digest)
            lengths: list[int] = []
            tile_modes: list[str] = []
            for tile_index in range(expected["tile_count"]):
                offset = tile_index * CASV_TEMPORAL_TILE_ENTRY.size
                mode_id, stored_length = CASV_TEMPORAL_TILE_ENTRY.unpack_from(
                    table, offset
                )
                mode = ID_MODES.get(mode_id)
                x = tile_index * media["tile_width"]
                width = min(media["tile_width"], media["width"] - x)
                tile_canonical = width * expected["height"] * media["bytes_per_pixel"]
                invalid_temporal = expected["is_keyframe"] and mode in TEMPORAL_MODES
                if (
                    mode is None
                    or invalid_temporal
                    or not 1 <= tile_canonical <= MAX_TILE_CANONICAL_BYTES
                    or not 1 <= stored_length <= MAX_STORED_TILE_BYTES
                    or (mode == "CANONICAL_RAW" and stored_length != tile_canonical)
                ):
                    raise IndependentCASVTemporalStreamError(
                        "CASV/0.6 tile table is invalid"
                    )
                lengths.append(stored_length)
                tile_modes.append(mode)
            if sum(lengths) != payload_length:
                raise IndependentCASVTemporalStreamError(
                    "CASV/0.6 payload accounting differs"
                )
            payload_offset = stream.tell()
            if (
                payload_offset + payload_length + CASV_TEMPORAL_FOOTER.size
                > archive_bytes
            ):
                raise IndependentCASVTemporalStreamError(
                    "CASV/0.6 record exceeds archive"
                )
            _hash_stream_bytes(stream, payload_length, content_digest)
            modes.update(tile_modes)
            records.append(
                {
                    **expected,
                    "record_offset": record_offset,
                    "payload_offset": payload_offset,
                    "payload_length": payload_length,
                    "stored_length": CASV_TEMPORAL_RECORD_HEADER.size
                    + table_length
                    + payload_length,
                    "canonical_sha256": canonical_hash.hex(),
                    "tile_modes": tile_modes,
                    "tile_stored_lengths": lengths,
                }
            )
        footer = _read_exact(stream, CASV_TEMPORAL_FOOTER.size, "footer")
        if stream.read(1):
            raise IndependentCASVTemporalStreamError("CASV/0.6 has trailing bytes")
    footer_magic, receipt_count, receipt_chain_head, claimed_content_hash = (
        CASV_TEMPORAL_FOOTER.unpack(footer)
    )
    if footer_magic != CASV_TEMPORAL_FOOTER_MAGIC:
        raise IndependentCASVTemporalStreamError("CASV/0.6 footer magic differs")
    if receipt_count != sum(modes.values()) or receipt_chain_head == bytes(32):
        raise IndependentCASVTemporalStreamError("CASV/0.6 authority footer differs")
    if claimed_content_hash != content_digest.digest():
        raise IndependentCASVTemporalStreamError("CASV/0.6 content hash differs")
    return {
        "schema": "casulo.casv-temporal-inspection/0.6",
        "path": str(path),
        "archive_bytes": archive_bytes,
        "archive_sha256": _sha256_file(path) if compute_archive_sha256 else None,
        "archive_sha256_computed": compute_archive_sha256,
        "content_sha256": content_digest.hexdigest(),
        "canonical_media": {
            key: media[key]
            for key in (
                "width",
                "height",
                "frame_count",
                "fps_numerator",
                "fps_denominator",
                "pixel_format",
                "canonical_bytes",
                "canonical_sha256",
            )
        },
        "tile_width": media["tile_width"],
        "strip_height": media["strip_height"],
        "keyframe_interval": media["keyframe_interval"],
        "frame_bytes": media["frame_bytes"],
        "record_count": len(records),
        "tile_count": sum(modes.values()),
        "storage_modes": dict(modes),
        "temporal_tile_count": sum(modes[mode] for mode in TEMPORAL_MODES),
        "selection_receipt_count": receipt_count,
        "selection_receipt_chain_head": receipt_chain_head.hex(),
        "records": records,
        "foreign_bitstreams_embedded": False,
        "audio_included": False,
    }


def _decode_record(
    stream: BinaryIO,
    media: dict[str, Any],
    record: dict[str, Any],
    previous_strip: bytes | None,
) -> bytes:
    stream.seek(record["payload_offset"])
    payload = _read_exact(stream, record["payload_length"], "record payload")
    cursor = 0
    strip = bytearray(record["canonical_length"])
    strip_row_bytes = media["width"] * media["bytes_per_pixel"]
    for tile_index, (mode, stored_length) in enumerate(
        zip(record["tile_modes"], record["tile_stored_lengths"], strict=True)
    ):
        stored = payload[cursor : cursor + stored_length]
        cursor += stored_length
        x = tile_index * media["tile_width"]
        width = min(media["tile_width"], media["width"] - x)
        previous = None
        if mode in TEMPORAL_MODES:
            if previous_strip is None:
                raise IndependentCASVTemporalStreamError(
                    "CASV/0.6 temporal tile has no previous strip"
                )
            previous = _extract_tile(
                previous_strip,
                full_width=media["width"],
                x=x,
                width=width,
                height=record["height"],
                bytes_per_pixel=media["bytes_per_pixel"],
            )
        tile = _decode_tile(
            mode,
            stored,
            width=width,
            height=record["height"],
            bytes_per_pixel=media["bytes_per_pixel"],
            previous=previous,
        )
        tile_row_bytes = width * media["bytes_per_pixel"]
        source_offset = 0
        x_offset = x * media["bytes_per_pixel"]
        for row in range(record["height"]):
            destination = row * strip_row_bytes + x_offset
            strip[destination : destination + tile_row_bytes] = tile[
                source_offset : source_offset + tile_row_bytes
            ]
            source_offset += tile_row_bytes
    if cursor != len(payload):
        raise IndependentCASVTemporalStreamError(
            "CASV/0.6 tile payload has trailing bytes"
        )
    restored = bytes(strip)
    if hashlib.sha256(restored).hexdigest() != record["canonical_sha256"]:
        raise IndependentCASVTemporalStreamError("CASV/0.6 decoded strip hash differs")
    return restored


def iter_casv_temporal_canonical(archive: str | Path) -> Iterator[bytes]:
    inspected = inspect_casv_temporal_stream(archive, compute_archive_sha256=False)
    media = {
        **inspected["canonical_media"],
        "tile_width": inspected["tile_width"],
        "strip_height": inspected["strip_height"],
        "keyframe_interval": inspected["keyframe_interval"],
        "frame_bytes": inspected["frame_bytes"],
        "bytes_per_pixel": PIXEL_FORMAT_GEOMETRY[
            inspected["canonical_media"]["pixel_format"]
        ][1],
    }
    with (
        Path(inspected["path"]).open("rb") as stream,
        tempfile.TemporaryFile() as previous_frame,
        tempfile.TemporaryFile() as current_frame,
    ):
        active_frame = -1
        for record in inspected["records"]:
            if record["frame_index"] != active_frame:
                if active_frame >= 0:
                    if current_frame.tell() != media["frame_bytes"]:
                        raise IndependentCASVTemporalStreamError(
                            "CASV/0.6 decoded frame spool differs"
                        )
                    previous_frame, current_frame = current_frame, previous_frame
                    current_frame.seek(0)
                    current_frame.truncate(0)
                active_frame = record["frame_index"]
            previous_strip = None
            if any(mode in TEMPORAL_MODES for mode in record["tile_modes"]):
                previous_frame.seek(record["frame_offset"])
                previous_strip = _read_exact(
                    previous_frame,
                    record["canonical_length"],
                    "previous-frame strip",
                )
            restored = _decode_record(stream, media, record, previous_strip)
            current_frame.seek(record["frame_offset"])
            current_frame.write(restored)
            yield restored


def verify_casv_temporal_stream(archive: str | Path) -> dict[str, Any]:
    inspected = inspect_casv_temporal_stream(archive)
    digest = hashlib.sha256()
    canonical_bytes = 0
    maximum_decoded_strip_bytes = 0
    for strip in iter_casv_temporal_canonical(archive):
        digest.update(strip)
        canonical_bytes += len(strip)
        maximum_decoded_strip_bytes = max(maximum_decoded_strip_bytes, len(strip))
    media = inspected["canonical_media"]
    if (
        canonical_bytes != media["canonical_bytes"]
        or digest.hexdigest() != media["canonical_sha256"]
    ):
        raise IndependentCASVTemporalStreamError(
            "CASV/0.6 canonical media hash differs"
        )
    return {
        "schema": "casulo.casv-independent-verification/0.6",
        "status": "PASS",
        "archive": inspected["path"],
        "archive_bytes": inspected["archive_bytes"],
        "archive_sha256": inspected["archive_sha256"],
        "content_sha256": inspected["content_sha256"],
        "canonical_bytes": canonical_bytes,
        "canonical_sha256": digest.hexdigest(),
        "canonical_media": media,
        "record_count": inspected["record_count"],
        "tile_count": inspected["tile_count"],
        "storage_modes": inspected["storage_modes"],
        "temporal_tile_count": inspected["temporal_tile_count"],
        "keyframe_interval": inspected["keyframe_interval"],
        "selection_receipt_count": inspected["selection_receipt_count"],
        "selection_receipt_chain_head": inspected["selection_receipt_chain_head"],
        "maximum_decoded_strip_bytes": maximum_decoded_strip_bytes,
        "maximum_reference_spool_bytes": inspected["frame_bytes"],
        "previous_frame_spool_medium": "ANONYMOUS_TEMPORARY_FILE",
        "full_frame_memory_allocation_required": False,
        "foreign_bitstreams_embedded": False,
        "audio_included": False,
    }


def unpack_casv_temporal_stream(
    archive: str | Path, output: str | Path
) -> dict[str, Any]:
    output_path = Path(output).resolve()
    if output_path.exists():
        raise IndependentCASVTemporalStreamError(
            f"output already exists: {output_path}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".casv-part")
    digest = hashlib.sha256()
    written = 0
    try:
        with temporary.open("xb") as stream:
            for strip in iter_casv_temporal_canonical(archive):
                stream.write(strip)
                digest.update(strip)
                written += len(strip)
            stream.flush()
            os.fsync(stream.fileno())
        media = inspect_casv_temporal_stream(archive, compute_archive_sha256=False)[
            "canonical_media"
        ]
        if (
            written != media["canonical_bytes"]
            or digest.hexdigest() != media["canonical_sha256"]
        ):
            raise IndependentCASVTemporalStreamError("CASV/0.6 unpack hash differs")
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema": "casulo.casv-temporal-unpack/0.6",
        "status": "PASS",
        "output": str(output_path),
        "bytes": written,
        "sha256": digest.hexdigest(),
    }


__all__ = [
    "CASV_TEMPORAL_FOOTER",
    "CASV_TEMPORAL_FOOTER_MAGIC",
    "CASV_TEMPORAL_HEADER",
    "CASV_TEMPORAL_MAGIC",
    "CASV_TEMPORAL_RECORD_HEADER",
    "CASV_TEMPORAL_RECORD_MAGIC",
    "CASV_TEMPORAL_TILE_ENTRY",
    "IndependentCASVTemporalStreamError",
    "MODE_IDS",
    "inspect_casv_temporal_stream",
    "iter_casv_temporal_canonical",
    "unpack_casv_temporal_stream",
    "verify_casv_temporal_stream",
]
