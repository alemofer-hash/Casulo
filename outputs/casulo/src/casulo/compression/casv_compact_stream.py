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
from .casv_tile_authority import CASVCompactTAuthority
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
from .independent_casv_compact_stream import (
    CASV_COMPACT_FOOTER,
    CASV_COMPACT_FOOTER_MAGIC,
    CASV_COMPACT_HEADER,
    CASV_COMPACT_MAGIC,
    CASV_COMPACT_RECORD_HEADER,
    CASV_COMPACT_RECORD_MAGIC,
    CASV_COMPACT_TILE_ENTRY,
    MODE_IDS,
    PIXEL_FORMAT_IDS,
    verify_casv_compact_stream,
)


MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES = 64 * 1024 * 1024


class CASVCompactStreamError(RuntimeError):
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


def _implementation_hashes(
    authority: CASVCompactTAuthority,
) -> dict[str, str]:
    repository = Path(__file__).resolve().parents[3]
    paths = {
        "compact_encoder": Path(__file__).resolve(),
        "independent_decoder": (
            repository / "src/casulo/compression/independent_casv_compact_stream.py"
        ),
        "tile_ir": repository / "src/casulo/compression/casv_tile_ir.py",
        "t_authority_adapter": (
            repository / "src/casulo/compression/casv_tile_authority.py"
        ),
        "productive_t_executor": repository / "src/casulo/t/productive.py",
        "t_policy": authority.policy_source,
        "t_runtime": authority.executor.runtime,
    }
    return {name: _sha256_file(path) for name, path in paths.items()}


def _read_block(source: BinaryIO, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = source.read(length - len(result))
        if chunk is None:
            raise CASVCompactStreamError("canonical source returned a null read")
        if not chunk:
            break
        result.extend(chunk)
    return bytes(result)


def _bounded_zlib(payload: bytes, expected_bytes: int) -> bytes:
    decoder = zlib.decompressobj()
    restored = decoder.decompress(payload, expected_bytes + 1)
    if len(restored) > expected_bytes or decoder.unconsumed_tail:
        raise CASVCompactStreamError("candidate zlib output exceeds tile bounds")
    restored += decoder.flush(expected_bytes - len(restored) + 1)
    if (
        len(restored) != expected_bytes
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise CASVCompactStreamError("candidate zlib output is not exact")
    return restored


def _seal_evidence(
    evidence_dir: Path,
    candidate: Path,
    *,
    published: bool,
) -> tuple[str, str, int]:
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
    if published:
        entries.append(
            {
                "path": f"ARCHIVE::{candidate.name}",
                "bytes": candidate.stat().st_size,
                "sha256": _sha256_file(candidate),
            }
        )
    manifest_path = evidence_dir / "MANIFEST.json"
    manifest_path.write_bytes(
        _canonical_json(
            {
                "schema": "casulo.casv-compact-evidence-manifest/0.5",
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


def _write_hashed(output: BinaryIO, digest: Any, payload: bytes) -> None:
    output.write(payload)
    digest.update(payload)


def pack_casv_compact_stream_reader(
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
    """Write compact CASV/0.5 and let T classify it before publication."""

    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    spec.validate(enforce_memory_limit=False)
    layout_summary = summarize_layout(
        spec,
        tile_width=tile_width,
        strip_height=strip_height,
    )
    if not source_label or Path(source_label).name != source_label:
        raise CASVCompactStreamError("canonical source label must be a confined file name")
    if archive_path.exists() or evidence_path.exists():
        raise CASVCompactStreamError("CASV/0.5 destinations must be new and append-only")
    evidence_path.mkdir(parents=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_name(archive_path.name + ".casv-part")
    if temporary.exists():
        raise CASVCompactStreamError(f"CASV/0.5 temporary already exists: {temporary}")

    authority = CASVCompactTAuthority(
        policy_source,
        evidence_path / "authority",
        runtime=runtime,
    )
    canonical_digest = hashlib.sha256()
    direct_zlib = zlib.compressobj(level=9)
    direct_zlib_bytes = 0
    content_digest = hashlib.sha256()
    record_summaries: list[dict[str, Any]] = []
    mode_counts: Counter[str] = Counter()
    candidate_totals: Counter[str] = Counter()
    selected_tile_payload_bytes = 0
    maximum_candidate_working_set_bytes = 0
    candidate_path = temporary
    published = False
    judgement_verdict = "NOT_JUDGED"
    independent: dict[str, Any] | None = None
    candidate_bytes = 0
    candidate_sha256 = ""
    try:
        with temporary.open("xb") as output:
            _write_hashed(output, content_digest, CASV_COMPACT_MAGIC)
            header = CASV_COMPACT_HEADER.pack(
                PIXEL_FORMAT_IDS[spec.pixel_format],
                0,
                CASV_COMPACT_HEADER.size,
                spec.width,
                spec.height,
                spec.frame_count,
                spec.fps_numerator,
                spec.fps_denominator,
                tile_width,
                strip_height,
                spec.expected_bytes,
                bytes(32),
            )
            header_offset = output.tell()
            _write_hashed(output, content_digest, header)
            for layout in iter_strip_layouts(
                spec,
                tile_width=tile_width,
                strip_height=strip_height,
            ):
                strip = _read_block(canonical_source, layout.canonical_bytes)
                if len(strip) != layout.canonical_bytes:
                    raise CASVCompactStreamError(
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
                        if decode_tile_payload(
                            mode,
                            payload,
                            width=tile_layout.width,
                            height=layout.height,
                            bytes_per_pixel=layout.bytes_per_pixel,
                            zlib_decoder=_bounded_zlib,
                        ) != canonical_tile:
                            raise CASVCompactStreamError(
                                f"{mode} candidate failed exact tile reconstruction"
                            )
                    candidates.append((tile_layout, family))
                    working_set += len(canonical_tile) + sum(
                        len(payload) for payload in family.payloads.values()
                    )
                    costs = {
                        mode: CASV_COMPACT_TILE_ENTRY.size + len(payload)
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
                    raise CASVCompactStreamError(
                        "candidate family exceeds the CASV/0.5 encoder memory covenant"
                    )
                chain_start = authority.previous_receipt_hash
                decisions = authority.decide_tiles(
                    authority_payloads,
                    record_index=layout.record_index,
                )
                table = bytearray()
                selected_payload = bytearray()
                for (_tile_layout, family), decision in zip(
                    candidates,
                    decisions,
                    strict=True,
                ):
                    stored = family.payloads[decision.storage_mode]
                    table.extend(
                        CASV_COMPACT_TILE_ENTRY.pack(
                            MODE_IDS[decision.storage_mode],
                            len(stored),
                        )
                    )
                    selected_payload.extend(stored)
                    mode_counts[decision.storage_mode] += 1
                selected_tile_payload_bytes += len(selected_payload)
                record_header = CASV_COMPACT_RECORD_HEADER.pack(
                    CASV_COMPACT_RECORD_MAGIC,
                    layout.record_index,
                    len(selected_payload),
                    bytes.fromhex(strip_hash),
                )
                record_offset = output.tell()
                _write_hashed(output, content_digest, record_header)
                _write_hashed(output, content_digest, bytes(table))
                _write_hashed(output, content_digest, bytes(selected_payload))
                record_summaries.append(
                    {
                        "index": layout.record_index,
                        "frame_index": layout.frame_index,
                        "plane_index": layout.plane_index,
                        "y": layout.y,
                        "height": layout.height,
                        "canonical_offset": layout.canonical_offset,
                        "canonical_length": layout.canonical_bytes,
                        "canonical_sha256": strip_hash,
                        "record_offset": record_offset,
                        "stored_length": CASV_COMPACT_RECORD_HEADER.size
                        + len(table)
                        + len(selected_payload),
                        "tile_count": len(layout.tiles),
                        "selection_receipt_chain_start": chain_start,
                        "selection_receipt_chain_end": authority.previous_receipt_hash,
                        "storage_modes": dict(
                            Counter(item.storage_mode for item in decisions)
                        ),
                    }
                )
            if _read_block(canonical_source, 1):
                raise CASVCompactStreamError(
                    "canonical stream exceeded its declared media size"
                )
            direct_zlib_bytes += len(direct_zlib.flush())
            if precommit_validator is not None:
                precommit_validator()

            canonical_hash = canonical_digest.digest()
            output.seek(header_offset)
            final_header = CASV_COMPACT_HEADER.pack(
                PIXEL_FORMAT_IDS[spec.pixel_format],
                0,
                CASV_COMPACT_HEADER.size,
                spec.width,
                spec.height,
                spec.frame_count,
                spec.fps_numerator,
                spec.fps_denominator,
                tile_width,
                strip_height,
                spec.expected_bytes,
                canonical_hash,
            )
            output.write(final_header)
            output.flush()
            os.fsync(output.fileno())

        content_digest = hashlib.sha256()
        with temporary.open("rb") as content:
            while block := content.read(8 * 1024 * 1024):
                content_digest.update(block)
        selection_authority = authority.manifest()
        with temporary.open("ab") as output:
            output.write(
                CASV_COMPACT_FOOTER.pack(
                    CASV_COMPACT_FOOTER_MAGIC,
                    authority.storage_decision_count,
                    bytes.fromhex(authority.previous_receipt_hash),
                    content_digest.digest(),
                )
            )
            output.flush()
            os.fsync(output.fileno())

        candidate_bytes = temporary.stat().st_size
        candidate_sha256 = _sha256_file(temporary)
        independent = verify_casv_compact_stream(temporary)
        exact = (
            independent["canonical_sha256"] == canonical_digest.hexdigest()
            and independent["canonical_bytes"] == spec.expected_bytes
            and independent["selection_receipt_chain_head"]
            == selection_authority["receipt_chain_head"]
            and independent["selection_receipt_count"]
            == selection_authority["storage_decision_count"]
        )
        judgement = authority.judge(
            exact_reconstruction=exact,
            source_bytes=spec.expected_bytes,
            archive_bytes=candidate_bytes,
            reference_zlib_bytes=direct_zlib_bytes,
            partition_exact=exact,
        )
        judgement_verdict = judgement.verdict
        if judgement_verdict == "REJECT":
            rejected = evidence_path / "rejected-candidate.casv"
            os.replace(temporary, rejected)
            candidate_path = rejected
        else:
            os.replace(temporary, archive_path)
            candidate_path = archive_path
            published = True
        independent = {**independent, "archive": str(candidate_path)}
    except (CASVTileIRError, OSError, zlib.error) as exc:
        raise CASVCompactStreamError(str(exc)) from exc
    finally:
        if temporary.exists():
            temporary.unlink()

    if independent is None:
        raise CASVCompactStreamError("CASV/0.5 independent verification did not run")
    selected_record_stream_bytes = sum(
        record["stored_length"] for record in record_summaries
    )
    fixed_container_bytes = (
        len(CASV_COMPACT_MAGIC)
        + CASV_COMPACT_HEADER.size
        + CASV_COMPACT_FOOTER.size
    )
    authority_bytes = _directory_bytes(evidence_path / "authority")
    status = {
        "ACCEPT_BEATS_REFERENCE": "PASS_BEATS_DIRECT_ZLIB",
        "ACCEPT_RAW_ONLY": "EXACT_NONCOMPETITIVE",
        "REJECT": "REJECTED_NO_PUBLICATION",
    }[judgement_verdict]
    report = {
        "schema": "casulo.casv-compact-pack-report/0.5",
        "status": status,
        "scientific_scope": "BOUNDED_ENGINEERING_GATE_ONLY",
        "archive_published": published,
        "archive": str(archive_path) if published else None,
        "candidate_path": str(candidate_path),
        "candidate_archive_bytes": candidate_bytes,
        "candidate_archive_sha256": candidate_sha256,
        "canonical_source": source_descriptor,
        "canonical_source_label": source_label,
        "canonical_source_bytes": spec.expected_bytes,
        "canonical_source_sha256": canonical_digest.hexdigest(),
        "layout": layout_summary,
        "storage_modes": dict(mode_counts),
        "candidate_payload_bytes_including_tile_entries": dict(candidate_totals),
        "direct_whole_stream_zlib_bytes": direct_zlib_bytes,
        "reference_baseline": {
            "algorithm": "ZLIB_RFC1950_DEFLATE",
            "level": 9,
            "whole_canonical_stream": True,
            "zlib_compile_version": zlib.ZLIB_VERSION,
            "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        },
        "selected_tile_payload_bytes": selected_tile_payload_bytes,
        "selected_record_stream_bytes": selected_record_stream_bytes,
        "fixed_container_bytes": fixed_container_bytes,
        "tile_payload_advantage_bytes_vs_direct_zlib": direct_zlib_bytes
        - selected_tile_payload_bytes,
        "record_stream_advantage_bytes_vs_direct_zlib": direct_zlib_bytes
        - selected_record_stream_bytes,
        "archive_advantage_bytes_vs_direct_zlib": direct_zlib_bytes
        - candidate_bytes,
        "maximum_candidate_working_set_bytes": maximum_candidate_working_set_bytes,
        "encoder_working_set_covenant_bytes": MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES,
        "authority_artifact_bytes": authority_bytes,
        "candidate_plus_authority_bytes": candidate_bytes + authority_bytes,
        "implementation_sha256": _implementation_hashes(authority),
        "cost_verdict": judgement_verdict,
        "cost_verdict_baseline": authority.cost_verdict_baseline,
        "exact_media": independent["status"] == "PASS",
        "independent_decoder": independent,
        "source_adapter": dict(source_provenance or {"kind": "canonical-file-direct"}),
        "authority_at_commit": selection_authority,
        "authority_final": authority.manifest(),
        "claims": {
            "compact_binary_index_implemented": True,
            "spatial_tiling_implemented": True,
            "full_frame_allocation_required": False,
            "t_selected_each_committed_tile": True,
            "t_judgement_consumed_before_publication": True,
            "independent_exact_reconstruction": independent["status"] == "PASS",
            "native_casv_file": True,
            "contains_mp4_or_hevc_payload": False,
            "audio_included": False,
            "temporal_prediction_implemented": False,
            "natural_video_compression_proven": False,
            "full_resolution_eight_k_encode_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (evidence_path / "record-index.json").write_bytes(
        _canonical_json(
            {
                "schema": "casulo.casv-compact-record-index/0.5",
                "records": record_summaries,
            }
        )
        + b"\n"
    )
    (evidence_path / "layout.json").write_bytes(_canonical_json(layout_summary) + b"\n")
    (evidence_path / "independent-verification.json").write_bytes(
        _canonical_json(independent) + b"\n"
    )
    (evidence_path / "pack-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, entry_count = _seal_evidence(
        evidence_path,
        candidate_path,
        published=published,
    )
    return {
        **report,
        "evidence": {
            "directory": str(evidence_path),
            "manifest_sha256": manifest_hash,
            "sha256sums_sha256": sums_hash,
            "entry_count": entry_count,
        },
    }


def pack_casv_compact_stream_file(
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
        raise CASVCompactStreamError("canonical source length differs from its media spec")
    with source_path.open("rb") as source:
        return pack_casv_compact_stream_reader(
            source,
            spec,
            archive,
            evidence_dir=evidence_dir,
            policy_source=policy_source,
            runtime=runtime,
            tile_width=tile_width,
            strip_height=strip_height,
            source_label=source_label or source_path.name,
            source_descriptor=str(source_path),
            source_provenance=source_provenance,
        )


__all__ = [
    "CASVCompactStreamError",
    "pack_casv_compact_stream_file",
    "pack_casv_compact_stream_reader",
]
