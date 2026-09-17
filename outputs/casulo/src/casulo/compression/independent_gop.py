from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import tempfile
import zipfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


class IndependentGOPError(RuntimeError):
    pass


SHA256 = re.compile(r"[0-9a-f]{64}")
PAYLOAD = re.compile(r"payloads/([0-9a-f]{64})\.bin")
TRANSFORMS = frozenset({"raw", "zlib", "xor-reference-prefix-zlib"})
XOR_PREFIX_LIMIT = 1024 * 1024


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
    )


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _t_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise IndependentGOPError(f"invalid SHA-256: {label}")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise IndependentGOPError(f"invalid integer: {label}")
    return value


def _load_json(archive: zipfile.ZipFile, name: str, *, maximum: int) -> Any:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise IndependentGOPError(f"missing archive member: {name}") from exc
    if info.file_size > maximum:
        raise IndependentGOPError(f"archive member exceeds limit: {name}")
    try:
        return json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IndependentGOPError(f"invalid JSON member: {name}") from exc


def _safe_decompress(payload: bytes, expected_size: int) -> bytes:
    decoder = zlib.decompressobj()
    result = decoder.decompress(payload, expected_size + 1)
    if len(result) > expected_size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise IndependentGOPError("bounded zlib decode failed")
    result += decoder.flush()
    if len(result) != expected_size:
        raise IndependentGOPError("decoded payload size differs")
    return result


def _inverse(
    name: str,
    payload: bytes,
    expected_size: int,
    reference: bytes | None,
) -> bytes:
    if name == "raw":
        decoded = payload
    elif name == "zlib":
        decoded = _safe_decompress(payload, expected_size)
    elif name == "xor-reference-prefix-zlib":
        if reference is None or len(payload) < 8:
            raise IndependentGOPError("xor-reference payload lacks its reference or header")
        prefix_bytes, compressed_bytes = struct.unpack(">II", payload[:8])
        if (
            prefix_bytes <= 0
            or prefix_bytes > expected_size
            or prefix_bytes > len(reference)
            or prefix_bytes > XOR_PREFIX_LIMIT
            or compressed_bytes <= 0
            or 8 + compressed_bytes > len(payload)
        ):
            raise IndependentGOPError("xor-reference payload header differs")
        residual = _safe_decompress(payload[8 : 8 + compressed_bytes], prefix_bytes)
        prefix = bytes(
            left ^ right for left, right in zip(residual, reference[:prefix_bytes])
        )
        decoded = prefix + payload[8 + compressed_bytes :]
    else:
        raise IndependentGOPError(f"unknown GOP inverse: {name}")
    if len(decoded) != expected_size:
        raise IndependentGOPError("GOP inverse produced the wrong byte count")
    return decoded


def _validate_tcap(archive: zipfile.ZipFile, authority: Mapping[str, Any]) -> None:
    manifest = _load_json(
        archive, "authority/tcap/MANIFEST.json", maximum=16 * 1024 * 1024
    )
    if manifest.get("schema") != "casulo.tcap/2.0":
        raise IndependentGOPError("embedded TCAP schema differs")
    sections = manifest.get("sections")
    sources = manifest.get("sources")
    if not isinstance(sections, dict) or not isinstance(sources, list):
        raise IndependentGOPError("embedded TCAP manifest is incomplete")
    for entry in list(sections.values()) + sources:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise IndependentGOPError("embedded TCAP entry is invalid")
        name = f"authority/tcap/{entry['file']}"
        try:
            info = archive.getinfo(name)
        except KeyError as exc:
            raise IndependentGOPError(f"missing embedded TCAP member: {name}") from exc
        if info.file_size > 16 * 1024 * 1024:
            raise IndependentGOPError("embedded TCAP member exceeds limit")
        content = archive.read(info)
        if hashlib.sha256(content).hexdigest() != _hash(entry.get("sha256"), name):
            raise IndependentGOPError("embedded TCAP member hash differs")
    seed = {"schema": "casulo.tcap/2.0", "sections": sections, "sources": sources}
    if (
        _t_hash(seed) != manifest.get("tcap_hash")
        or manifest.get("tcap_hash") != authority.get("tcap_sha256")
    ):
        raise IndependentGOPError("embedded TCAP identity differs")
    policy = archive.read("authority/policy.t")
    if hashlib.sha256(policy).hexdigest() != authority.get("t_source_sha256"):
        raise IndependentGOPError("embedded T policy hash differs")


def _read_jsonl(raw: bytes, label: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IndependentGOPError(f"invalid {label} line {line_number}") from exc
        if not isinstance(value, dict):
            raise IndependentGOPError(f"{label} line must be an object")
        result.append(value)
    return result


def _validate_receipts(
    archive: zipfile.ZipFile,
    plan: Mapping[str, Any],
) -> tuple[int, str]:
    receipt_info = archive.getinfo("authority/receipts.jsonl")
    trace_info = archive.getinfo("authority/decisions.jsonl")
    if receipt_info.file_size > 256 * 1024 * 1024 or trace_info.file_size > 256 * 1024 * 1024:
        raise IndependentGOPError("GOP authority log exceeds limit")
    receipt_raw = archive.read(receipt_info)
    trace_raw = archive.read(trace_info)
    receipts = _read_jsonl(receipt_raw, "T receipt")
    traces = _read_jsonl(trace_raw, "T trace")
    entries = plan["entries"]
    authority = plan["authority"]
    if (
        authority.get("decision_protocol") != ["plan", "decide"]
        or authority.get("unit") != "nal_body"
        or authority.get("receipts_per_unit") != 2
    ):
        raise IndependentGOPError("unsupported GOP T decision protocol")
    if len(receipts) != len(entries) * 2 or len(traces) != len(receipts):
        raise IndependentGOPError("GOP T receipt count differs")
    if hashlib.sha256(receipt_raw).hexdigest() != authority.get("receipt_log_sha256"):
        raise IndependentGOPError("GOP T receipt log hash differs")
    if hashlib.sha256(trace_raw).hexdigest() != authority.get("decision_trace_sha256"):
        raise IndependentGOPError("GOP T trace hash differs")
    previous = "0" * 64
    for index, (receipt, trace) in enumerate(zip(receipts, traces, strict=True)):
        claimed = _hash(receipt.get("receipt_hash"), f"receipt {index}")
        if _t_hash({key: value for key, value in receipt.items() if key != "receipt_hash"}) != claimed:
            raise IndependentGOPError(f"GOP T receipt hash differs at {index}")
        if receipt.get("previous_receipt_hash") != previous:
            raise IndependentGOPError(f"GOP T receipt chain differs at {index}")
        if receipt.get("t_source_hash") != authority.get("t_source_sha256"):
            raise IndependentGOPError("GOP receipt T source identity differs")
        if receipt.get("t_ir_hash") != authority.get("t_ir_sha256"):
            raise IndependentGOPError("GOP receipt T IR identity differs")
        if receipt.get("tcap_hash") != authority.get("tcap_sha256"):
            raise IndependentGOPError("GOP receipt TCAP identity differs")
        if receipt.get("result") != "ok":
            raise IndependentGOPError("non-accepting T receipt in GOP archive")
        if trace.get("schema") != "casulo.gop-t-decision-trace/1.0":
            raise IndependentGOPError("GOP T trace schema differs")
        if trace.get("receipt_hash") != claimed:
            raise IndependentGOPError("GOP trace-to-receipt link differs")
        if receipt.get("canonical_input_hash") != _t_hash(trace.get("input")):
            raise IndependentGOPError("GOP T input hash differs")
        if receipt.get("canonical_output_hash") != _t_hash(trace.get("observable")):
            raise IndependentGOPError("GOP T output hash differs")
        previous = claimed

    families = {
        "RAW_ONLY": {"raw"},
        "RAW_ZLIB": {"raw", "zlib"},
        "RAW_ZLIB_XOR": {"raw", "zlib", "xor-reference-prefix-zlib"},
    }
    for entry in entries:
        index = entry["index"]
        planning = receipts[index * 2]
        decision = receipts[index * 2 + 1]
        plan_trace = traces[index * 2]
        decision_trace = traces[index * 2 + 1]
        if not str(planning.get("runtime_function", "")).endswith("::plan"):
            raise IndependentGOPError("GOP planning receipt is absent")
        if not str(decision.get("runtime_function", "")).endswith("::decide"):
            raise IndependentGOPError("GOP decision receipt is absent")
        if plan_trace.get("phase") != "plan" or decision_trace.get("phase") != "decide":
            raise IndependentGOPError("GOP T decision phases differ")
        if plan_trace.get("unit_index") != index or decision_trace.get("unit_index") != index:
            raise IndependentGOPError("GOP T decision index differs")
        if entry.get("planning_receipt_hash") != planning.get("receipt_hash"):
            raise IndependentGOPError("GOP entry-to-planning receipt link differs")
        if entry.get("authority_receipt_hash") != decision.get("receipt_hash"):
            raise IndependentGOPError("GOP entry-to-decision receipt link differs")
        plan_input = plan_trace.get("input", {})
        if (
            plan_input.get("nal_class") != entry.get("nal_class")
            or plan_input.get("source_bytes") != entry.get("body_bytes")
            or plan_input.get("reference_available")
            != (entry.get("reference_entry_id") is not None)
        ):
            raise IndependentGOPError("GOP planning evidence differs")
        family_result = plan_trace.get("observable", {}).get("result", {})
        family = family_result.get("value") if family_result.get("kind") == "ok" else None
        if family != entry.get("candidate_family"):
            raise IndependentGOPError("GOP candidate family was not consumed")
        if family not in families or set(entry.get("candidate_bytes", {})) != families[family]:
            raise IndependentGOPError("GOP executed candidate set differs from T plan")
        candidate_bytes = entry["candidate_bytes"]
        decision_input = decision_trace.get("input", {})
        expected = {
            "raw_bytes": candidate_bytes["raw"],
            "has_zlib": "zlib" in candidate_bytes,
            "zlib_bytes": candidate_bytes.get("zlib", candidate_bytes["raw"]),
            "has_xor_reference": "xor-reference-prefix-zlib" in candidate_bytes,
            "xor_reference_bytes": candidate_bytes.get(
                "xor-reference-prefix-zlib", candidate_bytes["raw"]
            ),
        }
        if any(decision_input.get(key) != value for key, value in expected.items()):
            raise IndependentGOPError("GOP candidate measurements differ from T evidence")
        result = decision_trace.get("observable", {}).get("result", {})
        if result.get("kind") != "ok" or result.get("value") != entry.get("transform"):
            raise IndependentGOPError("GOP T transform selection was not consumed")
    if previous != authority.get("receipt_chain_head"):
        raise IndependentGOPError("GOP T receipt chain head differs")
    return len(receipts), previous


def _validate_plan(plan: object) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(plan, dict) or plan.get("schema") != "casulo.hevc-gop-transform-ir/1.0":
        raise IndependentGOPError("unsupported HEVC GOP transform IR")
    expected_top = {
        "schema",
        "source",
        "origin",
        "nal_length_bytes",
        "samples",
        "entries",
        "base",
        "dynamics",
        "residual",
        "authority",
        "primitives",
        "probe",
        "plan_sha256",
    }
    if set(plan) != expected_top:
        raise IndependentGOPError("HEVC GOP IR fields differ")
    seed = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if _canonical_hash(seed) != _hash(plan.get("plan_sha256"), "plan sha256"):
        raise IndependentGOPError("HEVC GOP IR canonical hash differs")
    source = plan.get("source")
    authority = plan.get("authority")
    entries = plan.get("entries")
    samples = plan.get("samples")
    if (
        not isinstance(source, dict)
        or not isinstance(authority, dict)
        or not isinstance(entries, list)
        or not entries
        or not isinstance(samples, list)
        or not samples
    ):
        raise IndependentGOPError("HEVC GOP IR core objects are invalid")
    source_bytes = _integer(source.get("bytes"), "source bytes", minimum=1)
    _hash(source.get("sha256"), "source sha256")
    width = plan.get("nal_length_bytes")
    if width not in {1, 2, 4}:
        raise IndependentGOPError("unsupported HEVC NAL length width")
    if authority.get("causal") is not True:
        raise IndependentGOPError("HEVC GOP T authority is not causal")
    for key in (
        "t_source_sha256",
        "t_ir_sha256",
        "tcap_sha256",
        "receipt_chain_head",
        "receipt_log_sha256",
        "decision_trace_sha256",
    ):
        _hash(authority.get(key), key)

    base = plan.get("base")
    dynamics = plan.get("dynamics")
    residual = plan.get("residual")
    if not isinstance(base, dict) or not isinstance(dynamics, dict) or not isinstance(residual, dict):
        raise IndependentGOPError("HEVC GOP partitions are invalid")
    base_ids = base.get("base_ids")
    dynamic_ids = dynamics.get("entry_ids")
    residual_ids = residual.get("entry_ids")
    if not all(isinstance(value, list) for value in (base_ids, dynamic_ids, residual_ids)):
        raise IndependentGOPError("HEVC GOP partition identifiers are invalid")
    if len(set(base_ids)) != len(base_ids) or len(set(dynamic_ids)) != len(dynamic_ids) or len(set(residual_ids)) != len(residual_ids):
        raise IndependentGOPError("HEVC GOP partition contains duplicate identifiers")
    if set(dynamic_ids) & set(residual_ids):
        raise IndependentGOPError("HEVC GOP dynamics and residual overlap")

    expected_entry_fields = {
        "index",
        "entry_id",
        "base_id",
        "sample_index",
        "nal_index",
        "nal_unit_type",
        "nal_class",
        "layer_id",
        "temporal_id_plus1",
        "corpus_prefix_offset",
        "length_prefix_hex",
        "nal_bytes",
        "header_hex",
        "base_source_sha256",
        "body_bytes",
        "body_source_sha256",
        "lane",
        "transform",
        "inverse",
        "reference_entry_id",
        "payload_path",
        "payload_sha256",
        "payload_bytes",
        "candidate_family",
        "candidate_bytes",
        "primitive",
        "planning_receipt_hash",
        "authority_receipt_hash",
    }
    entry_ids: set[str] = set()
    expected_offset = 0
    base_bytes = 0
    dynamic_bytes = 0
    residual_bytes = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != expected_entry_fields:
            raise IndependentGOPError("HEVC GOP entry fields differ")
        if entry.get("index") != index or entry.get("corpus_prefix_offset") != expected_offset:
            raise IndependentGOPError("HEVC GOP entry sequence has a gap or overlap")
        entry_id = entry.get("entry_id")
        base_id = entry.get("base_id")
        if (
            not isinstance(entry_id, str)
            or entry_id in entry_ids
            or not isinstance(base_id, str)
        ):
            raise IndependentGOPError("HEVC GOP entry identity differs")
        entry_ids.add(entry_id)
        prefix_hex = entry.get("length_prefix_hex")
        header_hex = entry.get("header_hex")
        nal_bytes = _integer(entry.get("nal_bytes"), "NAL bytes", minimum=3)
        body_bytes = _integer(entry.get("body_bytes"), "NAL body bytes", minimum=1)
        if body_bytes != nal_bytes - 2 or not isinstance(prefix_hex, str) or not isinstance(header_hex, str):
            raise IndependentGOPError("HEVC GOP NAL dimensions differ")
        try:
            prefix = bytes.fromhex(prefix_hex)
            header = bytes.fromhex(header_hex)
        except ValueError as exc:
            raise IndependentGOPError("HEVC GOP base hex is invalid") from exc
        if len(prefix) != width or len(header) != 2 or int.from_bytes(prefix, "big") != nal_bytes:
            raise IndependentGOPError("HEVC GOP NAL base differs")
        observed_nal_type = (header[0] >> 1) & 0x3F
        observed_layer_id = ((header[0] & 0x01) << 5) | (header[1] >> 3)
        observed_temporal_id = header[1] & 0x07
        if (
            header[0] & 0x80
            or observed_temporal_id == 0
            or entry.get("nal_unit_type") != observed_nal_type
            or entry.get("layer_id") != observed_layer_id
            or entry.get("temporal_id_plus1") != observed_temporal_id
        ):
            raise IndependentGOPError("HEVC GOP decoded NAL header semantics differ")
        if hashlib.sha256(prefix + header).hexdigest() != _hash(
            entry.get("base_source_sha256"), "base source sha256"
        ):
            raise IndependentGOPError("HEVC GOP base hash differs")
        _hash(entry.get("body_source_sha256"), "body source sha256")
        transform = entry.get("transform")
        lane = entry.get("lane")
        if transform not in TRANSFORMS or entry.get("inverse") != transform:
            raise IndependentGOPError("HEVC GOP inverse differs")
        if (transform == "raw" and lane != "residual") or (
            transform != "raw" and lane != "dynamics"
        ):
            raise IndependentGOPError("HEVC GOP transform is assigned to the wrong lane")
        reference = entry.get("reference_entry_id")
        if reference is not None and reference not in entry_ids:
            raise IndependentGOPError("HEVC GOP reference is not strictly backward")
        if transform == "xor-reference-prefix-zlib" and reference is None:
            raise IndependentGOPError("HEVC GOP XOR transform lacks a reference")
        payload_hash = _hash(entry.get("payload_sha256"), "payload sha256")
        if entry.get("payload_path") != f"payloads/{payload_hash}.bin":
            raise IndependentGOPError("HEVC GOP payload is not content-addressed")
        payload_bytes = _integer(entry.get("payload_bytes"), "payload bytes")
        if payload_bytes > 64 * 1024 * 1024:
            raise IndependentGOPError("HEVC GOP payload exceeds decoder memory contract")
        candidates = entry.get("candidate_bytes")
        if not isinstance(candidates, dict) or candidates.get("raw") != body_bytes:
            raise IndependentGOPError("HEVC GOP raw candidate differs")
        for name, size in candidates.items():
            if name not in TRANSFORMS:
                raise IndependentGOPError("unknown HEVC GOP candidate")
            _integer(size, "candidate bytes")
        if candidates.get(transform) != payload_bytes:
            raise IndependentGOPError("HEVC GOP selected candidate size differs")
        _hash(entry.get("planning_receipt_hash"), "planning receipt hash")
        _hash(entry.get("authority_receipt_hash"), "authority receipt hash")
        expected_offset += width + nal_bytes
        base_bytes += width + 2
        if lane == "dynamics":
            dynamic_bytes += body_bytes
        else:
            residual_bytes += body_bytes

    if expected_offset != source_bytes:
        raise IndependentGOPError("HEVC GOP entries do not exactly cover source")
    if set(base_ids) != {entry["base_id"] for entry in entries}:
        raise IndependentGOPError("HEVC GOP base partition differs")
    if set(dynamic_ids) != {entry["entry_id"] for entry in entries if entry["lane"] == "dynamics"}:
        raise IndependentGOPError("HEVC GOP dynamics partition differs")
    if set(residual_ids) != {entry["entry_id"] for entry in entries if entry["lane"] == "residual"}:
        raise IndependentGOPError("HEVC GOP residual partition differs")
    if (
        base.get("source_bytes") != base_bytes
        or dynamics.get("source_bytes") != dynamic_bytes
        or residual.get("source_bytes") != residual_bytes
        or base_bytes + dynamic_bytes + residual_bytes != source_bytes
    ):
        raise IndependentGOPError("HEVC GOP partition accounting differs")

    expected_sample_fields = {
        "sample_index",
        "corpus_offset",
        "bytes",
        "sha256",
        "is_irap",
        "entry_ids",
    }
    ordered_sample_entries: list[str] = []
    sample_offset = 0
    entry_by_id = {entry["entry_id"]: entry for entry in entries}
    for position, sample in enumerate(samples):
        if not isinstance(sample, dict) or set(sample) != expected_sample_fields:
            raise IndependentGOPError("HEVC GOP sample fields differ")
        if sample.get("corpus_offset") != sample_offset:
            raise IndependentGOPError("HEVC GOP sample sequence differs")
        if position == 0 and sample.get("is_irap") is not True:
            raise IndependentGOPError("HEVC GOP source does not start at IRAP")
        ids = sample.get("entry_ids")
        if not isinstance(ids, list) or not ids or any(identity not in entry_by_id for identity in ids):
            raise IndependentGOPError("HEVC GOP sample entry mapping differs")
        if any(entry_by_id[identity]["sample_index"] != sample.get("sample_index") for identity in ids):
            raise IndependentGOPError("HEVC GOP sample identity differs")
        if any(entry_by_id[identity]["nal_index"] != index for index, identity in enumerate(ids)):
            raise IndependentGOPError("HEVC GOP NAL ordering differs inside sample")
        computed_bytes = sum(width + entry_by_id[identity]["nal_bytes"] for identity in ids)
        if sample.get("bytes") != computed_bytes:
            raise IndependentGOPError("HEVC GOP sample byte count differs")
        _hash(sample.get("sha256"), "sample sha256")
        sample_offset += computed_bytes
        ordered_sample_entries.extend(ids)
    if sample_offset != source_bytes or ordered_sample_entries != [entry["entry_id"] for entry in entries]:
        raise IndependentGOPError("HEVC GOP samples do not exactly partition entries")
    return entries, samples


def reconstruct_gop_independently(
    archive_path: str | Path,
    destination: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Reconstruct a GOP corpus without encoder, transform, or T imports."""

    source_archive = Path(archive_path).resolve()
    target = None if destination is None else Path(destination).resolve()
    if target is not None and target.exists() and not overwrite:
        raise IndependentGOPError(f"destination already exists: {target}")
    with zipfile.ZipFile(source_archive) as archive:
        names = [info.filename for info in archive.infolist()]
        if len(names) != len(set(names)) or len(names) > 100_000:
            raise IndependentGOPError("duplicate or excessive GOP archive members")
        if any(
            Path(name).is_absolute()
            or name.startswith("/")
            or "\\" in name
            or ":" in name
            or ".." in Path(name).parts
            for name in names
        ):
            raise IndependentGOPError("unsafe GOP archive member path")
        required = {
            "plan.json",
            "work-accounting.json",
            "authority/policy.t",
            "authority/receipts.jsonl",
            "authority/decisions.jsonl",
            "authority/tcap/MANIFEST.json",
        }
        if not required.issubset(names):
            raise IndependentGOPError("GOP archive is missing required members")
        if any(info.compress_type != zipfile.ZIP_STORED for info in archive.infolist()):
            raise IndependentGOPError("GOP archive transport must be stored")
        plan = _load_json(archive, "plan.json", maximum=32 * 1024 * 1024)
        entries, samples = _validate_plan(plan)
        _validate_tcap(archive, plan["authority"])
        receipt_count, receipt_head = _validate_receipts(archive, plan)

        accounting = _load_json(
            archive, "work-accounting.json", maximum=16 * 1024 * 1024
        )
        if not isinstance(accounting, dict) or accounting.get("schema") != "casulo.hevc-gop-work-accounting/1.0":
            raise IndependentGOPError("GOP work accounting schema differs")
        expected_counts = Counter(entry["transform"] for entry in entries)
        if (
            accounting.get("source_bytes") != plan["source"]["bytes"]
            or accounting.get("sample_count") != len(samples)
            or accounting.get("nal_body_count") != len(entries)
            or accounting.get("base_source_bytes") != plan["base"]["source_bytes"]
            or accounting.get("dynamics_source_bytes") != plan["dynamics"]["source_bytes"]
            or accounting.get("residual_source_bytes") != plan["residual"]["source_bytes"]
            or accounting.get("partition_exact") is not True
            or accounting.get("transform_counts") != dict(sorted(expected_counts.items()))
            or accounting.get("t_policy_calls") != receipt_count
            or accounting.get("t_receipt_chain_head") != receipt_head
        ):
            raise IndependentGOPError("GOP work accounting differs from verified IR")

        referenced_payloads = {entry["payload_path"] for entry in entries}
        actual_payloads = {name for name in names if PAYLOAD.fullmatch(name)}
        if actual_payloads != referenced_payloads:
            raise IndependentGOPError("GOP payload membership differs")
        for payload_name in referenced_payloads:
            match = PAYLOAD.fullmatch(payload_name)
            if match is None or archive.getinfo(payload_name).file_size > 64 * 1024 * 1024:
                raise IndependentGOPError("GOP payload path or size differs")

        temporary: Path | None = None
        output = None
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            os.close(handle)
            temporary = Path(temporary_name)
            output = temporary.open("wb", buffering=4 * 1024 * 1024)

        future_references = Counter(
            entry["reference_entry_id"]
            for entry in entries
            if entry["transform"] == "xor-reference-prefix-zlib"
        )
        decoded_references: dict[str, bytes] = {}
        entry_by_id = {entry["entry_id"]: entry for entry in entries}
        corpus_digest = hashlib.sha256()
        reconstructed_bytes = 0
        peak_reference_bytes = 0
        try:
            for sample in samples:
                sample_digest = hashlib.sha256()
                sample_bytes = 0
                for entry_id in sample["entry_ids"]:
                    entry = entry_by_id[entry_id]
                    prefix = bytes.fromhex(entry["length_prefix_hex"])
                    header = bytes.fromhex(entry["header_hex"])
                    payload = archive.read(entry["payload_path"])
                    if len(payload) != entry["payload_bytes"]:
                        raise IndependentGOPError("GOP payload byte count differs")
                    if hashlib.sha256(payload).hexdigest() != entry["payload_sha256"]:
                        raise IndependentGOPError("GOP payload hash differs")
                    reference_id = entry["reference_entry_id"]
                    reference = (
                        None
                        if entry["transform"] != "xor-reference-prefix-zlib"
                        else decoded_references.get(reference_id)
                    )
                    if entry["transform"] == "xor-reference-prefix-zlib" and reference is None:
                        raise IndependentGOPError("GOP decoded reference is unavailable")
                    body = _inverse(
                        entry["inverse"],
                        payload,
                        entry["body_bytes"],
                        reference=reference,
                    )
                    if hashlib.sha256(body).hexdigest() != entry["body_source_sha256"]:
                        raise IndependentGOPError("GOP body hash differs after inverse")
                    reconstructed = prefix + header + body
                    sample_digest.update(reconstructed)
                    corpus_digest.update(reconstructed)
                    sample_bytes += len(reconstructed)
                    reconstructed_bytes += len(reconstructed)
                    if output is not None:
                        output.write(reconstructed)
                    if future_references.get(entry_id, 0) > 0:
                        decoded_references[entry_id] = body
                        peak_reference_bytes = max(
                            peak_reference_bytes,
                            sum(len(value) for value in decoded_references.values()),
                        )
                    if entry["transform"] == "xor-reference-prefix-zlib":
                        future_references[reference_id] -= 1
                        if future_references[reference_id] == 0:
                            decoded_references.pop(reference_id, None)
                if sample_bytes != sample["bytes"] or sample_digest.hexdigest() != sample["sha256"]:
                    raise IndependentGOPError("GOP reconstructed sample differs")
            if reconstructed_bytes != plan["source"]["bytes"]:
                raise IndependentGOPError("GOP reconstructed byte count differs")
            if corpus_digest.hexdigest() != plan["source"]["sha256"]:
                raise IndependentGOPError("GOP reconstructed corpus hash differs")
            if output is not None:
                output.flush()
                os.fsync(output.fileno())
                output.close()
                output = None
            if temporary is not None and target is not None:
                os.replace(temporary, target)
                temporary = None
        finally:
            if output is not None:
                output.close()
            if temporary is not None and temporary.exists():
                temporary.unlink()

    return {
        "schema": "casulo.independent-gop-reconstruction/1.0",
        "status": "PASS",
        "archive": str(source_archive),
        "destination": None if target is None else str(target),
        "source_bytes": reconstructed_bytes,
        "source_sha256": corpus_digest.hexdigest(),
        "samples": len(samples),
        "nal_bodies": len(entries),
        "t_receipts": receipt_count,
        "t_receipt_chain_head": receipt_head,
        "peak_retained_reference_bytes": peak_reference_bytes,
        "decoder_dependency": "stdlib-only; no encoder, transform, authority, or T runtime import",
    }


__all__ = ["IndependentGOPError", "reconstruct_gop_independently"]
