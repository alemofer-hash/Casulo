from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from .casv_import import (
    CASVImportError,
    CanonicalVideoDecodePlan,
    prepare_video_decode_plan,
)
from .casv_compact_stream import (
    CASVCompactStreamError,
    pack_casv_compact_stream_reader,
)
from .casv_temporal_stream import (
    CASVTemporalStreamError,
    pack_casv_temporal_stream_reader,
)
from .casv_program_stream import (
    CASVProgramStreamError,
    pack_casv_program_stream_reader,
)
from .casv_stream_archive import (
    CASVStreamArchiveError,
    pack_casv_stream_reader,
)
from .casv_tiled_stream import (
    CASVTiledStreamError,
    pack_casv_tiled_stream_reader,
)


MAX_STDERR_CAPTURE_BYTES = 64 * 1024
MAX_STDERR_EXCERPT_BYTES = 4096
DEFAULT_MAX_CANONICAL_BYTES = 1024 * 1024 * 1024


class CASVStreamImportError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _implementation_hashes(
    policy_source: str | Path,
    *,
    program_stream: bool = False,
    tiled_stream: bool = False,
    compact_stream: bool = False,
    temporal_stream: bool = False,
) -> dict[str, str]:
    repository = Path(__file__).resolve().parents[3]
    paths = {
        "stream_import": Path(__file__).resolve(),
        "decode_plan": repository / "src/casulo/compression/casv_import.py",
        "t_authority": repository / "src/casulo/compression/casv_authority.py",
        "t_policy": Path(policy_source).resolve(strict=True),
    }
    if temporal_stream:
        paths.update(
            {
                "temporal_stream_archive": (
                    repository / "src/casulo/compression/casv_temporal_stream.py"
                ),
                "temporal_ir": (
                    repository / "src/casulo/compression/casv_temporal_ir.py"
                ),
                "tile_ir": repository / "src/casulo/compression/casv_tile_ir.py",
                "tile_authority": (
                    repository / "src/casulo/compression/casv_tile_authority.py"
                ),
                "independent_decoder": (
                    repository
                    / "src/casulo/compression/independent_casv_temporal_stream.py"
                ),
            }
        )
    elif compact_stream:
        paths.update(
            {
                "compact_stream_archive": (
                    repository / "src/casulo/compression/casv_compact_stream.py"
                ),
                "tile_ir": repository / "src/casulo/compression/casv_tile_ir.py",
                "tile_authority": (
                    repository / "src/casulo/compression/casv_tile_authority.py"
                ),
                "independent_decoder": (
                    repository
                    / "src/casulo/compression/independent_casv_compact_stream.py"
                ),
            }
        )
    elif tiled_stream:
        paths.update(
            {
                "tiled_stream_archive": (
                    repository / "src/casulo/compression/casv_tiled_stream.py"
                ),
                "tile_ir": repository / "src/casulo/compression/casv_tile_ir.py",
                "tile_authority": (
                    repository / "src/casulo/compression/casv_tile_authority.py"
                ),
                "independent_decoder": (
                    repository
                    / "src/casulo/compression/independent_casv_tiled_stream.py"
                ),
            }
        )
    elif program_stream:
        paths.update(
            {
                "program_stream_archive": (
                    repository / "src/casulo/compression/casv_program_stream.py"
                ),
                "segment_ir": repository / "src/casulo/compression/casv_segment_ir.py",
                "independent_decoder": (
                    repository
                    / "src/casulo/compression/independent_casv_program_stream.py"
                ),
            }
        )
    else:
        paths.update(
            {
                "stream_archive": (
                    repository / "src/casulo/compression/casv_stream_archive.py"
                ),
                "independent_decoder": (
                    repository / "src/casulo/compression/independent_casv_stream.py"
                ),
            }
        )
    return {name: _sha256_file(path) for name, path in paths.items()}


class _StderrCollector:
    def __init__(self) -> None:
        self.captured = bytearray()
        self.total_bytes = 0
        self.digest = hashlib.sha256()

    def drain(self, stream: BinaryIO) -> None:
        while block := stream.read(16 * 1024):
            self.total_bytes += len(block)
            self.digest.update(block)
            remaining = MAX_STDERR_CAPTURE_BYTES - len(self.captured)
            if remaining > 0:
                self.captured.extend(block[:remaining])

    def summary(self) -> dict[str, Any]:
        excerpt = bytes(self.captured[:MAX_STDERR_EXCERPT_BYTES]).decode(
            "utf-8",
            errors="replace",
        )
        return {
            "bytes": self.total_bytes,
            "sha256": self.digest.hexdigest(),
            "capture_truncated": self.total_bytes > len(self.captured),
            "excerpt_truncated": self.total_bytes > MAX_STDERR_EXCERPT_BYTES,
            "excerpt": excerpt,
        }


def _execute_stream_pack(
    plan: CanonicalVideoDecodePlan,
    archive_path: Path,
    evidence_path: Path,
    *,
    policy_source: str | Path,
    runtime: str | Path | None,
    timeout_seconds: int,
    provenance: dict[str, Any],
    packer: Callable[..., dict[str, Any]],
    packer_options: Mapping[str, Any],
) -> dict[str, Any]:
    started_utc = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.perf_counter()
    try:
        process = subprocess.Popen(
            list(plan.command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except OSError as exc:
        raise CASVStreamImportError(
            f"ffmpeg stream decode could not start: {exc}"
        ) from exc
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise CASVStreamImportError("ffmpeg did not expose the required pipes")

    collector = _StderrCollector()
    stderr_thread = threading.Thread(
        target=collector.drain,
        args=(process.stderr,),
        name="casv-ffmpeg-stderr-drain",
        daemon=True,
    )
    stderr_thread.start()
    timed_out = threading.Event()

    def abort_on_timeout() -> None:
        timed_out.set()
        try:
            process.kill()
        except OSError:
            pass

    timer = threading.Timer(timeout_seconds, abort_on_timeout)
    timer.daemon = True
    timer.start()

    def validate_ffmpeg_completion() -> None:
        returncode = process.wait()
        timer.cancel()
        stderr_thread.join(timeout=5)
        stderr_summary = collector.summary()
        provenance["ffmpeg_execution"] = {
            "returncode": returncode,
            "timed_out": timed_out.is_set(),
            "started_utc": started_utc,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_monotonic_seconds": time.perf_counter() - started_monotonic,
            "stderr": stderr_summary,
            "stdout_transport": "DIRECT_BOUNDED_PIPE",
            "raw_intermediate_created": False,
        }
        if stderr_thread.is_alive():
            raise CASVStreamImportError("ffmpeg stderr drain did not terminate")
        if timed_out.is_set():
            raise CASVStreamImportError("ffmpeg stream decode exceeded its timeout")
        if returncode != 0:
            raise CASVStreamImportError(
                "ffmpeg stream decode failed: "
                + (stderr_summary["excerpt"].strip() or f"exit {returncode}")
            )

    try:
        result = packer(
            process.stdout,
            plan.spec,
            archive_path,
            evidence_dir=evidence_path,
            policy_source=policy_source,
            runtime=runtime,
            source_label=plan.source_path.name,
            source_descriptor="FFMPEG_STDOUT_PIPE",
            source_provenance=provenance,
            precommit_validator=validate_ffmpeg_completion,
            **dict(packer_options),
        )
    except Exception as exc:
        timer.cancel()
        killed_for_cleanup = False
        try:
            returncode = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            killed_for_cleanup = True
            process.kill()
            returncode = process.wait()
        stderr_thread.join(timeout=5)
        if timed_out.is_set():
            raise CASVStreamImportError(
                "ffmpeg stream decode exceeded its timeout"
            ) from exc
        controlled = isinstance(
            exc,
            (
                CASVImportError,
                CASVCompactStreamError,
                CASVTemporalStreamError,
                CASVProgramStreamError,
                CASVStreamArchiveError,
                CASVStreamImportError,
                CASVTiledStreamError,
            ),
        )
        if returncode != 0 and not killed_for_cleanup and not controlled:
            summary = collector.summary()
            raise CASVStreamImportError(
                "ffmpeg stream decode failed before canonical completion: "
                + (summary["excerpt"].strip() or f"exit {returncode}")
            ) from exc
        raise
    finally:
        timer.cancel()
        process.stdout.close()
        process.stderr.close()

    return {
        **result,
        "stream_import": {
            "source_label": plan.source_path.name,
            "source_sha256": provenance["source_sha256"],
            "transport": "FFMPEG_STDOUT_PIPE",
            "raw_intermediate_created": False,
            "ffmpeg_execution": provenance["ffmpeg_execution"],
        },
    }


def pack_video_to_casv_stream(
    source: str | Path,
    archive: str | Path,
    *,
    frame_count: int,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    crop: tuple[int, int, int, int] | None = None,
    preserve_source_pixel_format: bool = False,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    expected_source_sha256: str | None = None,
    segment_bytes: int = 8 * 1024 * 1024,
    timeout_seconds: int = 600,
    maximum_canonical_bytes: int | None = DEFAULT_MAX_CANONICAL_BYTES,
) -> dict[str, Any]:
    """Decode FFmpeg stdout directly into CASV/0.2 without a raw intermediary."""

    if not 1 <= timeout_seconds <= 86_400:
        raise CASVStreamImportError("stream import timeout is outside safe bounds")
    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    if archive_path.exists() or evidence_path.exists():
        raise CASVStreamImportError(
            "stream import destinations must be new and append-only"
        )
    plan = prepare_video_decode_plan(
        source,
        frame_count=frame_count,
        crop=crop,
        preserve_source_pixel_format=preserve_source_pixel_format,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        expected_source_sha256=expected_source_sha256,
        maximum_canonical_bytes=maximum_canonical_bytes,
    )
    provenance = dict(plan.provenance)
    provenance["implementation_sha256"] = _implementation_hashes(policy_source)
    return _execute_stream_pack(
        plan,
        archive_path,
        evidence_path,
        policy_source=policy_source,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        provenance=provenance,
        packer=pack_casv_stream_reader,
        packer_options={"segment_bytes": segment_bytes},
    )


def pack_video_to_casv_program_stream(
    source: str | Path,
    archive: str | Path,
    *,
    frame_count: int,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    crop: tuple[int, int, int, int] | None = None,
    preserve_source_pixel_format: bool = False,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    expected_source_sha256: str | None = None,
    frames_per_segment: int = 8,
    timeout_seconds: int = 600,
    maximum_canonical_bytes: int | None = DEFAULT_MAX_CANONICAL_BYTES,
) -> dict[str, Any]:
    """Decode FFmpeg stdout into causal CASV/0.3 without a raw intermediary."""

    if not 1 <= timeout_seconds <= 86_400:
        raise CASVStreamImportError("stream import timeout is outside safe bounds")
    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    if archive_path.exists() or evidence_path.exists():
        raise CASVStreamImportError(
            "stream import destinations must be new and append-only"
        )
    plan = prepare_video_decode_plan(
        source,
        frame_count=frame_count,
        crop=crop,
        preserve_source_pixel_format=preserve_source_pixel_format,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        expected_source_sha256=expected_source_sha256,
        maximum_canonical_bytes=maximum_canonical_bytes,
    )
    provenance = dict(plan.provenance)
    provenance["implementation_sha256"] = _implementation_hashes(
        policy_source,
        program_stream=True,
    )
    return _execute_stream_pack(
        plan,
        archive_path,
        evidence_path,
        policy_source=policy_source,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        provenance=provenance,
        packer=pack_casv_program_stream_reader,
        packer_options={"frames_per_segment": frames_per_segment},
    )


def pack_video_to_casv_tiled_stream(
    source: str | Path,
    archive: str | Path,
    *,
    frame_count: int,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    crop: tuple[int, int, int, int] | None = None,
    preserve_source_pixel_format: bool = False,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    expected_source_sha256: str | None = None,
    tile_width: int = 512,
    strip_height: int = 128,
    timeout_seconds: int = 600,
    maximum_canonical_bytes: int | None = DEFAULT_MAX_CANONICAL_BYTES,
) -> dict[str, Any]:
    """Decode FFmpeg stdout into bounded CASV/0.4 tiled strips."""

    if not 1 <= timeout_seconds <= 86_400:
        raise CASVStreamImportError("stream import timeout is outside safe bounds")
    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    if archive_path.exists() or evidence_path.exists():
        raise CASVStreamImportError(
            "stream import destinations must be new and append-only"
        )
    plan = prepare_video_decode_plan(
        source,
        frame_count=frame_count,
        crop=crop,
        preserve_source_pixel_format=preserve_source_pixel_format,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        expected_source_sha256=expected_source_sha256,
        maximum_canonical_bytes=maximum_canonical_bytes,
    )
    provenance = dict(plan.provenance)
    provenance["implementation_sha256"] = _implementation_hashes(
        policy_source,
        tiled_stream=True,
    )
    return _execute_stream_pack(
        plan,
        archive_path,
        evidence_path,
        policy_source=policy_source,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        provenance=provenance,
        packer=pack_casv_tiled_stream_reader,
        packer_options={"tile_width": tile_width, "strip_height": strip_height},
    )


def pack_video_to_casv_compact_stream(
    source: str | Path,
    archive: str | Path,
    *,
    frame_count: int,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    crop: tuple[int, int, int, int] | None = None,
    preserve_source_pixel_format: bool = False,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    expected_source_sha256: str | None = None,
    tile_width: int = 512,
    strip_height: int = 128,
    timeout_seconds: int = 600,
    maximum_canonical_bytes: int | None = DEFAULT_MAX_CANONICAL_BYTES,
) -> dict[str, Any]:
    """Decode FFmpeg stdout into compact CASV/0.5 tiled strips."""

    if not 1 <= timeout_seconds <= 86_400:
        raise CASVStreamImportError("stream import timeout is outside safe bounds")
    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    if archive_path.exists() or evidence_path.exists():
        raise CASVStreamImportError(
            "stream import destinations must be new and append-only"
        )
    plan = prepare_video_decode_plan(
        source,
        frame_count=frame_count,
        crop=crop,
        preserve_source_pixel_format=preserve_source_pixel_format,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        expected_source_sha256=expected_source_sha256,
        maximum_canonical_bytes=maximum_canonical_bytes,
    )
    provenance = dict(plan.provenance)
    provenance["implementation_sha256"] = _implementation_hashes(
        policy_source,
        compact_stream=True,
    )
    return _execute_stream_pack(
        plan,
        archive_path,
        evidence_path,
        policy_source=policy_source,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        provenance=provenance,
        packer=pack_casv_compact_stream_reader,
        packer_options={"tile_width": tile_width, "strip_height": strip_height},
    )


def pack_video_to_casv_temporal_stream(
    source: str | Path,
    archive: str | Path,
    *,
    frame_count: int,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    crop: tuple[int, int, int, int] | None = None,
    preserve_source_pixel_format: bool = False,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    expected_source_sha256: str | None = None,
    tile_width: int = 512,
    strip_height: int = 128,
    keyframe_interval: int = 8,
    timeout_seconds: int = 600,
    maximum_canonical_bytes: int | None = DEFAULT_MAX_CANONICAL_BYTES,
) -> dict[str, Any]:
    """Decode FFmpeg stdout into temporal CASV/0.6 tiled strips."""

    if not 1 <= timeout_seconds <= 86_400:
        raise CASVStreamImportError("stream import timeout is outside safe bounds")
    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    if archive_path.exists() or evidence_path.exists():
        raise CASVStreamImportError(
            "stream import destinations must be new and append-only"
        )
    plan = prepare_video_decode_plan(
        source,
        frame_count=frame_count,
        crop=crop,
        preserve_source_pixel_format=preserve_source_pixel_format,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        expected_source_sha256=expected_source_sha256,
        maximum_canonical_bytes=maximum_canonical_bytes,
    )
    provenance = dict(plan.provenance)
    provenance["implementation_sha256"] = _implementation_hashes(
        policy_source,
        temporal_stream=True,
    )
    return _execute_stream_pack(
        plan,
        archive_path,
        evidence_path,
        policy_source=policy_source,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        provenance=provenance,
        packer=pack_casv_temporal_stream_reader,
        packer_options={
            "tile_width": tile_width,
            "strip_height": strip_height,
            "keyframe_interval": keyframe_interval,
        },
    )


__all__ = [
    "CASVStreamImportError",
    "DEFAULT_MAX_CANONICAL_BYTES",
    "pack_video_to_casv_program_stream",
    "pack_video_to_casv_compact_stream",
    "pack_video_to_casv_temporal_stream",
    "pack_video_to_casv_stream",
    "pack_video_to_casv_tiled_stream",
]
