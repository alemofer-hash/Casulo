from __future__ import annotations

import hashlib
import io
import os
import random
from pathlib import Path

import pytest

from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_player import play_casv
from casulo.compression.casv_temporal_repack import (
    CASVTemporalRepackError,
    _size_classification,
    repack_program_to_temporal_campaign,
)
from casulo.compression.casv_temporal_stream import (
    CASVTemporalStreamError,
    pack_casv_temporal_stream_reader,
)
from casulo.compression.independent_casv_temporal_stream import (
    IndependentCASVTemporalStreamError,
    inspect_casv_temporal_stream,
    unpack_casv_temporal_stream,
    verify_casv_temporal_stream,
)


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = (
    ROOT
    / "t-runtime"
    / "target"
    / "release"
    / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
)
POLICY = ROOT / "examples" / "t-v2" / "compression_casv_temporal.t"
FORCE_SPATIAL = ROOT / "examples" / "t-v2" / "compression_casv_temporal_force_spatial.t"


def temporal_fixture(spec: CanonicalVideoSpec) -> bytes:
    frame_bytes = spec.expected_bytes // spec.frame_count
    base = bytearray(random.Random(20260910).randbytes(frame_bytes))
    frames = []
    for frame in range(spec.frame_count):
        current = bytearray(base)
        for index in range(frame * 31, min(frame * 31 + 97, frame_bytes)):
            current[index] = (current[index] + frame * 7) & 0xFF
        frames.append(bytes(current))
    return b"".join(frames)


def pack(
    root: Path,
    payload: bytes,
    spec: CanonicalVideoSpec,
    *,
    policy: Path = POLICY,
    keyframe_interval: int = 8,
) -> dict[str, object]:
    return pack_casv_temporal_stream_reader(
        io.BytesIO(payload),
        spec,
        root / "video.casv",
        evidence_dir=root / "evidence",
        policy_source=policy,
        runtime=RUNTIME,
        tile_width=64,
        strip_height=48,
        keyframe_interval=keyframe_interval,
        source_label="canonical.rgb",
    )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_temporal_archive_executes_and_roundtrips(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(128, 96, 3, 24)
    payload = temporal_fixture(spec)
    report = pack(tmp_path, payload, spec)

    assert report["status"] == "PASS_BEATS_DIRECT_ZLIB"
    assert report["archive_published"] is True
    assert report["temporal_candidate_tiles"] > 0
    assert report["temporal_selected_tiles"] > 0
    assert (
        report["storage_modes"].get("TEMPORAL_XOR_ZLIB", 0)
        + report["storage_modes"].get("TEMPORAL_SUB_ZLIB", 0)
        == report["temporal_selected_tiles"]
    )
    verified = verify_casv_temporal_stream(tmp_path / "video.casv")
    assert verified["canonical_sha256"] == hashlib.sha256(payload).hexdigest()
    assert verified["temporal_tile_count"] == report["temporal_selected_tiles"]
    unpack_casv_temporal_stream(tmp_path / "video.casv", tmp_path / "restored.rgb")
    assert (tmp_path / "restored.rgb").read_bytes() == payload


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_keyframe_forbids_temporal_reference(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(128, 96, 3, 24)
    report = pack(tmp_path, temporal_fixture(spec), spec, keyframe_interval=2)
    inspected = inspect_casv_temporal_stream(Path(report["candidate_path"]))

    keyframe_records = [
        record for record in inspected["records"] if record["frame_index"] == 2
    ]
    assert keyframe_records
    assert all(
        not mode.startswith("TEMPORAL_")
        for record in keyframe_records
        for mode in record["tile_modes"]
    )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_t_mutation_disables_temporal_choices_but_not_exactness(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(128, 96, 3, 24)
    payload = temporal_fixture(spec)
    default = pack(tmp_path / "default", payload, spec)
    spatial = pack(tmp_path / "spatial", payload, spec, policy=FORCE_SPATIAL)

    assert default["temporal_selected_tiles"] > 0
    assert spatial["temporal_selected_tiles"] == 0
    assert (
        default["authority_final"]["tcap_sha256"]
        != spatial["authority_final"]["tcap_sha256"]
    )
    assert spatial["candidate_archive_bytes"] > default["candidate_archive_bytes"]
    assert (
        verify_casv_temporal_stream(Path(spatial["candidate_path"]))["canonical_sha256"]
        == default["canonical_source_sha256"]
    )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_temporal_content_corruption_is_rejected(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(128, 96, 3, 24)
    report = pack(tmp_path, temporal_fixture(spec), spec)
    archive = Path(report["candidate_path"])
    inspected = inspect_casv_temporal_stream(archive)
    corrupted = bytearray(archive.read_bytes())
    corrupted[inspected["records"][0]["payload_offset"]] ^= 0x20
    broken = tmp_path / "broken.casv"
    broken.write_bytes(corrupted)

    with pytest.raises(
        IndependentCASVTemporalStreamError, match="content hash differs"
    ):
        inspect_casv_temporal_stream(broken)


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_reference_player_uses_independent_temporal_decoder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = CanonicalVideoSpec(128, 96, 3, 24)
    payload = temporal_fixture(spec)
    report = pack(tmp_path, payload, spec)

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
    played = play_casv(Path(report["candidate_path"]))

    assert process.stdin.payload == payload
    assert process.stdin.closed is True
    assert played["schema"] == "casulo.casv-reference-playback/0.6"
    assert played["canonical_bytes_piped"] == len(payload)


def test_invalid_keyframe_interval_fails_before_output(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(16, 8, 1, 24)
    with pytest.raises(CASVTemporalStreamError, match="keyframe interval"):
        pack(tmp_path, bytes(spec.expected_bytes), spec, keyframe_interval=0)
    assert not (tmp_path / "video.casv").exists()
    assert not (tmp_path / "evidence").exists()


def test_independent_temporal_decoder_has_no_forward_imports() -> None:
    source = (
        ROOT / "src/casulo/compression/independent_casv_temporal_stream.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "from .casv_temporal_stream import",
        "from .casv_temporal_ir import",
        "from .casv_tile_ir import",
        "from .casv_tile_authority import",
    )
    assert all(statement not in source for statement in forbidden)


def test_repack_rejects_wrong_frozen_source_hash_before_campaign(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sealed-v03.casv"
    source.write_bytes(b"not-the-frozen-source")
    campaign = tmp_path / "campaign"

    with pytest.raises(
        CASVTemporalRepackError,
        match="archive hash differs from the frozen expected hash",
    ):
        repack_program_to_temporal_campaign(
            source,
            campaign,
            expected_source_archive_sha256="0" * 64,
            policy_source=POLICY,
            runtime=RUNTIME,
        )

    assert not campaign.exists()


@pytest.mark.parametrize(
    ("candidate", "baseline", "canonical", "expected"),
    (
        (50, 100, 1_000, "BREAKTHROUGH_CANDIDATE"),
        (70, 100, 500, "SUBSTANTIAL_ADVANTAGE"),
        (85, 100, 500, "MATERIAL_ADVANTAGE"),
        (94, 100, 500, "SMALL_ADVANTAGE"),
        (104, 100, 500, "COMPETITIVE"),
        (106, 100, 500, "NEGATIVE"),
    ),
)
def test_mature_baseline_classification_is_frozen_before_results(
    candidate: int,
    baseline: int,
    canonical: int,
    expected: str,
) -> None:
    assert _size_classification(candidate, baseline, canonical) == expected
