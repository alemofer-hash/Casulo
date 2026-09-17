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

from .gop_authority import GOPTAuthority
from .gop_transforms import gop_candidate_set, gop_primitive_manifest
from .structural_ir import canonical_bytes, canonical_sha256


class GOPArchiveError(RuntimeError):
    pass


def _sha256_file(path: Path, *, block_bytes: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=block_bytes) as stream:
        while block := stream.read(block_bytes):
            digest.update(block)
    return digest.hexdigest()


def _entropy_millibits(data: bytes) -> tuple[int, int]:
    if not data:
        return 0, 0
    sample_bytes = 64 * 1024
    if len(data) <= sample_bytes * 3:
        sample = data
    else:
        middle = (len(data) - sample_bytes) // 2
        sample = data[:sample_bytes] + data[middle : middle + sample_bytes] + data[-sample_bytes:]
    counts = Counter(sample)
    length = len(sample)
    bits = -sum((count / length) * math.log2(count / length) for count in counts.values())
    return max(0, min(8000, round(bits * 1000))), length


def _write_zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def _entry_id(index: int, sample_index: int, nal_index: int) -> str:
    seed = f"{index}:{sample_index}:{nal_index}".encode("ascii")
    return f"nal-{index:08d}-{hashlib.sha256(seed).hexdigest()[:16]}"


def _validate_corpus_manifest(corpus: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != "casulo.hevc-sample-corpus/1.0":
        raise GOPArchiveError("unsupported GOP corpus manifest")
    source = manifest.get("corpus")
    samples = manifest.get("samples")
    if not isinstance(source, dict) or not isinstance(samples, list) or not samples:
        raise GOPArchiveError("GOP corpus manifest is incomplete")
    if source.get("bytes") != corpus.stat().st_size:
        raise GOPArchiveError("GOP corpus byte length differs")
    if source.get("sha256") != _sha256_file(corpus):
        raise GOPArchiveError("GOP corpus hash differs")
    width = manifest.get("nal_length_bytes")
    if width not in {1, 2, 4}:
        raise GOPArchiveError("unsupported GOP corpus NAL length width")
    expected = 0
    entry_count = 0
    for sample_position, sample in enumerate(samples):
        if not isinstance(sample, dict) or sample.get("corpus_offset") != expected:
            raise GOPArchiveError("GOP sample sequence has a gap or overlap")
        sample_bytes = sample.get("bytes")
        nals = sample.get("nal_units")
        if not isinstance(sample_bytes, int) or sample_bytes <= 0 or not isinstance(nals, list):
            raise GOPArchiveError("GOP sample metadata is invalid")
        if sample_position == 0 and sample.get("is_irap") is not True:
            raise GOPArchiveError("GOP corpus must start at an IRAP sample")
        within = expected
        for nal_position, nal in enumerate(nals):
            if nal.get("nal_index") != nal_position or nal.get("corpus_prefix_offset") != within:
                raise GOPArchiveError("GOP NAL sequence has a gap or overlap")
            prefix_hex = nal.get("length_prefix_hex")
            header_hex = nal.get("header_hex")
            nal_bytes = nal.get("nal_bytes")
            body_bytes = nal.get("body_bytes")
            if (
                not isinstance(prefix_hex, str)
                or len(prefix_hex) != width * 2
                or not isinstance(header_hex, str)
                or len(header_hex) != 4
                or not isinstance(nal_bytes, int)
                or nal_bytes < 2
                or not isinstance(body_bytes, int)
                or body_bytes <= 0
                or body_bytes != nal_bytes - 2
            ):
                raise GOPArchiveError("GOP NAL dimensions are invalid")
            try:
                prefix = bytes.fromhex(prefix_hex)
                bytes.fromhex(header_hex)
            except ValueError as exc:
                raise GOPArchiveError("GOP NAL base contains invalid hex") from exc
            if int.from_bytes(prefix, "big") != nal_bytes:
                raise GOPArchiveError("GOP NAL prefix differs from declared length")
            if nal.get("corpus_body_offset") != within + width + 2:
                raise GOPArchiveError("GOP NAL body offset differs")
            within += width + nal_bytes
            entry_count += 1
        if within != expected + sample_bytes:
            raise GOPArchiveError("GOP NAL units do not exactly cover a sample")
        expected += sample_bytes
    if expected != corpus.stat().st_size:
        raise GOPArchiveError("GOP samples do not exactly cover the corpus")
    if manifest.get("nal_unit_count") != entry_count:
        raise GOPArchiveError("GOP NAL count differs")


def pack_gop_corpus(
    corpus: str | Path,
    archive: str | Path,
    *,
    corpus_manifest: dict[str, Any],
    evidence_dir: str | Path,
    policy_source: str | Path,
    runtime: str | Path | None = None,
) -> dict[str, Any]:
    """Encode a sample-aligned HEVC corpus as base + dynamics + residual."""

    source = Path(corpus).resolve()
    target = Path(archive).resolve()
    evidence = Path(evidence_dir).resolve()
    if not source.is_file():
        raise GOPArchiveError(f"GOP corpus not found: {source}")
    if target.exists() or evidence.exists():
        raise GOPArchiveError("GOP archive and evidence paths must be new")
    _validate_corpus_manifest(source, corpus_manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True)
    started_ns = time.perf_counter_ns()
    authority = GOPTAuthority(policy_source, evidence / "authority", runtime=runtime)
    payload_root = Path(tempfile.mkdtemp(prefix="casulo-gop-payloads-", dir=target.parent))
    entries: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    measurements: list[dict[str, Any]] = []
    stored_payloads: set[str] = set()
    prior_by_class: dict[str, tuple[str, bytes]] = {}
    transform_counts: Counter[str] = Counter()
    candidate_families: Counter[str] = Counter()
    unique_payload_bytes = 0
    candidate_work_bytes = 0
    candidate_invocations = 0
    candidate_encode_ns = 0
    candidate_inverse_ns = 0
    selected_operations = 0
    base_source_bytes = 0
    dynamics_source_bytes = 0
    residual_source_bytes = 0
    width = int(corpus_manifest["nal_length_bytes"])
    expected_corpus_offset = 0
    try:
        with source.open("rb", buffering=4 * 1024 * 1024) as reader:
            for sample in corpus_manifest["samples"]:
                if sample["corpus_offset"] != expected_corpus_offset:
                    raise GOPArchiveError("sample offset changed after manifest validation")
                sample_entry_ids: list[str] = []
                sample_start = expected_corpus_offset
                for nal in sample["nal_units"]:
                    entry_index = len(entries)
                    entry_id = _entry_id(
                        entry_index, int(sample["sample_index"]), int(nal["nal_index"])
                    )
                    prefix = bytes.fromhex(nal["length_prefix_hex"])
                    header = bytes.fromhex(nal["header_hex"])
                    reader.seek(int(nal["corpus_prefix_offset"]))
                    observed_base = reader.read(width + 2)
                    if observed_base != prefix + header:
                        raise GOPArchiveError("sealed NAL base differs from corpus bytes")
                    body_bytes = int(nal["body_bytes"])
                    body = reader.read(body_bytes)
                    if len(body) != body_bytes:
                        raise GOPArchiveError("truncated NAL body in corpus")
                    entropy_started = time.perf_counter_ns()
                    entropy_millibits, entropy_sample_bytes = _entropy_millibits(body)
                    entropy_ns = time.perf_counter_ns() - entropy_started
                    reference = prior_by_class.get(str(nal["nal_class"]))
                    planning = authority.plan(
                        unit_index=entry_index,
                        nal_class=str(nal["nal_class"]),
                        source_bytes=body_bytes,
                        high_entropy=entropy_millibits >= 7500,
                        reference_available=reference is not None,
                    )
                    family = {
                        "RAW_ONLY": ("raw",),
                        "RAW_ZLIB": ("raw", "zlib"),
                        "RAW_ZLIB_XOR": (
                            "raw",
                            "zlib",
                            "xor-reference-prefix-zlib",
                        ),
                    }[planning.candidate_family]
                    candidates = gop_candidate_set(
                        body,
                        names=family,
                        reference=None if reference is None else reference[1],
                    )
                    decision = authority.decide(
                        unit_index=entry_index,
                        candidates=candidates,
                    )
                    selected = candidates[decision.transform]
                    payload_path = f"payloads/{selected.payload_sha256}.bin"
                    if selected.payload_sha256 not in stored_payloads:
                        (payload_root / f"{selected.payload_sha256}.bin").write_bytes(
                            selected.payload
                        )
                        stored_payloads.add(selected.payload_sha256)
                        unique_payload_bytes += selected.payload_bytes
                    lane = "dynamics" if selected.name != "raw" else "residual"
                    base_id = f"base-{entry_id}"
                    entry = {
                        "index": entry_index,
                        "entry_id": entry_id,
                        "base_id": base_id,
                        "sample_index": int(sample["sample_index"]),
                        "nal_index": int(nal["nal_index"]),
                        "nal_unit_type": int(nal["nal_unit_type"]),
                        "nal_class": str(nal["nal_class"]),
                        "layer_id": int(nal["layer_id"]),
                        "temporal_id_plus1": int(nal["temporal_id_plus1"]),
                        "corpus_prefix_offset": int(nal["corpus_prefix_offset"]),
                        "length_prefix_hex": prefix.hex(),
                        "nal_bytes": int(nal["nal_bytes"]),
                        "header_hex": header.hex(),
                        "base_source_sha256": hashlib.sha256(prefix + header).hexdigest(),
                        "body_bytes": body_bytes,
                        "body_source_sha256": selected.source_sha256,
                        "lane": lane,
                        "transform": selected.name,
                        "inverse": selected.name,
                        "reference_entry_id": None if reference is None else reference[0],
                        "payload_path": payload_path,
                        "payload_sha256": selected.payload_sha256,
                        "payload_bytes": selected.payload_bytes,
                        "candidate_family": planning.candidate_family,
                        "candidate_bytes": {
                            name: candidate.payload_bytes
                            for name, candidate in sorted(candidates.items())
                        },
                        "primitive": selected.primitive,
                        "planning_receipt_hash": planning.receipt["receipt_hash"],
                        "authority_receipt_hash": decision.receipt["receipt_hash"],
                    }
                    entries.append(entry)
                    sample_entry_ids.append(entry_id)
                    base_source_bytes += width + 2
                    if lane == "dynamics":
                        dynamics_source_bytes += body_bytes
                    else:
                        residual_source_bytes += body_bytes
                    transform_counts[selected.name] += 1
                    candidate_families[planning.candidate_family] += 1
                    candidate_work_bytes += sum(
                        candidate.payload_bytes for candidate in candidates.values()
                    )
                    candidate_invocations += len(candidates)
                    candidate_encode_ns += sum(
                        candidate.encode_ns for candidate in candidates.values()
                    )
                    candidate_inverse_ns += sum(
                        candidate.inverse_verify_ns for candidate in candidates.values()
                    )
                    selected_operations += selected.logical_operations
                    measurements.append({
                        "entry_index": entry_index,
                        "entry_id": entry_id,
                        "sample_index": sample["sample_index"],
                        "nal_index": nal["nal_index"],
                        "nal_unit_type": nal["nal_unit_type"],
                        "nal_class": nal["nal_class"],
                        "source_bytes": body_bytes,
                        "entropy_sample_bytes": entropy_sample_bytes,
                        "entropy_millibits_per_byte": entropy_millibits,
                        "entropy_observation_ns": entropy_ns,
                        "reference_entry_id": None if reference is None else reference[0],
                        "candidate_family_selected_by_t": planning.candidate_family,
                        "selected_by_t": selected.name,
                        "candidates": {
                            name: {
                                "payload_bytes": candidate.payload_bytes,
                                "encode_ns": candidate.encode_ns,
                                "inverse_verify_ns": candidate.inverse_verify_ns,
                                "logical_operations": candidate.logical_operations,
                                "reference_bytes": candidate.reference_bytes,
                                "roundtrip": candidate.roundtrip,
                            }
                            for name, candidate in sorted(candidates.items())
                        },
                    })
                    prior_by_class[str(nal["nal_class"])] = (entry_id, body)
                    expected_corpus_offset += width + int(nal["nal_bytes"])
                if expected_corpus_offset != sample_start + int(sample["bytes"]):
                    raise GOPArchiveError("encoded NAL units do not exactly cover sample")
                sample_rows.append(
                    {
                        "sample_index": int(sample["sample_index"]),
                        "corpus_offset": int(sample["corpus_offset"]),
                        "bytes": int(sample["bytes"]),
                        "sha256": str(sample["sha256"]),
                        "is_irap": bool(sample["is_irap"]),
                        "entry_ids": sample_entry_ids,
                    }
                )
        if expected_corpus_offset != source.stat().st_size:
            raise GOPArchiveError("encoded entries do not exactly cover corpus")
        if base_source_bytes + dynamics_source_bytes + residual_source_bytes != source.stat().st_size:
            raise GOPArchiveError("base + dynamics + residual accounting differs")

        authority_manifest = authority.manifest(
            decision_protocol=["plan", "decide"],
            unit="nal_body",
            receipts_per_unit=2,
        )
        seed = {
            "schema": "casulo.hevc-gop-transform-ir/1.0",
            "source": {
                "name": source.name,
                "bytes": source.stat().st_size,
                "sha256": _sha256_file(source),
            },
            "origin": {
                "name": Path(corpus_manifest["source"]["path"]).name,
                "bytes": corpus_manifest["source"]["bytes"],
                "accepted_sha256": corpus_manifest["source"].get("accepted_sha256"),
            },
            "nal_length_bytes": width,
            "samples": sample_rows,
            "entries": entries,
            "base": {
                "role": "exact NAL length prefixes and two-byte headers",
                "source_bytes": base_source_bytes,
                "base_ids": [entry["base_id"] for entry in entries],
            },
            "dynamics": {
                "role": "NAL bodies transformed reversibly under T authority",
                "source_bytes": dynamics_source_bytes,
                "entry_ids": [
                    entry["entry_id"] for entry in entries if entry["lane"] == "dynamics"
                ],
            },
            "residual": {
                "role": "opaque entropy-coded NAL bodies retained literally",
                "source_bytes": residual_source_bytes,
                "entry_ids": [
                    entry["entry_id"] for entry in entries if entry["lane"] == "residual"
                ],
            },
            "authority": authority_manifest,
            "primitives": gop_primitive_manifest(),
            "probe": {
                "sample_aligned": corpus_manifest["sample_aligned"],
                "starts_with_irap": corpus_manifest["starts_with_irap"],
                "complete_gop": corpus_manifest["complete_gop"],
                "scientific_eligible": corpus_manifest["scientific_eligible"],
                "sample_indices": corpus_manifest["sample_indices"],
            },
        }
        plan = {**seed, "plan_sha256": canonical_sha256(seed)}
        accounting = {
            "schema": "casulo.hevc-gop-work-accounting/1.0",
            "source_bytes": source.stat().st_size,
            "sample_count": len(sample_rows),
            "nal_body_count": len(entries),
            "base_source_bytes": base_source_bytes,
            "dynamics_source_bytes": dynamics_source_bytes,
            "residual_source_bytes": residual_source_bytes,
            "partition_exact": base_source_bytes + dynamics_source_bytes + residual_source_bytes
            == source.stat().st_size,
            "unique_payload_bytes": unique_payload_bytes,
            "candidate_encoded_bytes_total": candidate_work_bytes,
            "candidate_primitive_invocations": candidate_invocations,
            "candidate_encode_ns_observed": candidate_encode_ns,
            "candidate_inverse_verify_ns_observed": candidate_inverse_ns,
            "selected_transform_operations_lower_bound": selected_operations,
            "transform_counts": dict(sorted(transform_counts.items())),
            "candidate_family_counts": dict(sorted(candidate_families.items())),
            "t_policy_calls": authority.receipt_count,
            "t_receipt_chain_head": authority.previous_receipt_hash,
        }
        (evidence / "corpus_manifest.json").write_bytes(canonical_bytes(corpus_manifest))
        (evidence / "gop_transform_ir.json").write_bytes(canonical_bytes(plan))
        (evidence / "work_accounting.json").write_bytes(canonical_bytes(accounting))
        with (evidence / "transform_measurements.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as stream:
            for measurement in measurements:
                stream.write(
                    json.dumps(
                        measurement,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )

        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            with zipfile.ZipFile(temporary, "x", allowZip64=True) as output:
                _write_zip_entry(output, "plan.json", canonical_bytes(plan))
                _write_zip_entry(output, "work-accounting.json", canonical_bytes(accounting))
                _write_zip_entry(
                    output, "authority/policy.t", Path(policy_source).resolve().read_bytes()
                )
                _write_zip_entry(output, "authority/receipts.jsonl", authority.receipt_path.read_bytes())
                _write_zip_entry(output, "authority/decisions.jsonl", authority.trace_path.read_bytes())
                for file in sorted((evidence / "authority" / "policy.tcap").rglob("*")):
                    if file.is_file():
                        relative = file.relative_to(
                            evidence / "authority" / "policy.tcap"
                        ).as_posix()
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
            json.dumps({"status": "FAIL", "source": str(source)}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        shutil.rmtree(payload_root, ignore_errors=True)

    result = {
        "schema": "casulo.hevc-gop-pack-result/1.0",
        "status": "PASS",
        "source": str(source),
        "source_bytes": source.stat().st_size,
        "source_sha256": _sha256_file(source),
        "archive": str(target),
        "archive_bytes": target.stat().st_size,
        "archive_sha256": _sha256_file(target),
        "archive_to_source_ratio": target.stat().st_size / source.stat().st_size,
        "plan_sha256": plan["plan_sha256"],
        "authority": authority_manifest,
        "work_accounting": accounting,
        "elapsed_seconds": (time.perf_counter_ns() - started_ns) / 1_000_000_000,
    }
    (evidence / "pack_result.json").write_bytes(canonical_bytes(result))
    return result


__all__ = ["GOPArchiveError", "pack_gop_corpus"]
