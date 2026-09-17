from __future__ import annotations

import hashlib
import os
import struct
import zipfile
from pathlib import Path

import pytest

from casulo.compression.content_chunking import ranges_for_file
from casulo.compression.independent_structural import (
    IndependentReconstructionError,
    reconstruct_independently,
)
from casulo.compression.mp4_hevc import MP4AnalysisError, analyze_mp4_hevc
from casulo.compression.reversible_transforms import candidate_set, decode_transform
from casulo.compression.structural_archive import pack_structural


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
DEFAULT_POLICY = ROOT / "examples" / "t-v2" / "compression_structural.t"
RAW_POLICY = ROOT / "examples" / "t-v2" / "compression_structural_force_raw.t"


def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def hevc_file(path: Path, media: bytes | None = None) -> bytes:
    hvcc_header = bytes([1, 4]) + bytes(10) + bytes([120]) + bytes(8) + bytes([3, 3])
    arrays = b"".join(
        bytes([nal_type]) + struct.pack(">H", 1) + struct.pack(">H", len(unit)) + unit
        for nal_type, unit in ((32, b"vps"), (33, b"sps-data"), (34, b"pps"))
    )
    hvcc = box(b"hvcC", hvcc_header + arrays)
    sample_entry = box(b"hev1", bytes(78) + hvcc)
    stsd = box(b"stsd", bytes(4) + struct.pack(">I", 1) + sample_entry)
    sample_a = struct.pack(">I", 4) + bytes([19 << 1, 1]) + b"aa"
    sample_b = struct.pack(">I", 4) + bytes([1 << 1, 1]) + b"bb"
    payload = sample_a + sample_b + (
        media if media is not None else (b"ABCD" * 300_000 + bytes(range(256)) * 100)
    )
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 0) + b"isomhevc")
    first_sample = len(ftyp) + 8
    stsz = box(b"stsz", bytes(4) + struct.pack(">II", 0, 2) + struct.pack(">II", 8, 8))
    stsc = box(b"stsc", bytes(4) + struct.pack(">I", 1) + struct.pack(">III", 1, 1, 1))
    co64 = box(b"co64", bytes(4) + struct.pack(">I", 2) + struct.pack(">QQ", first_sample, first_sample + 8))
    moov = box(b"moov", box(b"trak", box(b"mdia", box(b"minf", box(b"stbl", stsd + stsz + stsc + co64)))))
    content = ftyp + box(b"mdat", payload) + moov
    path.write_bytes(content)
    return content


def test_mp4_hevc_analysis_is_bounded_and_structural(tmp_path: Path) -> None:
    source = tmp_path / "sample.mp4"
    content = hevc_file(source)
    analysis = analyze_mp4_hevc(source)
    assert analysis["is_iso_bmff"] is True
    assert analysis["is_hevc"] is True
    assert analysis["top_level_exact_cover"] is True
    assert analysis["source"]["bytes"] == len(content)
    assert analysis["sample_entries"] == ["hev1"]
    assert analysis["hevc_configuration_records"][0]["vps_count"] == 1
    assert analysis["hevc_configuration_records"][0]["sps_count"] == 1
    assert analysis["hevc_configuration_records"][0]["pps_count"] == 1
    assert analysis["hevc_sample_probe"] is not None
    assert analysis["hevc_sample_probe"]["declared_samples"] == 2


def test_mp4_parser_rejects_parent_overrun(tmp_path: Path) -> None:
    source = tmp_path / "bad.mp4"
    source.write_bytes(struct.pack(">I4s", 1000, b"mdat") + b"x")
    with pytest.raises(MP4AnalysisError, match="exceeds parent"):
        analyze_mp4_hevc(source)


@pytest.mark.parametrize("length", [0, 1, 3, 4, 5, 1024, 65_537])
def test_every_transform_has_total_inverse(length: int) -> None:
    data = bytes((index * 17 + index // 7) & 0xFF for index in range(length))
    for candidate in candidate_set(data, kind="metadata_payload").values():
        assert decode_transform(candidate.name, candidate.payload, length) == data


def test_content_defined_ranges_are_deterministic_and_cover_input(tmp_path: Path) -> None:
    source = tmp_path / "bytes.bin"
    source.write_bytes(os.urandom(2 * 1024 * 1024 + 31))
    first = ranges_for_file(source, offset=0, length=source.stat().st_size)
    second = ranges_for_file(source, offset=0, length=source.stat().st_size)
    assert first == second
    assert first[0].offset == 0
    assert sum(item.length for item in first) == source.stat().st_size
    assert all(left.offset + left.length == right.offset for left, right in zip(first, first[1:]))


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_t_policy_is_causal_and_independent_decoder_roundtrips(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    original = hevc_file(source)
    default = pack_structural(
        source,
        tmp_path / "default.zip",
        evidence_dir=tmp_path / "default-evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        probe={"scientific_eligible": False},
    )
    forced = pack_structural(
        source,
        tmp_path / "raw.zip",
        evidence_dir=tmp_path / "raw-evidence",
        policy_source=RAW_POLICY,
        runtime=RUNTIME,
        probe={"scientific_eligible": False},
    )
    restored = tmp_path / "restored.mp4"
    verified = reconstruct_independently(tmp_path / "default.zip", restored)
    assert restored.read_bytes() == original
    assert verified["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert default["authority"]["tcap_sha256"] != forced["authority"]["tcap_sha256"]
    assert default["work_accounting"]["transform_counts"] != forced["work_accounting"]["transform_counts"]
    assert default["archive_bytes"] != forced["archive_bytes"]
    assert forced["work_accounting"]["transform_counts"] == {"raw": forced["work_accounting"]["source_segments"]}
    assert default["work_accounting"]["candidate_primitive_invocations"] > forced["work_accounting"]["candidate_primitive_invocations"]
    assert default["authority"]["receipt_count"] == 2 * default["work_accounting"]["source_segments"]


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_independent_decoder_rejects_payload_corruption(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    hevc_file(source, b"repetition" * 100_000)
    archive = tmp_path / "valid.zip"
    pack_structural(
        source,
        archive,
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        probe={"scientific_eligible": False},
    )
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive) as reader, zipfile.ZipFile(corrupt, "w", allowZip64=True) as writer:
        changed = False
        for info in reader.infolist():
            payload = reader.read(info)
            if not changed and info.filename.startswith("payloads/"):
                payload = bytes([payload[0] ^ 1]) + payload[1:]
                changed = True
            writer.writestr(info.filename, payload)
    with pytest.raises(IndependentReconstructionError, match="payload hash differs"):
        reconstruct_independently(corrupt)

    corrupt_trace = tmp_path / "corrupt-trace.zip"
    with zipfile.ZipFile(archive) as reader, zipfile.ZipFile(corrupt_trace, "w", allowZip64=True) as writer:
        for info in reader.infolist():
            payload = reader.read(info)
            if info.filename == "authority/decisions.jsonl":
                payload = payload.replace(b'"phase":"plan"', b'"phase":"xxxx"', 1)
            writer.writestr(info.filename, payload)
    with pytest.raises(IndependentReconstructionError, match="decision trace hash differs"):
        reconstruct_independently(corrupt_trace)


def test_independent_decoder_does_not_import_encoder_or_transform_module() -> None:
    source = (ROOT / "src/casulo/compression/independent_structural.py").read_text(encoding="utf-8")
    assert "reversible_transforms" not in source
    assert "structural_archive" not in source
    assert "structural_authority" not in source
