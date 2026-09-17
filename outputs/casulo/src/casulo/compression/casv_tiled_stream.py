from __future__ import annotations

import hashlib
import json
import os
import zlib
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO, Callable

from .casv_ir import CanonicalVideoSpec
from .casv_tile_authority import CASVTileTAuthority
from .casv_tile_ir import (
    CASVTileIRError,
    DEFAULT_STRIP_HEIGHT,
    DEFAULT_TILE_WIDTH,
    build_tile_candidates,
    decode_tile_payload,
    extract_tile,
    iter_strip_layouts,
    summarize_layout,
)
from .independent_casv_tiled_stream import (
    CASV_TILED_FOOTER,
    CASV_TILED_FOOTER_MAGIC,
    CASV_TILED_STREAM_MAGIC,
    CASV_TILED_STRIP_HEADER,
    CASV_TILED_STRIP_MAGIC,
    CASV_TILED_TILE_ENTRY,
    MAX_MANIFEST_BYTES,
    MAX_RECORDS,
    MODE_IDS,
    verify_casv_tiled_stream,
)


MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES = 64 * 1024 * 1024


class CASVTiledStreamError(RuntimeError):
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
    result = bytearray()
    while len(result) < length:
        chunk = source.read(length - len(result))
        if chunk is None:
            raise CASVTiledStreamError("canonical source returned a null read")
        if not chunk:
            break
        result.extend(chunk)
    return bytes(result)


def _bounded_zlib(payload: bytes, expected_bytes: int) -> bytes:
    decoder = zlib.decompressobj()
    restored = decoder.decompress(payload, expected_bytes + 1)
    if len(restored) > expected_bytes or decoder.unconsumed_tail:
        raise CASVTiledStreamError("candidate zlib output exceeds tile bounds")
    restored += decoder.flush(expected_bytes - len(restored) + 1)
    if (
        len(restored) != expected_bytes
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise CASVTiledStreamError("candidate zlib output is not exact")
    return restored


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
                "schema": "casulo.casv-tiled-evidence-manifest/0.4",
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


def pack_casv_tiled_stream_reader(
    canonical_source: BinaryIO,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    tile_width: int = DEFAULT_TILE_WIDTH,
    strip_height: int = DEFAULT_STRIP_HEIGHT,
    source_label: str,
    source_descriptor: str = "BOUNDED_BINARY_STREAM",
    source_provenance: Mapping[str, Any] | None = None,
    precommit_validator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Write CASV/0.4 from canonical-order strips without allocating a frame."""

    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    spec.validate(enforce_memory_limit=False)
    layout_summary = summarize_layout(
        spec,
        tile_width=tile_width,
        strip_height=strip_height,
    )
    if layout_summary["record_count"] > MAX_RECORDS:
        raise CASVTiledStreamError("CASV/0.4 needs more strip records than permitted")
    if not source_label or Path(source_label).name != source_label:
        raise CASVTiledStreamError("canonical source label must be a confined file name")
    if archive_path.exists() or evidence_path.exists():
        raise CASVTiledStreamError("CASV/0.4 destinations must be new and append-only")
    evidence_path.mkdir(parents=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_name(archive_path.name + ".casv-part")
    if temporary.exists():
        raise CASVTiledStreamError(f"CASV/0.4 temporary already exists: {temporary}")

    authority = CASVTileTAuthority(
        policy_source,
        evidence_path / "authority",
        runtime=runtime,
    )
    canonical_digest = hashlib.sha256()
    direct_zlib = zlib.compressobj(level=9)
    direct_zlib_bytes = 0
    records: list[dict[str, Any]] = []
    stored_offset = len(CASV_TILED_STREAM_MAGIC)
    mode_counts: Counter[str] = Counter()
    candidate_totals: Counter[str] = Counter()
    selected_predictor_exact_bytes = 0
    selected_tile_payload_bytes = 0
    maximum_candidate_working_set_bytes = 0
    try:
        with temporary.open("xb") as output:
            output.write(CASV_TILED_STREAM_MAGIC)
            for layout in iter_strip_layouts(
                spec,
                tile_width=tile_width,
                strip_height=strip_height,
            ):
                strip = _read_block(canonical_source, layout.canonical_bytes)
                if len(strip) != layout.canonical_bytes:
                    raise CASVTiledStreamError(
                        "canonical stream ended before its declared media size"
                    )
                canonical_digest.update(strip)
                direct_zlib_bytes += len(direct_zlib.compress(strip))
                strip_hash = hashlib.sha256(strip).hexdigest()
                candidates = []
                authority_payloads: list[dict[str, Any]] = []
                working_set = len(strip)
                for tile_layout in layout.tiles:
                    canonical_tile = extract_tile(strip, layout, tile_layout)
                    family = build_tile_candidates(
                        canonical_tile,
                        width=tile_layout.width,
                        height=layout.height,
                        bytes_per_pixel=layout.bytes_per_pixel,
                    )
                    for mode, payload in family.payloads.items():
                        restored = decode_tile_payload(
                            mode,
                            payload,
                            width=tile_layout.width,
                            height=layout.height,
                            bytes_per_pixel=layout.bytes_per_pixel,
                            zlib_decoder=_bounded_zlib,
                        )
                        if restored != canonical_tile:
                            raise CASVTiledStreamError(
                                f"{mode} candidate failed exact tile reconstruction"
                            )
                    candidates.append((tile_layout, family))
                    working_set += len(canonical_tile) + sum(
                        len(payload) for payload in family.payloads.values()
                    )
                    costs = {
                        mode: CASV_TILED_TILE_ENTRY.size + len(payload)
                        for mode, payload in family.payloads.items()
                    }
                    candidate_totals.update(costs)
                    authority_payloads.append(
                        {
                            "tile_index": tile_layout.tile_index,
                            "frame_index": layout.frame_index,
                            "plane_index": layout.plane_index,
                            "canonical_sha256": hashlib.sha256(canonical_tile).hexdigest(),
                            "exact_candidate_reconstruction": True,
                            "no_foreign_bitstream": True,
                            "dc_xor_bytes": costs["DC_XOR_ZLIB"],
                            "paeth_bytes": costs["PAETH_ZLIB"],
                            "direct_zlib_bytes": costs["CANONICAL_ZLIB"],
                            "raw_bytes": costs["CANONICAL_RAW"],
                        }
                    )
                maximum_candidate_working_set_bytes = max(
                    maximum_candidate_working_set_bytes,
                    working_set,
                )
                if working_set > MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES:
                    raise CASVTiledStreamError(
                        "candidate family exceeds the CASV/0.4 encoder memory covenant"
                    )
                chain_start = authority.previous_receipt_hash
                decisions = authority.decide_tiles(
                    authority_payloads,
                    record_index=layout.record_index,
                )
                table = bytearray()
                selected_payload = bytearray()
                for (tile_layout, family), decision in zip(
                    candidates,
                    decisions,
                    strict=True,
                ):
                    mode = decision.storage_mode
                    stored = family.payloads[mode]
                    table.extend(
                        CASV_TILED_TILE_ENTRY.pack(
                            tile_layout.x,
                            tile_layout.width,
                            MODE_IDS[mode],
                            tile_layout.canonical_bytes,
                            len(stored),
                        )
                    )
                    selected_payload.extend(stored)
                    mode_counts[mode] += 1
                    if mode == "DC_XOR_ZLIB":
                        selected_predictor_exact_bytes += family.dc_exact_bytes
                    elif mode == "PAETH_ZLIB":
                        selected_predictor_exact_bytes += family.paeth_zero_bytes
                header = CASV_TILED_STRIP_HEADER.pack(
                    CASV_TILED_STRIP_MAGIC,
                    layout.record_index,
                    layout.frame_index,
                    layout.plane_index,
                    layout.y,
                    layout.width,
                    layout.height,
                    layout.bytes_per_pixel,
                    len(layout.tiles),
                    layout.canonical_bytes,
                    len(selected_payload),
                    bytes.fromhex(strip_hash),
                )
                encoded = header + table + selected_payload
                selected_tile_payload_bytes += len(selected_payload)
                output.write(encoded)
                records.append(
                    {
                        "index": layout.record_index,
                        "frame_index": layout.frame_index,
                        "plane_index": layout.plane_index,
                        "y": layout.y,
                        "width": layout.width,
                        "height": layout.height,
                        "bytes_per_pixel": layout.bytes_per_pixel,
                        "tile_count": len(layout.tiles),
                        "canonical_offset": layout.canonical_offset,
                        "canonical_length": layout.canonical_bytes,
                        "canonical_sha256": strip_hash,
                        "stored_offset": stored_offset,
                        "stored_length": len(encoded),
                        "stored_sha256": hashlib.sha256(encoded).hexdigest(),
                        "selection_receipt_chain_start": chain_start,
                        "selection_receipt_chain_end": authority.previous_receipt_hash,
                        "selection_receipt_count": len(decisions),
                        "storage_modes": dict(Counter(item.storage_mode for item in decisions)),
                    }
                )
                stored_offset += len(encoded)

            if _read_block(canonical_source, 1):
                raise CASVTiledStreamError(
                    "canonical stream exceeded its declared media size"
                )
            direct_zlib_bytes += len(direct_zlib.flush())
            if precommit_validator is not None:
                precommit_validator()
            selection_authority = authority.manifest()
            manifest: dict[str, Any] = {
                "schema": "casulo.casv/0.4",
                "format": "CASV",
                "format_version": "0.4",
                "layout": "TILED_STRIP_RECORDS_THEN_HASHED_MANIFEST_FOOTER",
                "equivalence_contract": "EXACT_MEDIA",
                "canonical_media": spec.as_dict(),
                "source": {
                    "label": source_label,
                    "canonical_bytes": spec.expected_bytes,
                    "canonical_sha256": canonical_digest.hexdigest(),
                },
                "source_adapter": dict(
                    source_provenance or {"kind": "canonical-file-direct"}
                ),
                "representation": {
                    "composition": "bounded strips + independently selected exact tiles",
                    "tile_width": tile_width,
                    "strip_height": strip_height,
                    "record_count": len(records),
                    "tile_count": sum(mode_counts.values()),
                    "candidate_modes": list(MODE_IDS),
                    "candidate_selection_authority": "T",
                    "candidate_selection_granularity": "TILE",
                    "spatial_predictors": ["modal-sample XOR", "bytewise Paeth"],
                    "temporal_prediction": "NOT_IMPLEMENTED_IN_0_4",
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
                    "selection_receipt_count": sum(mode_counts.values()),
                },
                "records": records,
            }
            manifest_bytes = _canonical_json(manifest)
            if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                raise CASVTiledStreamError("CASV/0.4 manifest exceeds bounded size")
            output.write(manifest_bytes)
            output.write(
                CASV_TILED_FOOTER.pack(
                    CASV_TILED_FOOTER_MAGIC,
                    len(manifest_bytes),
                    hashlib.sha256(manifest_bytes).digest(),
                )
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, archive_path)
    except (CASVTileIRError, OSError, zlib.error) as exc:
        raise CASVTiledStreamError(str(exc)) from exc
    finally:
        if temporary.exists():
            temporary.unlink()

    independent = verify_casv_tiled_stream(archive_path)
    exact = (
        independent["canonical_sha256"] == canonical_digest.hexdigest()
        and independent["canonical_bytes"] == spec.expected_bytes
    )
    judgement = authority.judge(
        exact_reconstruction=exact,
        source_bytes=spec.expected_bytes,
        archive_bytes=archive_path.stat().st_size,
        partition_exact=exact,
    )
    archive_bytes = archive_path.stat().st_size
    selected_record_stream_bytes = sum(record["stored_length"] for record in records)
    authority_bytes = _directory_bytes(evidence_path / "authority")
    report = {
        "schema": "casulo.casv-tiled-pack-report/0.4",
        "status": "PASS" if exact else "FAIL",
        "scientific_scope": "BOUNDED_ENGINEERING_GATE_ONLY",
        "archive": str(archive_path),
        "archive_bytes": archive_bytes,
        "archive_sha256": _sha256_file(archive_path),
        "canonical_source": source_descriptor,
        "canonical_source_bytes": spec.expected_bytes,
        "canonical_source_sha256": canonical_digest.hexdigest(),
        "layout": layout_summary,
        "storage_modes": dict(mode_counts),
        "candidate_payload_bytes_including_tile_entries": dict(candidate_totals),
        "direct_whole_stream_zlib_bytes": direct_zlib_bytes,
        "selected_tile_payload_bytes": selected_tile_payload_bytes,
        "selected_record_stream_bytes": selected_record_stream_bytes,
        "tile_payload_advantage_bytes_vs_direct_zlib": direct_zlib_bytes
        - selected_tile_payload_bytes,
        "record_stream_advantage_bytes_vs_direct_zlib": direct_zlib_bytes
        - selected_record_stream_bytes,
        "archive_advantage_bytes_vs_direct_zlib": direct_zlib_bytes - archive_bytes,
        "selected_predictor_exact_bytes": selected_predictor_exact_bytes,
        "maximum_candidate_working_set_bytes": maximum_candidate_working_set_bytes,
        "encoder_working_set_covenant_bytes": MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES,
        "authority_artifact_bytes": authority_bytes,
        "archive_plus_authority_bytes": archive_bytes + authority_bytes,
        "archive_reduction_fraction_vs_raw_canonical": 1.0
        - archive_bytes / spec.expected_bytes,
        "archive_plus_authority_reduction_fraction_vs_raw_canonical": 1.0
        - (archive_bytes + authority_bytes) / spec.expected_bytes,
        "cost_verdict": judgement.verdict,
        "cost_verdict_baseline": "RAW_CANONICAL_BYTES",
        "exact_media": exact,
        "independent_decoder": independent,
        "source_adapter": manifest["source_adapter"],
        "authority": authority.manifest(),
        "claims": {
            "spatial_tiling_implemented": True,
            "full_frame_allocation_required": False,
            "t_selected_each_committed_tile": True,
            "independent_exact_reconstruction": exact,
            "native_casv_file": True,
            "contains_mp4_or_hevc_payload": False,
            "audio_included": False,
            "temporal_prediction_implemented": False,
            "natural_video_compression_proven": False,
            "full_resolution_eight_k_encode_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (evidence_path / "pack-report.json").write_bytes(_canonical_json(report) + b"\n")
    (evidence_path / "independent-verification.json").write_bytes(
        _canonical_json(independent) + b"\n"
    )
    (evidence_path / "layout.json").write_bytes(_canonical_json(layout_summary) + b"\n")
    manifest_hash, sums_hash, evidence_entries = _seal_evidence(
        evidence_path,
        archive_path,
    )
    return {
        **report,
        "evidence": {
            "directory": str(evidence_path),
            "manifest_sha256": manifest_hash,
            "sha256sums_sha256": sums_hash,
            "entry_count": evidence_entries,
        },
    }


def pack_casv_tiled_stream_file(
    canonical_source: str | Path,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    tile_width: int = DEFAULT_TILE_WIDTH,
    strip_height: int = DEFAULT_STRIP_HEIGHT,
    source_label: str | None = None,
    source_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_path = Path(canonical_source).resolve(strict=True)
    if not source_path.is_file() or source_path.stat().st_size != spec.expected_bytes:
        raise CASVTiledStreamError("canonical source length differs from its media spec")
    with source_path.open("rb") as source:
        return pack_casv_tiled_stream_reader(
            source,
            spec,
            archive,
            evidence_dir=evidence_dir,
            policy_source=policy_source,
            runtime=runtime,
            tile_width=tile_width,
            strip_height=strip_height,
            source_label=Path(source_label or source_path.name).name,
            source_descriptor=str(source_path),
            source_provenance=source_provenance,
        )


__all__ = [
    "CASVTiledStreamError",
    "MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES",
    "pack_casv_tiled_stream_file",
    "pack_casv_tiled_stream_reader",
]
