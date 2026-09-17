from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from pathlib import Path
from typing import Any, Mapping


CASV_MAGIC = b"CASV\x00\x01\r\n"
CASV_HEADER = struct.Struct(">8sQ")
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_CANONICAL_BYTES = 256 * 1024 * 1024
PIXEL_FORMAT_BYTES = {"RGB8": 3, "YUV444P10LE": 6}
_BASE_HEADER = struct.Struct(">4sIIIIIIIII")
_MATERIAL = struct.Struct(">BBBB")
_BASE_TRACK = struct.Struct(">iiIIII")
_DYNAMICS_HEADER = struct.Struct(">4sI")
_DYNAMICS_TRACK = struct.Struct(">ii")


class IndependentCASVError(RuntimeError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _bounded_zlib(payload: bytes, expected_bytes: int) -> bytes:
    decoder = zlib.decompressobj()
    restored = decoder.decompress(payload, expected_bytes + 1)
    if len(restored) > expected_bytes:
        raise IndependentCASVError("zlib section exceeds declared canonical size")
    restored += decoder.flush()
    if decoder.unused_data or decoder.unconsumed_tail:
        raise IndependentCASVError("zlib section has trailing or unconsumed data")
    if len(restored) != expected_bytes:
        raise IndependentCASVError("zlib section length differs from declaration")
    return restored


def _parse_archive(path: Path) -> tuple[dict[str, Any], dict[str, bytes], str, int]:
    if not path.is_file():
        raise IndependentCASVError(f"CASV archive not found: {path}")
    archive_size = path.stat().st_size
    if archive_size < CASV_HEADER.size:
        raise IndependentCASVError("CASV archive is truncated")
    with path.open("rb") as stream:
        header = stream.read(CASV_HEADER.size)
        magic, manifest_length = CASV_HEADER.unpack(header)
        if magic != CASV_MAGIC:
            raise IndependentCASVError("CASV magic or version differs")
        if not 1 <= manifest_length <= MAX_MANIFEST_BYTES:
            raise IndependentCASVError("CASV manifest length is invalid")
        manifest_bytes = stream.read(manifest_length)
        if len(manifest_bytes) != manifest_length:
            raise IndependentCASVError("CASV manifest is truncated")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IndependentCASVError("CASV manifest is not canonical UTF-8 JSON") from exc
        if not isinstance(manifest, dict):
            raise IndependentCASVError("CASV manifest root must be an object")
        if _canonical_json(manifest) != manifest_bytes:
            raise IndependentCASVError("CASV manifest is not canonical")
        payload = stream.read()
    if manifest.get("schema") != "casulo.casv/0.1":
        raise IndependentCASVError("unsupported CASV manifest schema")
    if manifest.get("foreign_bitstreams_embedded") is not False:
        raise IndependentCASVError("CASV archive does not prove a native canonical payload")
    section_specs = manifest.get("sections")
    if not isinstance(section_specs, list) or len(section_specs) > 16:
        raise IndependentCASVError("CASV section table is invalid")
    sections: dict[str, bytes] = {}
    expected_offset = 0
    for section in section_specs:
        if not isinstance(section, dict):
            raise IndependentCASVError("CASV section entry is invalid")
        name = section.get("name")
        offset = section.get("offset")
        length = section.get("length")
        claimed_hash = section.get("sha256")
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or name in sections
        ):
            raise IndependentCASVError("CASV section name is invalid")
        if not isinstance(offset, int) or not isinstance(length, int):
            raise IndependentCASVError("CASV section bounds are invalid")
        if offset != expected_offset or length < 0 or offset + length > len(payload):
            raise IndependentCASVError("CASV sections are not contiguous and bounded")
        body = payload[offset : offset + length]
        if not isinstance(claimed_hash, str) or _sha256(body) != claimed_hash:
            raise IndependentCASVError(f"CASV section hash differs: {name}")
        sections[name] = body
        expected_offset += length
    if expected_offset != len(payload):
        raise IndependentCASVError("CASV archive has unmanifested trailing bytes")
    return manifest, sections, _sha256(path.read_bytes()), archive_size


def _render_generative(
    manifest: Mapping[str, Any], sections: Mapping[str, bytes]
) -> tuple[bytes, int, int]:
    base = sections.get("base")
    dynamics = sections.get("dynamics")
    if base is None or dynamics is None or len(base) < _BASE_HEADER.size:
        raise IndependentCASVError("generative CASV sections are incomplete")
    (
        magic,
        width,
        height,
        frame_count,
        fps_numerator,
        fps_denominator,
        background_index,
        material_count,
        track_count,
        ambient,
    ) = _BASE_HEADER.unpack_from(base)
    if magic != b"CVB1" or not all(
        isinstance(value, int) and value > 0
        for value in (width, height, frame_count, fps_numerator, fps_denominator)
    ):
        raise IndependentCASVError("visual base header is invalid")
    expected_bytes = width * height * frame_count * 3
    if expected_bytes <= 0 or expected_bytes > MAX_CANONICAL_BYTES:
        raise IndependentCASVError("canonical media exceeds CASV/0.1 decoder bounds")
    if not 1 <= material_count <= 65_536 or track_count > 1_000_000:
        raise IndependentCASVError("visual base counts are invalid")
    expected_base = _BASE_HEADER.size + material_count * _MATERIAL.size + track_count * _BASE_TRACK.size
    if len(base) != expected_base or not 0 <= background_index < material_count or ambient > 255:
        raise IndependentCASVError("visual base length or indexes differ")

    offset = _BASE_HEADER.size
    materials: list[tuple[int, int, int, int]] = []
    for _ in range(material_count):
        materials.append(_MATERIAL.unpack_from(base, offset))
        offset += _MATERIAL.size
    base_tracks: list[tuple[int, int, int, int, int, int]] = []
    z_values: set[int] = set()
    for _ in range(track_count):
        item = _BASE_TRACK.unpack_from(base, offset)
        offset += _BASE_TRACK.size
        x0, y0, rect_width, rect_height, material_index, z_index = item
        if rect_width <= 0 or rect_height <= 0 or material_index >= material_count or z_index in z_values:
            raise IndependentCASVError("visual base rectangle is invalid")
        z_values.add(z_index)
        base_tracks.append(item)

    if len(dynamics) < _DYNAMICS_HEADER.size:
        raise IndependentCASVError("temporal dynamics header is truncated")
    dynamics_magic, dynamics_count = _DYNAMICS_HEADER.unpack_from(dynamics)
    expected_dynamics = _DYNAMICS_HEADER.size + dynamics_count * _DYNAMICS_TRACK.size
    if dynamics_magic != b"CVD1" or dynamics_count != track_count or len(dynamics) != expected_dynamics:
        raise IndependentCASVError("temporal dynamics count or length differs")
    velocities = [
        _DYNAMICS_TRACK.unpack_from(dynamics, _DYNAMICS_HEADER.size + index * _DYNAMICS_TRACK.size)
        for index in range(track_count)
    ]

    declared = manifest.get("canonical_media")
    expected_declared = {
        "canonical_bytes": expected_bytes,
        "fps_denominator": fps_denominator,
        "fps_numerator": fps_numerator,
        "frame_count": frame_count,
        "height": height,
        "pixel_format": "RGB8",
        "width": width,
    }
    if declared != expected_declared:
        raise IndependentCASVError("canonical media declaration differs from visual program")

    def resolve(material: tuple[int, int, int, int]) -> bytes:
        red, green, blue, brightness = material
        return bytes(
            (((channel * brightness + 127) // 255 * ambient + 127) // 255)
            for channel in (red, green, blue)
        )

    background = resolve(materials[background_index])
    rendered = bytearray()
    indexed_tracks = sorted(
        zip(base_tracks, velocities, strict=True), key=lambda pair: pair[0][5]
    )
    for frame_index in range(frame_count):
        frame = bytearray(background * (width * height))
        for track, velocity in indexed_tracks:
            x0, y0, rect_width, rect_height, material_index, _z_index = track
            dx, dy = velocity
            x = x0 + frame_index * dx
            y = y0 + frame_index * dy
            if x < 0 or y < 0 or x + rect_width > width or y + rect_height > height:
                raise IndependentCASVError("visual track leaves the canonical frame")
            row = resolve(materials[material_index]) * rect_width
            for offset_y in range(rect_height):
                start = ((y + offset_y) * width + x) * 3
                frame[start : start + len(row)] = row
        rendered.extend(frame)

    residual_spec = manifest.get("residual")
    if not isinstance(residual_spec, dict):
        raise IndependentCASVError("CASV residual declaration is missing")
    residual_encoding = residual_spec.get("encoding")
    if residual_encoding == "ZERO":
        if "residual" in sections or residual_spec.get("nonzero_bytes") != 0:
            raise IndependentCASVError("zero residual declaration differs from sections")
        residual = bytes(expected_bytes)
    elif residual_encoding == "XOR_ZLIB":
        encoded_residual = sections.get("residual")
        if encoded_residual is None:
            raise IndependentCASVError("encoded residual section is missing")
        residual = _bounded_zlib(encoded_residual, expected_bytes)
        if sum(value != 0 for value in residual) != residual_spec.get("nonzero_bytes"):
            raise IndependentCASVError("residual non-zero accounting differs")
    else:
        raise IndependentCASVError("unsupported CASV residual encoding")
    restored = bytes(predicted ^ delta for predicted, delta in zip(rendered, residual, strict=True))
    return restored, track_count, sum(value != 0 for value in residual)


def _validated_canonical_media(
    manifest: Mapping[str, Any], source_bytes: int
) -> dict[str, Any]:
    media = manifest.get("canonical_media")
    if not isinstance(media, dict):
        raise IndependentCASVError("CASV canonical media declaration is missing")
    fields = ("width", "height", "frame_count", "fps_numerator", "fps_denominator")
    if any(not isinstance(media.get(field), int) or media[field] <= 0 for field in fields):
        raise IndependentCASVError("CASV canonical media dimensions are invalid")
    pixel_format = media.get("pixel_format")
    bytes_per_pixel = PIXEL_FORMAT_BYTES.get(pixel_format)
    if bytes_per_pixel is None:
        raise IndependentCASVError("CASV canonical pixel format is unsupported")
    expected_bytes = (
        media["width"] * media["height"] * media["frame_count"] * bytes_per_pixel
    )
    if (
        expected_bytes != source_bytes
        or media.get("canonical_bytes") != expected_bytes
        or expected_bytes > MAX_CANONICAL_BYTES
    ):
        raise IndependentCASVError("CASV canonical media byte accounting differs")
    return media


def _decode_casv(archive: str | Path) -> tuple[dict[str, Any], bytes]:
    archive_path = Path(archive).resolve()
    manifest, sections, archive_hash, archive_size = _parse_archive(archive_path)
    if manifest.get("equivalence_contract") != "EXACT_MEDIA":
        raise IndependentCASVError("CASV/0.1 decoder accepts only EXACT_MEDIA")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise IndependentCASVError("CASV canonical source declaration is missing")
    source_bytes = source.get("canonical_bytes")
    source_hash = source.get("canonical_sha256")
    if (
        not isinstance(source_bytes, int)
        or not 1 <= source_bytes <= MAX_CANONICAL_BYTES
        or not isinstance(source_hash, str)
        or len(source_hash) != 64
    ):
        raise IndependentCASVError("CASV canonical source identity is invalid")
    canonical_media = _validated_canonical_media(manifest, source_bytes)

    mode = manifest.get("storage_mode")
    track_count = 0
    residual_nonzero = 0
    if mode == "GENERATIVE_EXACT":
        restored, track_count, residual_nonzero = _render_generative(manifest, sections)
    elif mode == "CANONICAL_ZLIB":
        payload = sections.get("canonical")
        if payload is None or set(sections) != {"canonical"}:
            raise IndependentCASVError("canonical zlib section set differs")
        restored = _bounded_zlib(payload, source_bytes)
    elif mode == "CANONICAL_RAW":
        restored = sections.get("canonical", b"")
        if set(sections) != {"canonical"} or len(restored) != source_bytes:
            raise IndependentCASVError("canonical raw section length differs")
    else:
        raise IndependentCASVError("unsupported CASV storage mode")

    if len(restored) != source_bytes or _sha256(restored) != source_hash:
        raise IndependentCASVError("reconstructed canonical media identity differs")
    report = {
        "schema": "casulo.casv-independent-verification/0.1",
        "status": "PASS",
        "archive": str(archive_path),
        "archive_bytes": archive_size,
        "archive_sha256": archive_hash,
        "storage_mode": mode,
        "equivalence_contract": "EXACT_MEDIA",
        "canonical_media": canonical_media,
        "canonical_bytes": len(restored),
        "canonical_sha256": source_hash,
        "detected_tracks": track_count,
        "residual_nonzero_bytes": residual_nonzero,
        "destination": None,
        "foreign_bitstreams_embedded": False,
    }
    return report, restored


def decode_casv_canonical_bytes(
    archive: str | Path,
) -> tuple[dict[str, Any], bytes]:
    """Return verified canonical bytes for bounded consumers such as the reference player."""

    return _decode_casv((archive))


def reconstruct_casv_independently(
    archive: str | Path,
    destination: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Decode CASV using only the format contract and Python's standard library."""

    report, restored = _decode_casv(archive)
    destination_path: Path | None = None
    if destination is not None:
        destination_path = Path(destination).resolve()
        if destination_path.exists() and not overwrite:
            raise IndependentCASVError(f"destination already exists: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination_path.with_name(destination_path.name + ".casv-part")
        if temporary.exists():
            raise IndependentCASVError(f"temporary destination already exists: {temporary}")
        try:
            temporary.write_bytes(restored)
            os.replace(temporary, destination_path)
        finally:
            if temporary.exists():
                temporary.unlink()
    return {
        **report,
        "destination": str(destination_path) if destination_path is not None else None,
    }


__all__ = [
    "IndependentCASVError",
    "decode_casv_canonical_bytes",
    "reconstruct_casv_independently",
]
