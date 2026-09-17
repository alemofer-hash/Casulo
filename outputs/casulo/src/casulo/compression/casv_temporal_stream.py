from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zlib
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, Mapping

from .casv_ir import CanonicalVideoSpec
from .casv_temporal_ir import (
    CASVTemporalIRError,
    build_temporal_candidates,
    restore_temporal,
)
from .casv_tile_authority import CASVTemporalTAuthority
from .casv_tile_ir import (
    CASVTileIRError,
    build_tile_candidates,
    decode_tile_payload,
    extract_tile,
    iter_strip_layouts,
    summarize_layout,
)
from .independent_casv_temporal_stream import (
    CASV_TEMPORAL_FOOTER,
    CASV_TEMPORAL_FOOTER_MAGIC,
    CASV_TEMPORAL_HEADER,
    CASV_TEMPORAL_MAGIC,
    CASV_TEMPORAL_RECORD_HEADER,
    CASV_TEMPORAL_RECORD_MAGIC,
    CASV_TEMPORAL_TILE_ENTRY,
    MODE_IDS,
    verify_casv_temporal_stream,
)


DEFAULT_KEYFRAME_INTERVAL = 8
MAX_KEYFRAME_INTERVAL = 1024
MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES = 192 * 1024 * 1024
UNAVAILABLE_TEMPORAL_COST = 2_147_483_647


class CASVTemporalStreamError(RuntimeError):
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
    authority: CASVTemporalTAuthority,
) -> dict[str, str | None]:
    files = {
        "temporal_encoder": Path(__file__).resolve(),
        "independent_decoder": Path(__file__).with_name(
            "independent_casv_temporal_stream.py"
        ),
        "temporal_ir": Path(__file__).with_name("casv_temporal_ir.py"),
        "tile_ir": Path(__file__).with_name("casv_tile_ir.py"),
        "authority_adapter": Path(__file__).with_name("casv_tile_authority.py"),
        "productive_t_executor": Path(__file__).parents[1] / "t" / "productive.py",
        "t_policy": authority.policy_source,
        "t_runtime": authority.executor.runtime,
    }
    return {
        name: _sha256_file(path) if path.is_file() else None
        for name, path in files.items()
    }


def _read_block(source: BinaryIO, length: int) -> bytes:
    payload = bytearray()
    while len(payload) < length:
        block = source.read(length - len(payload))
        if not block:
            break
        payload.extend(block)
    return bytes(payload)


def _bounded_zlib(payload: bytes, expected_bytes: int) -> bytes:
    decoder = zlib.decompressobj()
    restored = decoder.decompress(payload, expected_bytes + 1)
    if len(restored) > expected_bytes or decoder.unconsumed_tail:
        raise CASVTemporalStreamError("zlib candidate exceeds temporal tile bounds")
    restored += decoder.flush(expected_bytes - len(restored) + 1)
    if len(restored) != expected_bytes or not decoder.eof or decoder.unused_data:
        raise CASVTemporalStreamError("zlib candidate does not reconstruct exactly")
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
                "schema": "casulo.casv-temporal-evidence-manifest/0.6",
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


def pack_casv_temporal_stream_reader(
    canonical_source: BinaryIO,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    tile_width: int = 512,
    strip_height: int = 128,
    keyframe_interval: int = DEFAULT_KEYFRAME_INTERVAL,
    source_label: str,
    source_descriptor: str = "BOUNDED_BINARY_STREAM",
    source_provenance: Mapping[str, Any] | None = None,
    precommit_validator: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Write temporal CASV/0.6 and let T judge it before publication."""

    archive_path = Path(archive).resolve()
    evidence_path = Path(evidence_dir).resolve()
    spec.validate(enforce_memory_limit=False)
    if (
        type(keyframe_interval) is not int
        or not 1 <= keyframe_interval <= MAX_KEYFRAME_INTERVAL
    ):
        raise CASVTemporalStreamError("keyframe interval is outside CASV/0.6 bounds")
    layout_summary = summarize_layout(
        spec,
        tile_width=tile_width,
        strip_height=strip_height,
    )
    layout_summary = {
        **layout_summary,
        "schema": "casulo.casv-temporal-layout/0.6",
        "keyframe_interval": keyframe_interval,
        "previous_frame_spool_bytes": spec.expected_bytes // spec.frame_count,
        "full_frame_memory_allocation_required": False,
    }
    if not source_label or Path(source_label).name != source_label:
        raise CASVTemporalStreamError(
            "canonical source label must be a confined file name"
        )
    if archive_path.exists() or evidence_path.exists():
        raise CASVTemporalStreamError(
            "CASV/0.6 destinations must be new and append-only"
        )
    evidence_path.mkdir(parents=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_name(archive_path.name + ".casv-part")
    if temporary.exists():
        raise CASVTemporalStreamError(f"CASV/0.6 temporary already exists: {temporary}")

    authority = CASVTemporalTAuthority(
        policy_source,
        evidence_path / "authority",
        runtime=runtime,
    )
    canonical_digest = hashlib.sha256()
    direct_zlib = zlib.compressobj(level=9)
    direct_zlib_bytes = 0
    record_summaries: list[dict[str, Any]] = []
    mode_counts: Counter[str] = Counter()
    candidate_totals: Counter[str] = Counter()
    selected_tile_payload_bytes = 0
    maximum_candidate_working_set_bytes = 0
    temporal_candidate_tiles = 0
    candidate_path = temporary
    published = False
    judgement_verdict = "NOT_JUDGED"
    independent: dict[str, Any] | None = None
    candidate_bytes = 0
    candidate_sha256 = ""
    frame_bytes = spec.expected_bytes // spec.frame_count
    try:
        content_digest = hashlib.sha256()
        with (
            temporary.open("xb") as output,
            tempfile.TemporaryFile() as previous_frame,
            tempfile.TemporaryFile() as current_frame,
        ):
            _write_hashed(output, content_digest, CASV_TEMPORAL_MAGIC)
            header = CASV_TEMPORAL_HEADER.pack(
                {"RGB8": 1, "YUV444P10LE": 2}[spec.pixel_format],
                0,
                CASV_TEMPORAL_HEADER.size,
                spec.width,
                spec.height,
                spec.frame_count,
                spec.fps_numerator,
                spec.fps_denominator,
                tile_width,
                strip_height,
                keyframe_interval,
                spec.expected_bytes,
                bytes(32),
            )
            header_offset = output.tell()
            _write_hashed(output, content_digest, header)
            active_frame = -1
            for layout in iter_strip_layouts(
                spec,
                tile_width=tile_width,
                strip_height=strip_height,
            ):
                if layout.frame_index != active_frame:
                    if active_frame >= 0:
                        if current_frame.tell() != frame_bytes:
                            raise CASVTemporalStreamError(
                                "current-frame spool length differs"
                            )
                        previous_frame, current_frame = current_frame, previous_frame
                        current_frame.seek(0)
                        current_frame.truncate(0)
                    active_frame = layout.frame_index
                strip = _read_block(canonical_source, layout.canonical_bytes)
                if len(strip) != layout.canonical_bytes:
                    raise CASVTemporalStreamError(
                        "canonical stream ended before its declared media size"
                    )
                frame_offset = (
                    layout.canonical_offset - layout.frame_index * frame_bytes
                )
                current_frame.seek(frame_offset)
                current_frame.write(strip)
                canonical_digest.update(strip)
                direct_zlib_bytes += len(direct_zlib.compress(strip))
                strip_hash = hashlib.sha256(strip).hexdigest()
                temporal_available = (
                    layout.frame_index > 0
                    and layout.frame_index % keyframe_interval != 0
                )
                previous_strip = None
                if temporal_available:
                    previous_frame.seek(frame_offset)
                    previous_strip = _read_block(previous_frame, layout.canonical_bytes)
                    if len(previous_strip) != layout.canonical_bytes:
                        raise CASVTemporalStreamError(
                            "previous-frame spool is incomplete"
                        )
                candidates: list[tuple[Any, dict[str, bytes]]] = []
                authority_payloads: list[dict[str, Any]] = []
                working_set = len(strip) + len(previous_strip or b"")
                for tile_layout in layout.tiles:
                    canonical_tile = extract_tile(strip, layout, tile_layout)
                    spatial = build_tile_candidates(
                        canonical_tile,
                        width=tile_layout.width,
                        height=layout.height,
                        bytes_per_pixel=layout.bytes_per_pixel,
                    )
                    payloads = dict(spatial.payloads)
                    reference_hash = "0" * 64
                    if previous_strip is not None:
                        previous_tile = extract_tile(
                            previous_strip, layout, tile_layout
                        )
                        temporal = build_temporal_candidates(
                            canonical_tile,
                            previous_tile,
                        )
                        payloads.update(temporal.payloads)
                        reference_hash = temporal.reference_sha256
                        temporal_candidate_tiles += 1
                    else:
                        previous_tile = None
                    for mode, payload in payloads.items():
                        if mode.startswith("TEMPORAL_"):
                            residual = _bounded_zlib(payload, len(canonical_tile))
                            restored = restore_temporal(
                                mode, residual, previous_tile or b""
                            )
                        else:
                            restored = decode_tile_payload(
                                mode,
                                payload,
                                width=tile_layout.width,
                                height=layout.height,
                                bytes_per_pixel=layout.bytes_per_pixel,
                                zlib_decoder=_bounded_zlib,
                            )
                        if restored != canonical_tile:
                            raise CASVTemporalStreamError(
                                f"{mode} candidate failed exact tile reconstruction"
                            )
                    candidates.append((tile_layout, payloads))
                    working_set += len(canonical_tile) + sum(
                        len(payload) for payload in payloads.values()
                    )
                    costs = {
                        mode: CASV_TEMPORAL_TILE_ENTRY.size + len(payload)
                        for mode, payload in payloads.items()
                    }
                    candidate_totals.update(costs)
                    authority_payloads.append(
                        {
                            "tile_index": tile_layout.tile_index,
                            "frame_index": layout.frame_index,
                            "plane_index": layout.plane_index,
                            "canonical_sha256": hashlib.sha256(
                                canonical_tile
                            ).hexdigest(),
                            "temporal_reference_sha256": reference_hash,
                            "temporal_available": temporal_available,
                            "exact_candidate_reconstruction": True,
                            "no_foreign_bitstream": True,
                            "dc_xor_bytes": costs["DC_XOR_ZLIB"],
                            "paeth_bytes": costs["PAETH_ZLIB"],
                            "direct_zlib_bytes": costs["CANONICAL_ZLIB"],
                            "raw_bytes": costs["CANONICAL_RAW"],
                            "temporal_xor_bytes": costs.get(
                                "TEMPORAL_XOR_ZLIB", UNAVAILABLE_TEMPORAL_COST
                            ),
                            "temporal_sub_bytes": costs.get(
                                "TEMPORAL_SUB_ZLIB", UNAVAILABLE_TEMPORAL_COST
                            ),
                        }
                    )
                maximum_candidate_working_set_bytes = max(
                    maximum_candidate_working_set_bytes,
                    working_set,
                )
                if working_set > MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES:
                    raise CASVTemporalStreamError(
                        "candidate family exceeds CASV/0.6 encoder memory covenant"
                    )
                chain_start = authority.previous_receipt_hash
                decisions = authority.decide_tiles(
                    authority_payloads,
                    record_index=layout.record_index,
                )
                table = bytearray()
                selected_payload = bytearray()
                for (_tile_layout, payloads), decision in zip(
                    candidates,
                    decisions,
                    strict=True,
                ):
                    if decision.storage_mode not in payloads:
                        raise CASVTemporalStreamError(
                            "T selected a candidate unavailable for this keyframe"
                        )
                    stored = payloads[decision.storage_mode]
                    table.extend(
                        CASV_TEMPORAL_TILE_ENTRY.pack(
                            MODE_IDS[decision.storage_mode],
                            len(stored),
                        )
                    )
                    selected_payload.extend(stored)
                    mode_counts[decision.storage_mode] += 1
                selected_tile_payload_bytes += len(selected_payload)
                record_header = CASV_TEMPORAL_RECORD_HEADER.pack(
                    CASV_TEMPORAL_RECORD_MAGIC,
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
                        "is_keyframe": not temporal_available,
                        "canonical_offset": layout.canonical_offset,
                        "canonical_length": layout.canonical_bytes,
                        "canonical_sha256": strip_hash,
                        "record_offset": record_offset,
                        "stored_length": CASV_TEMPORAL_RECORD_HEADER.size
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
                raise CASVTemporalStreamError(
                    "canonical stream exceeded its declared media size"
                )
            direct_zlib_bytes += len(direct_zlib.flush())
            if current_frame.tell() != frame_bytes:
                raise CASVTemporalStreamError("final frame spool length differs")
            if precommit_validator is not None:
                precommit_validator()

            canonical_hash = canonical_digest.digest()
            output.seek(header_offset)
            output.write(
                CASV_TEMPORAL_HEADER.pack(
                    {"RGB8": 1, "YUV444P10LE": 2}[spec.pixel_format],
                    0,
                    CASV_TEMPORAL_HEADER.size,
                    spec.width,
                    spec.height,
                    spec.frame_count,
                    spec.fps_numerator,
                    spec.fps_denominator,
                    tile_width,
                    strip_height,
                    keyframe_interval,
                    spec.expected_bytes,
                    canonical_hash,
                )
            )
            output.flush()
            os.fsync(output.fileno())

        content_digest = hashlib.sha256()
        with temporary.open("rb") as content:
            while block := content.read(8 * 1024 * 1024):
                content_digest.update(block)
        selection_authority = authority.manifest()
        with temporary.open("ab") as output:
            output.write(
                CASV_TEMPORAL_FOOTER.pack(
                    CASV_TEMPORAL_FOOTER_MAGIC,
                    authority.storage_decision_count,
                    bytes.fromhex(authority.previous_receipt_hash),
                    content_digest.digest(),
                )
            )
            output.flush()
            os.fsync(output.fileno())

        candidate_bytes = temporary.stat().st_size
        candidate_sha256 = _sha256_file(temporary)
        independent = verify_casv_temporal_stream(temporary)
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
    except (CASVTileIRError, CASVTemporalIRError, OSError, zlib.error) as exc:
        raise CASVTemporalStreamError(str(exc)) from exc
    finally:
        if temporary.exists():
            temporary.unlink()

    if independent is None:
        raise CASVTemporalStreamError("CASV/0.6 independent verification did not run")
    selected_record_stream_bytes = sum(
        record["stored_length"] for record in record_summaries
    )
    fixed_container_bytes = (
        len(CASV_TEMPORAL_MAGIC) + CASV_TEMPORAL_HEADER.size + CASV_TEMPORAL_FOOTER.size
    )
    authority_bytes = _directory_bytes(evidence_path / "authority")
    status = {
        "ACCEPT_BEATS_REFERENCE": "PASS_BEATS_DIRECT_ZLIB",
        "ACCEPT_RAW_ONLY": "EXACT_NONCOMPETITIVE",
        "REJECT": "REJECTED_NO_PUBLICATION",
    }[judgement_verdict]
    temporal_selected = sum(
        mode_counts[mode] for mode in mode_counts if mode.startswith("TEMPORAL_")
    )
    report = {
        "schema": "casulo.casv-temporal-pack-report/0.6",
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
        "keyframe_interval": keyframe_interval,
        "keyframe_count": sum(
            frame % keyframe_interval == 0 for frame in range(spec.frame_count)
        ),
        "temporal_candidate_tiles": temporal_candidate_tiles,
        "temporal_selected_tiles": temporal_selected,
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
        "archive_advantage_bytes_vs_direct_zlib": direct_zlib_bytes - candidate_bytes,
        "maximum_candidate_working_set_bytes": maximum_candidate_working_set_bytes,
        "encoder_working_set_covenant_bytes": MAX_ENCODER_CANDIDATE_WORKING_SET_BYTES,
        "previous_frame_spool_bytes": frame_bytes,
        "previous_frame_spool_medium": "ANONYMOUS_TEMPORARY_FILE",
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
            "temporal_prediction_implemented": True,
            "temporal_candidate_executed": temporal_candidate_tiles > 0,
            "temporal_candidate_selected": temporal_selected > 0,
            "keyframes_explicit_and_enforced": True,
            "full_frame_memory_allocation_required": False,
            "t_selected_each_committed_tile": True,
            "t_judgement_consumed_before_publication": True,
            "independent_exact_reconstruction": independent["status"] == "PASS",
            "native_casv_file": True,
            "contains_mp4_or_hevc_payload": False,
            "audio_included": False,
            "natural_video_compression_proven": False,
            "full_resolution_eight_k_encode_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (evidence_path / "record-index.json").write_bytes(
        _canonical_json(
            {
                "schema": "casulo.casv-temporal-record-index/0.6",
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


def pack_casv_temporal_stream_file(
    canonical_source: str | Path,
    spec: CanonicalVideoSpec,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    tile_width: int = 512,
    strip_height: int = 128,
    keyframe_interval: int = DEFAULT_KEYFRAME_INTERVAL,
    source_label: str | None = None,
    source_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_path = Path(canonical_source).resolve(strict=True)
    if not source_path.is_file() or source_path.stat().st_size != spec.expected_bytes:
        raise CASVTemporalStreamError(
            "canonical source length differs from its media spec"
        )
    with source_path.open("rb") as source:
        return pack_casv_temporal_stream_reader(
            source,
            spec,
            archive,
            evidence_dir=evidence_dir,
            policy_source=policy_source,
            runtime=runtime,
            tile_width=tile_width,
            strip_height=strip_height,
            keyframe_interval=keyframe_interval,
            source_label=source_label or source_path.name,
            source_descriptor=str(source_path),
            source_provenance=source_provenance,
        )


__all__ = [
    "CASVTemporalStreamError",
    "DEFAULT_KEYFRAME_INTERVAL",
    "pack_casv_temporal_stream_file",
    "pack_casv_temporal_stream_reader",
]
