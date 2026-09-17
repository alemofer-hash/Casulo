from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import pytest

from casulo.compression.casv_archive import pack_casv_frames
from casulo.compression.casv_import import (
    CASVImportError,
    import_video_to_canonical,
    import_video_to_canonical_rgb8,
)
from casulo.compression.casv_ir import (
    CASVIRError,
    CanonicalVideoSpec,
    infer_rectilinear_program,
)
from casulo.compression.casv_probe import (
    make_noise_probe_video,
    make_structured_probe_video,
)
from casulo.compression.casv_player import build_ffplay_command, play_casv
from casulo.compression.independent_casv import (
    IndependentCASVError,
    reconstruct_casv_independently,
)
from casulo.compression.tooling import resolve_tool


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
DEFAULT_POLICY = ROOT / "examples" / "t-v2" / "compression_casv.t"
RAW_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_force_raw.t"


def _spec() -> CanonicalVideoSpec:
    return CanonicalVideoSpec(96, 54, 12, 24)


def test_rectilinear_inference_builds_exact_zero_residual_program() -> None:
    spec = _spec()
    frames = make_structured_probe_video(spec)
    inference = infer_rectilinear_program(frames, spec)
    assert inference.detected_tracks == 2
    assert inference.rendered == frames
    assert inference.residual_nonzero_bytes == 0
    assert inference.exact_predicted_pixels == inference.total_pixels


def test_canonical_contract_rejects_wrong_payload_length() -> None:
    with pytest.raises(CASVIRError, match="payload length differs"):
        infer_rectilinear_program(b"too-short", _spec())


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_casv_is_native_exact_and_t_mutation_changes_representation(tmp_path: Path) -> None:
    spec = _spec()
    frames = make_structured_probe_video(spec)
    default_archive = tmp_path / "default.casv"
    raw_archive = tmp_path / "raw.casv"
    default = pack_casv_frames(
        frames,
        spec,
        default_archive,
        evidence_dir=tmp_path / "default-evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
    )
    forced = pack_casv_frames(
        frames,
        spec,
        raw_archive,
        evidence_dir=tmp_path / "raw-evidence",
        policy_source=RAW_POLICY,
        runtime=RUNTIME,
    )
    default_verified = reconstruct_casv_independently(default_archive)
    raw_verified = reconstruct_casv_independently(raw_archive)
    assert default_archive.read_bytes().startswith(b"CASV\x00\x01\r\n")
    assert not default_archive.read_bytes().startswith(b"PK")
    assert default["storage_mode"] == "GENERATIVE_EXACT"
    assert forced["storage_mode"] == "CANONICAL_RAW"
    assert default["authority"]["tcap_sha256"] != forced["authority"]["tcap_sha256"]
    assert default_verified["canonical_sha256"] == raw_verified["canonical_sha256"]
    assert default_verified["foreign_bitstreams_embedded"] is False
    assert default["cost_verdict"] == "ACCEPT"


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_residual_closes_unmodelled_information_exactly(tmp_path: Path) -> None:
    spec = _spec()
    frames = bytearray(make_structured_probe_video(spec))
    offset = (5 * spec.frame_bytes) + (2 * spec.width + 3) * 3
    frames[offset : offset + 3] = b"\x7f\x11\xe3"
    result = pack_casv_frames(
        bytes(frames),
        spec,
        tmp_path / "residual.casv",
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
    )
    verified = reconstruct_casv_independently(tmp_path / "residual.casv")
    assert result["exact_media"] is True
    assert verified["canonical_sha256"] == result["canonical_source_sha256"]
    if result["storage_mode"] == "GENERATIVE_EXACT":
        assert result["residual"]["nonzero_bytes"] > 0


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_noise_control_is_not_reported_as_compression(tmp_path: Path) -> None:
    spec = _spec()
    noise = make_noise_probe_video(spec)
    result = pack_casv_frames(
        noise,
        spec,
        tmp_path / "noise.casv",
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
    )
    assert result["storage_mode"] == "CANONICAL_RAW"
    assert result["archive_bytes"] > len(noise)
    assert result["cost_verdict"] == "REJECT"
    assert reconstruct_casv_independently(tmp_path / "noise.casv")["status"] == "PASS"


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_independent_decoder_rejects_corrupted_section(tmp_path: Path) -> None:
    spec = _spec()
    frames = make_structured_probe_video(spec)
    archive = tmp_path / "valid.casv"
    pack_casv_frames(
        frames,
        spec,
        archive,
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
    )
    payload = bytearray(archive.read_bytes())
    _magic, manifest_length = struct.unpack(">8sQ", payload[:16])
    manifest = json.loads(payload[16 : 16 + manifest_length])
    assert manifest["sections"]
    payload[-1] ^= 1
    corrupt = tmp_path / "corrupt.casv"
    corrupt.write_bytes(payload)
    with pytest.raises(IndependentCASVError, match="section hash differs"):
        reconstruct_casv_independently(corrupt)


def test_independent_decoder_has_no_forward_path_imports() -> None:
    source = (ROOT / "src/casulo/compression/independent_casv.py").read_text(
        encoding="utf-8"
    )
    assert "casv_archive" not in source
    assert "casv_authority" not in source
    assert "casv_ir" not in source


def test_reference_player_command_is_argument_safe(tmp_path: Path) -> None:
    command = build_ffplay_command(
        tmp_path / "ffplay.exe",
        tmp_path / "frames with spaces.rgb",
        {
            "width": 96,
            "height": 54,
            "fps_numerator": 24_000,
            "fps_denominator": 1_001,
        },
    )
    assert command[0].endswith("ffplay.exe")
    assert command[-1].endswith("frames with spaces.rgb")
    assert "24000/1001" in command
    assert "shell" not in " ".join(command).lower()


@pytest.mark.skipif(
    not RUNTIME.is_file() or resolve_tool("ffmpeg") is None or resolve_tool("ffprobe") is None,
    reason="CASV import toolchain unavailable",
)
def test_video_import_decodes_canonical_media_without_embedding_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = CanonicalVideoSpec(96, 54, 6, 24)
    frames = make_structured_probe_video(spec)
    raw = tmp_path / "source.rgb"
    source_video = tmp_path / "source.mkv"
    raw.write_bytes(frames)
    ffmpeg = resolve_tool("ffmpeg")
    assert ffmpeg is not None
    encoded = subprocess.run(
        [
            str(ffmpeg),
            "-nostdin",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-video_size",
            "96x54",
            "-framerate",
            "24",
            "-i",
            str(raw),
            "-c:v",
            "ffv1",
            "-y",
            str(source_video),
        ],
        check=False,
        capture_output=True,
        shell=False,
    )
    assert encoded.returncode == 0, encoded.stderr.decode(errors="replace")
    imported = import_video_to_canonical_rgb8(source_video, max_frames=6)
    assert imported.frames == frames
    assert imported.spec == spec
    assert imported.provenance["source_bitstream_embedded"] is False
    with pytest.raises(CASVImportError, match="crop is outside"):
        import_video_to_canonical_rgb8(
            source_video,
            max_frames=1,
            crop=(95, 53, 2, 2),
        )

    archive = tmp_path / "imported.casv"
    packed = pack_casv_frames(
        imported.frames,
        imported.spec,
        archive,
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        source_label=source_video.name,
        source_provenance=imported.provenance,
    )
    verified = reconstruct_casv_independently(archive)
    assert verified["canonical_sha256"] == imported.provenance["canonical_sha256"]
    assert packed["source_adapter"]["source_bitstream_embedded"] is False
    assert packed["source_adapter"]["canonicalization"] == {
        "contract": "EXACT_AFTER_RGB8_CANONICALIZATION",
        "output_pixel_format": "RGB8",
        "source_container_identity_preserved": False,
        "source_native_sample_identity_claimed": False,
        "transform": "FFMPEG_DECODE_AND_RGB24_CONVERSION",
    }
    assert packed["claims"]["canonical_rgb8_exact"] is True
    assert packed["claims"]["source_native_sample_identity_proven"] is False
    assert source_video.read_bytes() not in archive.read_bytes()

    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> object:
        observed["command"] = command
        observed["kwargs"] = kwargs
        observed["raw_exists_during_playback"] = Path(command[-1]).is_file()
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(
        "casulo.compression.casv_player.resolve_ffplay",
        lambda _explicit=None: ffmpeg.with_name("ffplay.exe"),
    )
    monkeypatch.setattr("casulo.compression.casv_player.subprocess.run", fake_run)
    played = play_casv(archive)
    assert played["status"] == "PASS"
    assert played["player_profile"] == "REFERENCE_PIPE_BOUNDED_MEMORY_NOT_INCREMENTAL_DECODE"
    assert observed["command"][-1] == "pipe:0"  # type: ignore[index]
    assert observed["raw_exists_during_playback"] is False
    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["check"] is False
    assert kwargs["shell"] is False
    assert kwargs["input"] == frames
    assert played["canonical_bytes_piped"] == len(frames)


@pytest.mark.skipif(
    not RUNTIME.is_file() or resolve_tool("ffmpeg") is None or resolve_tool("ffprobe") is None,
    reason="CASV native-sample import toolchain unavailable",
)
def test_native_yuv444p10le_samples_survive_casv_roundtrip(tmp_path: Path) -> None:
    width, height, frame_count = 16, 8, 3
    sample_count = width * height * 3 * frame_count
    native_samples = b"".join(
        struct.pack("<H", (index * 37 + 11) % 1024) for index in range(sample_count)
    )
    raw = tmp_path / "source-yuv444p10le.raw"
    source_video = tmp_path / "source-yuv444p10le.mkv"
    raw.write_bytes(native_samples)
    ffmpeg = resolve_tool("ffmpeg")
    assert ffmpeg is not None
    encoded = subprocess.run(
        [
            str(ffmpeg),
            "-nostdin",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p10le",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            "24",
            "-i",
            str(raw),
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "yuv444p10le",
            "-y",
            str(source_video),
        ],
        check=False,
        capture_output=True,
        shell=False,
    )
    assert encoded.returncode == 0, encoded.stderr.decode(errors="replace")

    imported = import_video_to_canonical(
        source_video,
        max_frames=frame_count,
        preserve_source_pixel_format=True,
    )
    assert imported.spec.pixel_format == "YUV444P10LE"
    assert imported.frames == native_samples
    assert imported.provenance["canonicalization"]["contract"] == (
        "EXACT_FFMPEG_DECODED_NATIVE_SAMPLE_STREAM"
    )
    assert imported.provenance["kind"] == "ffmpeg-native-sample-bounded-import"
    archive = tmp_path / "native-samples.casv"
    packed = pack_casv_frames(
        imported.frames,
        imported.spec,
        archive,
        evidence_dir=tmp_path / "native-evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        source_label=source_video.name,
        source_provenance=imported.provenance,
    )
    restored = tmp_path / "restored-yuv444p10le.raw"
    verified = reconstruct_casv_independently(archive, restored)
    assert restored.read_bytes() == native_samples
    assert verified["canonical_media"]["pixel_format"] == "YUV444P10LE"
    assert packed["representation"]["generative_candidate_available"] is False
    assert packed["storage_mode"] in {"CANONICAL_ZLIB", "CANONICAL_RAW"}
    assert packed["claims"]["source_native_sample_identity_proven"] is True


def test_video_import_rejects_missing_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError):
        import_video_to_canonical_rgb8(
            missing,
            max_frames=1,
            crop=(0, 0, 1, 1),
        )
