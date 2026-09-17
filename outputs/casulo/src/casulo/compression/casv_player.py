from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .independent_casv import decode_casv_canonical_bytes
from .independent_casv_compact_stream import (
    CASV_COMPACT_MAGIC,
    IndependentCASVCompactStreamError,
    iter_casv_compact_canonical,
    verify_casv_compact_stream,
)
from .independent_casv_temporal_stream import (
    CASV_TEMPORAL_MAGIC,
    IndependentCASVTemporalStreamError,
    iter_casv_temporal_canonical,
    verify_casv_temporal_stream,
)
from .independent_casv_stream import (
    CASV_STREAM_MAGIC,
    IndependentCASVStreamError,
    iter_casv_stream_segments,
    verify_casv_stream,
)
from .independent_casv_program_stream import (
    CASV_PROGRAM_STREAM_MAGIC,
    IndependentCASVProgramStreamError,
    iter_casv_program_stream_segments,
    verify_casv_program_stream,
)
from .independent_casv_tiled_stream import (
    CASV_TILED_STREAM_MAGIC,
    IndependentCASVTiledStreamError,
    iter_casv_tiled_canonical,
    verify_casv_tiled_stream,
)
from .tooling import resolve_tool


class CASVPlayerError(RuntimeError):
    pass


def resolve_ffplay(explicit: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    if resolved := shutil.which("ffplay"):
        candidates.append(Path(resolved))
    ffmpeg = resolve_tool("ffmpeg")
    if ffmpeg is not None:
        candidates.append(
            ffmpeg.with_name(
                "ffplay.exe" if ffmpeg.suffix.lower() == ".exe" else "ffplay"
            )
        )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve(strict=True)
        except OSError:
            continue
    return None


def build_ffplay_command(
    ffplay: str | Path,
    raw_frames: str | Path,
    canonical_media: Mapping[str, Any],
) -> list[str]:
    try:
        width = int(canonical_media["width"])
        height = int(canonical_media["height"])
        fps_numerator = int(canonical_media["fps_numerator"])
        fps_denominator = int(canonical_media["fps_denominator"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CASVPlayerError("CASV canonical media metadata is invalid") from exc
    if min(width, height, fps_numerator, fps_denominator) <= 0:
        raise CASVPlayerError(
            "CASV playback dimensions and frame rate must be positive"
        )
    pixel_formats = {"RGB8": "rgb24", "YUV444P10LE": "yuv444p10le"}
    pixel_format = pixel_formats.get(canonical_media.get("pixel_format", "RGB8"))
    if pixel_format is None:
        raise CASVPlayerError(
            "CASV pixel format is not supported by the reference player"
        )
    return [
        str(Path(ffplay).resolve()),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "rawvideo",
        "-pixel_format",
        pixel_format,
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        f"{fps_numerator}/{fps_denominator}",
        "-autoexit",
        str(Path(raw_frames).resolve()),
    ]


def build_ffplay_pipe_command(
    ffplay: str | Path,
    canonical_media: Mapping[str, Any],
) -> list[str]:
    command = build_ffplay_command(
        ffplay, Path("casv-placeholder.raw"), canonical_media
    )
    command[-1] = "pipe:0"
    return command


def play_casv(
    archive: str | Path,
    *,
    ffplay_path: str | Path | None = None,
) -> dict[str, Any]:
    """Play bounded CASV/0.1 or independently verified CASV/0.2-0.6 streams."""

    ffplay = resolve_ffplay(ffplay_path)
    if ffplay is None:
        raise CASVPlayerError(
            "ffplay was not found; install/qualify the FFmpeg toolchain"
        )
    archive_path = Path(archive).resolve()
    try:
        with archive_path.open("rb") as stream:
            magic = stream.read(len(CASV_STREAM_MAGIC))
    except OSError as exc:
        raise CASVPlayerError(
            f"CASV archive could not be read: {archive_path}"
        ) from exc
    if magic == CASV_TEMPORAL_MAGIC:
        return _play_casv_temporal_stream(archive_path, ffplay)
    if magic == CASV_COMPACT_MAGIC:
        return _play_casv_compact_stream(archive_path, ffplay)
    if magic == CASV_TILED_STREAM_MAGIC:
        return _play_casv_tiled_stream(archive_path, ffplay)
    if magic == CASV_PROGRAM_STREAM_MAGIC:
        return _play_casv_program_stream(archive_path, ffplay)
    if magic == CASV_STREAM_MAGIC:
        return _play_casv_stream(archive_path, ffplay)
    verified, canonical = decode_casv_canonical_bytes(archive)
    command = build_ffplay_pipe_command(ffplay, verified["canonical_media"])
    completed = subprocess.run(
        command,
        input=canonical,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        message = getattr(completed, "stderr", b"") or b""
        raise CASVPlayerError(
            f"ffplay exited with status {completed.returncode}: "
            f"{message.decode('utf-8', errors='replace').strip()}"
        )
    return {
        "schema": "casulo.casv-reference-playback/0.1",
        "status": "PASS",
        "archive": str(Path(archive).resolve()),
        "archive_sha256": verified["archive_sha256"],
        "canonical_sha256": verified["canonical_sha256"],
        "ffplay": str(ffplay),
        "player_profile": "REFERENCE_PIPE_BOUNDED_MEMORY_NOT_INCREMENTAL_DECODE",
        "canonical_bytes_piped": len(canonical),
        "temporary_media_retained": False,
    }


def _play_casv_stream(archive: Path, ffplay: Path) -> dict[str, Any]:
    """Verify first, then decode a second pass directly into ffplay stdin."""

    try:
        verified = verify_casv_stream(archive)
    except IndependentCASVStreamError as exc:
        raise CASVPlayerError(str(exc)) from exc
    command = build_ffplay_pipe_command(ffplay, verified["canonical_media"])
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        raise CASVPlayerError(f"ffplay could not be started: {exc}") from exc
    piped = 0
    try:
        if process.stdin is None:
            raise CASVPlayerError("ffplay stdin pipe was not created")
        for decoded in iter_casv_stream_segments(archive):
            process.stdin.write(decoded)
            piped += len(decoded)
        process.stdin.close()
        returncode = process.wait()
    except (BrokenPipeError, OSError, IndependentCASVStreamError) as exc:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait()
        except OSError:
            pass
        raise CASVPlayerError(f"CASV stream playback failed: {exc}") from exc
    if returncode != 0:
        raise CASVPlayerError(f"ffplay exited with status {returncode}")
    if piped != verified["canonical_bytes"]:
        raise CASVPlayerError("CASV stream playback byte accounting differs")
    return {
        "schema": "casulo.casv-reference-playback/0.2",
        "status": "PASS",
        "archive": str(archive),
        "archive_sha256": verified["archive_sha256"],
        "canonical_sha256": verified["canonical_sha256"],
        "ffplay": str(ffplay),
        "player_profile": "REFERENCE_PIPE_INCREMENTAL_SEGMENTS_TWO_PASS_VERIFIED",
        "canonical_bytes_piped": piped,
        "maximum_canonical_segment_bytes": verified["maximum_canonical_segment_bytes"],
        "maximum_explicit_segment_buffers_bytes": verified[
            "maximum_explicit_segment_buffers_bytes"
        ],
        "process_peak_rss_measured": False,
        "temporary_media_retained": False,
    }


def _play_casv_program_stream(archive: Path, ffplay: Path) -> dict[str, Any]:
    """Verify CASV/0.3, then independently render each program into ffplay."""

    try:
        verified = verify_casv_program_stream(archive)
    except IndependentCASVProgramStreamError as exc:
        raise CASVPlayerError(str(exc)) from exc
    command = build_ffplay_pipe_command(ffplay, verified["canonical_media"])
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        raise CASVPlayerError(f"ffplay could not be started: {exc}") from exc
    piped = 0
    try:
        if process.stdin is None:
            raise CASVPlayerError("ffplay stdin pipe was not created")
        for decoded in iter_casv_program_stream_segments(archive):
            process.stdin.write(decoded)
            piped += len(decoded)
        process.stdin.close()
        returncode = process.wait()
    except (BrokenPipeError, OSError, IndependentCASVProgramStreamError) as exc:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait()
        except OSError:
            pass
        raise CASVPlayerError(f"CASV/0.3 playback failed: {exc}") from exc
    if returncode != 0:
        raise CASVPlayerError(f"ffplay exited with status {returncode}")
    if piped != verified["canonical_bytes"]:
        raise CASVPlayerError("CASV/0.3 playback byte accounting differs")
    return {
        "schema": "casulo.casv-reference-playback/0.3",
        "status": "PASS",
        "archive": str(archive),
        "archive_sha256": verified["archive_sha256"],
        "canonical_sha256": verified["canonical_sha256"],
        "ffplay": str(ffplay),
        "player_profile": "REFERENCE_PIPE_CAUSAL_PROGRAMS_TWO_PASS_VERIFIED",
        "canonical_bytes_piped": piped,
        "generative_segments": verified["generative_segments"],
        "maximum_canonical_segment_bytes": verified["maximum_canonical_segment_bytes"],
        "process_peak_rss_measured": False,
        "temporary_media_retained": False,
    }


def _play_casv_tiled_stream(archive: Path, ffplay: Path) -> dict[str, Any]:
    """Verify CASV/0.4, then reconstruct bounded strips into ffplay."""

    try:
        verified = verify_casv_tiled_stream(archive)
    except IndependentCASVTiledStreamError as exc:
        raise CASVPlayerError(str(exc)) from exc
    command = build_ffplay_pipe_command(ffplay, verified["canonical_media"])
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        raise CASVPlayerError(f"ffplay could not be started: {exc}") from exc
    piped = 0
    try:
        if process.stdin is None:
            raise CASVPlayerError("ffplay stdin pipe was not created")
        for decoded in iter_casv_tiled_canonical(archive):
            process.stdin.write(decoded)
            piped += len(decoded)
        process.stdin.close()
        returncode = process.wait()
    except (BrokenPipeError, OSError, IndependentCASVTiledStreamError) as exc:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait()
        except OSError:
            pass
        raise CASVPlayerError(f"CASV/0.4 playback failed: {exc}") from exc
    if returncode != 0:
        raise CASVPlayerError(f"ffplay exited with status {returncode}")
    if piped != verified["canonical_bytes"]:
        raise CASVPlayerError("CASV/0.4 playback byte accounting differs")
    return {
        "schema": "casulo.casv-reference-playback/0.4",
        "status": "PASS",
        "archive": str(archive),
        "archive_sha256": verified["archive_sha256"],
        "canonical_sha256": verified["canonical_sha256"],
        "ffplay": str(ffplay),
        "player_profile": "REFERENCE_PIPE_TILED_STRIPS_TWO_PASS_VERIFIED",
        "canonical_bytes_piped": piped,
        "maximum_decoded_strip_bytes": verified["maximum_decoded_strip_bytes"],
        "process_peak_rss_measured": False,
        "temporary_media_retained": False,
    }


def _play_casv_compact_stream(archive: Path, ffplay: Path) -> dict[str, Any]:
    """Verify CASV/0.5, then reconstruct bounded strips into ffplay."""

    try:
        verified = verify_casv_compact_stream(archive)
    except IndependentCASVCompactStreamError as exc:
        raise CASVPlayerError(str(exc)) from exc
    command = build_ffplay_pipe_command(ffplay, verified["canonical_media"])
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        raise CASVPlayerError(f"ffplay could not be started: {exc}") from exc
    piped = 0
    try:
        if process.stdin is None:
            raise CASVPlayerError("ffplay stdin pipe was not created")
        for decoded in iter_casv_compact_canonical(archive):
            process.stdin.write(decoded)
            piped += len(decoded)
        process.stdin.close()
        returncode = process.wait()
    except (BrokenPipeError, OSError, IndependentCASVCompactStreamError) as exc:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait()
        except OSError:
            pass
        raise CASVPlayerError(f"CASV/0.5 playback failed: {exc}") from exc
    if returncode != 0:
        raise CASVPlayerError(f"ffplay exited with status {returncode}")
    if piped != verified["canonical_bytes"]:
        raise CASVPlayerError("CASV/0.5 playback byte accounting differs")
    return {
        "schema": "casulo.casv-reference-playback/0.5",
        "status": "PASS",
        "archive": str(archive),
        "archive_sha256": verified["archive_sha256"],
        "canonical_sha256": verified["canonical_sha256"],
        "ffplay": str(ffplay),
        "player_profile": "REFERENCE_PIPE_COMPACT_TILED_STRIPS_TWO_PASS_VERIFIED",
        "canonical_bytes_piped": piped,
        "maximum_decoded_strip_bytes": verified["maximum_decoded_strip_bytes"],
        "process_peak_rss_measured": False,
        "temporary_media_retained": False,
    }


def _play_casv_temporal_stream(archive: Path, ffplay: Path) -> dict[str, Any]:
    """Verify CASV/0.6, then reconstruct bounded strips into ffplay."""

    try:
        verified = verify_casv_temporal_stream(archive)
    except IndependentCASVTemporalStreamError as exc:
        raise CASVPlayerError(str(exc)) from exc
    command = build_ffplay_pipe_command(ffplay, verified["canonical_media"])
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        raise CASVPlayerError(f"ffplay could not be started: {exc}") from exc
    piped = 0
    try:
        if process.stdin is None:
            raise CASVPlayerError("ffplay stdin pipe was not created")
        for decoded in iter_casv_temporal_canonical(archive):
            process.stdin.write(decoded)
            piped += len(decoded)
        process.stdin.close()
        returncode = process.wait()
    except (BrokenPipeError, OSError, IndependentCASVTemporalStreamError) as exc:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait()
        except OSError:
            pass
        raise CASVPlayerError(f"CASV/0.6 playback failed: {exc}") from exc
    if returncode != 0:
        raise CASVPlayerError(f"ffplay exited with status {returncode}")
    if piped != verified["canonical_bytes"]:
        raise CASVPlayerError("CASV/0.6 playback byte accounting differs")
    return {
        "schema": "casulo.casv-reference-playback/0.6",
        "status": "PASS",
        "archive": str(archive),
        "archive_sha256": verified["archive_sha256"],
        "canonical_sha256": verified["canonical_sha256"],
        "ffplay": str(ffplay),
        "player_profile": "REFERENCE_PIPE_TEMPORAL_TILES_TWO_PASS_VERIFIED",
        "canonical_bytes_piped": piped,
        "maximum_decoded_strip_bytes": verified["maximum_decoded_strip_bytes"],
        "previous_frame_spool_bytes": verified["canonical_media"]["width"]
        * verified["canonical_media"]["height"]
        * ({"RGB8": 3, "YUV444P10LE": 6}[verified["canonical_media"]["pixel_format"]]),
        "process_peak_rss_measured": False,
        "temporary_media_retained": False,
    }


__all__ = [
    "CASVPlayerError",
    "build_ffplay_command",
    "build_ffplay_pipe_command",
    "play_casv",
    "resolve_ffplay",
]
