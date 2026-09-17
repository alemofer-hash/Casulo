from __future__ import annotations

import io
import os
import random
from pathlib import Path

import pytest

from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_tiled_stream import pack_casv_tiled_stream_reader
from casulo.compression.independent_casv_tiled_stream import (
    CASV_TILED_STRIP_HEADER,
    CASV_TILED_STREAM_MAGIC,
    CASV_TILED_TILE_ENTRY,
    IndependentCASVTiledStreamError,
    inspect_casv_tiled_stream,
    unpack_casv_tiled_stream,
    verify_casv_tiled_stream,
)


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / (
    "casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime"
)
POLICY = ROOT / "examples" / "t-v2" / "compression_casv_tile.t"
FORCE_RAW = ROOT / "examples" / "t-v2" / "compression_casv_tile_force_raw.t"


def rgb_frames(spec: CanonicalVideoSpec) -> bytes:
    result = bytearray()
    for frame in range(spec.frame_count):
        for y in range(spec.height):
            for x in range(spec.width):
                result.extend(((x * 3 + frame) & 0xFF, (y * 7) & 0xFF, (x + y) & 0xFF))
    return bytes(result)


def yuv10_frames(spec: CanonicalVideoSpec) -> bytes:
    result = bytearray()
    for frame in range(spec.frame_count):
        for plane in range(3):
            for y in range(spec.height):
                for x in range(spec.width):
                    value = (plane * 211 + x * 5 + y * 3 + frame) % 1024
                    result.extend(value.to_bytes(2, "little"))
    return bytes(result)


def pack(tmp_path: Path, payload: bytes, spec: CanonicalVideoSpec, policy: Path = POLICY):
    return pack_casv_tiled_stream_reader(
        io.BytesIO(payload),
        spec,
        tmp_path / "video.casv",
        evidence_dir=tmp_path / "evidence",
        policy_source=policy,
        runtime=RUNTIME,
        tile_width=max(1, spec.width // 2),
        strip_height=max(1, spec.height // 2),
        source_label="canonical.bin",
    )


@pytest.mark.parametrize("pixel_format", ["RGB8", "YUV444P10LE"])
def test_tiled_archive_is_independently_byte_exact(tmp_path: Path, pixel_format: str) -> None:
    spec = CanonicalVideoSpec(32, 16, 2, 30, pixel_format=pixel_format)
    payload = rgb_frames(spec) if pixel_format == "RGB8" else yuv10_frames(spec)
    report = pack(tmp_path, payload, spec)

    assert report["status"] == "PASS"
    assert report["exact_media"] is True
    assert report["claims"]["spatial_tiling_implemented"] is True
    assert report["claims"]["full_frame_allocation_required"] is False
    assert report["authority"]["storage_decision_count"] == report["layout"]["tile_count"]
    assert report["authority"]["physical_batch_invocations"] == report["layout"]["record_count"]
    selected_payload = (
        report["selected_record_stream_bytes"]
        - report["layout"]["record_count"] * CASV_TILED_STRIP_HEADER.size
        - report["layout"]["tile_count"] * CASV_TILED_TILE_ENTRY.size
    )
    assert report["selected_tile_payload_bytes"] == selected_payload
    assert report["record_stream_advantage_bytes_vs_direct_zlib"] == (
        report["direct_whole_stream_zlib_bytes"]
        - report["selected_record_stream_bytes"]
    )
    assert report["archive_advantage_bytes_vs_direct_zlib"] == (
        report["direct_whole_stream_zlib_bytes"] - report["archive_bytes"]
    )
    assert report["cost_verdict_baseline"] == "RAW_CANONICAL_BYTES"
    assert "payload_advantage_bytes_vs_direct_zlib" not in report
    verified = verify_casv_tiled_stream(tmp_path / "video.casv")
    assert verified["canonical_sha256"] == report["canonical_source_sha256"]
    unpacked = unpack_casv_tiled_stream(tmp_path / "video.casv", tmp_path / "restored.bin")
    assert unpacked["status"] == "PASS"
    assert (tmp_path / "restored.bin").read_bytes() == payload


def test_only_t_policy_mutation_changes_storage_not_media(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(24, 12, 1, 24, pixel_format="RGB8")
    payload = rgb_frames(spec)
    normal = pack_casv_tiled_stream_reader(
        io.BytesIO(payload), spec, tmp_path / "normal.casv",
        evidence_dir=tmp_path / "normal-evidence", policy_source=POLICY,
        runtime=RUNTIME, tile_width=12, strip_height=6, source_label="same.bin",
    )
    forced = pack_casv_tiled_stream_reader(
        io.BytesIO(payload), spec, tmp_path / "forced.casv",
        evidence_dir=tmp_path / "forced-evidence", policy_source=FORCE_RAW,
        runtime=RUNTIME, tile_width=12, strip_height=6, source_label="same.bin",
    )

    assert normal["canonical_source_sha256"] == forced["canonical_source_sha256"]
    assert normal["authority"]["t_source_sha256"] != forced["authority"]["t_source_sha256"]
    assert forced["storage_modes"] == {"CANONICAL_RAW": forced["layout"]["tile_count"]}
    assert normal["storage_modes"] != forced["storage_modes"]


def test_incompressible_tiles_fall_back_without_false_claim(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(48, 24, 1, 24, pixel_format="RGB8")
    payload = random.Random(19).randbytes(spec.expected_bytes)
    report = pack(tmp_path, payload, spec)

    assert report["cost_verdict"] in {"ACCEPT", "REJECT"}
    assert report["claims"]["natural_video_compression_proven"] is False
    assert report["claims"]["near_total_compression_proven"] is False


def test_corrupted_strip_is_rejected_before_decode(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(24, 12, 1, 24, pixel_format="RGB8")
    payload = rgb_frames(spec)
    pack(tmp_path, payload, spec)
    archive = tmp_path / "video.casv"
    inspected = inspect_casv_tiled_stream(archive)
    record = inspected["manifest"]["records"][0]
    corrupted = bytearray(archive.read_bytes())
    corrupted[record["stored_offset"] + record["stored_length"] - 1] ^= 0x40
    broken = tmp_path / "broken.casv"
    broken.write_bytes(corrupted)

    with pytest.raises(IndependentCASVTiledStreamError, match="strip hash differs"):
        verify_casv_tiled_stream(broken)


def test_truncated_archive_and_wrong_magic_are_rejected(tmp_path: Path) -> None:
    truncated = tmp_path / "truncated.casv"
    truncated.write_bytes(CASV_TILED_STREAM_MAGIC)
    with pytest.raises(IndependentCASVTiledStreamError, match="truncated"):
        inspect_casv_tiled_stream(truncated)

    wrong = tmp_path / "wrong.casv"
    wrong.write_bytes(b"NOTCASV!" + b"0" * 100)
    with pytest.raises(IndependentCASVTiledStreamError):
        inspect_casv_tiled_stream(wrong)
