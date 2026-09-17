"""Independent, standard-library-only decoder for motion CASV/0.7."""

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


CASV_MOTION_MAGIC = b"CASV\x00\x07\r\n"
CASV_MOTION_RECORD_MAGIC = b"CVM7"
CASV_MOTION_FOOTER_MAGIC = b"CV7END\r\n"
CASV_MOTION_HEADER = struct.Struct(">BBH9IQ32s")
CASV_MOTION_RECORD_HEADER = struct.Struct(">4sII32s")
CASV_MOTION_TILE_ENTRY = struct.Struct(">BI")
CASV_MOTION_VECTOR = struct.Struct(">bb")
CASV_MOTION_FOOTER = struct.Struct(">8sI32s32s")

PIXEL_FORMAT_IDS = {"RGB8": 1, "YUV444P10LE": 2}
ID_PIXEL_FORMATS = {value: key for key, value in PIXEL_FORMAT_IDS.items()}
MODE_IDS = {
    "CANONICAL_RAW": 0,
    "CANONICAL_ZLIB": 1,
    "DC_XOR_ZLIB": 2,
    "PAETH_ZLIB": 3,
    "TEMPORAL_XOR_ZLIB": 4,
    "TEMPORAL_SUB_ZLIB": 5,
    "MOTION_XOR_ZLIB": 6,
    "MOTION_SUB_ZLIB": 7,
}
ID_MODES = {value: key for key, value in MODE_IDS.items()}
PIXEL_FORMAT_GEOMETRY = {"RGB8": (1, 3), "YUV444P10LE": (3, 2)}
TEMPORAL_MODES = frozenset({"TEMPORAL_XOR_ZLIB", "TEMPORAL_SUB_ZLIB"})
MOTION_MODES = frozenset({"MOTION_XOR_ZLIB", "MOTION_SUB_ZLIB"})

MAX_RECORDS = 100_000
MAX_TILES_PER_RECORD = 65_536
MAX_TILE_CANONICAL_BYTES = 8 * 1024 * 1024
MAX_STRIP_CANONICAL_BYTES = 64 * 1024 * 1024
MAX_STORED_TILE_BYTES = MAX_TILE_CANONICAL_BYTES + 1024 * 1024
MAX_KEYFRAME_INTERVAL = 1024
MAX_MOTION_RADIUS = 32


class IndependentCASVMotionStreamError(RuntimeError):
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
        raise IndependentCASVMotionStreamError(f"CASV/0.7 {label} is truncated")
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


def _bounded_zlib(payload: bytes, expected_bytes: int) -> bytes:
    decoder = zlib.decompressobj()
    restored = decoder.decompress(payload, expected_bytes + 1)
    if len(restored) > expected_bytes or decoder.unconsumed_tail:
        raise IndependentCASVMotionStreamError("CASV/0.7 zlib output exceeds bounds")
    restored += decoder.flush(expected_bytes - len(restored) + 1)
    if len(restored) > expected_bytes:
        raise IndependentCASVMotionStreamError("CASV/0.7 zlib output exceeds bounds")
    if not decoder.eof or decoder.unused_data or len(restored) != expected_bytes:
        raise IndependentCASVMotionStreamError("CASV/0.7 zlib stream is not exact")
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
        raise IndependentCASVMotionStreamError("CASV/0.7 Paeth residual differs")
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


def _read_reference_tile(
    frame: BinaryIO,
    media: dict[str, Any],
    *,
    plane_index: int,
    x: int,
    y: int,
    width: int,
    height: int,
) -> bytes:
    if (
        not 0 <= plane_index < media["plane_count"]
        or x < 0
        or y < 0
        or x + width > media["width"]
        or y + height > media["height"]
    ):
        raise IndependentCASVMotionStreamError(
            "CASV/0.7 motion reference exceeds previous frame"
        )
    bytes_per_pixel = media["bytes_per_pixel"]
    row_bytes = media["width"] * bytes_per_pixel
    tile_row_bytes = width * bytes_per_pixel
    plane_bytes = media["width"] * media["height"] * bytes_per_pixel
    base = plane_index * plane_bytes + y * row_bytes + x * bytes_per_pixel
    result = bytearray(tile_row_bytes * height)
    cursor = 0
    for row in range(height):
        frame.seek(base + row * row_bytes)
        value = _read_exact(frame, tile_row_bytes, "previous-frame motion reference")
        result[cursor : cursor + tile_row_bytes] = value
        cursor += tile_row_bytes
    return bytes(result)


def _decode_tile(
    mode: str,
    stored: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
    reference: bytes | None,
) -> bytes:
    expected = width * height * bytes_per_pixel
    if mode == "CANONICAL_RAW":
        if len(stored) != expected:
            raise IndependentCASVMotionStreamError("CASV/0.7 raw tile differs")
        return stored
    if mode == "CANONICAL_ZLIB":
        return _bounded_zlib(stored, expected)
    if mode == "DC_XOR_ZLIB":
        if len(stored) <= bytes_per_pixel:
            raise IndependentCASVMotionStreamError("CASV/0.7 DC tile is truncated")
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
    if mode in TEMPORAL_MODES | MOTION_MODES:
        if reference is None or len(reference) != expected:
            raise IndependentCASVMotionStreamError(
                "CASV/0.7 temporal reference is unavailable"
            )
        compressed = stored
        if mode in MOTION_MODES:
            if len(stored) <= CASV_MOTION_VECTOR.size:
                raise IndependentCASVMotionStreamError(
                    "CASV/0.7 motion payload is truncated"
                )
            compressed = stored[CASV_MOTION_VECTOR.size :]
        residual = _bounded_zlib(compressed, expected)
        if mode in {"TEMPORAL_XOR_ZLIB", "MOTION_XOR_ZLIB"}:
            return bytes(
                left ^ right for left, right in zip(residual, reference, strict=True)
            )
        return bytes(
            (left + right) & 0xFF
            for left, right in zip(residual, reference, strict=True)
        )
    raise IndependentCASVMotionStreamError("CASV/0.7 tile mode is unknown")


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
        motion_radius,
        canonical_bytes,
        canonical_hash,
    ) = values
    pixel_format = ID_PIXEL_FORMATS.get(pixel_format_id)
    if pixel_format is None or flags != 0 or header_size != CASV_MOTION_HEADER.size:
        raise IndependentCASVMotionStreamError("CASV/0.7 header contract differs")
    fields = (
        width,
        height,
        frame_count,
        fps_numerator,
        fps_denominator,
        tile_width,
        strip_height,
        keyframe_interval,
        motion_radius,
    )
    if any(type(value) is not int or value <= 0 for value in fields):
        raise IndependentCASVMotionStreamError("CASV/0.7 dimensions are invalid")
    if width > 16_384 or height > 16_384 or frame_count > 1_000_000:
        raise IndependentCASVMotionStreamError("CASV/0.7 media exceeds bounds")
    if tile_width > width or strip_height > height:
        raise IndependentCASVMotionStreamError("CASV/0.7 tile geometry exceeds media")
    if keyframe_interval > MAX_KEYFRAME_INTERVAL or motion_radius > MAX_MOTION_RADIUS:
        raise IndependentCASVMotionStreamError("CASV/0.7 prediction bounds differ")
    plane_count, bytes_per_pixel = PIXEL_FORMAT_GEOMETRY[pixel_format]
    frame_bytes = width * height * plane_count * bytes_per_pixel
    expected_bytes = frame_bytes * frame_count
    if canonical_bytes != expected_bytes:
        raise IndependentCASVMotionStreamError(
            "CASV/0.7 canonical byte count differs"
        )
    strips_per_plane = (height + strip_height - 1) // strip_height
    records_per_frame = plane_count * strips_per_plane
    expected_records = frame_count * records_per_frame
    if not 1 <= expected_records <= MAX_RECORDS:
        raise IndependentCASVMotionStreamError("CASV/0.7 record count exceeds bounds")
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
        "motion_radius": motion_radius,
        "plane_count": plane_count,
        "bytes_per_pixel": bytes_per_pixel,
        "frame_bytes": frame_bytes,
        "records_per_frame": records_per_frame,
        "record_count": expected_records,
    }


def _iter_expected_records(media: dict[str, Any]) -> Iterator[dict[str, int]]:
    index = 0
    canonical_offset = 0
    plane_bytes = media["width"] * media["height"] * media["bytes_per_pixel"]
    for frame_index in range(media["frame_count"]):
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
                    raise IndependentCASVMotionStreamError(
                        "CASV/0.7 derived record exceeds bounds"
                    )
                yield {
                    "index": index,
                    "frame_index": frame_index,
                    "plane_index": plane_index,
                    "y": y,
                    "height": height,
                    "canonical_offset": canonical_offset,
                    "frame_offset": plane_index * plane_bytes
                    + y * media["width"] * media["bytes_per_pixel"],
                    "canonical_length": canonical_length,
                    "tile_count": tile_count,
                    "is_keyframe": frame_index % media["keyframe_interval"] == 0,
                }
                index += 1
                canonical_offset += canonical_length


def inspect_casv_motion_stream(
    archive: str | Path,
    *,
    compute_archive_sha256: bool = True,
) -> dict[str, Any]:
    path = Path(archive).resolve()
    if not path.is_file():
        raise IndependentCASVMotionStreamError(f"CASV/0.7 archive not found: {path}")
    archive_bytes = path.stat().st_size
    minimum = (
        len(CASV_MOTION_MAGIC)
        + CASV_MOTION_HEADER.size
        + CASV_MOTION_RECORD_HEADER.size
        + CASV_MOTION_TILE_ENTRY.size
        + CASV_MOTION_FOOTER.size
    )
    if archive_bytes < minimum:
        raise IndependentCASVMotionStreamError("CASV/0.7 archive is truncated")

    content_digest = hashlib.sha256()
    records: list[dict[str, Any]] = []
    modes: Counter[str] = Counter()
    vectors: Counter[str] = Counter()
    with path.open("rb") as stream:
        magic = _read_hashed(stream, len(CASV_MOTION_MAGIC), "magic", content_digest)
        if magic != CASV_MOTION_MAGIC:
            raise IndependentCASVMotionStreamError("CASV/0.7 magic differs")
        packed_header = _read_hashed(
            stream, CASV_MOTION_HEADER.size, "header", content_digest
        )
        media = _validate_header(CASV_MOTION_HEADER.unpack(packed_header))
        for expected in _iter_expected_records(media):
            record_offset = stream.tell()
            packed_record = _read_hashed(
                stream,
                CASV_MOTION_RECORD_HEADER.size,
                "record header",
                content_digest,
            )
            record_magic, index, payload_length, canonical_hash = (
                CASV_MOTION_RECORD_HEADER.unpack(packed_record)
            )
            if record_magic != CASV_MOTION_RECORD_MAGIC or index != expected["index"]:
                raise IndependentCASVMotionStreamError("CASV/0.7 record order differs")
            table_length = expected["tile_count"] * CASV_MOTION_TILE_ENTRY.size
            table = _read_hashed(stream, table_length, "tile table", content_digest)
            lengths: list[int] = []
            tile_modes: list[str] = []
            for tile_index in range(expected["tile_count"]):
                offset = tile_index * CASV_MOTION_TILE_ENTRY.size
                mode_id, stored_length = CASV_MOTION_TILE_ENTRY.unpack_from(table, offset)
                mode = ID_MODES.get(mode_id)
                x = tile_index * media["tile_width"]
                width = min(media["tile_width"], media["width"] - x)
                tile_canonical = width * expected["height"] * media["bytes_per_pixel"]
                predictive = mode in TEMPORAL_MODES | MOTION_MODES
                if (
                    mode is None
                    or (expected["is_keyframe"] and predictive)
                    or not 1 <= tile_canonical <= MAX_TILE_CANONICAL_BYTES
                    or not 1 <= stored_length <= MAX_STORED_TILE_BYTES
                    or (mode == "CANONICAL_RAW" and stored_length != tile_canonical)
                    or (mode in MOTION_MODES and stored_length <= CASV_MOTION_VECTOR.size)
                ):
                    raise IndependentCASVMotionStreamError(
                        "CASV/0.7 tile table is invalid"
                    )
                lengths.append(stored_length)
                tile_modes.append(mode)
            if sum(lengths) != payload_length:
                raise IndependentCASVMotionStreamError(
                    "CASV/0.7 payload accounting differs"
                )
            payload_offset = stream.tell()
            if payload_offset + payload_length + CASV_MOTION_FOOTER.size > archive_bytes:
                raise IndependentCASVMotionStreamError("CASV/0.7 record exceeds archive")
            tile_vectors: list[list[int] | None] = []
            for tile_index, (mode, stored_length) in enumerate(
                zip(tile_modes, lengths, strict=True)
            ):
                stored = _read_hashed(
                    stream, stored_length, "tile payload", content_digest
                )
                if mode in MOTION_MODES:
                    dx, dy = CASV_MOTION_VECTOR.unpack_from(stored)
                    x = tile_index * media["tile_width"]
                    width = min(media["tile_width"], media["width"] - x)
                    if (
                        (dx, dy) == (0, 0)
                        or abs(dx) > media["motion_radius"]
                        or abs(dy) > media["motion_radius"]
                        or x + dx < 0
                        or x + dx + width > media["width"]
                        or expected["y"] + dy < 0
                        or expected["y"] + dy + expected["height"] > media["height"]
                    ):
                        raise IndependentCASVMotionStreamError(
                            "CASV/0.7 motion vector is invalid"
                        )
                    tile_vectors.append([dx, dy])
                    vectors[f"{dx},{dy}"] += 1
                else:
                    tile_vectors.append(None)
            modes.update(tile_modes)
            records.append(
                {
                    **expected,
                    "record_offset": record_offset,
                    "payload_offset": payload_offset,
                    "payload_length": payload_length,
                    "stored_length": CASV_MOTION_RECORD_HEADER.size
                    + table_length
                    + payload_length,
                    "canonical_sha256": canonical_hash.hex(),
                    "tile_modes": tile_modes,
                    "tile_stored_lengths": lengths,
                    "tile_motion_vectors": tile_vectors,
                }
            )
        footer = _read_exact(stream, CASV_MOTION_FOOTER.size, "footer")
        if stream.read(1):
            raise IndependentCASVMotionStreamError("CASV/0.7 has trailing bytes")
    footer_magic, receipt_count, receipt_chain_head, claimed_content_hash = (
        CASV_MOTION_FOOTER.unpack(footer)
    )
    if footer_magic != CASV_MOTION_FOOTER_MAGIC:
        raise IndependentCASVMotionStreamError("CASV/0.7 footer magic differs")
    if receipt_count != sum(modes.values()) or receipt_chain_head == bytes(32):
        raise IndependentCASVMotionStreamError("CASV/0.7 authority footer differs")
    if claimed_content_hash != content_digest.digest():
        raise IndependentCASVMotionStreamError("CASV/0.7 content hash differs")
    return {
        "schema": "casulo.casv-motion-inspection/0.7",
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
        "motion_radius": media["motion_radius"],
        "frame_bytes": media["frame_bytes"],
        "record_count": len(records),
        "tile_count": sum(modes.values()),
        "storage_modes": dict(modes),
        "temporal_tile_count": sum(modes[mode] for mode in TEMPORAL_MODES),
        "motion_tile_count": sum(modes[mode] for mode in MOTION_MODES),
        "motion_vectors": dict(vectors),
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
    previous_frame: BinaryIO,
) -> bytes:
    stream.seek(record["payload_offset"])
    payload = _read_exact(stream, record["payload_length"], "record payload")
    cursor = 0
    strip = bytearray(record["canonical_length"])
    strip_row_bytes = media["width"] * media["bytes_per_pixel"]
    for tile_index, (mode, stored_length, vector) in enumerate(
        zip(
            record["tile_modes"],
            record["tile_stored_lengths"],
            record["tile_motion_vectors"],
            strict=True,
        )
    ):
        stored = payload[cursor : cursor + stored_length]
        cursor += stored_length
        x = tile_index * media["tile_width"]
        width = min(media["tile_width"], media["width"] - x)
        reference = None
        if mode in TEMPORAL_MODES:
            reference = _read_reference_tile(
                previous_frame,
                media,
                plane_index=record["plane_index"],
                x=x,
                y=record["y"],
                width=width,
                height=record["height"],
            )
        elif mode in MOTION_MODES:
            if vector is None:
                raise IndependentCASVMotionStreamError(
                    "CASV/0.7 motion vector is unavailable"
                )
            reference = _read_reference_tile(
                previous_frame,
                media,
                plane_index=record["plane_index"],
                x=x + vector[0],
                y=record["y"] + vector[1],
                width=width,
                height=record["height"],
            )
        tile = _decode_tile(
            mode,
            stored,
            width=width,
            height=record["height"],
            bytes_per_pixel=media["bytes_per_pixel"],
            reference=reference,
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
        raise IndependentCASVMotionStreamError(
            "CASV/0.7 tile payload has trailing bytes"
        )
    restored = bytes(strip)
    if hashlib.sha256(restored).hexdigest() != record["canonical_sha256"]:
        raise IndependentCASVMotionStreamError("CASV/0.7 decoded strip hash differs")
    return restored


def iter_casv_motion_canonical(archive: str | Path) -> Iterator[bytes]:
    inspected = inspect_casv_motion_stream(archive, compute_archive_sha256=False)
    media = {
        **inspected["canonical_media"],
        "tile_width": inspected["tile_width"],
        "strip_height": inspected["strip_height"],
        "keyframe_interval": inspected["keyframe_interval"],
        "motion_radius": inspected["motion_radius"],
        "frame_bytes": inspected["frame_bytes"],
        "plane_count": PIXEL_FORMAT_GEOMETRY[
            inspected["canonical_media"]["pixel_format"]
        ][0],
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
                        raise IndependentCASVMotionStreamError(
                            "CASV/0.7 decoded frame spool differs"
                        )
                    previous_frame, current_frame = current_frame, previous_frame
                    current_frame.seek(0)
                    current_frame.truncate(0)
                active_frame = record["frame_index"]
            restored = _decode_record(stream, media, record, previous_frame)
            current_frame.seek(record["frame_offset"])
            current_frame.write(restored)
            yield restored


def verify_casv_motion_stream(archive: str | Path) -> dict[str, Any]:
    inspected = inspect_casv_motion_stream(archive)
    digest = hashlib.sha256()
    canonical_bytes = 0
    maximum_decoded_strip_bytes = 0
    for strip in iter_casv_motion_canonical(archive):
        digest.update(strip)
        canonical_bytes += len(strip)
        maximum_decoded_strip_bytes = max(maximum_decoded_strip_bytes, len(strip))
    media = inspected["canonical_media"]
    if (
        canonical_bytes != media["canonical_bytes"]
        or digest.hexdigest() != media["canonical_sha256"]
    ):
        raise IndependentCASVMotionStreamError(
            "CASV/0.7 canonical media hash differs"
        )
    return {
        "schema": "casulo.casv-independent-verification/0.7",
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
        "motion_tile_count": inspected["motion_tile_count"],
        "motion_vectors": inspected["motion_vectors"],
        "motion_radius": inspected["motion_radius"],
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


def unpack_casv_motion_stream(
    archive: str | Path, output: str | Path
) -> dict[str, Any]:
    output_path = Path(output).resolve()
    if output_path.exists():
        raise IndependentCASVMotionStreamError(f"output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".casv-part")
    digest = hashlib.sha256()
    written = 0
    try:
        with temporary.open("xb") as stream:
            for strip in iter_casv_motion_canonical(archive):
                stream.write(strip)
                digest.update(strip)
                written += len(strip)
            stream.flush()
            os.fsync(stream.fileno())
        media = inspect_casv_motion_stream(archive, compute_archive_sha256=False)[
            "canonical_media"
        ]
        if (
            written != media["canonical_bytes"]
            or digest.hexdigest() != media["canonical_sha256"]
        ):
            raise IndependentCASVMotionStreamError("CASV/0.7 unpack hash differs")
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema": "casulo.casv-motion-unpack/0.7",
        "status": "PASS",
        "output": str(output_path),
        "bytes": written,
        "sha256": digest.hexdigest(),
    }


__all__ = [
    "CASV_MOTION_FOOTER",
    "CASV_MOTION_FOOTER_MAGIC",
    "CASV_MOTION_HEADER",
    "CASV_MOTION_MAGIC",
    "CASV_MOTION_RECORD_HEADER",
    "CASV_MOTION_RECORD_MAGIC",
    "CASV_MOTION_TILE_ENTRY",
    "CASV_MOTION_VECTOR",
    "IndependentCASVMotionStreamError",
    "MODE_IDS",
    "inspect_casv_motion_stream",
    "iter_casv_motion_canonical",
    "unpack_casv_motion_stream",
    "verify_casv_motion_stream",
]
