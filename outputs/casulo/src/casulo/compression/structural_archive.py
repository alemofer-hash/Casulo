from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from .content_chunking import iter_content_defined_ranges
from .mp4_hevc import analyze_mp4_hevc
from .reversible_transforms import candidate_set, primitive_manifest
from .structural_authority import StructuralTAuthority
from .structural_ir import SegmentIR, build_ir, canonical_bytes


class StructuralArchiveError(RuntimeError):
    pass


def _sha256_file(path: Path, *, block_bytes: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=block_bytes) as stream:
        while block := stream.read(block_bytes):
            digest.update(block)
    return digest.hexdigest()


def _segment_id(index: int, offset: int, length: int, kind: str) -> str:
    seed = f"{index}:{offset}:{length}:{kind}".encode("ascii")
    return f"seg-{index:08d}-{hashlib.sha256(seed).hexdigest()[:16]}"


def _entropy_millibits(data: bytes) -> int:
    if not data:
        return 0
    counts = Counter(data)
    length = len(data)
    bits = -sum((count / length) * math.log2(count / length) for count in counts.values())
    return max(0, min(8000, round(bits * 1000)))


def _write_zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def _ranges(
    source: Path,
    top_boxes: list[dict[str, Any]],
) -> list[tuple[int, int, str, str]]:
    result: list[tuple[int, int, str, str]] = []
    with source.open("rb", buffering=1024 * 1024) as stream:
        for box in top_boxes:
            result.append((box["offset"], box["header_bytes"], "box_header", "fixed"))
            payload_offset = box["payload_offset"]
            payload_bytes = box["payload_bytes"]
            if payload_bytes == 0:
                continue
            kind = "media_payload" if box["type"] == "mdat" else "metadata_payload"
            if payload_bytes <= 1024 * 1024:
                result.append((payload_offset, payload_bytes, kind, "fixed"))
                continue
            for chunk in iter_content_defined_ranges(
                stream,
                offset=payload_offset,
                length=payload_bytes,
            ):
                result.append((chunk.offset, chunk.length, kind, f"cdc:{chunk.boundary}"))
    ordered = sorted(result, key=lambda item: item[0])
    expected = 0
    for offset, length, _kind, _boundary in ordered:
        if offset != expected or length <= 0:
            raise StructuralArchiveError("structural ranges do not exactly cover the source")
        expected += length
    if expected != source.stat().st_size:
        raise StructuralArchiveError("structural ranges end before the source")
    return ordered


def pack_structural(
    source: str | Path,
    archive: str | Path,
    *,
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    src = Path(source).resolve()
    target = Path(archive).resolve()
    evidence = Path(evidence_dir).resolve()
    if not src.is_file():
        raise StructuralArchiveError(f"source not found: {src}")
    if target.exists():
        raise StructuralArchiveError(f"archive already exists: {target}")
    if evidence.exists():
        raise StructuralArchiveError(f"evidence directory already exists: {evidence}")
    evidence.mkdir(parents=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    started_ns = time.perf_counter_ns()
    source_hash = _sha256_file(src)
    analysis = analyze_mp4_hevc(
        src,
        strict_sample_layout=not (probe is not None and probe.get("scientific_eligible") is False),
    )
    ranges = _ranges(src, analysis["top_level_boxes"])
    authority = StructuralTAuthority(policy_source, evidence / "authority", runtime=runtime)
    payload_root = Path(tempfile.mkdtemp(prefix="casulo-structural-payloads-", dir=target.parent))
    segments: list[SegmentIR] = []
    transform_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    candidate_work_bytes = 0
    selected_transform_operations = 0
    candidate_encode_ns = 0
    candidate_inverse_verify_ns = 0
    candidate_primitive_invocations = 0
    measurements: list[dict[str, Any]] = []
    unique_payload_bytes = 0
    stored_payloads: set[str] = set()
    try:
        with src.open("rb", buffering=4 * 1024 * 1024) as reader:
            for index, (offset, length, kind, boundary) in enumerate(ranges):
                reader.seek(offset)
                data = reader.read(length)
                if len(data) != length:
                    raise StructuralArchiveError(f"truncated source segment at {offset}")
                entropy_started = time.perf_counter_ns()
                entropy_millibits = _entropy_millibits(data)
                entropy_ns = time.perf_counter_ns() - entropy_started
                planning = authority.plan(
                    segment_index=index,
                    kind=kind,
                    source_bytes=length,
                    entropy_millibits_per_byte=entropy_millibits,
                )
                family = {
                    "RAW_ONLY": ("raw",),
                    "RAW_ZLIB_SHUFFLE": ("raw", "zlib", "shuffle4-zlib"),
                    "ALL": None,
                }[planning.candidate_family]
                candidates = candidate_set(data, kind=kind, names=family)
                decision = authority.decide(segment_index=index, kind=kind, candidates=candidates)
                selected = candidates[decision.transform]
                payload_name = f"payloads/{selected.payload_sha256}.bin"
                if selected.payload_sha256 not in stored_payloads:
                    (payload_root / f"{selected.payload_sha256}.bin").write_bytes(selected.payload)
                    stored_payloads.add(selected.payload_sha256)
                    unique_payload_bytes += selected.payload_bytes
                lane = "base" if kind == "box_header" else (
                    "residual" if selected.name == "raw" else "dynamics"
                )
                segment = SegmentIR(
                    index=index,
                    segment_id=_segment_id(index, offset, length, kind),
                    source_offset=offset,
                    source_length=length,
                    source_sha256=selected.source_sha256,
                    kind=kind,
                    lane=lane,
                    transform=selected.name,
                    inverse=selected.name,
                    payload_path=payload_name,
                    payload_sha256=selected.payload_sha256,
                    payload_bytes=selected.payload_bytes,
                    candidate_bytes={name: item.payload_bytes for name, item in candidates.items()},
                    primitive=selected.primitive,
                    authority_receipt_hash=str(decision.receipt["receipt_hash"]),
                )
                segments.append(segment)
                transform_counts[selected.name] += 1
                kind_counts[kind] += 1
                candidate_work_bytes += sum(item.payload_bytes for item in candidates.values())
                selected_transform_operations += selected.logical_operations
                candidate_encode_ns += sum(item.encode_ns for item in candidates.values())
                candidate_inverse_verify_ns += sum(item.inverse_verify_ns for item in candidates.values())
                candidate_primitive_invocations += len(candidates)
                measurements.append(
                    {
                        "segment_index": index,
                        "segment_id": segment.segment_id,
                        "kind": kind,
                        "source_bytes": length,
                        "entropy_millibits_per_byte": entropy_millibits,
                        "entropy_observation_ns": entropy_ns,
                        "candidate_family_selected_by_t": planning.candidate_family,
                        "planning_receipt_hash": planning.receipt["receipt_hash"],
                        "selected_by_t": selected.name,
                        "selection_receipt_hash": decision.receipt["receipt_hash"],
                        "candidates": {
                            name: {
                                "payload_bytes": item.payload_bytes,
                                "encode_ns": item.encode_ns,
                                "inverse_verify_ns": item.inverse_verify_ns,
                                "reversible_prepass_byte_operations": item.logical_operations,
                                "roundtrip": item.roundtrip,
                            }
                            for name, item in sorted(candidates.items())
                        },
                    }
                )

        authority_manifest = authority.manifest()
        plan = build_ir(
            source={"name": src.name, "bytes": src.stat().st_size, "sha256": source_hash},
            structure=analysis,
            segments=segments,
            authority=authority_manifest,
            primitives=primitive_manifest(),
            probe=probe,
        )
        accounting = {
            "schema": "casulo.structural-work-accounting/1.0",
            "source_bytes": src.stat().st_size,
            "source_segments": len(segments),
            "candidate_work_bytes": candidate_work_bytes,
            "candidate_encoded_bytes_total": candidate_work_bytes,
            "candidate_encode_ns_observed": candidate_encode_ns,
            "candidate_inverse_verify_ns_observed": candidate_inverse_verify_ns,
            "candidate_primitive_invocations": candidate_primitive_invocations,
            "selected_transform_operations_lower_bound": selected_transform_operations,
            "unique_payload_bytes": unique_payload_bytes,
            "logical_payload_reduction_bytes": src.stat().st_size - unique_payload_bytes,
            "transform_counts": dict(sorted(transform_counts.items())),
            "kind_counts": dict(sorted(kind_counts.items())),
            "t_policy_calls": authority.receipt_count,
            "t_segment_plans": len(segments),
            "t_segment_selections": len(segments),
            "t_receipt_chain_head": authority.previous_receipt_hash,
            "cdc": {
                "algorithm": "FastCDC-compatible deterministic gear boundaries",
                "gear_table_seed": "casulo-gear-v1",
                "min_bytes": 256 * 1024,
                "average_bytes": 1024 * 1024,
                "max_bytes": 4 * 1024 * 1024,
            },
        }
        (evidence / "mp4_hevc_analysis.json").write_bytes(canonical_bytes(analysis))
        (evidence / "transform_ir.json").write_bytes(canonical_bytes(plan))
        with (evidence / "transform_measurements.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for measurement in measurements:
                stream.write(json.dumps(measurement, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        (evidence / "work_accounting.json").write_bytes(canonical_bytes(accounting))

        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            with zipfile.ZipFile(temporary, "x", allowZip64=True) as output:
                _write_zip_entry(output, "plan.json", canonical_bytes(plan))
                _write_zip_entry(output, "work-accounting.json", canonical_bytes(accounting))
                _write_zip_entry(output, "authority/policy.t", Path(policy_source).resolve().read_bytes())
                _write_zip_entry(output, "authority/receipts.jsonl", authority.receipt_path.read_bytes())
                _write_zip_entry(output, "authority/decisions.jsonl", authority.trace_path.read_bytes())
                for file in sorted((evidence / "authority" / "policy.tcap").rglob("*")):
                    if file.is_file():
                        relative = file.relative_to(evidence / "authority" / "policy.tcap").as_posix()
                        _write_zip_entry(output, f"authority/tcap/{relative}", file.read_bytes())
                for payload_hash in sorted(stored_payloads):
                    _write_zip_entry(
                        output,
                        f"payloads/{payload_hash}.bin",
                        (payload_root / f"{payload_hash}.bin").read_bytes(),
                    )
            os.replace(temporary, target)
        except BaseException:
            if temporary.exists():
                temporary.unlink()
            raise
    except BaseException:
        (evidence / "FAILED.json").write_text(
            json.dumps({"status": "FAIL", "source": str(src)}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        shutil.rmtree(payload_root, ignore_errors=True)

    result = {
        "schema": "casulo.structural-pack-result/1.0",
        "status": "PASS",
        "source": str(src),
        "source_bytes": src.stat().st_size,
        "source_sha256": source_hash,
        "archive": str(target),
        "archive_bytes": target.stat().st_size,
        "archive_sha256": _sha256_file(target),
        "archive_to_source_ratio": target.stat().st_size / src.stat().st_size,
        "plan_sha256": plan["plan_sha256"],
        "authority": authority_manifest,
        "work_accounting": accounting,
        "elapsed_seconds": (time.perf_counter_ns() - started_ns) / 1_000_000_000,
    }
    (evidence / "pack_result.json").write_bytes(canonical_bytes(result))
    return result
