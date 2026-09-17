from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from casulo.compression.casv_ir import CanonicalVideoSpec
from casulo.compression.casv_player import play_casv
from casulo.compression.casv_stream_archive import pack_casv_stream_file
from casulo.compression.independent_casv_stream import (
    CASV_STREAM_FOOTER,
    IndependentCASVStreamError,
    extract_casv_stream_frames,
    inspect_casv_stream,
    verify_casv_stream,
)


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
DEFAULT_POLICY = ROOT / "examples" / "t-v2" / "compression_casv.t"


def _rgb_spec() -> CanonicalVideoSpec:
    return CanonicalVideoSpec(32, 16, 8, 24)


def _mixed_payload(spec: CanonicalVideoSpec) -> bytes:
    random_bytes = random.Random(20260910).randbytes(4096)
    payload = b"\x00" * 4096 + random_bytes + (b"CASULO-T-STREAM" * 256)
    return payload[: spec.expected_bytes].ljust(spec.expected_bytes, b"T")


def _pack(tmp_path: Path) -> tuple[Path, bytes, dict[str, object]]:
    spec = _rgb_spec()
    payload = _mixed_payload(spec)
    source = tmp_path / "canonical.rgb"
    archive = tmp_path / "stream.casv"
    source.write_bytes(payload)
    result = pack_casv_stream_file(
        source,
        spec,
        archive,
        evidence_dir=tmp_path / "evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        segment_bytes=1024,
    )
    return archive, payload, result


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_stream_archive_roundtrip_and_t_receipts_are_per_segment(tmp_path: Path) -> None:
    archive, payload, packed = _pack(tmp_path)
    restored = tmp_path / "restored.rgb"
    verified = verify_casv_stream(archive, restored)
    inspected = inspect_casv_stream(archive)

    assert archive.read_bytes().startswith(b"CASV\x00\x02\r\n")
    assert restored.read_bytes() == payload
    assert verified["canonical_sha256"] == hashlib.sha256(payload).hexdigest()
    assert verified["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert verified["archive_sha256_computed"] is True
    assert verified["maximum_canonical_segment_bytes"] == 1024
    assert verified["maximum_explicit_segment_buffers_bytes"] <= 2048
    assert verified["process_peak_rss_measured"] is False
    assert verified["segment_count"] == 12
    assert packed["segment_count"] == 12
    assert packed["raw_segments"] > 0
    assert packed["zlib_segments"] > 0
    assert inspected["manifest"]["authority_at_commit"]["receipt_count"] == 12

    receipts = [
        json.loads(line)
        for line in (tmp_path / "evidence/authority/receipts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(receipts) == 13  # 12 segment decisions plus the final cost judgement.
    assert len({receipt["receipt_hash"] for receipt in receipts}) == len(receipts)
    call_names = {
        path.name for path in (tmp_path / "evidence/authority/calls").glob("*.json")
    }
    assert call_names == {
        *(f"decide-{index:08d}.json" for index in range(12)),
        "judge-00000000.json",
    }
    assert packed["authority"]["storage_decision_count"] == 12
    assert packed["authority"]["cost_judgement_count"] == 1
    traces = [
        json.loads(line)
        for line in (tmp_path / "evidence/authority/decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    indexed_segments = inspected["manifest"]["segments"]
    assert [trace["input"]["segment_index"] for trace in traces[:-1]] == list(range(12))
    assert [trace["input"]["canonical_sha256"] for trace in traces[:-1]] == [
        segment["canonical_sha256"] for segment in indexed_segments
    ]


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_stream_selected_frames_are_exact_but_do_not_claim_whole_payload(
    tmp_path: Path,
) -> None:
    archive, payload, _packed = _pack(tmp_path)
    selected = tmp_path / "frames-2-4.rgb"
    result = extract_casv_stream_frames(
        archive,
        selected,
        start_frame=2,
        frame_count=3,
    )
    frame_bytes = _rgb_spec().frame_bytes
    expected = payload[2 * frame_bytes : 5 * frame_bytes]
    assert selected.read_bytes() == expected
    assert result["canonical_sha256"] == hashlib.sha256(expected).hexdigest()
    assert result["integrity_scope"] == "SELECTED_SEGMENTS_AND_HASH_VERIFIED_INDEX"
    assert result["whole_archive_payload_verified"] is False
    assert result["archive_sha256_computed"] is False


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_stream_decoder_rejects_payload_and_footer_corruption(tmp_path: Path) -> None:
    archive, _payload, _packed = _pack(tmp_path)
    corrupted_payload = bytearray(archive.read_bytes())
    corrupted_payload[len(b"CASV\x00\x02\r\n") + 10] ^= 1
    payload_corrupt = tmp_path / "payload-corrupt.casv"
    payload_corrupt.write_bytes(corrupted_payload)
    with pytest.raises(IndependentCASVStreamError, match="stored hash differs"):
        verify_casv_stream(payload_corrupt)

    corrupted = bytearray(archive.read_bytes())
    corrupted[-1] ^= 1
    footer_corrupt = tmp_path / "footer-corrupt.casv"
    footer_corrupt.write_bytes(corrupted)
    with pytest.raises(IndependentCASVStreamError, match="manifest hash differs"):
        inspect_casv_stream(footer_corrupt)


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_stream_manifest_future_schema_fails_closed(tmp_path: Path) -> None:
    archive, _payload, _packed = _pack(tmp_path)
    raw = archive.read_bytes()
    footer = raw[-CASV_STREAM_FOOTER.size :]
    footer_magic, manifest_length, _digest = CASV_STREAM_FOOTER.unpack(footer)
    manifest_offset = len(raw) - CASV_STREAM_FOOTER.size - manifest_length
    manifest = json.loads(raw[manifest_offset : -CASV_STREAM_FOOTER.size])
    manifest["schema"] = "casulo.casv/99.0"
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    rewritten = (
        raw[:manifest_offset]
        + encoded
        + CASV_STREAM_FOOTER.pack(
            footer_magic,
            len(encoded),
            hashlib.sha256(encoded).digest(),
        )
    )
    future = tmp_path / "future.casv"
    future.write_bytes(rewritten)
    with pytest.raises(IndependentCASVStreamError, match="unsupported CASV stream schema"):
        inspect_casv_stream(future)


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_yuv444p10le_stream_roundtrip(tmp_path: Path) -> None:
    spec = CanonicalVideoSpec(8, 4, 8, 24, pixel_format="YUV444P10LE")
    payload = b"".join(
        ((index * 37 + 11) % 1024).to_bytes(2, "little")
        for index in range(spec.expected_bytes // 2)
    )
    source = tmp_path / "native-yuv.raw"
    archive = tmp_path / "native-yuv.casv"
    restored = tmp_path / "native-yuv-restored.raw"
    source.write_bytes(payload)
    pack_casv_stream_file(
        source,
        spec,
        archive,
        evidence_dir=tmp_path / "native-yuv-evidence",
        policy_source=DEFAULT_POLICY,
        runtime=RUNTIME,
        segment_bytes=1024,
    )
    verified = verify_casv_stream(archive, restored)
    assert restored.read_bytes() == payload
    assert verified["canonical_media"]["pixel_format"] == "YUV444P10LE"


@pytest.mark.skipif(not RUNTIME.is_file(), reason="release Rust T runtime unavailable")
def test_reference_player_uses_incremental_segment_pipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, payload, _packed = _pack(tmp_path)
    observed: dict[str, object] = {}

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
            self.killed = False

        def wait(self) -> int:
            return 0

        def kill(self) -> None:
            self.killed = True

    process = FakeProcess()

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return process

    monkeypatch.setattr(
        "casulo.compression.casv_player.resolve_ffplay",
        lambda _explicit=None: tmp_path / "ffplay.exe",
    )
    monkeypatch.setattr("casulo.compression.casv_player.subprocess.Popen", fake_popen)
    played = play_casv(archive)
    assert played["status"] == "PASS"
    assert played["player_profile"] == (
        "REFERENCE_PIPE_INCREMENTAL_SEGMENTS_TWO_PASS_VERIFIED"
    )
    assert process.stdin.payload == payload
    assert process.stdin.closed is True
    assert observed["command"][-1] == "pipe:0"  # type: ignore[index]
    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False


def test_independent_stream_decoder_has_no_forward_path_imports() -> None:
    source = (ROOT / "src/casulo/compression/independent_casv_stream.py").read_text(
        encoding="utf-8"
    )
    assert "casv_stream_archive" not in source
    assert "casv_authority" not in source
    assert "casv_ir" not in source
