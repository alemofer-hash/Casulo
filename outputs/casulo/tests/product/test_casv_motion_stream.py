from __future__ import annotations

import hashlib
import io
import os
import random
from pathlib import Path

import pytest

from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_motion_ir import (
    MOTION_VECTOR,
    build_motion_candidates,
    parse_motion_payload,
    restore_motion,
)
from casulo.compression.casv_motion_campaign import (
    CASVMotionCampaignError,
    run_motion_holdout_campaign,
)
from casulo.compression.casv_motion_stream import pack_casv_motion_stream_reader
from casulo.compression.independent_casv_motion_stream import (
    IndependentCASVMotionStreamError,
    inspect_casv_motion_stream,
    unpack_casv_motion_stream,
    verify_casv_motion_stream,
)


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = (
    ROOT
    / "t-runtime"
    / "target"
    / "release"
    / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
)
POLICY = ROOT / "examples" / "t-v2" / "compression_casv_motion.t"
FORCE_NO_MOTION = (
    ROOT / "examples" / "t-v2" / "compression_casv_motion_force_no_motion.t"
)


def shifted_rgb_fixture(spec: CanonicalVideoSpec, dx: int = 3) -> bytes:
    assert spec.pixel_format == "RGB8"
    randomizer = random.Random(20260911)
    frame_bytes = spec.width * spec.height * 3
    first = randomizer.randbytes(frame_bytes)
    frames = [first]
    previous = first
    row_bytes = spec.width * 3
    for _frame in range(1, spec.frame_count):
        current = bytearray(frame_bytes)
        for y in range(spec.height):
            row = y * row_bytes
            copied = (spec.width - dx) * 3
            current[row : row + copied] = previous[
                row + dx * 3 : row + dx * 3 + copied
            ]
            current[row + copied : row + row_bytes] = randomizer.randbytes(dx * 3)
        frames.append(bytes(current))
        previous = bytes(current)
    return b"".join(frames)


def pack(
    root: Path,
    payload: bytes,
    spec: CanonicalVideoSpec,
    *,
    policy: Path = POLICY,
    keyframe_interval: int = 8,
) -> dict[str, object]:
    return pack_casv_motion_stream_reader(
        io.BytesIO(payload),
        spec,
        root / "video.casv",
        evidence_dir=root / "evidence",
        policy_source=policy,
        runtime=RUNTIME,
        tile_width=16,
        strip_height=16,
        keyframe_interval=keyframe_interval,
        motion_radius=4,
        score_stride_pixels=2,
        motion_finalists=4,
        source_label="canonical.rgb",
    )


def test_motion_ir_accounts_vector_prefix_and_restores_exactly() -> None:
    current = bytes(range(96))
    best_reference = current
    other_reference = bytes(reversed(current))
    candidates = build_motion_candidates(
        current,
        ((2, 0, best_reference), (-1, 0, other_reference)),
        width=16,
        height=2,
        bytes_per_pixel=3,
        radius=4,
        score_stride_pixels=1,
        finalists=2,
    )
    for mode, payload in candidates.payloads.items():
        dx, dy, compressed = parse_motion_payload(payload, 4)
        assert (dx, dy) == (2, 0)
        assert payload[: MOTION_VECTOR.size] == MOTION_VECTOR.pack(2, 0)
        import zlib

        restored = restore_motion(mode, zlib.decompress(compressed), best_reference)
        assert restored == current


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_motion_archive_executes_t_and_roundtrips(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(64, 32, 3, 24)
    payload = shifted_rgb_fixture(spec)
    report = pack(tmp_path, payload, spec)

    assert report["motion_candidate_tiles"] > 0
    assert report["motion_selected_tiles"] > 0
    assert report["claims"]["motion_vector_cost_in_bitstream"] is True
    archive = Path(report["candidate_path"])
    verified = verify_casv_motion_stream(archive)
    assert verified["canonical_sha256"] == hashlib.sha256(payload).hexdigest()
    assert verified["motion_tile_count"] == report["motion_selected_tiles"]
    unpack_casv_motion_stream(archive, tmp_path / "restored.rgb")
    assert (tmp_path / "restored.rgb").read_bytes() == payload


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_keyframe_forbids_temporal_and_motion_references(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(64, 32, 3, 24)
    report = pack(
        tmp_path,
        shifted_rgb_fixture(spec),
        spec,
        keyframe_interval=2,
    )
    inspected = inspect_casv_motion_stream(Path(report["candidate_path"]))
    records = [record for record in inspected["records"] if record["frame_index"] == 2]
    assert records
    assert all(
        not mode.startswith(("TEMPORAL_", "MOTION_"))
        for record in records
        for mode in record["tile_modes"]
    )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_t_only_mutation_disables_motion_but_preserves_exactness(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(64, 32, 3, 24)
    payload = shifted_rgb_fixture(spec)
    default = pack(tmp_path / "default", payload, spec)
    mutated = pack(
        tmp_path / "mutated",
        payload,
        spec,
        policy=FORCE_NO_MOTION,
    )

    assert default["motion_selected_tiles"] > 0
    assert mutated["motion_selected_tiles"] == 0
    assert (
        default["authority_final"]["tcap_sha256"]
        != mutated["authority_final"]["tcap_sha256"]
    )
    assert mutated["candidate_archive_bytes"] > default["candidate_archive_bytes"]
    assert (
        verify_casv_motion_stream(Path(mutated["candidate_path"]))[
            "canonical_sha256"
        ]
        == default["canonical_source_sha256"]
    )


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_independent_decoder_rejects_out_of_radius_motion_vector(
    tmp_path: Path,
) -> None:
    spec = CanonicalVideoSpec(64, 32, 3, 24)
    report = pack(tmp_path, shifted_rgb_fixture(spec), spec)
    archive = Path(report["candidate_path"])
    inspected = inspect_casv_motion_stream(archive)
    corrupted = bytearray(archive.read_bytes())
    target_found = False
    for record in inspected["records"]:
        cursor = record["payload_offset"]
        for mode, stored_length in zip(
            record["tile_modes"], record["tile_stored_lengths"], strict=True
        ):
            if mode.startswith("MOTION_"):
                corrupted[cursor] = 127
                target_found = True
                break
            cursor += stored_length
        if target_found:
            break
    assert target_found
    broken = tmp_path / "invalid-vector.casv"
    broken.write_bytes(corrupted)

    with pytest.raises(
        IndependentCASVMotionStreamError,
        match="motion vector is invalid",
    ):
        inspect_casv_motion_stream(broken)


def test_independent_motion_decoder_has_no_forward_imports() -> None:
    source = (
        ROOT / "src/casulo/compression/independent_casv_motion_stream.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "from .casv_motion_stream import",
        "from .casv_motion_ir import",
        "from .casv_temporal_ir import",
        "from .casv_tile_ir import",
        "from .casv_motion_authority import",
    )
    assert all(statement not in source for statement in forbidden)


def test_campaign_rejects_wrong_preregistration_hash_before_output(
    tmp_path: Path,
) -> None:
    preregistration = tmp_path / "protocol.json"
    preregistration.write_text("{}", encoding="utf-8")
    output = tmp_path / "campaign"

    with pytest.raises(CASVMotionCampaignError, match="preregistration hash differs"):
        run_motion_holdout_campaign(
            preregistration,
            output,
            default_policy=POLICY,
            force_no_motion_policy=FORCE_NO_MOTION,
            runtime=RUNTIME,
        )

    assert not output.exists()
