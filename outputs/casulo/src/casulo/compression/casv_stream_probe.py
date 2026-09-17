from __future__ import annotations

import hashlib
import json
import os
import random
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .casv_ir import CanonicalVideoSpec
from .casv_stream_archive import pack_casv_stream_file
from .independent_casv_stream import (
    IndependentCASVStreamError,
    extract_casv_stream_frames,
    verify_casv_stream,
)


class CASVStreamProbeError(RuntimeError):
    pass


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _implementation_label(path: Path, repository: Path) -> str:
    try:
        return path.relative_to(repository).as_posix()
    except ValueError:
        return f"external-policy/{path.name}"


def _probe_frames(spec: CanonicalVideoSpec) -> bytes:
    output = bytearray()
    random_source = random.Random(20260910)
    for frame_index in range(spec.frame_count):
        if frame_index < spec.frame_count // 2:
            color = bytes((20 + frame_index, 40, 80))
            output.extend(color * (spec.width * spec.height))
        else:
            output.extend(random_source.randbytes(spec.frame_bytes))
    return bytes(output)


def _seal(root: Path) -> tuple[str, str, int]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}:
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    manifest = root / "MANIFEST.json"
    manifest.write_bytes(
        _canonical_json(
            {"schema": "casulo.casv-stream-probe-manifest/0.2", "entries": entries}
        )
        + b"\n"
    )
    sums = root / "SHA256SUMS"
    sums.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries),
        encoding="utf-8",
        newline="\n",
    )
    return _sha256_file(manifest), _sha256_file(sums), len(entries)


def run_casv_stream_probe(
    output: str | Path,
    *,
    policy_source: str | Path,
    runtime: str | Path | None = None,
) -> dict[str, Any]:
    """Run a short synthetic engineering gate; never substitutes for natural video."""

    root = Path(output).resolve()
    if root.exists():
        raise CASVStreamProbeError(f"append-only probe destination already exists: {root}")
    root.mkdir(parents=True)
    started_at = datetime.now(timezone.utc).isoformat()
    spec = CanonicalVideoSpec(64, 36, 16, 24)
    frames = _probe_frames(spec)
    source = root / "canonical-source.rgb"
    archive = root / "probe.casv"
    restored = root / "canonical-restored.rgb"
    selected = root / "frames-5-8.rgb"
    source.write_bytes(frames)

    packed = pack_casv_stream_file(
        source,
        spec,
        archive,
        evidence_dir=root / "pack-evidence",
        policy_source=policy_source,
        runtime=runtime,
        segment_bytes=4096,
        source_label="synthetic-mixed-stream.rgb",
        source_provenance={
            "kind": "synthetic-engineering-regression",
            "scientific_proof": False,
        },
    )
    verified = verify_casv_stream(archive, restored)
    selected_result = extract_casv_stream_frames(
        archive,
        selected,
        start_frame=5,
        frame_count=4,
    )
    selected_expected = frames[5 * spec.frame_bytes : 9 * spec.frame_bytes]

    corrupted = root / "corrupted-segment.casv"
    corrupt_payload = bytearray(archive.read_bytes())
    corrupt_payload[len(b"CASV\x00\x02\r\n") + 3] ^= 1
    corrupted.write_bytes(corrupt_payload)
    corruption_rejected = False
    corruption_error = ""
    try:
        verify_casv_stream(corrupted)
    except IndependentCASVStreamError as exc:
        corruption_rejected = True
        corruption_error = str(exc)

    gates = {
        "whole_roundtrip_exact": restored.read_bytes() == frames,
        "whole_sha256_exact": verified["canonical_sha256"]
        == hashlib.sha256(frames).hexdigest(),
        "selected_frames_exact": selected.read_bytes() == selected_expected,
        "selected_scope_is_not_whole_archive": (
            selected_result["whole_archive_payload_verified"] is False
        ),
        "raw_segment_exercised": packed["raw_segments"] > 0,
        "zlib_segment_exercised": packed["zlib_segments"] > 0,
        "one_t_decision_per_segment": packed["authority"]["storage_decision_count"]
        == packed["segment_count"],
        "one_t_cost_judgement": packed["authority"]["cost_judgement_count"] == 1,
        "corruption_rejected": corruption_rejected,
        "no_foreign_video_bitstream": packed["claims"]["contains_mp4_or_hevc_payload"]
        is False,
    }
    repository = Path(__file__).resolve().parents[3]
    implementation_paths = (
        repository / "src/casulo/compression/casv_stream_archive.py",
        repository / "src/casulo/compression/independent_casv_stream.py",
        repository / "src/casulo/compression/casv_authority.py",
        repository / "src/casulo/compression/casv_ir.py",
        repository / "src/casulo/compression/casv_player.py",
        repository / "src/casulo/compression/casv_stream_probe.py",
        repository / "src/casulo/compression/cli.py",
        Path(policy_source).resolve(),
    )
    implementation_sha256 = {
        _implementation_label(path, repository): _sha256_file(path)
        for path in implementation_paths
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    report: dict[str, Any] = {
        "schema": "casulo.casv-stream-probe/0.2",
        "status": status,
        "scope": "SYNTHETIC_ENGINEERING_REGRESSION_ONLY",
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_media": spec.as_dict(),
        "canonical_bytes": len(frames),
        "canonical_sha256": hashlib.sha256(frames).hexdigest(),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": _sha256_file(archive),
        "archive_reduction_fraction_vs_raw_canonical": (
            1.0 - archive.stat().st_size / len(frames)
        ),
        "segment_count": packed["segment_count"],
        "raw_segments": packed["raw_segments"],
        "zlib_segments": packed["zlib_segments"],
        "tcap_sha256": packed["authority"]["tcap_sha256"],
        "receipt_chain_head": packed["authority"]["receipt_chain_head"],
        "implementation_sha256": implementation_sha256,
        "independent_verification": verified,
        "selected_range_verification": selected_result,
        "corruption_error": corruption_error,
        "gates": gates,
        "claims": {
            "forward_only_archive_layout_exercised": True,
            "bounded_incremental_decode_exercised": True,
            "selective_frame_extraction_exercised": True,
            "natural_video_compression_proven": False,
            "eight_k_video_compression_proven": False,
            "advantage_over_hevc_proven": False,
        },
    }
    report_path = root / "probe-report.json"
    report_path.write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, entry_count = _seal(root)
    if status != "PASS":
        raise CASVStreamProbeError("CASV/0.2 streaming engineering probe failed")
    return {
        **report,
        "output": str(root),
        "manifest_entries": entry_count,
        "manifest_sha256": manifest_hash,
        "sha256sums_sha256": sums_hash,
        "process_id": os.getpid(),
    }


__all__ = ["CASVStreamProbeError", "run_casv_stream_probe"]
