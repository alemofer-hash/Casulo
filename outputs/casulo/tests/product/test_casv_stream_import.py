from __future__ import annotations

import hashlib
import io
import random
import subprocess
from pathlib import Path

import pytest

from casulo.compression.casv_import import (
    CASVImportError,
    CanonicalVideoDecodePlan,
    prepare_video_decode_plan,
)
from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_probe import make_structured_probe_video
from casulo.compression.casv_stream_archive import (
    CASVStreamArchiveError,
    pack_casv_stream_reader,
)
from casulo.compression.casv_stream_import import (
    CASVStreamImportError,
    pack_video_to_casv_compact_stream,
    pack_video_to_casv_stream,
    pack_video_to_casv_temporal_stream,
)
from casulo.compression.independent_casv_compact_stream import (
    verify_casv_compact_stream,
)
from casulo.compression.independent_casv_stream import (
    inspect_casv_stream,
    verify_casv_stream,
)
from casulo.compression.independent_casv_temporal_stream import (
    verify_casv_temporal_stream,
)
from casulo.compression.tooling import resolve_tool


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
DEFAULT_POLICY = ROOT / "examples" / "t-v2" / "compression_casv.t"
COMPACT_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_compact.t"
TEMPORAL_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_temporal.t"
TOOLCHAIN_AVAILABLE = (
    RUNTIME.is_file()
    and resolve_tool("ffmpeg") is not None
    and resolve_tool("ffprobe") is not None
)


class _ShortReadStream(io.BytesIO):
    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = 7
        return super().read(min(size, 7))


def _encode_ffv1(
    raw: Path,
    destination: Path,
    *,
    width: int,
    height: int,
    frame_rate: int,
    pixel_format: str,
) -> None:
    ffmpeg = resolve_tool("ffmpeg")
    assert ffmpeg is not None
    command = [
        str(ffmpeg),
        "-nostdin",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pixel_format,
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        str(frame_rate),
        "-i",
        str(raw),
        "-c:v",
        "ffv1",
    ]
    if pixel_format == "yuv444p10le":
        command.extend(["-level", "3", "-pix_fmt", pixel_format])
    command.extend(["-y", str(destination)])
    encoded = subprocess.run(command, check=False, capture_output=True, shell=False)
    assert encoded.returncode == 0, encoded.stderr.decode(errors="replace")


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_stream_reader_accepts_short_pipe_reads(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(64, 36, 2, 24)
    payload = make_structured_probe_video(spec)
    archive = tmp_path / "short-reads.casv"
    packed = pack_casv_stream_reader(
        _ShortReadStream(payload),
        spec,
        archive,
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        segment_bytes=1024,
        source_label="pipe.rgb",
    )
    restored = tmp_path / "restored.rgb"
    verified = verify_casv_stream(archive, restored)
    assert restored.read_bytes() == payload
    assert verified["canonical_sha256"] == hashlib.sha256(payload).hexdigest()
    assert packed["status"] == "PASS"


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
@pytest.mark.parametrize("delta", (-1, 1))
def test_stream_reader_rejects_wrong_length_before_atomic_publish(
    tmp_path: Path,
    delta: int,
) -> None:
    spec = CanonicalVideoSpec(64, 36, 1, 24)
    payload = make_structured_probe_video(spec)
    altered = payload[:-1] if delta < 0 else payload + b"X"
    archive = tmp_path / f"wrong-length-{delta}.casv"
    with pytest.raises(CASVStreamArchiveError, match="declared media size"):
        pack_casv_stream_reader(
            io.BytesIO(altered),
            spec,
            archive,
            evidence_dir=tmp_path / f"evidence-{delta}",
            policy_source=DEFAULT_POLICY,
            runtime=RUNTIME,
            segment_bytes=1024,
            source_label="pipe.rgb",
        )
    assert not archive.exists()
    assert not archive.with_name(archive.name + ".casv-part").exists()


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_stream_reader_rejects_failed_precommit_validator(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(64, 36, 1, 24)
    payload = make_structured_probe_video(spec)
    archive = tmp_path / "precommit-failure.casv"

    def reject() -> None:
        raise CASVStreamImportError("producer exit was not successful")

    with pytest.raises(CASVStreamImportError, match="producer exit"):
        pack_casv_stream_reader(
            io.BytesIO(payload),
            spec,
            archive,
            evidence_dir=tmp_path / "evidence",
            policy_source=DEFAULT_POLICY,
            runtime=RUNTIME,
            segment_bytes=1024,
            source_label="pipe.rgb",
            precommit_validator=reject,
        )
    assert not archive.exists()
    assert not archive.with_name(archive.name + ".casv-part").exists()


@pytest.mark.skipif(not TOOLCHAIN_AVAILABLE, reason="CASV stream toolchain unavailable")
def test_direct_ffmpeg_rgb_stream_roundtrip_without_raw_intermediate(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(64, 36, 6, 24)
    frames = make_structured_probe_video(spec)
    raw = tmp_path / "encoding-input.rgb"
    source = tmp_path / "source.mkv"
    raw.write_bytes(frames)
    _encode_ffv1(
        raw,
        source,
        width=spec.width,
        height=spec.height,
        frame_rate=24,
        pixel_format="rgb24",
    )
    before = {path.resolve() for path in tmp_path.rglob("*.raw")}
    archive = tmp_path / "direct.casv"
    result = pack_video_to_casv_stream(
        source,
        archive,
        frame_count=spec.frame_count,
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        segment_bytes=2048,
        maximum_canonical_bytes=4 * 1024 * 1024,
    )
    after = {path.resolve() for path in tmp_path.rglob("*.raw")}
    restored = tmp_path / "restored.rgb"
    verified = verify_casv_stream(archive, restored)
    manifest = inspect_casv_stream(archive)["manifest"]

    assert before == after
    assert restored.read_bytes() == frames
    assert verified["canonical_sha256"] == hashlib.sha256(frames).hexdigest()
    assert result["stream_import"]["raw_intermediate_created"] is False
    assert result["stream_import"]["ffmpeg_execution"]["returncode"] == 0
    assert manifest["source_adapter"]["transport"] == "FFMPEG_STDOUT_PIPE"
    assert manifest["source_adapter"]["raw_intermediate_created"] is False
    assert manifest["source_adapter"]["command_template"][6] == "<SOURCE>"
    assert source.read_bytes() not in archive.read_bytes()


@pytest.mark.skipif(not TOOLCHAIN_AVAILABLE, reason="CASV stream toolchain unavailable")
def test_direct_ffmpeg_native_yuv444p10le_roundtrip(tmp_path: Path) -> None:
    width, height, frame_count = 16, 8, 3
    spec = CanonicalVideoSpec(
        width,
        height,
        frame_count,
        24,
        pixel_format="YUV444P10LE",
    )
    samples = b"".join(
        ((index * 37 + 11) % 1024).to_bytes(2, "little")
        for index in range(spec.expected_bytes // 2)
    )
    raw = tmp_path / "encoding-input-yuv.raw"
    source = tmp_path / "native.mkv"
    raw.write_bytes(samples)
    _encode_ffv1(
        raw,
        source,
        width=width,
        height=height,
        frame_rate=24,
        pixel_format="yuv444p10le",
    )
    archive = tmp_path / "native.casv"
    result = pack_video_to_casv_stream(
        source,
        archive,
        frame_count=frame_count,
        evidence_dir=tmp_path / "native-evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        preserve_source_pixel_format=True,
        segment_bytes=1024,
        maximum_canonical_bytes=4 * 1024 * 1024,
    )
    restored = tmp_path / "restored-yuv.raw"
    verified = verify_casv_stream(archive, restored)
    assert restored.read_bytes() == samples
    assert verified["canonical_media"]["pixel_format"] == "YUV444P10LE"
    assert result["source_adapter"]["canonicalization"]["contract"] == (
        "EXACT_FFMPEG_DECODED_NATIVE_SAMPLE_STREAM"
    )


@pytest.mark.skipif(not TOOLCHAIN_AVAILABLE, reason="CASV stream toolchain unavailable")
def test_direct_ffmpeg_compact_stream_roundtrip_without_raw_intermediate(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(64, 36, 2, 24)
    frames = bytes(
        (
            (x * 17 + y * 29 + frame * 43) & 0xFF
            if channel == 0
            else (x * 13 + y * 7 + frame * 31) & 0xFF
            if channel == 1
            else (x * 3 + y * 19 + frame * 71) & 0xFF
        )
        for frame in range(spec.frame_count)
        for y in range(spec.height)
        for x in range(spec.width)
        for channel in range(3)
    )
    raw = tmp_path / "encoding-input-compact.rgb"
    source = tmp_path / "compact-source.mkv"
    raw.write_bytes(frames)
    _encode_ffv1(
        raw,
        source,
        width=spec.width,
        height=spec.height,
        frame_rate=24,
        pixel_format="rgb24",
    )
    before = {path.resolve() for path in tmp_path.rglob("*.raw")}
    archive = tmp_path / "compact.casv"
    result = pack_video_to_casv_compact_stream(
        source,
        archive,
        frame_count=spec.frame_count,
        evidence_dir=tmp_path / "compact-evidence",
        policy_source=COMPACT_POLICY,
        runtime=RUNTIME,
        tile_width=32,
        strip_height=18,
        maximum_canonical_bytes=4 * 1024 * 1024,
    )
    after = {path.resolve() for path in tmp_path.rglob("*.raw")}
    verified = verify_casv_compact_stream(archive)

    assert before == after
    assert result["archive_published"] is True
    assert verified["canonical_sha256"] == hashlib.sha256(frames).hexdigest()
    assert result["stream_import"]["raw_intermediate_created"] is False
    assert result["stream_import"]["ffmpeg_execution"]["returncode"] == 0


@pytest.mark.skipif(not TOOLCHAIN_AVAILABLE, reason="CASV stream toolchain unavailable")
def test_direct_ffmpeg_temporal_stream_roundtrip_without_raw_intermediate(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(128, 96, 3, 24)
    frame_bytes = spec.expected_bytes // spec.frame_count
    base = bytearray(random.Random(20260912).randbytes(frame_bytes))
    frames = b"".join(
        bytes(
            (value + frame if index < 97 else value) & 0xFF
            for index, value in enumerate(base)
        )
        for frame in range(spec.frame_count)
    )
    raw = tmp_path / "encoding-input-temporal.rgb"
    source = tmp_path / "temporal-source.mkv"
    raw.write_bytes(frames)
    _encode_ffv1(
        raw,
        source,
        width=spec.width,
        height=spec.height,
        frame_rate=24,
        pixel_format="rgb24",
    )
    before = {path.resolve() for path in tmp_path.rglob("*.raw")}
    archive = tmp_path / "temporal.casv"
    result = pack_video_to_casv_temporal_stream(
        source,
        archive,
        frame_count=spec.frame_count,
        evidence_dir=tmp_path / "temporal-evidence",
        policy_source=TEMPORAL_POLICY,
        runtime=RUNTIME,
        tile_width=64,
        strip_height=48,
        keyframe_interval=8,
        maximum_canonical_bytes=4 * 1024 * 1024,
    )
    after = {path.resolve() for path in tmp_path.rglob("*.raw")}
    verified = verify_casv_temporal_stream(archive)

    assert before == after
    assert result["archive_published"] is True
    assert result["temporal_selected_tiles"] > 0
    assert verified["canonical_sha256"] == hashlib.sha256(frames).hexdigest()
    assert result["stream_import"]["raw_intermediate_created"] is False
    assert result["stream_import"]["ffmpeg_execution"]["returncode"] == 0


@pytest.mark.skipif(not TOOLCHAIN_AVAILABLE, reason="CASV stream toolchain unavailable")
def test_decode_plan_rejects_projected_stream_over_bound(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(64, 36, 2, 24)
    raw = tmp_path / "encoding-input.rgb"
    source = tmp_path / "source.mkv"
    raw.write_bytes(make_structured_probe_video(spec))
    _encode_ffv1(
        raw,
        source,
        width=spec.width,
        height=spec.height,
        frame_rate=24,
        pixel_format="rgb24",
    )
    with pytest.raises(CASVImportError, match="configured byte bound"):
        prepare_video_decode_plan(
            source,
            frame_count=2,
            maximum_canonical_bytes=1024,
        )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_ffmpeg_nonzero_exit_cannot_publish_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.fake"
    source.write_bytes(b"source")
    spec = CanonicalVideoSpec(64, 36, 1, 24)
    frames = make_structured_probe_video(spec)
    plan = CanonicalVideoDecodePlan(
        source_path=source,
        ffmpeg_path=tmp_path / "ffmpeg.exe",
        ffprobe_path=tmp_path / "ffprobe.exe",
        spec=spec,
        command=("ffmpeg", "pipe:1"),
        provenance={
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "raw_intermediate_created": False,
        },
    )

    class FailedProcess:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(frames)
            self.stderr = io.BytesIO(b"synthetic ffmpeg failure")

        def wait(self, timeout: float | None = None) -> int:
            return 9

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        "casulo.compression.casv_stream_import.prepare_video_decode_plan",
        lambda *args, **kwargs: plan,
    )
    real_popen = subprocess.Popen

    def selective_popen(*args: object, **kwargs: object) -> object:
        command = args[0]
        if isinstance(command, list) and command[0] == "ffmpeg":
            return FailedProcess()
        return real_popen(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "casulo.compression.casv_stream_import.subprocess.Popen",
        selective_popen,
    )
    archive = tmp_path / "failed.casv"
    with pytest.raises(CASVStreamImportError, match="synthetic ffmpeg failure"):
        pack_video_to_casv_stream(
            source,
            archive,
            frame_count=1,
            evidence_dir=tmp_path / "failed-evidence",
            policy_source=DEFAULT_POLICY,
            runtime=RUNTIME,
            segment_bytes=1024,
        )
    assert not archive.exists()
    assert not archive.with_name(archive.name + ".casv-part").exists()
