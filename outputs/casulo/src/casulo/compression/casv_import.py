from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from .casv_ir import CASV_PIXEL_FORMAT_BYTES, CanonicalVideoSpec
from .tooling import resolve_tool


MAX_IMPORT_BYTES = 64 * 1024 * 1024


class CASVImportError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ImportedCanonicalVideo:
    frames: bytes
    spec: CanonicalVideoSpec
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CanonicalVideoDecodePlan:
    source_path: Path
    ffmpeg_path: Path
    ffprobe_path: Path
    spec: CanonicalVideoSpec
    command: tuple[str, ...]
    provenance: dict[str, Any]


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _tool_hash(path: Path) -> str:
    return _hash_file(path)


def _version(path: Path) -> str:
    completed = subprocess.run(
        [str(path), "-version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        shell=False,
    )
    lines = (completed.stdout or completed.stderr).splitlines()
    return lines[0].strip() if lines else "unknown"


def _probe(source: Path, ffprobe: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=index,codec_name,width,height,avg_frame_rate,r_frame_rate,pix_fmt,"
            "color_range,color_space,color_transfer,color_primaries,chroma_location,"
            "sample_aspect_ratio,field_order",
            "-of",
            "json",
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        shell=False,
    )
    if completed.returncode != 0:
        raise CASVImportError(f"ffprobe failed: {completed.stderr.strip()}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CASVImportError("ffprobe did not return valid JSON") from exc
    streams = payload.get("streams")
    if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict):
        raise CASVImportError("source needs exactly one selected video stream")
    return streams[0]


def _frame_rate(stream: dict[str, Any]) -> Fraction:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        if isinstance(value, str) and value not in {"0/0", "N/A"}:
            try:
                rate = Fraction(value)
            except (ValueError, ZeroDivisionError):
                continue
            if rate > 0:
                return rate
    raise CASVImportError("source video has no valid frame rate")


def prepare_video_decode_plan(
    source: str | Path,
    *,
    frame_count: int,
    crop: tuple[int, int, int, int] | None = None,
    preserve_source_pixel_format: bool = False,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    expected_source_sha256: str | None = None,
    maximum_canonical_bytes: int | None = None,
) -> CanonicalVideoDecodePlan:
    """Freeze a video-only FFmpeg stdout plan before archive mutation."""

    source_path = Path(source).resolve(strict=True)
    if not source_path.is_file() or source_path.stat().st_size <= 0:
        raise CASVImportError("source video is missing or empty")
    if not 1 <= frame_count <= 1_000_000:
        raise CASVImportError("requested frame count is outside the CASV bounds")
    ffmpeg = Path(ffmpeg_path).resolve(strict=True) if ffmpeg_path else resolve_tool("ffmpeg")
    ffprobe = Path(ffprobe_path).resolve(strict=True) if ffprobe_path else resolve_tool("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise CASVImportError("ffmpeg and ffprobe are required for the source adapter")

    stream = _probe(source_path, ffprobe)
    try:
        source_width = int(stream["width"])
        source_height = int(stream["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CASVImportError("ffprobe did not expose valid video dimensions") from exc
    source_pixel_format = stream.get("pix_fmt")
    if preserve_source_pixel_format:
        format_mapping = {
            "rgb24": ("RGB8", "rgb24"),
            "yuv444p10le": ("YUV444P10LE", "yuv444p10le"),
        }
        selected = format_mapping.get(source_pixel_format)
        if selected is None:
            raise CASVImportError(
                f"source pixel format is not yet preservation-safe: {source_pixel_format!r}"
            )
        canonical_pixel_format, ffmpeg_pixel_format = selected
    else:
        canonical_pixel_format, ffmpeg_pixel_format = "RGB8", "rgb24"

    output_width, output_height = source_width, source_height
    filter_argument: str | None = None
    derivation = "SOURCE_DECODE_PREFIX"
    if crop is not None:
        x, y, width, height = crop
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > source_width
            or y + height > source_height
        ):
            raise CASVImportError("crop is outside the source frame")
        output_width, output_height = width, height
        filter_argument = f"crop={width}:{height}:{x}:{y}"
        derivation = "DERIVED_SPATIAL_CROP_PROBE"

    rate = _frame_rate(stream)
    spec = CanonicalVideoSpec(
        width=output_width,
        height=output_height,
        frame_count=frame_count,
        fps_numerator=rate.numerator,
        fps_denominator=rate.denominator,
        pixel_format=canonical_pixel_format,
    )
    spec.validate(enforce_memory_limit=False)
    if maximum_canonical_bytes is not None and spec.expected_bytes > maximum_canonical_bytes:
        raise CASVImportError("planned canonical stream exceeds its configured byte bound")

    source_hash = _hash_file(source_path)
    if expected_source_sha256 is not None and source_hash.lower() != expected_source_sha256.lower():
        raise CASVImportError("source SHA-256 differs from the frozen identity")
    command = [
        str(ffmpeg),
        "-nostdin",
        "-v",
        "error",
        "-noautorotate",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-frames:v",
        str(frame_count),
    ]
    if filter_argument is not None:
        command.extend(["-vf", filter_argument])
    command.extend(
        [
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            ffmpeg_pixel_format,
            "pipe:1",
        ]
    )
    command_template = list(command)
    command_template[0] = "ffmpeg"
    command_template[6] = "<SOURCE>"
    provenance = {
        "schema": "casulo.casv-source-adapter/0.2",
        "kind": (
            "ffmpeg-native-sample-stream-plan"
            if preserve_source_pixel_format
            else "ffmpeg-rgb8-stream-plan"
        ),
        "transport": "FFMPEG_STDOUT_PIPE",
        "derivation": derivation,
        "source_label": source_path.name,
        "source_bytes": source_path.stat().st_size,
        "source_sha256": source_hash,
        "source_video": {
            "codec_name": stream.get("codec_name"),
            "pixel_format": source_pixel_format,
            "width": source_width,
            "height": source_height,
            "frame_rate": f"{rate.numerator}/{rate.denominator}",
            "color_range": stream.get("color_range"),
            "color_space": stream.get("color_space"),
            "color_transfer": stream.get("color_transfer"),
            "color_primaries": stream.get("color_primaries"),
            "chroma_location": stream.get("chroma_location"),
            "sample_aspect_ratio": stream.get("sample_aspect_ratio"),
            "field_order": stream.get("field_order"),
        },
        "canonicalization": {
            "contract": (
                "EXACT_FFMPEG_DECODED_NATIVE_SAMPLE_STREAM"
                if preserve_source_pixel_format
                else "EXACT_AFTER_RGB8_CANONICALIZATION"
            ),
            "output_pixel_format": canonical_pixel_format,
            "source_container_identity_preserved": False,
            "source_native_sample_identity_claimed": preserve_source_pixel_format,
            "transform": (
                "FFMPEG_DECODE_TO_DECLARED_NATIVE_RAW_PIXEL_FORMAT"
                if preserve_source_pixel_format
                else "FFMPEG_DECODE_AND_RGB24_CONVERSION"
            ),
        },
        "crop": (
            None
            if crop is None
            else {"x": crop[0], "y": crop[1], "width": crop[2], "height": crop[3]}
        ),
        "requested_frames": frame_count,
        "expected_canonical_bytes": spec.expected_bytes,
        "ffmpeg": {"version": _version(ffmpeg), "sha256": _tool_hash(ffmpeg)},
        "ffprobe": {"version": _version(ffprobe), "sha256": _tool_hash(ffprobe)},
        "command_template": command_template,
        "source_bitstream_embedded": False,
        "raw_intermediate_created": False,
        "audio_included": False,
    }
    return CanonicalVideoDecodePlan(
        source_path=source_path,
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        spec=spec,
        command=tuple(command),
        provenance=provenance,
    )


def import_video_to_canonical(
    source: str | Path,
    *,
    max_frames: int,
    crop: tuple[int, int, int, int] | None = None,
    preserve_source_pixel_format: bool = False,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    expected_source_sha256: str | None = None,
    timeout_seconds: int = 120,
) -> ImportedCanonicalVideo:
    """Decode a bounded prefix without retaining source bitstream bytes."""

    source_path = Path(source).resolve(strict=True)
    if not source_path.is_file() or source_path.stat().st_size <= 0:
        raise CASVImportError("source video is missing or empty")
    if not 1 <= max_frames <= 64:
        raise CASVImportError("CASV bounded import requires 1 to 64 frames")
    ffmpeg = Path(ffmpeg_path).resolve(strict=True) if ffmpeg_path else resolve_tool("ffmpeg")
    ffprobe = Path(ffprobe_path).resolve(strict=True) if ffprobe_path else resolve_tool("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise CASVImportError("ffmpeg and ffprobe are required for the source adapter")
    stream = _probe(source_path, ffprobe)
    try:
        source_width = int(stream["width"])
        source_height = int(stream["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CASVImportError("ffprobe did not expose valid video dimensions") from exc
    source_pixel_format = stream.get("pix_fmt")
    if preserve_source_pixel_format:
        format_mapping = {
            "rgb24": ("RGB8", "rgb24"),
            "yuv444p10le": ("YUV444P10LE", "yuv444p10le"),
        }
        selected = format_mapping.get(source_pixel_format)
        if selected is None:
            raise CASVImportError(
                f"source pixel format is not yet preservation-safe: {source_pixel_format!r}"
            )
        canonical_pixel_format, ffmpeg_pixel_format = selected
    else:
        canonical_pixel_format, ffmpeg_pixel_format = "RGB8", "rgb24"

    output_width, output_height = source_width, source_height
    filter_argument: str | None = None
    derivation = "SOURCE_DECODE_PREFIX"
    if crop is not None:
        x, y, width, height = crop
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > source_width
            or y + height > source_height
        ):
            raise CASVImportError("crop is outside the source frame")
        output_width, output_height = width, height
        filter_argument = f"crop={width}:{height}:{x}:{y}"
        derivation = "DERIVED_SPATIAL_CROP_PROBE"
    projected_bytes = (
        output_width
        * output_height
        * CASV_PIXEL_FORMAT_BYTES[canonical_pixel_format]
        * max_frames
    )
    if projected_bytes > MAX_IMPORT_BYTES:
        raise CASVImportError(
            "bounded importer would exceed 64 MiB; CV1 streaming segments are not implemented"
        )

    source_hash = _hash_file(source_path)
    if expected_source_sha256 is not None and source_hash.lower() != expected_source_sha256.lower():
        raise CASVImportError("source SHA-256 differs from the frozen identity")
    command = [
        str(ffmpeg),
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-frames:v",
        str(max_frames),
    ]
    if filter_argument is not None:
        command.extend(["-vf", filter_argument])
    command.extend(["-f", "rawvideo", "-pix_fmt", ffmpeg_pixel_format, "pipe:1"])
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise CASVImportError("ffmpeg canonical decode exceeded the bounded timeout") from exc
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise CASVImportError(f"ffmpeg canonical decode failed: {message}")
    frame_bytes = output_width * output_height * CASV_PIXEL_FORMAT_BYTES[canonical_pixel_format]
    if not stdout or len(stdout) % frame_bytes:
        raise CASVImportError("ffmpeg output is empty or not frame aligned")
    actual_frames = len(stdout) // frame_bytes
    if actual_frames > max_frames:
        raise CASVImportError("ffmpeg emitted more frames than requested")
    rate = _frame_rate(stream)
    spec = CanonicalVideoSpec(
        width=output_width,
        height=output_height,
        frame_count=actual_frames,
        fps_numerator=rate.numerator,
        fps_denominator=rate.denominator,
        pixel_format=canonical_pixel_format,
    )
    spec.validate()
    return ImportedCanonicalVideo(
        frames=stdout,
        spec=spec,
        provenance={
            "schema": "casulo.casv-source-adapter/0.1",
            "kind": (
                "ffmpeg-native-sample-bounded-import"
                if preserve_source_pixel_format
                else "ffmpeg-rgb8-bounded-import"
            ),
            "derivation": derivation,
            "source_label": source_path.name,
            "source_bytes": source_path.stat().st_size,
            "source_sha256": source_hash,
            "source_video": {
                "codec_name": stream.get("codec_name"),
                "pixel_format": source_pixel_format,
                "width": source_width,
                "height": source_height,
                "frame_rate": f"{rate.numerator}/{rate.denominator}",
                "color_range": stream.get("color_range"),
                "color_space": stream.get("color_space"),
                "color_transfer": stream.get("color_transfer"),
                "color_primaries": stream.get("color_primaries"),
                "chroma_location": stream.get("chroma_location"),
                "sample_aspect_ratio": stream.get("sample_aspect_ratio"),
                "field_order": stream.get("field_order"),
            },
            "canonicalization": {
                "contract": (
                    "EXACT_FFMPEG_DECODED_NATIVE_SAMPLE_STREAM"
                    if preserve_source_pixel_format
                    else "EXACT_AFTER_RGB8_CANONICALIZATION"
                ),
                "output_pixel_format": canonical_pixel_format,
                "source_container_identity_preserved": False,
                "source_native_sample_identity_claimed": preserve_source_pixel_format,
                "transform": (
                    "FFMPEG_DECODE_TO_DECLARED_NATIVE_RAW_PIXEL_FORMAT"
                    if preserve_source_pixel_format
                    else "FFMPEG_DECODE_AND_RGB24_CONVERSION"
                ),
            },
            "crop": (
                None
                if crop is None
                else {"x": crop[0], "y": crop[1], "width": crop[2], "height": crop[3]}
            ),
            "requested_frames": max_frames,
            "decoded_frames": actual_frames,
            "canonical_bytes": len(stdout),
            "canonical_sha256": hashlib.sha256(stdout).hexdigest(),
            "ffmpeg": {
                "version": _version(ffmpeg),
                "sha256": _tool_hash(ffmpeg),
            },
            "ffprobe": {
                "version": _version(ffprobe),
                "sha256": _tool_hash(ffprobe),
            },
            "source_bitstream_embedded": False,
        },
    )


def import_video_to_canonical_rgb8(
    source: str | Path,
    *,
    max_frames: int,
    crop: tuple[int, int, int, int] | None = None,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    expected_source_sha256: str | None = None,
    timeout_seconds: int = 120,
) -> ImportedCanonicalVideo:
    """Compatibility entrypoint for the original RGB8 canonical profile."""

    return import_video_to_canonical(
        source,
        max_frames=max_frames,
        crop=crop,
        preserve_source_pixel_format=False,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        expected_source_sha256=expected_source_sha256,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "CASVImportError",
    "CanonicalVideoDecodePlan",
    "ImportedCanonicalVideo",
    "import_video_to_canonical",
    "import_video_to_canonical_rgb8",
    "prepare_video_decode_plan",
]
