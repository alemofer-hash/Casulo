from __future__ import annotations

import hashlib
import io
import subprocess
from pathlib import Path

import pytest

from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_player import play_casv
from casulo.compression.casv_probe import (
    make_noise_probe_video,
    make_structured_probe_video,
)
from casulo.compression.casv_program_stream import (
    CASVProgramStreamError,
    pack_casv_program_stream_reader,
)
from casulo.compression.casv_stream_import import pack_video_to_casv_program_stream
from casulo.compression.independent_casv_program_stream import (
    IndependentCASVProgramStreamError,
    extract_casv_program_stream_frames,
    inspect_casv_program_stream,
    verify_casv_program_stream,
)
from casulo.compression.tooling import resolve_tool


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
DEFAULT_POLICY = ROOT / "examples" / "t-v2" / "compression_casv.t"
FORCE_RAW_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_force_raw.t"
TOOLCHAIN_AVAILABLE = (
    RUNTIME.is_file()
    and resolve_tool("ffmpeg") is not None
    and resolve_tool("ffprobe") is not None
)


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
        "-y",
        str(destination),
    ]
    encoded = subprocess.run(command, check=False, capture_output=True, shell=False)
    assert encoded.returncode == 0, encoded.stderr.decode(errors="replace")


def _structured_yuv444p10le(spec: CanonicalVideoSpec) -> bytes:
    output = bytearray()
    pixels = spec.width * spec.height
    for frame_index in range(spec.frame_count):
        planes = [
            bytearray(value.to_bytes(2, "little") * pixels)
            for value in (128, 512, 512)
        ]
        x = 4 + frame_index
        for plane, value in zip(planes, (800, 300, 700), strict=True):
            row = value.to_bytes(2, "little") * 12
            for offset_y in range(8):
                start = ((6 + offset_y) * spec.width + x) * 2
                plane[start : start + len(row)] = row
        output.extend(b"".join(planes))
    return bytes(output)


def _pack(
    tmp_path: Path,
    payload: bytes,
    spec: CanonicalVideoSpec,
    *,
    policy: Path = DEFAULT_POLICY,
    name: str = "program",
    frames_per_segment: int = 4,
) -> tuple[Path, dict[str, object]]:
    archive = tmp_path / f"{name}.casv"
    result = pack_casv_program_stream_reader(
        io.BytesIO(payload),
        spec,
        archive,
        evidence_dir=tmp_path / f"{name}-evidence",
        policy_source=policy,
        runtime=RUNTIME,
        frames_per_segment=frames_per_segment,
        source_label=f"{name}.canonical",
    )
    return archive, result


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_program_stream_rgb8_selects_causal_program_and_roundtrips(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(96, 54, 12, 24)
    source = make_structured_probe_video(spec)
    archive, packed = _pack(tmp_path, source, spec)
    restored = tmp_path / "restored.rgb"
    verified = verify_casv_program_stream(archive, restored)
    manifest = inspect_casv_program_stream(archive)["manifest"]

    assert restored.read_bytes() == source
    assert verified["canonical_sha256"] == hashlib.sha256(source).hexdigest()
    assert packed["storage_modes"] == {
        "GENERATIVE_EXACT": 3,
        "CANONICAL_ZLIB": 0,
        "CANONICAL_RAW": 0,
    }
    assert packed["proposals"] == {"executed": 3, "unavailable": 0, "selected": 3}
    assert all(segment["generative"]["residual_encoding"] == "ZERO" for segment in manifest["segments"])
    assert verified["detected_tracks"] == 6
    assert packed["authority"]["storage_decision_count"] == 3
    assert packed["authority"]["cost_judgement_count"] == 1


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_program_stream_yuv444p10le_native_renderer_roundtrips(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(64, 36, 8, 24, pixel_format="YUV444P10LE")
    source = _structured_yuv444p10le(spec)
    archive, packed = _pack(tmp_path, source, spec, name="yuv", frames_per_segment=4)
    restored = tmp_path / "restored.yuv"
    verified = verify_casv_program_stream(archive, restored)

    assert restored.read_bytes() == source
    assert verified["canonical_media"]["pixel_format"] == "YUV444P10LE"
    assert packed["storage_modes"]["GENERATIVE_EXACT"] == 2
    assert verified["residual_nonzero_bytes"] == 0


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_noise_executes_candidate_but_t_selects_lossless_fallback(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(96, 54, 4, 24)
    source = make_noise_probe_video(spec)
    archive, packed = _pack(tmp_path, source, spec, name="noise")
    restored = tmp_path / "restored-noise.rgb"
    verify_casv_program_stream(archive, restored)

    assert restored.read_bytes() == source
    assert packed["proposals"]["executed"] == 1
    assert packed["proposals"]["selected"] == 0
    assert packed["storage_modes"]["GENERATIVE_EXACT"] == 0
    assert packed["storage_modes"]["CANONICAL_RAW"] == 1


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_t_policy_mutation_causally_forces_raw_without_encoder_change(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(96, 54, 4, 24)
    source = make_structured_probe_video(spec)
    default_archive, default = _pack(tmp_path, source, spec, name="default")
    raw_archive, forced = _pack(
        tmp_path,
        source,
        spec,
        policy=FORCE_RAW_POLICY,
        name="forced",
    )

    assert default["storage_modes"]["GENERATIVE_EXACT"] == 1
    assert forced["storage_modes"]["CANONICAL_RAW"] == 1
    assert default["authority"]["tcap_sha256"] != forced["authority"]["tcap_sha256"]
    assert verify_casv_program_stream(default_archive)["canonical_sha256"] == verify_casv_program_stream(raw_archive)["canonical_sha256"]


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_selective_frame_extraction_decodes_only_intersecting_segments(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(64, 36, 12, 24)
    source = make_structured_probe_video(spec)
    archive, _packed = _pack(tmp_path, source, spec)
    selected = tmp_path / "frames-5-6.rgb"
    result = extract_casv_program_stream_frames(
        archive,
        selected,
        start_frame=5,
        frame_count=2,
    )

    expected = source[5 * spec.frame_bytes : 7 * spec.frame_bytes]
    assert selected.read_bytes() == expected
    assert result["selected_segments"] == 1
    assert result["whole_archive_payload_verified"] is False


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_corrupt_program_payload_is_rejected(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(64, 36, 4, 24)
    source = make_structured_probe_video(spec)
    archive, _packed = _pack(tmp_path, source, spec)
    manifest = inspect_casv_program_stream(archive)["manifest"]
    payload = bytearray(archive.read_bytes())
    payload[manifest["segments"][0]["stored_offset"] + 3] ^= 0xFF
    corrupt = tmp_path / "corrupt.casv"
    corrupt.write_bytes(payload)

    with pytest.raises(IndependentCASVProgramStreamError, match="stored hash"):
        verify_casv_program_stream(corrupt)


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
@pytest.mark.parametrize("delta", (-1, 1))
def test_wrong_stream_length_never_publishes(
    tmp_path: Path,
    delta: int,
) -> None:
    spec = CanonicalVideoSpec(64, 36, 4, 24)
    source = make_structured_probe_video(spec)
    altered = source[:-1] if delta < 0 else source + b"X"
    archive = tmp_path / f"wrong-{delta}.casv"
    with pytest.raises(CASVProgramStreamError, match="declared media size"):
        pack_casv_program_stream_reader(
            io.BytesIO(altered),
            spec,
            archive,
            evidence_dir=tmp_path / f"wrong-{delta}-evidence",
            policy_source=DEFAULT_POLICY,
            runtime=RUNTIME,
            frames_per_segment=4,
            source_label="wrong.rgb",
        )
    assert not archive.exists()
    assert not archive.with_name(archive.name + ".casv-part").exists()


def test_frame_aligned_segment_fails_closed_when_full_frame_exceeds_bound(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(8192, 4320, 1, 24, pixel_format="YUV444P10LE")
    with pytest.raises(CASVProgramStreamError, match="spatial tiling"):
        pack_casv_program_stream_reader(
            io.BytesIO(),
            spec,
            tmp_path / "too-wide.casv",
            evidence_dir=tmp_path / "evidence",
            policy_source=DEFAULT_POLICY,
            runtime=RUNTIME,
            frames_per_segment=1,
            source_label="8k.yuv",
        )


def test_independent_decoder_does_not_import_encoder_or_scene_inference() -> None:
    source = (ROOT / "src" / "casulo" / "compression" / "independent_casv_program_stream.py").read_text(encoding="utf-8")
    assert "from .casv_program_stream import" not in source
    assert "from .casv_segment_ir import" not in source
    assert "infer_segment_program" not in source


@pytest.mark.skipif(not TOOLCHAIN_AVAILABLE, reason="CASV stream toolchain unavailable")
def test_ffmpeg_stdout_flows_directly_into_program_segments(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(96, 54, 8, 24)
    source_frames = make_structured_probe_video(spec)
    raw = tmp_path / "encoder-input.rgb"
    video = tmp_path / "source.mkv"
    raw.write_bytes(source_frames)
    _encode_ffv1(
        raw,
        video,
        width=spec.width,
        height=spec.height,
        frame_rate=24,
        pixel_format="rgb24",
    )
    archive = tmp_path / "direct-program.casv"
    before = {path.resolve() for path in tmp_path.rglob("*.raw")}
    result = pack_video_to_casv_program_stream(
        video,
        archive,
        frame_count=8,
        evidence_dir=tmp_path / "direct-program-evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        frames_per_segment=4,
        maximum_canonical_bytes=4 * 1024 * 1024,
    )
    after = {path.resolve() for path in tmp_path.rglob("*.raw")}
    restored = tmp_path / "direct-program-restored.rgb"
    verify_casv_program_stream(archive, restored)

    assert before == after
    assert restored.read_bytes() == source_frames
    assert result["stream_import"]["raw_intermediate_created"] is False
    assert result["stream_import"]["ffmpeg_execution"]["returncode"] == 0
    assert result["storage_modes"]["GENERATIVE_EXACT"] == 2


@pytest.mark.skipif(not TOOLCHAIN_AVAILABLE, reason="CASV stream toolchain unavailable")
def test_ffmpeg_stdout_preserves_native_planar_yuv444p10le_program(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(64, 36, 4, 24, pixel_format="YUV444P10LE")
    source_frames = _structured_yuv444p10le(spec)
    raw = tmp_path / "encoder-input.yuv"
    video = tmp_path / "source-yuv.mkv"
    raw.write_bytes(source_frames)
    _encode_ffv1(
        raw,
        video,
        width=spec.width,
        height=spec.height,
        frame_rate=24,
        pixel_format="yuv444p10le",
    )
    archive = tmp_path / "direct-yuv-program.casv"
    result = pack_video_to_casv_program_stream(
        video,
        archive,
        frame_count=4,
        evidence_dir=tmp_path / "direct-yuv-program-evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        preserve_source_pixel_format=True,
        frames_per_segment=4,
        maximum_canonical_bytes=4 * 1024 * 1024,
    )
    restored = tmp_path / "direct-yuv-restored.yuv"
    verified = verify_casv_program_stream(archive, restored)

    assert restored.read_bytes() == source_frames
    assert verified["canonical_media"]["pixel_format"] == "YUV444P10LE"
    assert result["source_adapter"]["transport"] == "FFMPEG_STDOUT_PIPE"
    assert result["source_adapter"]["raw_intermediate_created"] is False


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_reference_player_uses_independent_program_decoder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = CanonicalVideoSpec(96, 54, 4, 24)
    source = make_structured_probe_video(spec)
    archive, _packed = _pack(tmp_path, source, spec)

    class CapturePipe:
        def __init__(self) -> None:
            self.payload = bytearray()
            self.closed = False

        def write(self, block: bytes) -> int:
            self.payload.extend(block)
            return len(block)

        def close(self) -> None:
            self.closed = True

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = CapturePipe()

        def wait(self) -> int:
            return 0

        def kill(self) -> None:
            return None

    process = FakeProcess()
    monkeypatch.setattr(
        "casulo.compression.casv_player.resolve_ffplay",
        lambda _explicit=None: tmp_path / "ffplay.exe",
    )
    monkeypatch.setattr(
        "casulo.compression.casv_player.subprocess.Popen",
        lambda _command, **_kwargs: process,
    )
    played = play_casv(archive)

    assert process.stdin.payload == source
    assert process.stdin.closed is True
    assert played["schema"] == "casulo.casv-reference-playback/0.3"
    assert played["generative_segments"] == 1
