from __future__ import annotations

import hashlib
import struct
import zipfile
from pathlib import Path

import pytest

from casulo.compression.gop_archive import pack_gop_corpus
from casulo.compression.gop_authority import GOPTAuthority
from casulo.compression.hevc_gop import (
    build_sample_aligned_corpus,
    choose_irap_aligned_probe,
    scan_hevc_access_units,
)
from casulo.compression.independent_gop import (
    IndependentGOPError,
    reconstruct_gop_independently,
)


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
DEFAULT_POLICY = ROOT / "examples" / "t-v2" / "compression_hevc_gop.t"
RAW_POLICY = ROOT / "examples" / "t-v2" / "compression_hevc_gop_force_raw.t"


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _nal(nal_type: int, body: bytes) -> bytes:
    payload = bytes([nal_type << 1, 1]) + body
    return struct.pack(">I", len(payload)) + payload


def _noise(length: int) -> bytes:
    blocks = []
    counter = 0
    while sum(len(item) for item in blocks) < length:
        blocks.append(hashlib.sha256(counter.to_bytes(8, "big")).digest())
        counter += 1
    return b"".join(blocks)[:length]


def _gop_mp4(path: Path) -> tuple[bytes, bytes]:
    shared = _noise(16 * 1024)
    first = _nal(39, b"metadata-a" * 32) + _nal(19, shared)
    second = _nal(39, b"metadata-a" * 32) + _nal(1, shared)
    hvcc_header = bytes([1, 4]) + bytes(10) + bytes([120]) + bytes(8) + bytes([3, 3])
    arrays = b"".join(
        bytes([nal_type]) + struct.pack(">H", 1) + struct.pack(">H", len(unit)) + unit
        for nal_type, unit in ((32, b"vps"), (33, b"sps-data"), (34, b"pps"))
    )
    hvcc = _box(b"hvcC", hvcc_header + arrays)
    sample_entry = _box(b"hev1", bytes(78) + hvcc)
    stsd = _box(b"stsd", bytes(4) + struct.pack(">I", 1) + sample_entry)
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0) + b"isomhevc")
    first_offset = len(ftyp) + 8
    stsz = _box(
        b"stsz",
        bytes(4)
        + struct.pack(">II", 0, 2)
        + struct.pack(">II", len(first), len(second)),
    )
    stsc = _box(
        b"stsc",
        bytes(4) + struct.pack(">I", 1) + struct.pack(">III", 1, 1, 1),
    )
    co64 = _box(
        b"co64",
        bytes(4)
        + struct.pack(">I", 2)
        + struct.pack(">QQ", first_offset, first_offset + len(first)),
    )
    moov = _box(
        b"moov",
        _box(b"trak", _box(b"mdia", _box(b"minf", _box(b"stbl", stsd + stsz + stsc + co64)))),
    )
    content = ftyp + _box(b"mdat", first + second) + moov
    path.write_bytes(content)
    return content, first + second


def test_gop_map_scans_every_access_unit_without_body_reads(tmp_path: Path) -> None:
    source = tmp_path / "gop.mp4"
    _content, corpus = _gop_mp4(source)
    analysis = scan_hevc_access_units(source)
    assert analysis["sample_count"] == 2
    assert analysis["nal_unit_count"] == 4
    assert analysis["gop_count"] == 1
    assert analysis["gops"][0]["starts_with_irap"] is True
    assert analysis["physical_header_bytes_read"] == 4 * (4 + 2)
    selected = choose_irap_aligned_probe(
        analysis, target_bytes=len(corpus), minimum_samples=2
    )
    assert selected == (0, 1)


def test_sample_aligned_corpus_is_exact(tmp_path: Path) -> None:
    source = tmp_path / "gop.mp4"
    _content, expected = _gop_mp4(source)
    analysis = scan_hevc_access_units(source)
    corpus = tmp_path / "corpus.bin"
    manifest = build_sample_aligned_corpus(source, corpus, analysis, (0, 1))
    assert corpus.read_bytes() == expected
    assert manifest["corpus"]["sha256"] == hashlib.sha256(expected).hexdigest()
    assert manifest["nal_unit_count"] == 4


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_t_gop_policy_changes_work_and_independent_decoder_roundtrips(
    tmp_path: Path,
) -> None:
    source = tmp_path / "gop.mp4"
    _content, expected = _gop_mp4(source)
    analysis = scan_hevc_access_units(source)
    corpus = tmp_path / "corpus.bin"
    manifest = build_sample_aligned_corpus(source, corpus, analysis, (0, 1))
    default = pack_gop_corpus(
        corpus,
        tmp_path / "default.zip",
        corpus_manifest=manifest,
        evidence_dir=tmp_path / "default-evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
    )
    forced = pack_gop_corpus(
        corpus,
        tmp_path / "raw.zip",
        corpus_manifest=manifest,
        evidence_dir=tmp_path / "raw-evidence",
        policy_source=RAW_POLICY,
        runtime=RUNTIME,
    )
    restored = tmp_path / "restored.bin"
    verified = reconstruct_gop_independently(tmp_path / "default.zip", restored)
    assert restored.read_bytes() == expected
    assert verified["source_sha256"] == hashlib.sha256(expected).hexdigest()
    assert default["authority"]["tcap_sha256"] != forced["authority"]["tcap_sha256"]
    assert default["work_accounting"]["candidate_primitive_invocations"] > forced[
        "work_accounting"
    ]["candidate_primitive_invocations"]
    assert default["work_accounting"]["transform_counts"].get(
        "xor-reference-prefix-zlib", 0
    ) >= 1
    assert forced["work_accounting"]["transform_counts"] == {"raw": 4}


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_t_cost_judge_rejects_expansion_and_accepts_reduction(tmp_path: Path) -> None:
    rejected_authority = GOPTAuthority(DEFAULT_POLICY, tmp_path / "reject", runtime=RUNTIME)
    rejected = rejected_authority.judge(
        exact_reconstruction=True,
        source_bytes=100,
        archive_bytes=101,
        base_source_bytes=10,
        dynamics_source_bytes=20,
        residual_source_bytes=70,
    )
    accepted_authority = GOPTAuthority(DEFAULT_POLICY, tmp_path / "accept", runtime=RUNTIME)
    accepted = accepted_authority.judge(
        exact_reconstruction=True,
        source_bytes=100,
        archive_bytes=99,
        base_source_bytes=10,
        dynamics_source_bytes=20,
        residual_source_bytes=70,
    )
    assert rejected.verdict == "REJECT"
    assert accepted.verdict == "ACCEPT"


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_independent_gop_decoder_rejects_payload_corruption(tmp_path: Path) -> None:
    source = tmp_path / "gop.mp4"
    _gop_mp4(source)
    analysis = scan_hevc_access_units(source)
    corpus = tmp_path / "corpus.bin"
    manifest = build_sample_aligned_corpus(source, corpus, analysis, (0, 1))
    archive = tmp_path / "valid.zip"
    pack_gop_corpus(
        corpus,
        archive,
        corpus_manifest=manifest,
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
    )
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive) as reader, zipfile.ZipFile(corrupt, "w") as writer:
        changed = False
        for info in reader.infolist():
            payload = reader.read(info)
            if not changed and info.filename.startswith("payloads/"):
                payload = bytes([payload[0] ^ 1]) + payload[1:]
                changed = True
            writer.writestr(info, payload)
    with pytest.raises(IndependentGOPError, match="payload hash differs"):
        reconstruct_gop_independently(corrupt)


def test_independent_gop_decoder_has_no_forward_path_imports() -> None:
    source = (ROOT / "src/casulo/compression/independent_gop.py").read_text(
        encoding="utf-8"
    )
    assert "gop_archive" not in source
    assert "gop_transforms" not in source
    assert "gop_authority" not in source
