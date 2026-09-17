from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, BinaryIO


CASV_PROGRAM_STREAM_MAGIC = b"CASV\x00\x03\r\n"
CASV_PROGRAM_STREAM_FOOTER_MAGIC = b"CV3IDX\r\n"
CASV_PROGRAM_STREAM_FOOTER = struct.Struct(">8sQ32s")
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_SEGMENTS = 65_536
MAX_SEGMENT_CANONICAL_BYTES = 64 * 1024 * 1024
MAX_TRACKS = 32
PIXEL_FORMAT_BYTES = {"RGB8": 3, "YUV444P10LE": 6}
PIXEL_FORMAT_IDS = {"RGB8": 1, "YUV444P10LE": 2}
SEGMENT_RENDERER = "casulo.rectilinear-rgb8-yuv444p10le/0.3"

_BASE_HEADER = struct.Struct(">4sIIIIIIIII")
_MATERIAL = struct.Struct(">HHH")
_BASE_TRACK = struct.Struct(">iiIIII")
_DYNAMICS_HEADER = struct.Struct(">4sI")
_DYNAMICS_TRACK = struct.Struct(">ii")
_PROGRAM_HEADER = struct.Struct(">4sIIII")


class IndependentCASVProgramStreamError(RuntimeError):
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
        raise IndependentCASVProgramStreamError(f"CASV/0.3 {label} is truncated")
    return payload


def _bounded_zlib(payload: bytes, expected_bytes: int) -> bytes:
    decoder = zlib.decompressobj()
    restored = decoder.decompress(payload, expected_bytes + 1)
    if len(restored) > expected_bytes or decoder.unconsumed_tail:
        raise IndependentCASVProgramStreamError("CASV/0.3 zlib output exceeds bounds")
    restored += decoder.flush(expected_bytes - len(restored) + 1)
    if len(restored) > expected_bytes:
        raise IndependentCASVProgramStreamError("CASV/0.3 zlib output exceeds bounds")
    if not decoder.eof or decoder.unused_data or len(restored) != expected_bytes:
        raise IndependentCASVProgramStreamError("CASV/0.3 zlib stream is not exact")
    return restored


def _validate_media(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    media = manifest.get("canonical_media")
    if not isinstance(media, dict):
        raise IndependentCASVProgramStreamError("canonical media declaration is missing")
    fields = ("width", "height", "frame_count", "fps_numerator", "fps_denominator")
    if any(type(media.get(field)) is not int or media[field] <= 0 for field in fields):
        raise IndependentCASVProgramStreamError("canonical media dimensions are invalid")
    if (
        media["width"] > 16_384
        or media["height"] > 16_384
        or media["frame_count"] > 1_000_000
    ):
        raise IndependentCASVProgramStreamError("canonical media exceeds format bounds")
    bytes_per_pixel = PIXEL_FORMAT_BYTES.get(media.get("pixel_format"))
    if bytes_per_pixel is None:
        raise IndependentCASVProgramStreamError("canonical pixel format is unsupported")
    frame_bytes = media["width"] * media["height"] * bytes_per_pixel
    canonical_bytes = frame_bytes * media["frame_count"]
    if media.get("canonical_bytes") != canonical_bytes:
        raise IndependentCASVProgramStreamError("canonical media byte accounting differs")
    return media, frame_bytes


def inspect_casv_program_stream(
    archive: str | Path,
    *,
    compute_archive_sha256: bool = True,
) -> dict[str, Any]:
    path = Path(archive).resolve()
    if not path.is_file():
        raise IndependentCASVProgramStreamError(f"CASV/0.3 archive not found: {path}")
    archive_bytes = path.stat().st_size
    minimum = len(CASV_PROGRAM_STREAM_MAGIC) + CASV_PROGRAM_STREAM_FOOTER.size + 2
    if archive_bytes < minimum:
        raise IndependentCASVProgramStreamError("CASV/0.3 archive is truncated")
    with path.open("rb") as stream:
        if (
            _read_exact(stream, len(CASV_PROGRAM_STREAM_MAGIC), "header")
            != CASV_PROGRAM_STREAM_MAGIC
        ):
            raise IndependentCASVProgramStreamError("CASV/0.3 magic differs")
        stream.seek(-CASV_PROGRAM_STREAM_FOOTER.size, os.SEEK_END)
        footer = _read_exact(stream, CASV_PROGRAM_STREAM_FOOTER.size, "footer")
        footer_magic, manifest_length, manifest_hash = (
            CASV_PROGRAM_STREAM_FOOTER.unpack(footer)
        )
        if footer_magic != CASV_PROGRAM_STREAM_FOOTER_MAGIC:
            raise IndependentCASVProgramStreamError("CASV/0.3 footer magic differs")
        if not 1 <= manifest_length <= MAX_MANIFEST_BYTES:
            raise IndependentCASVProgramStreamError("CASV/0.3 manifest length is invalid")
        manifest_offset = archive_bytes - CASV_PROGRAM_STREAM_FOOTER.size - manifest_length
        if manifest_offset < len(CASV_PROGRAM_STREAM_MAGIC):
            raise IndependentCASVProgramStreamError("CASV/0.3 manifest overlaps header")
        stream.seek(manifest_offset)
        manifest_bytes = _read_exact(stream, manifest_length, "manifest")
    if hashlib.sha256(manifest_bytes).digest() != manifest_hash:
        raise IndependentCASVProgramStreamError("CASV/0.3 manifest hash differs")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndependentCASVProgramStreamError("CASV/0.3 manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or _canonical_json(manifest) != manifest_bytes:
        raise IndependentCASVProgramStreamError("CASV/0.3 manifest is not canonical")
    if manifest.get("schema") != "casulo.casv/0.3":
        raise IndependentCASVProgramStreamError("unsupported CASV/0.3 schema")
    if manifest.get("equivalence_contract") != "EXACT_MEDIA":
        raise IndependentCASVProgramStreamError("CASV/0.3 requires EXACT_MEDIA")
    if manifest.get("foreign_bitstreams_embedded") is not False:
        raise IndependentCASVProgramStreamError("CASV/0.3 embeds a foreign bitstream")
    if manifest.get("audio_included") is not False:
        raise IndependentCASVProgramStreamError("CASV/0.3 audio is not implemented")
    media, frame_bytes = _validate_media(manifest)
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise IndependentCASVProgramStreamError("CASV/0.3 source identity is missing")
    if (
        source.get("canonical_bytes") != media["canonical_bytes"]
        or not _is_sha256(source.get("canonical_sha256"))
    ):
        raise IndependentCASVProgramStreamError("CASV/0.3 source identity is invalid")

    segments = manifest.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
        raise IndependentCASVProgramStreamError("CASV/0.3 segment index is invalid")
    expected_stored_offset = len(CASV_PROGRAM_STREAM_MAGIC)
    expected_canonical_offset = 0
    expected_frame_start = 0
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("index") != index:
            raise IndependentCASVProgramStreamError("CASV/0.3 segment order differs")
        stored_offset = segment.get("stored_offset")
        stored_length = segment.get("stored_length")
        canonical_offset = segment.get("canonical_offset")
        canonical_length = segment.get("canonical_length")
        frame_start = segment.get("frame_start")
        frame_count = segment.get("frame_count")
        mode = segment.get("storage_mode")
        candidates = segment.get("candidate_payload_bytes")
        if not isinstance(candidates, dict):
            raise IndependentCASVProgramStreamError("CASV/0.3 candidate costs are missing")
        selected_key = {
            "GENERATIVE_EXACT": "GENERATIVE_EXACT",
            "CANONICAL_ZLIB": "CANONICAL_ZLIB",
            "CANONICAL_RAW": "CANONICAL_RAW",
        }.get(mode)
        if (
            type(stored_offset) is not int
            or stored_offset != expected_stored_offset
            or type(stored_length) is not int
            or stored_length <= 0
            or stored_offset + stored_length > manifest_offset
            or type(canonical_offset) is not int
            or canonical_offset != expected_canonical_offset
            or type(canonical_length) is not int
            or not 1 <= canonical_length <= MAX_SEGMENT_CANONICAL_BYTES
            or type(frame_start) is not int
            or frame_start != expected_frame_start
            or type(frame_count) is not int
            or frame_count <= 0
            or canonical_offset != frame_start * frame_bytes
            or canonical_length != frame_count * frame_bytes
            or selected_key is None
            or candidates.get(selected_key) != stored_length
            or stored_length > canonical_length
            or not _is_sha256(segment.get("stored_sha256"))
            or not _is_sha256(segment.get("canonical_sha256"))
            or not _is_sha256(segment.get("selection_receipt_hash"))
        ):
            raise IndependentCASVProgramStreamError("CASV/0.3 segment bounds differ")
        available = candidates.get("GENERATIVE_EXACT")
        if available is not None and (type(available) is not int or available <= 0):
            raise IndependentCASVProgramStreamError("CASV/0.3 generative cost is invalid")
        for key in ("CANONICAL_ZLIB", "CANONICAL_RAW"):
            if type(candidates.get(key)) is not int or candidates[key] <= 0:
                raise IndependentCASVProgramStreamError("CASV/0.3 fallback cost is invalid")
        if mode == "GENERATIVE_EXACT":
            generative = segment.get("generative")
            if not isinstance(generative, dict) or generative.get("selected") is not True:
                raise IndependentCASVProgramStreamError("CASV/0.3 generative metadata is absent")
        expected_stored_offset += stored_length
        expected_canonical_offset += canonical_length
        expected_frame_start += frame_count
    if expected_stored_offset != manifest_offset:
        raise IndependentCASVProgramStreamError("CASV/0.3 payload has gaps or trailing bytes")
    if expected_canonical_offset != source["canonical_bytes"]:
        raise IndependentCASVProgramStreamError("CASV/0.3 canonical ranges differ")
    if expected_frame_start != media["frame_count"]:
        raise IndependentCASVProgramStreamError("CASV/0.3 frame ranges differ")
    return {
        "path": str(path),
        "archive_bytes": archive_bytes,
        "archive_sha256": _sha256_file(path) if compute_archive_sha256 else None,
        "archive_sha256_computed": compute_archive_sha256,
        "manifest": manifest,
        "manifest_offset": manifest_offset,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "canonical_media": media,
        "frame_bytes": frame_bytes,
    }


def _resolve_material(
    material: tuple[int, int, int],
    pixel_format: str,
) -> tuple[bytes, bytes, bytes] | bytes:
    if pixel_format == "RGB8":
        return bytes(material)
    return tuple(value.to_bytes(2, "little") for value in material)  # type: ignore[return-value]


def _render_program(
    encoded: bytes,
    segment: Mapping[str, Any],
    media: Mapping[str, Any],
) -> tuple[bytes, int, int, int]:
    if len(encoded) < _PROGRAM_HEADER.size:
        raise IndependentCASVProgramStreamError("CASV/0.3 program header is truncated")
    magic, base_length, dynamics_length, residual_mode, residual_length = (
        _PROGRAM_HEADER.unpack_from(encoded)
    )
    if magic != b"CVG3" or residual_mode not in {0, 1}:
        raise IndependentCASVProgramStreamError("CASV/0.3 program header is invalid")
    if (
        min(base_length, dynamics_length, residual_length) < 0
        or _PROGRAM_HEADER.size + base_length + dynamics_length + residual_length
        != len(encoded)
    ):
        raise IndependentCASVProgramStreamError("CASV/0.3 program lengths differ")
    cursor = _PROGRAM_HEADER.size
    base = encoded[cursor : cursor + base_length]
    cursor += base_length
    dynamics = encoded[cursor : cursor + dynamics_length]
    cursor += dynamics_length
    residual_payload = encoded[cursor:]
    if len(base) < _BASE_HEADER.size:
        raise IndependentCASVProgramStreamError("CASV/0.3 visual base is truncated")
    (
        base_magic,
        pixel_format_id,
        width,
        height,
        frame_count,
        fps_numerator,
        fps_denominator,
        background_index,
        material_count,
        track_count,
    ) = _BASE_HEADER.unpack_from(base)
    pixel_format = media["pixel_format"]
    expected_header = (
        b"CVB3",
        PIXEL_FORMAT_IDS[pixel_format],
        media["width"],
        media["height"],
        segment["frame_count"],
        media["fps_numerator"],
        media["fps_denominator"],
    )
    if (
        (base_magic, pixel_format_id, width, height, frame_count, fps_numerator, fps_denominator)
        != expected_header
        or not 1 <= material_count <= 65_536
        or not 0 <= track_count <= MAX_TRACKS
        or not 0 <= background_index < material_count
    ):
        raise IndependentCASVProgramStreamError("CASV/0.3 visual base header differs")
    expected_base = (
        _BASE_HEADER.size + material_count * _MATERIAL.size + track_count * _BASE_TRACK.size
    )
    if len(base) != expected_base:
        raise IndependentCASVProgramStreamError("CASV/0.3 visual base length differs")
    maximum = 255 if pixel_format == "RGB8" else 1023
    cursor = _BASE_HEADER.size
    materials: list[tuple[int, int, int]] = []
    for _ in range(material_count):
        material = _MATERIAL.unpack_from(base, cursor)
        cursor += _MATERIAL.size
        if any(value > maximum for value in material):
            raise IndependentCASVProgramStreamError("CASV/0.3 material exceeds precision")
        materials.append(material)
    tracks: list[tuple[int, int, int, int, int, int]] = []
    z_indexes: set[int] = set()
    for _ in range(track_count):
        track = _BASE_TRACK.unpack_from(base, cursor)
        cursor += _BASE_TRACK.size
        x0, y0, rect_width, rect_height, material_index, z_index = track
        if (
            rect_width <= 0
            or rect_height <= 0
            or material_index >= material_count
            or z_index in z_indexes
        ):
            raise IndependentCASVProgramStreamError("CASV/0.3 rectangle is invalid")
        z_indexes.add(z_index)
        tracks.append(track)
    if len(dynamics) < _DYNAMICS_HEADER.size:
        raise IndependentCASVProgramStreamError("CASV/0.3 dynamics are truncated")
    dynamics_magic, dynamics_count = _DYNAMICS_HEADER.unpack_from(dynamics)
    if (
        dynamics_magic != b"CVD3"
        or dynamics_count != track_count
        or len(dynamics) != _DYNAMICS_HEADER.size + track_count * _DYNAMICS_TRACK.size
    ):
        raise IndependentCASVProgramStreamError("CASV/0.3 dynamics differ")
    velocities = [
        _DYNAMICS_TRACK.unpack_from(
            dynamics,
            _DYNAMICS_HEADER.size + index * _DYNAMICS_TRACK.size,
        )
        for index in range(track_count)
    ]

    pixels = width * height
    ordered = sorted(zip(tracks, velocities, strict=True), key=lambda item: item[0][5])
    rendered = bytearray()
    for frame_index in range(frame_count):
        if pixel_format == "RGB8":
            background = _resolve_material(materials[background_index], pixel_format)
            assert isinstance(background, bytes)
            frame = bytearray(background * pixels)
            for track, velocity in ordered:
                x0, y0, rect_width, rect_height, material_index, _z = track
                dx, dy = velocity
                x = x0 + frame_index * dx
                y = y0 + frame_index * dy
                if x < 0 or y < 0 or x + rect_width > width or y + rect_height > height:
                    raise IndependentCASVProgramStreamError("CASV/0.3 track leaves frame")
                color = _resolve_material(materials[material_index], pixel_format)
                assert isinstance(color, bytes)
                row = color * rect_width
                for offset_y in range(rect_height):
                    start = ((y + offset_y) * width + x) * 3
                    frame[start : start + len(row)] = row
            rendered.extend(frame)
        else:
            background_samples = _resolve_material(materials[background_index], pixel_format)
            assert isinstance(background_samples, tuple)
            planes = [bytearray(value * pixels) for value in background_samples]
            for track, velocity in ordered:
                x0, y0, rect_width, rect_height, material_index, _z = track
                dx, dy = velocity
                x = x0 + frame_index * dx
                y = y0 + frame_index * dy
                if x < 0 or y < 0 or x + rect_width > width or y + rect_height > height:
                    raise IndependentCASVProgramStreamError("CASV/0.3 track leaves frame")
                samples = _resolve_material(materials[material_index], pixel_format)
                assert isinstance(samples, tuple)
                for plane, value in zip(planes, samples, strict=True):
                    row = value * rect_width
                    for offset_y in range(rect_height):
                        start = ((y + offset_y) * width + x) * 2
                        plane[start : start + len(row)] = row
            rendered.extend(b"".join(planes))

    expected_bytes = segment["canonical_length"]
    generative = segment.get("generative")
    if not isinstance(generative, dict):
        raise IndependentCASVProgramStreamError("CASV/0.3 generative metadata is missing")
    expected_encoding = "ZERO" if residual_mode == 0 else "XOR_ZLIB"
    if (
        generative.get("renderer") != SEGMENT_RENDERER
        or generative.get("base_bytes") != base_length
        or generative.get("dynamics_bytes") != dynamics_length
        or generative.get("residual_encoding") != expected_encoding
        or generative.get("residual_stored_bytes") != residual_length
        or generative.get("residual_logical_bytes") != expected_bytes
        or generative.get("detected_tracks") != track_count
        or generative.get("total_pixels") != pixels * frame_count
    ):
        raise IndependentCASVProgramStreamError("CASV/0.3 generative metadata differs")
    if residual_mode == 0:
        if residual_payload or generative.get("residual_nonzero_bytes") != 0:
            raise IndependentCASVProgramStreamError("CASV/0.3 zero residual differs")
        residual = bytes(expected_bytes)
    else:
        residual = _bounded_zlib(residual_payload, expected_bytes)
        if sum(value != 0 for value in residual) != generative.get(
            "residual_nonzero_bytes"
        ):
            raise IndependentCASVProgramStreamError("CASV/0.3 residual count differs")
    if len(rendered) != expected_bytes:
        raise IndependentCASVProgramStreamError("CASV/0.3 rendered length differs")
    restored = bytes(
        predicted ^ delta
        for predicted, delta in zip(rendered, residual, strict=True)
    )
    exact_pixels = _count_exact_pixels(bytes(rendered), restored, width, height, frame_count, pixel_format)
    if generative.get("exact_predicted_pixels") != exact_pixels:
        raise IndependentCASVProgramStreamError("CASV/0.3 predicted pixel count differs")
    return restored, track_count, int(generative["residual_nonzero_bytes"]), exact_pixels


def _count_exact_pixels(
    rendered: bytes,
    restored: bytes,
    width: int,
    height: int,
    frame_count: int,
    pixel_format: str,
) -> int:
    pixels = width * height
    exact = 0
    if pixel_format == "RGB8":
        return sum(
            rendered[offset : offset + 3] == restored[offset : offset + 3]
            for offset in range(0, len(rendered), 3)
        )
    frame_bytes = pixels * 6
    plane_bytes = pixels * 2
    for frame_index in range(frame_count):
        base = frame_index * frame_bytes
        for pixel in range(pixels):
            offset = pixel * 2
            if all(
                rendered[base + plane * plane_bytes + offset : base + plane * plane_bytes + offset + 2]
                == restored[base + plane * plane_bytes + offset : base + plane * plane_bytes + offset + 2]
                for plane in range(3)
            ):
                exact += 1
    return exact


def _decode_segment(
    encoded: bytes,
    segment: Mapping[str, Any],
    media: Mapping[str, Any],
) -> tuple[bytes, int, int, int]:
    if hashlib.sha256(encoded).hexdigest() != segment["stored_sha256"]:
        raise IndependentCASVProgramStreamError(
            f"CASV/0.3 stored hash differs at segment {segment['index']}"
        )
    expected = segment["canonical_length"]
    mode = segment["storage_mode"]
    if mode == "CANONICAL_RAW":
        decoded = encoded
        tracks = residual_nonzero = exact_pixels = 0
    elif mode == "CANONICAL_ZLIB":
        decoded = _bounded_zlib(encoded, expected)
        tracks = residual_nonzero = exact_pixels = 0
    else:
        decoded, tracks, residual_nonzero, exact_pixels = _render_program(
            encoded,
            segment,
            media,
        )
    if len(decoded) != expected:
        raise IndependentCASVProgramStreamError("CASV/0.3 decoded length differs")
    if hashlib.sha256(decoded).hexdigest() != segment["canonical_sha256"]:
        raise IndependentCASVProgramStreamError(
            f"CASV/0.3 canonical hash differs at segment {segment['index']}"
        )
    return decoded, tracks, residual_nonzero, exact_pixels


def iter_casv_program_stream_segments(
    archive: str | Path,
    *,
    inspected: Mapping[str, Any] | None = None,
) -> Iterator[bytes]:
    state = (
        dict(inspected)
        if inspected is not None
        else inspect_casv_program_stream(archive, compute_archive_sha256=False)
    )
    path = Path(state["path"])
    manifest = state["manifest"]
    media = state["canonical_media"]
    with path.open("rb") as stream:
        for segment in manifest["segments"]:
            stream.seek(segment["stored_offset"])
            encoded = _read_exact(stream, segment["stored_length"], "segment")
            decoded, _tracks, _residual, _exact = _decode_segment(encoded, segment, media)
            yield decoded


def verify_casv_program_stream(
    archive: str | Path,
    destination: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    inspected = inspect_casv_program_stream(archive, compute_archive_sha256=False)
    manifest = inspected["manifest"]
    media = inspected["canonical_media"]
    digest = hashlib.sha256()
    archive_digest = hashlib.sha256(CASV_PROGRAM_STREAM_MAGIC)
    total = 0
    generative_segments = 0
    detected_tracks = 0
    residual_nonzero = 0
    exact_predicted_pixels = 0
    destination_path: Path | None = None
    temporary: Path | None = None
    output: BinaryIO | None = None
    if destination is not None:
        destination_path = Path(destination).resolve()
        if destination_path.exists() and not overwrite:
            raise IndependentCASVProgramStreamError(
                f"destination already exists: {destination_path}"
            )
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination_path.with_name(destination_path.name + ".casv-part")
        if temporary.exists():
            raise IndependentCASVProgramStreamError(
                f"temporary destination already exists: {temporary}"
            )
        output = temporary.open("xb")
    try:
        with Path(inspected["path"]).open("rb") as source:
            for segment in manifest["segments"]:
                source.seek(segment["stored_offset"])
                encoded = _read_exact(source, segment["stored_length"], "segment")
                archive_digest.update(encoded)
                decoded, tracks, residual, exact = _decode_segment(encoded, segment, media)
                if segment["storage_mode"] == "GENERATIVE_EXACT":
                    generative_segments += 1
                    detected_tracks += tracks
                    residual_nonzero += residual
                    exact_predicted_pixels += exact
                digest.update(decoded)
                total += len(decoded)
                if output is not None:
                    output.write(decoded)
            source.seek(inspected["manifest_offset"])
            while block := source.read(1024 * 1024):
                archive_digest.update(block)
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
            output.close()
            output = None
        if total != manifest["source"]["canonical_bytes"]:
            raise IndependentCASVProgramStreamError("CASV/0.3 total length differs")
        if digest.hexdigest() != manifest["source"]["canonical_sha256"]:
            raise IndependentCASVProgramStreamError("CASV/0.3 total hash differs")
        if temporary is not None and destination_path is not None:
            os.replace(temporary, destination_path)
    finally:
        if output is not None:
            output.close()
        if temporary is not None and temporary.exists():
            temporary.unlink()
    modes: dict[str, int] = {}
    for segment in manifest["segments"]:
        mode = segment["storage_mode"]
        modes[mode] = modes.get(mode, 0) + 1
    return {
        "schema": "casulo.casv-program-stream-independent-verification/0.3",
        "status": "PASS",
        "archive": str(inspected["path"]),
        "archive_bytes": inspected["archive_bytes"],
        "archive_sha256": archive_digest.hexdigest(),
        "archive_sha256_computed": True,
        "manifest_sha256": inspected["manifest_sha256"],
        "canonical_media": media,
        "canonical_bytes": total,
        "canonical_sha256": digest.hexdigest(),
        "segment_count": len(manifest["segments"]),
        "storage_modes": modes,
        "generative_segments": generative_segments,
        "detected_tracks": detected_tracks,
        "residual_nonzero_bytes": residual_nonzero,
        "exact_predicted_pixels": exact_predicted_pixels,
        "destination": str(destination_path) if destination_path is not None else None,
        "foreign_bitstreams_embedded": False,
        "audio_included": False,
        "maximum_canonical_segment_bytes": max(
            segment["canonical_length"] for segment in manifest["segments"]
        ),
        "maximum_stored_segment_bytes": max(
            segment["stored_length"] for segment in manifest["segments"]
        ),
        "process_peak_rss_measured": False,
    }


def extract_casv_program_stream_frames(
    archive: str | Path,
    destination: str | Path,
    *,
    start_frame: int,
    frame_count: int,
    overwrite: bool = False,
) -> dict[str, Any]:
    inspected = inspect_casv_program_stream(archive, compute_archive_sha256=False)
    media = inspected["canonical_media"]
    if start_frame < 0 or frame_count <= 0 or start_frame + frame_count > media["frame_count"]:
        raise IndependentCASVProgramStreamError("requested frame range is outside media")
    byte_start = start_frame * inspected["frame_bytes"]
    byte_end = (start_frame + frame_count) * inspected["frame_bytes"]
    destination_path = Path(destination).resolve()
    if destination_path.exists() and not overwrite:
        raise IndependentCASVProgramStreamError(f"destination already exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(destination_path.name + ".casv-part")
    if temporary.exists():
        raise IndependentCASVProgramStreamError(f"temporary already exists: {temporary}")
    digest = hashlib.sha256()
    written = 0
    selected_segments = 0
    try:
        with Path(inspected["path"]).open("rb") as source, temporary.open("xb") as output:
            for segment in inspected["manifest"]["segments"]:
                segment_start = segment["canonical_offset"]
                segment_end = segment_start + segment["canonical_length"]
                if segment_end <= byte_start or segment_start >= byte_end:
                    continue
                source.seek(segment["stored_offset"])
                encoded = _read_exact(source, segment["stored_length"], "selected segment")
                decoded, _tracks, _residual, _exact = _decode_segment(
                    encoded,
                    segment,
                    media,
                )
                local_start = max(byte_start, segment_start) - segment_start
                local_end = min(byte_end, segment_end) - segment_start
                selected = decoded[local_start:local_end]
                output.write(selected)
                digest.update(selected)
                written += len(selected)
                selected_segments += 1
            output.flush()
            os.fsync(output.fileno())
        if written != byte_end - byte_start:
            raise IndependentCASVProgramStreamError("selected frame byte accounting differs")
        os.replace(temporary, destination_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema": "casulo.casv-program-stream-range-verification/0.3",
        "status": "PASS_SELECTED_RANGE",
        "integrity_scope": "SELECTED_SEGMENTS_AND_HASH_VERIFIED_INDEX",
        "whole_archive_payload_verified": False,
        "archive_sha256_computed": False,
        "start_frame": start_frame,
        "frame_count": frame_count,
        "selected_segments": selected_segments,
        "canonical_bytes": written,
        "canonical_sha256": digest.hexdigest(),
        "destination": str(destination_path),
    }


__all__ = [
    "CASV_PROGRAM_STREAM_FOOTER",
    "CASV_PROGRAM_STREAM_FOOTER_MAGIC",
    "CASV_PROGRAM_STREAM_MAGIC",
    "IndependentCASVProgramStreamError",
    "extract_casv_program_stream_frames",
    "inspect_casv_program_stream",
    "iter_casv_program_stream_segments",
    "verify_casv_program_stream",
]
