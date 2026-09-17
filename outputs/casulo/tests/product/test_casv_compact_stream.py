from __future__ import annotations

import hashlib
import io
import os
import random
from pathlib import Path

import pytest

from casulo.compression.casv_compact_stream import (
    CASVCompactStreamError,
    pack_casv_compact_stream_reader,
)
from casulo.compression.casv_compact_repack import (
    CASVCompactRepackError,
    repack_tiled_to_compact_campaign,
)
from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_player import play_casv
from casulo.compression.independent_casv_compact_stream import (
    CASV_COMPACT_FOOTER,
    CASV_COMPACT_HEADER,
    CASV_COMPACT_MAGIC,
    CASV_COMPACT_RECORD_HEADER,
    CASV_COMPACT_TILE_ENTRY,
    IndependentCASVCompactStreamError,
    inspect_casv_compact_stream,
    unpack_casv_compact_stream,
    verify_casv_compact_stream,
)
from casulo.compression.casv_tiled_stream import pack_casv_tiled_stream_reader


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / (
    "casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime"
)
POLICY = ROOT / "examples" / "t-v2" / "compression_casv_compact.t"
FORCE_RAW = ROOT / "examples" / "t-v2" / "compression_casv_compact_force_raw.t"
TILED_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_tile.t"


def rgb_frames(spec: CanonicalVideoSpec) -> bytes:
    output = bytearray()
    for frame in range(spec.frame_count):
        for y in range(spec.height):
            for x in range(spec.width):
                output.extend(
                    (
                        (x * 3 + frame) & 0xFF,
                        (y * 7) & 0xFF,
                        (x + y) & 0xFF,
                    )
                )
    return bytes(output)


def yuv10_frames(spec: CanonicalVideoSpec) -> bytes:
    output = bytearray()
    for frame in range(spec.frame_count):
        for plane in range(3):
            for y in range(spec.height):
                for x in range(spec.width):
                    value = (plane * 211 + x * 5 + y * 3 + frame) % 1024
                    output.extend(value.to_bytes(2, "little"))
    return bytes(output)


def spatial_ramp_frames(spec: CanonicalVideoSpec) -> bytes:
    return bytes(
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


def pack(
    root: Path,
    payload: bytes,
    spec: CanonicalVideoSpec,
    *,
    policy: Path = POLICY,
) -> dict[str, object]:
    return pack_casv_compact_stream_reader(
        io.BytesIO(payload),
        spec,
        root / "video.casv",
        evidence_dir=root / "evidence",
        policy_source=policy,
        runtime=RUNTIME,
        tile_width=max(1, spec.width // 2),
        strip_height=max(1, spec.height // 2),
        source_label="canonical.bin",
    )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
@pytest.mark.parametrize("pixel_format", ["RGB8", "YUV444P10LE"])
def test_compact_archive_is_exact_and_accounted(
    tmp_path: Path,
    pixel_format: str,
) -> None:
    spec = CanonicalVideoSpec(32, 16, 2, 30, pixel_format=pixel_format)
    payload = rgb_frames(spec) if pixel_format == "RGB8" else yuv10_frames(spec)
    report = pack(tmp_path, payload, spec)

    assert report["status"] in {"PASS_BEATS_DIRECT_ZLIB", "EXACT_NONCOMPETITIVE"}
    assert report["archive_published"] is True
    assert report["candidate_archive_bytes"] == (
        report["selected_record_stream_bytes"] + report["fixed_container_bytes"]
    )
    assert report["fixed_container_bytes"] == (
        len(CASV_COMPACT_MAGIC) + CASV_COMPACT_HEADER.size + CASV_COMPACT_FOOTER.size
    )
    expected_payload = (
        report["selected_record_stream_bytes"]
        - report["layout"]["record_count"] * CASV_COMPACT_RECORD_HEADER.size
        - report["layout"]["tile_count"] * CASV_COMPACT_TILE_ENTRY.size
    )
    assert report["selected_tile_payload_bytes"] == expected_payload
    assert report["archive_advantage_bytes_vs_direct_zlib"] == (
        report["direct_whole_stream_zlib_bytes"]
        - report["candidate_archive_bytes"]
    )
    assert report["reference_baseline"]["algorithm"] == "ZLIB_RFC1950_DEFLATE"
    assert report["reference_baseline"]["whole_canonical_stream"] is True
    assert report["authority_at_commit"]["receipt_count"] == report["layout"]["tile_count"]
    assert report["authority_final"]["receipt_count"] == report["layout"]["tile_count"] + 1
    assert report["claims"]["t_judgement_consumed_before_publication"] is True

    verified = verify_casv_compact_stream(tmp_path / "video.casv")
    assert verified["canonical_sha256"] == report["canonical_source_sha256"]
    unpack_casv_compact_stream(tmp_path / "video.casv", tmp_path / "restored.bin")
    assert (tmp_path / "restored.bin").read_bytes() == payload


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_incompressible_candidate_is_preserved_but_not_published(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(48, 24, 1, 24)
    payload = random.Random(20260910).randbytes(spec.expected_bytes)
    report = pack(tmp_path, payload, spec)

    assert report["status"] == "REJECTED_NO_PUBLICATION"
    assert report["cost_verdict"] == "REJECT"
    assert report["archive_published"] is False
    assert not (tmp_path / "video.casv").exists()
    rejected = tmp_path / "evidence" / "rejected-candidate.casv"
    assert rejected.is_file()
    assert verify_casv_compact_stream(rejected)["canonical_sha256"] == (
        report["canonical_source_sha256"]
    )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_t_policy_mutation_can_causally_prevent_publication(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(128, 72, 2, 24)
    payload = spatial_ramp_frames(spec)
    normal = pack(tmp_path / "normal", payload, spec)
    forced = pack(tmp_path / "forced", payload, spec, policy=FORCE_RAW)

    assert normal["archive_published"] is True
    assert forced["archive_published"] is False
    assert forced["storage_modes"] == {"CANONICAL_RAW": forced["layout"]["tile_count"]}
    assert normal["authority_final"]["tcap_sha256"] != forced["authority_final"]["tcap_sha256"]
    rejected = Path(forced["candidate_path"])
    assert verify_casv_compact_stream(rejected)["canonical_sha256"] == (
        normal["canonical_source_sha256"]
    )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_content_corruption_is_rejected(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(32, 16, 2, 24)
    report = pack(tmp_path, rgb_frames(spec), spec)
    assert report["archive_published"] is True
    archive = tmp_path / "video.casv"
    inspected = inspect_casv_compact_stream(archive)
    record = inspected["records"][0]
    corrupted = bytearray(archive.read_bytes())
    corrupted[record["payload_offset"]] ^= 0x80
    broken = tmp_path / "broken.casv"
    broken.write_bytes(corrupted)

    with pytest.raises(IndependentCASVCompactStreamError, match="content hash differs"):
        inspect_casv_compact_stream(broken)


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_short_or_long_input_never_publishes(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(16, 8, 1, 24)
    payload = rgb_frames(spec)
    for name, invalid in (("short", payload[:-1]), ("long", payload + b"x")):
        root = tmp_path / name
        with pytest.raises(CASVCompactStreamError, match="canonical stream"):
            pack(root, invalid, spec)
        assert not (root / "video.casv").exists()
        assert not (root / "video.casv.casv-part").exists()


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_sealed_tiled_archive_can_be_repacked_without_ffmpeg(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(48, 24, 2, 24)
    payload = rgb_frames(spec)
    source = tmp_path / "source-v04.casv"
    pack_casv_tiled_stream_reader(
        io.BytesIO(payload),
        spec,
        source,
        evidence_dir=tmp_path / "source-v04-evidence",
        policy_source=TILED_POLICY,
        runtime=RUNTIME,
        tile_width=32,
        strip_height=18,
        source_label="original.rgb",
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    campaign = tmp_path / "repack"
    result = repack_tiled_to_compact_campaign(
        source,
        campaign,
        expected_source_archive_sha256=source_hash,
        policy_source=POLICY,
        runtime=RUNTIME,
        tile_width=32,
        strip_height=18,
    )

    assert result["status"] == "PASS"
    assert result["source"]["ffmpeg_executed_during_repack"] is False
    assert result["gates"]["canonical_reconstruction_hash_preserved"] is True
    assert (campaign / "canonical-source.bin").read_bytes() == payload


def test_repack_rejects_unfrozen_source_hash_before_campaign_creation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-v04.casv"
    source.write_bytes(b"not-an-archive")
    campaign = tmp_path / "repack"
    with pytest.raises(CASVCompactRepackError, match="hash differs"):
        repack_tiled_to_compact_campaign(
            source,
            campaign,
            expected_source_archive_sha256="0" * 64,
            policy_source=POLICY,
            runtime=RUNTIME,
        )
    assert not campaign.exists()


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_reference_player_uses_independent_compact_decoder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = CanonicalVideoSpec(32, 16, 2, 24)
    payload = rgb_frames(spec)
    report = pack(tmp_path, payload, spec)
    assert report["archive_published"] is True

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
    played = play_casv(tmp_path / "video.casv")

    assert process.stdin.payload == payload
    assert process.stdin.closed is True
    assert played["schema"] == "casulo.casv-reference-playback/0.5"
    assert played["canonical_bytes_piped"] == len(payload)


def test_independent_compact_decoder_has_no_forward_path_imports() -> None:
    source = (
        ROOT / "src/casulo/compression/independent_casv_compact_stream.py"
    ).read_text(encoding="utf-8")
    assert "from .casv_compact_stream import" not in source
    assert "from .casv_tile_ir import" not in source
    assert "from .casv_tile_authority import" not in source
