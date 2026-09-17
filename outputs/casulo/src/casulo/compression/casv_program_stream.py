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
from .casv_segment_ir import (
    CASVSegmentIRError,
    encode_segment_candidate,
    infer_segment_program,
)
from .independent_casv_program_stream import (
    CASV_PROGRAM_STREAM_FOOTER,
    CASV_PROGRAM_STREAM_FOOTER_MAGIC,
    CASV_PROGRAM_STREAM_MAGIC,
    MAX_MANIFEST_BYTES,
    MAX_SEGMENT_CANONICAL_BYTES,
    MAX_SEGMENTS,
    verify_casv_program_stream,
)


class CASVProgramStreamError(RuntimeError):
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
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = source.read(remaining)
        if chunk is None:
            raise CASVProgramStreamError("canonical source returned an invalid null read")
        if not chunk:
            break
        if len(chunk) > remaining:
            raise CASVProgramStreamError(
                "canonical source exceeded the requested read bound"
            )
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
            {
                "schema": "casulo.casv-program-stream-evidence-manifest/0.3",
                "entries": entries,
            }
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


def _reconstruct_forward(rendered: bytes, residual: bytes) -> bytes:
    return bytes(
        predicted ^ delta
        for predicted, delta in zip(rendered, residual, strict=True)
    )


def pack_casv_program_stream_reader(
    canonical_source: BinaryIO,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    frames_per_segment: int = 8,
    source_label: str,
    source_descriptor: str = "BOUNDED_BINARY_STREAM",
    source_provenance: Mapping[str, Any] | None = None,
    precommit_validator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Write a forward-only CASV/0.3 base+dynamics+residual archive."""

    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    spec.validate(enforce_memory_limit=False)
    if not source_label or Path(source_label).name != source_label:
        raise CASVProgramStreamError(
            "canonical source label must be a confined file name"
        )
    if type(frames_per_segment) is not int or frames_per_segment <= 0:
        raise CASVProgramStreamError("frames per segment must be positive")
    segment_target_bytes = spec.frame_bytes * frames_per_segment
    if segment_target_bytes > MAX_SEGMENT_CANONICAL_BYTES:
        raise CASVProgramStreamError(
            "frame-aligned segment exceeds the CASV/0.3 canonical bound; "
            "spatial tiling is required"
        )
    if archive_path.exists():
        raise CASVProgramStreamError(f"CASV/0.3 archive already exists: {archive_path}")
    if evidence_path.exists():
        raise CASVProgramStreamError(
            f"CASV/0.3 evidence already exists: {evidence_path}"
        )
    evidence_path.mkdir(parents=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_name(archive_path.name + ".casv-part")
    if temporary.exists():
        raise CASVProgramStreamError(
            f"CASV/0.3 temporary already exists: {temporary}"
        )

    authority = CASVTAuthority(policy_source, evidence_path / "authority", runtime=runtime)
    canonical_digest = hashlib.sha256()
    canonical_offset = 0
    stored_offset = len(CASV_PROGRAM_STREAM_MAGIC)
    frame_start = 0
    segments: list[dict[str, Any]] = []
    storage_counts = {
        "GENERATIVE_EXACT": 0,
        "CANONICAL_ZLIB": 0,
        "CANONICAL_RAW": 0,
    }
    proposal_counts = {"executed": 0, "unavailable": 0, "selected": 0}
    try:
        with temporary.open("xb") as output:
            output.write(CASV_PROGRAM_STREAM_MAGIC)
            while frame_start < spec.frame_count:
                if len(segments) >= MAX_SEGMENTS:
                    raise CASVProgramStreamError(
                        "canonical source needs more segments than CASV/0.3 permits"
                    )
                group_frames = min(
                    frames_per_segment,
                    spec.frame_count - frame_start,
                )
                requested = spec.frame_bytes * group_frames
                block = _read_block(canonical_source, requested)
                if len(block) != requested:
                    raise CASVProgramStreamError(
                        "canonical stream ended before its declared media size"
                    )
                block_hash = hashlib.sha256(block).hexdigest()
                direct_zlib = zlib.compress(block, level=9)
                segment_spec = CanonicalVideoSpec(
                    width=spec.width,
                    height=spec.height,
                    frame_count=group_frames,
                    fps_numerator=spec.fps_numerator,
                    fps_denominator=spec.fps_denominator,
                    pixel_format=spec.pixel_format,
                )
                generative_payload: bytes | None = None
                generative_metadata: dict[str, Any] = {
                    "available": False,
                    "selected": False,
                }
                exact_generative = False
                try:
                    inference = infer_segment_program(block, segment_spec)
                    proposal_counts["executed"] += 1
                    candidate, candidate_metadata = encode_segment_candidate(inference)
                    restored = _reconstruct_forward(
                        inference.rendered,
                        inference.residual_xor,
                    )
                    exact_generative = restored == block
                    if not exact_generative:
                        raise CASVProgramStreamError(
                            "generative candidate failed forward exact reconstruction"
                        )
                    generative_payload = candidate
                    generative_metadata = {
                        **candidate_metadata,
                        "available": True,
                        "selected": False,
                        "program_sha256": hashlib.sha256(candidate).hexdigest(),
                    }
                except CASVSegmentIRError as exc:
                    proposal_counts["unavailable"] += 1
                    generative_metadata["unavailable_reason"] = str(exc)

                decision = authority.decide(
                    generative_candidate_available=generative_payload is not None,
                    exact_generative_reconstruction=exact_generative,
                    no_foreign_bitstream=True,
                    generative_bytes=(
                        len(generative_payload) if generative_payload is not None else 0
                    ),
                    direct_zlib_bytes=len(direct_zlib),
                    raw_bytes=len(block),
                    segment_index=len(segments),
                    canonical_sha256=block_hash,
                )
                if decision.storage_mode == "GENERATIVE_EXACT":
                    if generative_payload is None:
                        raise CASVProgramStreamError(
                            "T selected an unavailable generative candidate"
                        )
                    stored = generative_payload
                    generative_metadata["selected"] = True
                    proposal_counts["selected"] += 1
                elif decision.storage_mode == "CANONICAL_ZLIB":
                    stored = direct_zlib
                elif decision.storage_mode == "CANONICAL_RAW":
                    stored = block
                else:
                    raise CASVProgramStreamError(
                        "T selected an unknown CASV/0.3 storage mode"
                    )
                storage_counts[decision.storage_mode] += 1
                output.write(stored)
                segments.append(
                    {
                        "index": len(segments),
                        "frame_start": frame_start,
                        "frame_count": group_frames,
                        "canonical_offset": canonical_offset,
                        "canonical_length": len(block),
                        "canonical_sha256": block_hash,
                        "storage_mode": decision.storage_mode,
                        "stored_offset": stored_offset,
                        "stored_length": len(stored),
                        "stored_sha256": hashlib.sha256(stored).hexdigest(),
                        "candidate_payload_bytes": {
                            "GENERATIVE_EXACT": (
                                len(generative_payload)
                                if generative_payload is not None
                                else None
                            ),
                            "CANONICAL_ZLIB": len(direct_zlib),
                            "CANONICAL_RAW": len(block),
                        },
                        "generative": generative_metadata,
                        "selection_receipt_hash": decision.receipt["receipt_hash"],
                    }
                )
                canonical_digest.update(block)
                canonical_offset += len(block)
                stored_offset += len(stored)
                frame_start += group_frames

            if canonical_offset != spec.expected_bytes or not segments:
                raise CASVProgramStreamError(
                    "canonical stream ended outside its declared size"
                )
            if _read_block(canonical_source, 1):
                raise CASVProgramStreamError(
                    "canonical stream exceeded its declared media size"
                )
            if precommit_validator is not None:
                precommit_validator()
            selection_authority = authority.manifest()
            manifest: dict[str, Any] = {
                "schema": "casulo.casv/0.3",
                "format": "CASV",
                "format_version": "0.3",
                "layout": "PROGRAM_SEGMENTS_THEN_HASHED_MANIFEST_FOOTER",
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
                    "composition": "base + dynamics + exact xor residual",
                    "renderer": "casulo.rectilinear-rgb8-yuv444p10le/0.3",
                    "segment_alignment": "WHOLE_CANONICAL_FRAMES",
                    "frames_per_segment_target": frames_per_segment,
                    "segment_count": len(segments),
                    "candidate_selection_authority": "T",
                    "fallback_primitive": {
                        "name": "zlib",
                        "stream_format": "RFC1950",
                        "encoder_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
                    },
                },
                "foreign_bitstreams_embedded": False,
                "embedded_source_containers": [],
                "audio_included": False,
                "authority_at_commit": {
                    **selection_authority,
                    "selection_receipt_count": len(segments),
                },
                "segments": segments,
            }
            manifest_bytes = _canonical_json(manifest)
            if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                raise CASVProgramStreamError(
                    "CASV/0.3 manifest exceeds its bounded size"
                )
            output.write(manifest_bytes)
            output.write(
                CASV_PROGRAM_STREAM_FOOTER.pack(
                    CASV_PROGRAM_STREAM_FOOTER_MAGIC,
                    len(manifest_bytes),
                    hashlib.sha256(manifest_bytes).digest(),
                )
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, archive_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    independent = verify_casv_program_stream(archive_path)
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
    archive_bytes = archive_path.stat().st_size
    report = {
        "schema": "casulo.casv-program-stream-pack-report/0.3",
        "status": "PASS" if exact else "FAIL",
        "scientific_scope": "SHORT_CANONICAL_STREAM_ENGINEERING_GATE_ONLY",
        "archive": str(archive_path),
        "archive_bytes": archive_bytes,
        "archive_sha256": _sha256_file(archive_path),
        "canonical_source": source_descriptor,
        "canonical_source_bytes": canonical_offset,
        "canonical_source_sha256": canonical_digest.hexdigest(),
        "frames_per_segment_target": frames_per_segment,
        "segment_count": len(segments),
        "storage_modes": storage_counts,
        "proposals": proposal_counts,
        "maximum_canonical_segment_bytes": max(
            segment["canonical_length"] for segment in segments
        ),
        "archive_reduction_fraction_vs_raw_canonical": (
            1.0 - archive_bytes / canonical_offset
        ),
        "authority_artifact_bytes": authority_bytes,
        "archive_plus_authority_bytes": archive_bytes + authority_bytes,
        "archive_plus_authority_reduction_fraction_vs_raw_canonical": (
            1.0 - (archive_bytes + authority_bytes) / canonical_offset
        ),
        "cost_verdict": judgement.verdict,
        "exact_media": exact,
        "independent_decoder": independent,
        "source_adapter": manifest["source_adapter"],
        "authority": authority.manifest(),
        "claims": {
            "base_dynamics_residual_executed": proposal_counts["executed"] > 0,
            "native_yuv444p10le_renderer_available": True,
            "t_selected_each_committed_segment": True,
            "independent_exact_reconstruction": exact,
            "native_casv_file": True,
            "contains_mp4_or_hevc_payload": False,
            "audio_included": False,
            "spatial_tiling_implemented": False,
            "natural_video_compression_proven": False,
            "full_resolution_eight_k_compression_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (evidence_path / "pack-report.json").write_bytes(
        _canonical_json(report) + b"\n"
    )
    manifest_hash, sums_hash, evidence_entries = _seal_evidence(
        evidence_path,
        archive_path,
    )
    return {
        **report,
        "evidence_dir": str(evidence_path),
        "evidence_entries": evidence_entries,
        "evidence_manifest_sha256": manifest_hash,
        "evidence_sha256sums_sha256": sums_hash,
    }


def pack_casv_program_stream_file(
    canonical_source: str | Path,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    frames_per_segment: int = 8,
    source_label: str | None = None,
    source_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_path = Path(canonical_source).resolve(strict=True)
    if not source_path.is_file() or source_path.stat().st_size != spec.expected_bytes:
        raise CASVProgramStreamError(
            "canonical source length differs from its media spec"
        )
    with source_path.open("rb") as source:
        return pack_casv_program_stream_reader(
            source,
            spec,
            archive,
            evidence_dir=evidence_dir,
            policy_source=policy_source,
            runtime=runtime,
            frames_per_segment=frames_per_segment,
            source_label=Path(source_label or source_path.name).name,
            source_descriptor=str(source_path),
            source_provenance=source_provenance,
        )


__all__ = [
    "CASVProgramStreamError",
    "pack_casv_program_stream_file",
    "pack_casv_program_stream_reader",
]
