from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, BinaryIO


CASV_STREAM_MAGIC = b"CASV\x00\x02\r\n"
CASV_STREAM_FOOTER_MAGIC = b"CV2IDX\r\n"
CASV_STREAM_FOOTER = struct.Struct(">8sQ32s")
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_SEGMENTS = 65_536
MAX_SEGMENT_CANONICAL_BYTES = 64 * 1024 * 1024
PIXEL_FORMAT_BYTES = {"RGB8": 3, "YUV444P10LE": 6}


class IndependentCASVStreamError(RuntimeError):
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
        raise IndependentCASVStreamError(f"CASV stream {label} is truncated")
    return payload


def _validate_media(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    media = manifest.get("canonical_media")
    if not isinstance(media, dict):
        raise IndependentCASVStreamError("canonical media declaration is missing")
    fields = ("width", "height", "frame_count", "fps_numerator", "fps_denominator")
    if any(type(media.get(field)) is not int or media[field] <= 0 for field in fields):
        raise IndependentCASVStreamError("canonical media dimensions are invalid")
    if (
        media["width"] > 16_384
        or media["height"] > 16_384
        or media["frame_count"] > 1_000_000
    ):
        raise IndependentCASVStreamError("canonical media dimensions exceed format bounds")
    bytes_per_pixel = PIXEL_FORMAT_BYTES.get(media.get("pixel_format"))
    if bytes_per_pixel is None:
        raise IndependentCASVStreamError("canonical pixel format is unsupported")
    frame_bytes = media["width"] * media["height"] * bytes_per_pixel
    expected_bytes = frame_bytes * media["frame_count"]
    if media.get("canonical_bytes") != expected_bytes:
        raise IndependentCASVStreamError("canonical media byte accounting differs")
    return media, frame_bytes


def inspect_casv_stream(
    archive: str | Path,
    *,
    compute_archive_sha256: bool = True,
) -> dict[str, Any]:
    path = Path(archive).resolve()
    if not path.is_file():
        raise IndependentCASVStreamError(f"CASV stream archive not found: {path}")
    archive_bytes = path.stat().st_size
    minimum = len(CASV_STREAM_MAGIC) + CASV_STREAM_FOOTER.size + 2
    if archive_bytes < minimum:
        raise IndependentCASVStreamError("CASV stream archive is truncated")
    with path.open("rb") as stream:
        if _read_exact(stream, len(CASV_STREAM_MAGIC), "header") != CASV_STREAM_MAGIC:
            raise IndependentCASVStreamError("CASV stream magic or version differs")
        stream.seek(-CASV_STREAM_FOOTER.size, os.SEEK_END)
        footer = _read_exact(stream, CASV_STREAM_FOOTER.size, "footer")
        footer_magic, manifest_length, claimed_manifest_hash = CASV_STREAM_FOOTER.unpack(footer)
        if footer_magic != CASV_STREAM_FOOTER_MAGIC:
            raise IndependentCASVStreamError("CASV stream footer magic differs")
        if not 1 <= manifest_length <= MAX_MANIFEST_BYTES:
            raise IndependentCASVStreamError("CASV stream manifest length is invalid")
        manifest_offset = archive_bytes - CASV_STREAM_FOOTER.size - manifest_length
        if manifest_offset < len(CASV_STREAM_MAGIC):
            raise IndependentCASVStreamError("CASV stream manifest overlaps its header")
        stream.seek(manifest_offset)
        manifest_bytes = _read_exact(stream, manifest_length, "manifest")
    if hashlib.sha256(manifest_bytes).digest() != claimed_manifest_hash:
        raise IndependentCASVStreamError("CASV stream manifest hash differs")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndependentCASVStreamError("CASV stream manifest is not UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or _canonical_json(manifest) != manifest_bytes:
        raise IndependentCASVStreamError("CASV stream manifest is not canonical")
    if manifest.get("schema") != "casulo.casv/0.2":
        raise IndependentCASVStreamError("unsupported CASV stream schema")
    if manifest.get("foreign_bitstreams_embedded") is not False:
        raise IndependentCASVStreamError("CASV stream contains an untrusted foreign bitstream")
    media, frame_bytes = _validate_media(manifest)
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise IndependentCASVStreamError("CASV stream source identity is missing")
    canonical_bytes = source.get("canonical_bytes")
    canonical_sha256 = source.get("canonical_sha256")
    if (
        canonical_bytes != media["canonical_bytes"]
        or not _is_sha256(canonical_sha256)
    ):
        raise IndependentCASVStreamError("CASV stream source identity is invalid")
    segments = manifest.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
        raise IndependentCASVStreamError("CASV stream segment index is invalid")
    expected_stored_offset = len(CASV_STREAM_MAGIC)
    expected_canonical_offset = 0
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("index") != index:
            raise IndependentCASVStreamError("CASV stream segment order differs")
        stored_offset = segment.get("stored_offset")
        stored_length = segment.get("stored_length")
        canonical_offset = segment.get("canonical_offset")
        canonical_length = segment.get("canonical_length")
        storage_mode = segment.get("storage_mode")
        hashes = (segment.get("stored_sha256"), segment.get("canonical_sha256"))
        if (
            stored_offset != expected_stored_offset
            or canonical_offset != expected_canonical_offset
            or type(stored_offset) is not int
            or type(canonical_offset) is not int
            or type(stored_length) is not int
            or stored_length <= 0
            or type(canonical_length) is not int
            or not 1 <= canonical_length <= MAX_SEGMENT_CANONICAL_BYTES
            or stored_length > canonical_length
            or stored_offset + stored_length > manifest_offset
            or storage_mode not in {"CANONICAL_ZLIB", "CANONICAL_RAW"}
            or any(not _is_sha256(value) for value in hashes)
        ):
            raise IndependentCASVStreamError("CASV stream segment bounds are invalid")
        expected_stored_offset += stored_length
        expected_canonical_offset += canonical_length
    if expected_stored_offset != manifest_offset:
        raise IndependentCASVStreamError("CASV stream payload has gaps or trailing bytes")
    if expected_canonical_offset != canonical_bytes:
        raise IndependentCASVStreamError("CASV stream canonical ranges are not contiguous")
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


def _decode_segment(encoded: bytes, segment: Mapping[str, Any]) -> bytes:
    if hashlib.sha256(encoded).hexdigest() != segment["stored_sha256"]:
        raise IndependentCASVStreamError(
            f"CASV stream stored hash differs at segment {segment['index']}"
        )
    expected = segment["canonical_length"]
    if segment["storage_mode"] == "CANONICAL_RAW":
        decoded = encoded
    else:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(encoded, expected + 1)
        if len(decoded) > expected:
            raise IndependentCASVStreamError("CASV stream segment exceeds declared size")
        if decompressor.unconsumed_tail:
            raise IndependentCASVStreamError("CASV stream zlib segment exceeds declared size")
        decoded += decompressor.flush(expected - len(decoded) + 1)
        if len(decoded) > expected:
            raise IndependentCASVStreamError("CASV stream segment exceeds declared size")
        if not decompressor.eof or decompressor.unused_data:
            raise IndependentCASVStreamError("CASV stream zlib segment has trailing data")
    if len(decoded) != expected:
        raise IndependentCASVStreamError("CASV stream decoded segment length differs")
    if hashlib.sha256(decoded).hexdigest() != segment["canonical_sha256"]:
        raise IndependentCASVStreamError(
            f"CASV stream canonical hash differs at segment {segment['index']}"
        )
    return decoded


def iter_casv_stream_segments(
    archive: str | Path,
    *,
    inspected: Mapping[str, Any] | None = None,
) -> Iterator[bytes]:
    state = (
        dict(inspected)
        if inspected is not None
        else inspect_casv_stream(archive, compute_archive_sha256=False)
    )
    path = Path(state["path"])
    manifest = state["manifest"]
    with path.open("rb") as stream:
        for segment in manifest["segments"]:
            stream.seek(segment["stored_offset"])
            encoded = _read_exact(stream, segment["stored_length"], "segment")
            yield _decode_segment(encoded, segment)


def verify_casv_stream(
    archive: str | Path,
    destination: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    inspected = inspect_casv_stream(archive, compute_archive_sha256=False)
    manifest = inspected["manifest"]
    digest = hashlib.sha256()
    archive_digest = hashlib.sha256(CASV_STREAM_MAGIC)
    total = 0
    destination_path: Path | None = None
    temporary: Path | None = None
    output: BinaryIO | None = None
    if destination is not None:
        destination_path = Path(destination).resolve()
        if destination_path.exists() and not overwrite:
            raise IndependentCASVStreamError(f"destination already exists: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination_path.with_name(destination_path.name + ".casv-part")
        if temporary.exists():
            raise IndependentCASVStreamError(f"temporary destination already exists: {temporary}")
        output = temporary.open("xb")
    try:
        with Path(inspected["path"]).open("rb") as source:
            for segment in manifest["segments"]:
                source.seek(segment["stored_offset"])
                encoded = _read_exact(source, segment["stored_length"], "segment")
                archive_digest.update(encoded)
                decoded = _decode_segment(encoded, segment)
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
            raise IndependentCASVStreamError("CASV stream total decoded length differs")
        if digest.hexdigest() != manifest["source"]["canonical_sha256"]:
            raise IndependentCASVStreamError("CASV stream total canonical hash differs")
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
        "schema": "casulo.casv-stream-independent-verification/0.2",
        "status": "PASS",
        "archive": str(inspected["path"]),
        "archive_bytes": inspected["archive_bytes"],
        "archive_sha256": archive_digest.hexdigest(),
        "archive_sha256_computed": True,
        "manifest_sha256": inspected["manifest_sha256"],
        "canonical_media": inspected["canonical_media"],
        "canonical_bytes": total,
        "canonical_sha256": digest.hexdigest(),
        "segment_count": len(manifest["segments"]),
        "storage_modes": modes,
        "destination": str(destination_path) if destination_path is not None else None,
        "foreign_bitstreams_embedded": False,
        "maximum_canonical_segment_bytes": max(
            segment["canonical_length"] for segment in manifest["segments"]
        ),
        "maximum_stored_segment_bytes": max(
            segment["stored_length"] for segment in manifest["segments"]
        ),
        "maximum_explicit_segment_buffers_bytes": max(
            segment["canonical_length"] + segment["stored_length"]
            for segment in manifest["segments"]
        ),
        "process_peak_rss_measured": False,
    }


def extract_casv_stream_frames(
    archive: str | Path,
    destination: str | Path,
    *,
    start_frame: int,
    frame_count: int,
    overwrite: bool = False,
) -> dict[str, Any]:
    inspected = inspect_casv_stream(archive, compute_archive_sha256=False)
    media = inspected["canonical_media"]
    if start_frame < 0 or frame_count <= 0 or start_frame + frame_count > media["frame_count"]:
        raise IndependentCASVStreamError("requested frame range is outside canonical media")
    byte_start = start_frame * inspected["frame_bytes"]
    byte_end = (start_frame + frame_count) * inspected["frame_bytes"]
    destination_path = Path(destination).resolve()
    if destination_path.exists() and not overwrite:
        raise IndependentCASVStreamError(f"destination already exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(destination_path.name + ".casv-part")
    if temporary.exists():
        raise IndependentCASVStreamError(f"temporary destination already exists: {temporary}")
    selected_segments = 0
    digest = hashlib.sha256()
    written = 0
    try:
        with Path(inspected["path"]).open("rb") as source, temporary.open("xb") as output:
            for segment in inspected["manifest"]["segments"]:
                segment_start = segment["canonical_offset"]
                segment_end = segment_start + segment["canonical_length"]
                if segment_end <= byte_start or segment_start >= byte_end:
                    continue
                source.seek(segment["stored_offset"])
                encoded = _read_exact(source, segment["stored_length"], "selected segment")
                decoded = _decode_segment(encoded, segment)
                local_start = max(byte_start, segment_start) - segment_start
                local_end = min(byte_end, segment_end) - segment_start
                selected = decoded[local_start:local_end]
                output.write(selected)
                digest.update(selected)
                written += len(selected)
                selected_segments += 1
            output.flush()
            os.fsync(output.fileno())
        expected = byte_end - byte_start
        if written != expected:
            raise IndependentCASVStreamError("selected frame range byte accounting differs")
        os.replace(temporary, destination_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema": "casulo.casv-stream-range-verification/0.2",
        "status": "PASS_SELECTED_RANGE",
        "integrity_scope": "SELECTED_SEGMENTS_AND_HASH_VERIFIED_INDEX",
        "whole_archive_payload_verified": False,
        "archive_sha256_computed": False,
        "archive_sha256": inspected["archive_sha256"],
        "start_frame": start_frame,
        "frame_count": frame_count,
        "selected_segments": selected_segments,
        "canonical_bytes": written,
        "canonical_sha256": digest.hexdigest(),
        "destination": str(destination_path),
    }


__all__ = [
    "CASV_STREAM_FOOTER",
    "CASV_STREAM_FOOTER_MAGIC",
    "CASV_STREAM_MAGIC",
    "IndependentCASVStreamError",
    "extract_casv_stream_frames",
    "inspect_casv_stream",
    "iter_casv_stream_segments",
    "verify_casv_stream",
]
