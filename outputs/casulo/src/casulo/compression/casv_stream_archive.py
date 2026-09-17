from __future__ import annotations

import hashlib
import json
import os
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO, Callable

from .casv_authority import CASVTAuthority
from .casv_ir import CanonicalVideoSpec
from .independent_casv_stream import (
    CASV_STREAM_FOOTER,
    CASV_STREAM_FOOTER_MAGIC,
    CASV_STREAM_MAGIC,
    MAX_MANIFEST_BYTES,
    MAX_SEGMENT_CANONICAL_BYTES,
    MAX_SEGMENTS,
    verify_casv_stream,
)


MIN_SEGMENT_BYTES = 1024


class CASVStreamArchiveError(RuntimeError):
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
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _directory_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _read_block(source: BinaryIO, length: int) -> bytes:
    """Read up to length bytes while tolerating short pipe reads."""

    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = source.read(remaining)
        if chunk is None:
            raise CASVStreamArchiveError("canonical source returned an invalid null read")
        if not chunk:
            break
        if len(chunk) > remaining:
            raise CASVStreamArchiveError("canonical source exceeded the requested read bound")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _seal_evidence(evidence_dir: Path, archive: Path) -> tuple[str, str, int]:
    entries: list[dict[str, Any]] = []
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}:
            entries.append(
                {
                    "path": path.relative_to(evidence_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    entries.append(
        {
            "path": f"ARCHIVE::{archive.name}",
            "bytes": archive.stat().st_size,
            "sha256": _sha256_file(archive),
        }
    )
    manifest_path = evidence_dir / "MANIFEST.json"
    manifest_path.write_bytes(
        _canonical_json(
            {"schema": "casulo.casv-stream-evidence-manifest/0.2", "entries": entries}
        )
        + b"\n"
    )
    sums_path = evidence_dir / "SHA256SUMS"
    sums_path.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries),
        encoding="utf-8",
        newline="\n",
    )
    return _sha256_file(manifest_path), _sha256_file(sums_path), len(entries)


def pack_casv_stream_reader(
    canonical_source: BinaryIO,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    segment_bytes: int = 8 * 1024 * 1024,
    source_label: str,
    source_descriptor: str = "BOUNDED_BINARY_STREAM",
    source_provenance: Mapping[str, Any] | None = None,
    precommit_validator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Write CASV/0.2 from a bounded stream and publish only after validation."""

    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    spec.validate(enforce_memory_limit=False)
    if not source_label or Path(source_label).name != source_label:
        raise CASVStreamArchiveError("canonical source label must be a confined file name")
    if not MIN_SEGMENT_BYTES <= segment_bytes <= MAX_SEGMENT_CANONICAL_BYTES:
        raise CASVStreamArchiveError("segment size is outside the CASV/0.2 bounds")
    if archive_path.exists():
        raise CASVStreamArchiveError(f"CASV stream archive already exists: {archive_path}")
    if evidence_path.exists():
        raise CASVStreamArchiveError(f"CASV stream evidence already exists: {evidence_path}")
    evidence_path.mkdir(parents=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_name(archive_path.name + ".casv-part")
    if temporary.exists():
        raise CASVStreamArchiveError(f"CASV stream temporary already exists: {temporary}")

    authority = CASVTAuthority(policy_source, evidence_path / "authority", runtime=runtime)
    canonical_digest = hashlib.sha256()
    canonical_offset = 0
    stored_offset = len(CASV_STREAM_MAGIC)
    segments: list[dict[str, Any]] = []
    raw_segments = 0
    zlib_segments = 0
    try:
        with temporary.open("xb") as output:
            output.write(CASV_STREAM_MAGIC)
            while canonical_offset < spec.expected_bytes:
                if len(segments) >= MAX_SEGMENTS:
                    raise CASVStreamArchiveError(
                        "canonical source needs more segments than CASV/0.2 permits"
                    )
                requested = min(segment_bytes, spec.expected_bytes - canonical_offset)
                block = _read_block(canonical_source, requested)
                if len(block) != requested:
                    raise CASVStreamArchiveError(
                        "canonical stream ended before its declared media size"
                    )
                block_hash = hashlib.sha256(block).hexdigest()
                compressed = zlib.compress(block, level=9)
                decision = authority.decide(
                    generative_candidate_available=False,
                    exact_generative_reconstruction=False,
                    no_foreign_bitstream=True,
                    generative_bytes=0,
                    direct_zlib_bytes=len(compressed),
                    raw_bytes=len(block),
                    segment_index=len(segments),
                    canonical_sha256=block_hash,
                )
                if decision.storage_mode == "CANONICAL_ZLIB":
                    stored = compressed
                    zlib_segments += 1
                elif decision.storage_mode == "CANONICAL_RAW":
                    stored = block
                    raw_segments += 1
                else:
                    raise CASVStreamArchiveError(
                        "T selected a generative mode unavailable in CASV/0.2 streaming"
                    )
                output.write(stored)
                segments.append(
                    {
                        "index": len(segments),
                        "canonical_offset": canonical_offset,
                        "canonical_length": len(block),
                        "canonical_sha256": block_hash,
                        "storage_mode": decision.storage_mode,
                        "stored_offset": stored_offset,
                        "stored_length": len(stored),
                        "stored_sha256": hashlib.sha256(stored).hexdigest(),
                        "selection_receipt_hash": decision.receipt["receipt_hash"],
                    }
                )
                canonical_digest.update(block)
                canonical_offset += len(block)
                stored_offset += len(stored)
            if canonical_offset != spec.expected_bytes or not segments:
                raise CASVStreamArchiveError("canonical stream ended outside its declared size")
            if _read_block(canonical_source, 1):
                raise CASVStreamArchiveError(
                    "canonical stream exceeded its declared media size"
                )
            if precommit_validator is not None:
                precommit_validator()
            selection_authority = authority.manifest()
            manifest: dict[str, Any] = {
                "schema": "casulo.casv/0.2",
                "format": "CASV",
                "format_version": "0.2",
                "layout": "PAYLOAD_THEN_HASHED_MANIFEST_FOOTER",
                "equivalence_contract": "EXACT_MEDIA",
                "canonical_media": spec.as_dict(),
                "source": {
                    "label": source_label,
                    "canonical_bytes": canonical_offset,
                    "canonical_sha256": canonical_digest.hexdigest(),
                },
                "source_adapter": dict(
                    source_provenance or {"kind": "canonical-file-direct"}
                ),
                "representation": {
                    "composition": "ordered independent canonical segments",
                    "generative_candidate_available": False,
                    "segment_target_bytes": segment_bytes,
                    "segment_count": len(segments),
                    "primitive": {
                        "name": "zlib",
                        "stream_format": "RFC1950",
                        "encoder_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
                        "selection_authority": "T",
                    },
                },
                "foreign_bitstreams_embedded": False,
                "embedded_source_containers": [],
                "authority_at_commit": {
                    **selection_authority,
                    "selection_receipt_count": len(segments),
                },
                "segments": segments,
            }
            manifest_bytes = _canonical_json(manifest)
            if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                raise CASVStreamArchiveError("CASV/0.2 manifest exceeds its bounded size")
            manifest_hash = hashlib.sha256(manifest_bytes).digest()
            output.write(manifest_bytes)
            output.write(
                CASV_STREAM_FOOTER.pack(
                    CASV_STREAM_FOOTER_MAGIC,
                    len(manifest_bytes),
                    manifest_hash,
                )
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, archive_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    independent = verify_casv_stream(archive_path)
    exact = (
        independent["canonical_sha256"] == canonical_digest.hexdigest()
        and independent["canonical_bytes"] == canonical_offset
    )
    judgement = authority.judge(
        exact_reconstruction=exact,
        no_foreign_bitstream=True,
        source_bytes=canonical_offset,
        archive_bytes=archive_path.stat().st_size,
        partition_exact=exact,
    )
    authority_bytes = _directory_bytes(evidence_path / "authority")
    report = {
        "schema": "casulo.casv-stream-pack-report/0.2",
        "status": "PASS" if exact else "FAIL",
        "scientific_scope": "CANONICAL_STREAM_ENGINEERING_GATE_ONLY",
        "archive": str(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": _sha256_file(archive_path),
        "canonical_source": source_descriptor,
        "canonical_source_bytes": canonical_offset,
        "canonical_source_sha256": canonical_digest.hexdigest(),
        "segment_target_bytes": segment_bytes,
        "segment_count": len(segments),
        "raw_segments": raw_segments,
        "zlib_segments": zlib_segments,
        "maximum_canonical_segment_bytes": max(
            segment["canonical_length"] for segment in segments
        ),
        "archive_reduction_fraction_vs_raw_canonical": (
            1.0 - archive_path.stat().st_size / canonical_offset
        ),
        "authority_artifact_bytes": authority_bytes,
        "archive_plus_authority_bytes": archive_path.stat().st_size + authority_bytes,
        "cost_verdict": judgement.verdict,
        "exact_media": exact,
        "independent_decoder": independent,
        "source_adapter": manifest["source_adapter"],
        "authority": authority.manifest(),
        "claims": {
            "streaming_archive_written_forward_only": True,
            "incremental_decoder": True,
            "hash_verified_segment_index": True,
            "cryptographically_signed_index": False,
            "native_casv_file": True,
            "contains_mp4_or_hevc_payload": False,
            "natural_video_compression_proven": False,
            "eight_k_compression_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (evidence_path / "pack-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, evidence_entries = _seal_evidence(evidence_path, archive_path)
    return {
        **report,
        "evidence_dir": str(evidence_path),
        "evidence_entries": evidence_entries,
        "evidence_manifest_sha256": manifest_hash,
        "evidence_sha256sums_sha256": sums_hash,
    }


def pack_casv_stream_file(
    canonical_source: str | Path,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    segment_bytes: int = 8 * 1024 * 1024,
    source_label: str | None = None,
    source_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write CASV/0.2 forward-only from a canonical file with bounded memory."""

    source_path = Path(canonical_source).resolve(strict=True)
    if not source_path.is_file() or source_path.stat().st_size != spec.expected_bytes:
        raise CASVStreamArchiveError("canonical source length differs from its media spec")
    with source_path.open("rb") as source:
        return pack_casv_stream_reader(
            source,
            spec,
            archive,
            evidence_dir=evidence_dir,
            policy_source=policy_source,
            runtime=runtime,
            segment_bytes=segment_bytes,
            source_label=Path(source_label or source_path.name).name,
            source_descriptor=str(source_path),
            source_provenance=source_provenance,
        )


__all__ = [
    "CASVStreamArchiveError",
    "pack_casv_stream_file",
    "pack_casv_stream_reader",
]
