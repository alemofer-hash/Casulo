from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from pathlib import Path
from typing import Any, Mapping

from .casv_authority import CASVTAuthority
from .casv_ir import (
    CASV_EQUIVALENCE,
    CASV_PIXEL_FORMAT,
    CASV_RENDERER,
    CanonicalVideoSpec,
    encode_temporal_dynamics,
    encode_visual_base,
    infer_rectilinear_program,
    sha256_bytes,
    validate_canonical_frames,
)
from .independent_casv import reconstruct_casv_independently


CASV_MAGIC = b"CASV\x00\x01\r\n"
CASV_HEADER = struct.Struct(">8sQ")


class CASVArchiveError(RuntimeError):
    pass


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _section_table(sections: list[tuple[str, str, bytes]]) -> list[dict[str, Any]]:
    offset = 0
    table: list[dict[str, Any]] = []
    for name, role, payload in sections:
        table.append(
            {
                "name": name,
                "role": role,
                "offset": offset,
                "length": len(payload),
                "sha256": sha256_bytes(payload),
            }
        )
        offset += len(payload)
    return table


def _archive_blob(manifest: Mapping[str, Any], sections: list[tuple[str, str, bytes]]) -> bytes:
    manifest_bytes = _canonical_json(manifest)
    return (
        CASV_HEADER.pack(CASV_MAGIC, len(manifest_bytes))
        + manifest_bytes
        + b"".join(payload for _name, _role, payload in sections)
    )


def _directory_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _seal_evidence(evidence_dir: Path, archive: Path) -> tuple[str, str]:
    entries = []
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}:
            entries.append(
                {
                    "path": path.relative_to(evidence_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    entries.append(
        {
            "path": f"ARCHIVE::{archive.name}",
            "bytes": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }
    )
    manifest = {
        "schema": "casulo.casv-evidence-manifest/0.1",
        "entries": entries,
    }
    manifest_path = evidence_dir / "MANIFEST.json"
    manifest_path.write_bytes(_canonical_json(manifest) + b"\n")
    sums = "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries)
    sums_path = evidence_dir / "SHA256SUMS"
    sums_path.write_text(sums, encoding="utf-8", newline="\n")
    return (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        hashlib.sha256(sums_path.read_bytes()).hexdigest(),
    )


def pack_casv_frames(
    frames: bytes,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    source_label: str = "canonical.rgb",
    source_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile canonical RGB8 frames into a native CASV visual program."""

    validate_canonical_frames(frames, spec)
    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    if archive_path.exists():
        raise CASVArchiveError(f"CASV archive already exists: {archive_path}")
    if evidence_path.exists():
        raise CASVArchiveError(f"CASV evidence directory already exists: {evidence_path}")
    evidence_path.mkdir(parents=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    generative_available = spec.pixel_format == CASV_PIXEL_FORMAT
    inference = infer_rectilinear_program(frames, spec) if generative_available else None
    base = encode_visual_base(inference.program) if inference is not None else b""
    dynamics = encode_temporal_dynamics(inference.program) if inference is not None else b""
    residual_encoding = "UNAVAILABLE"
    residual_payload = b""
    if inference is not None:
        residual_encoding = "ZERO"
        if inference.residual_nonzero_bytes:
            residual_encoding = "XOR_ZLIB"
            residual_payload = zlib.compress(inference.residual_xor, level=9)
    direct_zlib = zlib.compress(frames, level=9)
    generative_bytes = (
        len(base) + len(dynamics) + len(residual_payload) if inference is not None else 0
    )

    authority = CASVTAuthority(
        policy_source,
        evidence_path / "authority",
        runtime=runtime,
    )
    storage = authority.decide(
        generative_candidate_available=generative_available,
        exact_generative_reconstruction=(
            bytes(
                predicted ^ delta
                for predicted, delta in zip(
                    inference.rendered,
                    inference.residual_xor,
                    strict=True,
                )
            )
            == frames
            if inference is not None
            else False
        ),
        no_foreign_bitstream=True,
        generative_bytes=generative_bytes,
        direct_zlib_bytes=len(direct_zlib),
        raw_bytes=len(frames),
        segment_index=0,
        canonical_sha256=sha256_bytes(frames),
    )

    sections: list[tuple[str, str, bytes]]
    residual_manifest: dict[str, Any] | None
    if storage.storage_mode == "GENERATIVE_EXACT":
        if inference is None:
            raise CASVArchiveError("T selected an unavailable generative representation")
        sections = [
            ("base", "invariant_blueprint_and_appearance", base),
            ("dynamics", "temporal_state_transitions", dynamics),
        ]
        if residual_payload:
            sections.append(("residual", "exact_xor_closure", residual_payload))
        residual_manifest = {
            "encoding": residual_encoding,
            "logical_bytes": len(inference.residual_xor),
            "stored_bytes": len(residual_payload),
            "nonzero_bytes": inference.residual_nonzero_bytes,
            "sha256_unencoded": sha256_bytes(inference.residual_xor),
        }
    elif storage.storage_mode == "CANONICAL_ZLIB":
        sections = [("canonical", "canonical_media_zlib_fallback", direct_zlib)]
        residual_manifest = None
    elif storage.storage_mode == "CANONICAL_RAW":
        sections = [("canonical", "canonical_media_raw_fallback", frames)]
        residual_manifest = None
    else:
        raise CASVArchiveError(f"unsupported storage mode selected by T: {storage.storage_mode}")

    selection_authority = authority.manifest()
    manifest: dict[str, Any] = {
        "schema": "casulo.casv/0.1",
        "format": "CASV",
        "format_version": "0.1",
        "equivalence_contract": CASV_EQUIVALENCE,
        "canonical_media": spec.as_dict(),
        "source": {
            "label": Path(source_label).name,
            "canonical_bytes": len(frames),
            "canonical_sha256": sha256_bytes(frames),
        },
        "source_adapter": dict(source_provenance or {"kind": "canonical-rgb-direct"}),
        "storage_mode": storage.storage_mode,
        "representation": {
            "composition": (
                "base + dynamics XOR residual"
                if inference is not None
                else "canonical fallback; generative candidate unavailable"
            ),
            "renderer": CASV_RENDERER if inference is not None else None,
            "edge_mode": inference.program.edge_mode if inference is not None else None,
            "proposer": (
                "deterministic_rectilinear_probe/0.1" if inference is not None else None
            ),
            "neural_proposer": "NOT_IMPLEMENTED",
            "generative_candidate_available": generative_available,
            "base_bytes": len(base),
            "dynamics_bytes": len(dynamics),
            "residual_stored_bytes": len(residual_payload),
            "detected_tracks": inference.detected_tracks if inference is not None else 0,
            "exact_predicted_pixels": (
                inference.exact_predicted_pixels if inference is not None else 0
            ),
            "total_pixels": inference.total_pixels if inference is not None else 0,
        },
        "residual": residual_manifest,
        "candidate_payload_bytes": {
            "GENERATIVE_EXACT": generative_bytes if generative_available else None,
            "CANONICAL_ZLIB": len(direct_zlib),
            "CANONICAL_RAW": len(frames),
        },
        "foreign_bitstreams_embedded": False,
        "embedded_source_containers": [],
        "authority_at_commit": {
            **selection_authority,
            "selected_storage_mode": storage.storage_mode,
            "selection_receipt_hash": storage.receipt["receipt_hash"],
        },
        "sections": _section_table(sections),
    }
    blob = _archive_blob(manifest, sections)
    temporary = archive_path.with_name(archive_path.name + ".casv-part")
    if temporary.exists():
        raise CASVArchiveError(f"CASV temporary archive already exists: {temporary}")
    try:
        temporary.write_bytes(blob)
        os.replace(temporary, archive_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    independent = reconstruct_casv_independently(archive_path)
    exact = (
        independent["canonical_sha256"] == sha256_bytes(frames)
        and independent["canonical_bytes"] == len(frames)
    )
    canonicalization = (
        source_provenance.get("canonicalization") if source_provenance is not None else None
    )
    source_native_sample_identity_proven = source_provenance is None or (
        isinstance(canonicalization, Mapping)
        and canonicalization.get("source_native_sample_identity_claimed") is True
        and exact
    )
    judgement = authority.judge(
        exact_reconstruction=exact,
        no_foreign_bitstream=True,
        source_bytes=len(frames),
        archive_bytes=archive_path.stat().st_size,
        partition_exact=exact,
    )
    authority_bytes = _directory_bytes(evidence_path / "authority")
    report = {
        "schema": "casulo.casv-pack-report/0.1",
        "status": "PASS" if exact else "FAIL",
        "scientific_scope": "SYNTHETIC_OR_CANONICAL_ENGINEERING_PROBE_ONLY",
        "archive": str(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "canonical_source_bytes": len(frames),
        "canonical_source_sha256": sha256_bytes(frames),
        "storage_mode": storage.storage_mode,
        "candidate_payload_bytes": manifest["candidate_payload_bytes"],
        "whole_archive_delta_bytes": archive_path.stat().st_size - len(frames),
        "whole_archive_reduction_fraction": 1.0 - archive_path.stat().st_size / len(frames),
        "authority_artifact_bytes": authority_bytes,
        "archive_plus_authority_bytes": archive_path.stat().st_size + authority_bytes,
        "cost_verdict": judgement.verdict,
        "exact_media": exact,
        "independent_decoder": independent,
        "representation": manifest["representation"],
        "residual": residual_manifest,
        "source_adapter": manifest["source_adapter"],
        "authority": authority.manifest(),
        "claims": {
            "native_casv_file": True,
            "contains_mp4_or_hevc_payload": False,
            "canonical_media_exact": exact,
            "canonical_rgb8_exact": exact and spec.pixel_format == CASV_PIXEL_FORMAT,
            "source_native_sample_identity_proven": source_native_sample_identity_proven,
            "natural_video_compression_proven": False,
            "eight_k_compression_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (evidence_path / "pack-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash = _seal_evidence(evidence_path, archive_path)
    return {
        **report,
        "evidence_dir": str(evidence_path),
        "evidence_manifest_sha256": manifest_hash,
        "evidence_sha256sums_sha256": sums_hash,
    }


__all__ = ["CASVArchiveError", "pack_casv_frames"]
