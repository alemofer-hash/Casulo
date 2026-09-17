from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Any, BinaryIO, Mapping


class IndependentReconstructionError(RuntimeError):
    pass


SHA256 = re.compile(r"[0-9a-f]{64}")
PAYLOAD = re.compile(r"payloads/([0-9a-f]{64})\.bin")
TRANSFORMS = frozenset({"raw", "zlib", "delta8-zlib", "xor-prev-zlib", "shuffle4-zlib"})


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _t_canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise IndependentReconstructionError(f"invalid SHA-256: {label}")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise IndependentReconstructionError(f"invalid integer: {label}")
    return value


def _safe_decompress(payload: bytes, expected_size: int) -> bytes:
    decoder = zlib.decompressobj()
    result = decoder.decompress(payload, expected_size + 1)
    if len(result) > expected_size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise IndependentReconstructionError("bounded zlib decode failed")
    result += decoder.flush()
    if len(result) != expected_size:
        raise IndependentReconstructionError("decoded payload size differs")
    return result


def _inverse(name: str, payload: bytes, expected_size: int) -> bytes:
    if name == "raw":
        decoded = payload
    elif name == "zlib":
        decoded = _safe_decompress(payload, expected_size)
    elif name == "delta8-zlib":
        coded = _safe_decompress(payload, expected_size)
        output = bytearray(expected_size)
        previous = 0
        for index, value in enumerate(coded):
            previous = (previous + value) & 0xFF
            output[index] = previous
        decoded = bytes(output)
    elif name == "xor-prev-zlib":
        coded = _safe_decompress(payload, expected_size)
        output = bytearray(expected_size)
        previous = 0
        for index, value in enumerate(coded):
            current = value ^ previous
            output[index] = current
            previous = current
        decoded = bytes(output)
    elif name == "shuffle4-zlib":
        coded = _safe_decompress(payload, expected_size)
        full = expected_size - expected_size % 4
        lane_size = full // 4
        output = bytearray(full)
        for lane in range(4):
            output[lane:full:4] = coded[lane * lane_size : (lane + 1) * lane_size]
        decoded = bytes(output) + coded[full:]
    else:
        raise IndependentReconstructionError(f"unknown inverse: {name}")
    if len(decoded) != expected_size:
        raise IndependentReconstructionError("inverse produced wrong byte count")
    return decoded


def _load_json(archive: zipfile.ZipFile, name: str, *, maximum: int) -> Any:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise IndependentReconstructionError(f"missing archive member: {name}") from exc
    if info.file_size > maximum:
        raise IndependentReconstructionError(f"archive member exceeds limit: {name}")
    try:
        return json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IndependentReconstructionError(f"invalid JSON member: {name}") from exc


def _validate_tcap(archive: zipfile.ZipFile, authority: Mapping[str, Any]) -> None:
    manifest = _load_json(archive, "authority/tcap/MANIFEST.json", maximum=16 * 1024 * 1024)
    if manifest.get("schema") != "casulo.tcap/2.0":
        raise IndependentReconstructionError("embedded TCAP schema differs")
    sections = manifest.get("sections")
    sources = manifest.get("sources")
    if not isinstance(sections, dict) or not isinstance(sources, list):
        raise IndependentReconstructionError("embedded TCAP manifest incomplete")
    for entry in list(sections.values()) + sources:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise IndependentReconstructionError("embedded TCAP entry invalid")
        name = f"authority/tcap/{entry['file']}"
        if archive.getinfo(name).file_size > 16 * 1024 * 1024:
            raise IndependentReconstructionError("embedded TCAP member exceeds limit")
        content = archive.read(name)
        if hashlib.sha256(content).hexdigest() != _hash(entry.get("sha256"), name):
            raise IndependentReconstructionError("embedded TCAP member hash differs")
    seed = {"schema": "casulo.tcap/2.0", "sections": sections, "sources": sources}
    if _t_canonical_hash(seed) != manifest.get("tcap_hash") or manifest.get("tcap_hash") != authority.get("tcap_sha256"):
        raise IndependentReconstructionError("embedded TCAP identity differs")
    policy = archive.read("authority/policy.t")
    if hashlib.sha256(policy).hexdigest() != authority.get("t_source_sha256"):
        raise IndependentReconstructionError("embedded T policy hash differs")


def _validate_receipts(archive: zipfile.ZipFile, plan: Mapping[str, Any]) -> tuple[int, str]:
    if archive.getinfo("authority/receipts.jsonl").file_size > 256 * 1024 * 1024:
        raise IndependentReconstructionError("T receipt log exceeds limit")
    if archive.getinfo("authority/decisions.jsonl").file_size > 256 * 1024 * 1024:
        raise IndependentReconstructionError("T decision trace exceeds limit")
    raw = archive.read("authority/receipts.jsonl")
    trace_raw = archive.read("authority/decisions.jsonl")
    receipts: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        try:
            receipt = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IndependentReconstructionError(f"invalid T receipt line {line_number}") from exc
        if not isinstance(receipt, dict):
            raise IndependentReconstructionError("T receipt must be an object")
        receipts.append(receipt)
    traces: list[dict[str, Any]] = []
    for line_number, line in enumerate(trace_raw.splitlines(), 1):
        try:
            trace = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IndependentReconstructionError(f"invalid T decision trace line {line_number}") from exc
        if not isinstance(trace, dict) or trace.get("schema") != "casulo.structural-t-decision-trace/1.0":
            raise IndependentReconstructionError("T decision trace schema differs")
        traces.append(trace)
    segments = plan["segments"]
    authority = plan["authority"]
    if authority.get("decision_protocol") != ["plan", "decide"] or authority.get("receipts_per_segment") != 2:
        raise IndependentReconstructionError("unsupported T decision protocol")
    if len(receipts) != 2 * len(segments) or len(traces) != len(receipts):
        raise IndependentReconstructionError("T receipt count differs from two-phase segment protocol")
    if hashlib.sha256(raw).hexdigest() != authority.get("receipt_log_sha256"):
        raise IndependentReconstructionError("T receipt log hash differs")
    if hashlib.sha256(trace_raw).hexdigest() != authority.get("decision_trace_sha256"):
        raise IndependentReconstructionError("T decision trace hash differs")
    previous = "0" * 64
    for index, (receipt, trace) in enumerate(zip(receipts, traces, strict=True)):
        claimed = _hash(receipt.get("receipt_hash"), f"receipt {index}")
        seed = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        if _t_canonical_hash(seed) != claimed:
            raise IndependentReconstructionError(f"T receipt hash differs at {index}")
        if receipt.get("previous_receipt_hash") != previous:
            raise IndependentReconstructionError(f"T receipt chain broken at {index}")
        if receipt.get("t_source_hash") != authority.get("t_source_sha256"):
            raise IndependentReconstructionError("receipt T source identity differs")
        if receipt.get("t_ir_hash") != authority.get("t_ir_sha256"):
            raise IndependentReconstructionError("receipt T IR identity differs")
        if receipt.get("tcap_hash") != authority.get("tcap_sha256"):
            raise IndependentReconstructionError("receipt TCAP identity differs")
        if receipt.get("result") != "ok":
            raise IndependentReconstructionError("non-accepting T receipt in published archive")
        if trace.get("receipt_hash") != claimed:
            raise IndependentReconstructionError("decision trace-to-receipt link differs")
        if receipt.get("canonical_input_hash") != _t_canonical_hash(trace.get("input")):
            raise IndependentReconstructionError("decision trace input hash differs")
        if receipt.get("canonical_output_hash") != _t_canonical_hash(trace.get("observable")):
            raise IndependentReconstructionError("decision trace output hash differs")
        previous = claimed
    for index, segment in enumerate(segments):
        planning = receipts[index * 2]
        decision = receipts[index * 2 + 1]
        if not str(planning.get("runtime_function", "")).endswith("::plan"):
            raise IndependentReconstructionError(f"planning receipt absent at segment {index}")
        if not str(decision.get("runtime_function", "")).endswith("::decide"):
            raise IndependentReconstructionError(f"decision receipt absent at segment {index}")
        if segment.get("authority_receipt_hash") != decision.get("receipt_hash"):
            raise IndependentReconstructionError(f"segment-to-decision receipt link differs at {index}")
        plan_trace = traces[index * 2]
        decision_trace = traces[index * 2 + 1]
        if plan_trace.get("phase") != "plan" or decision_trace.get("phase") != "decide":
            raise IndependentReconstructionError(f"T decision phases differ at segment {index}")
        if plan_trace.get("segment_index") != index or decision_trace.get("segment_index") != index:
            raise IndependentReconstructionError(f"T decision segment index differs at {index}")
        plan_input = plan_trace.get("input", {})
        plan_result = plan_trace.get("observable", {}).get("result", {})
        decision_input = decision_trace.get("input", {})
        decision_result = decision_trace.get("observable", {}).get("result", {})
        if plan_input.get("segment_kind") != segment.get("kind") or plan_input.get("source_bytes") != segment.get("source_length"):
            raise IndependentReconstructionError(f"T planning input differs at segment {index}")
        family = plan_result.get("value") if plan_result.get("kind") == "ok" else None
        expected_candidates = {
            "RAW_ONLY": {"raw"},
            "RAW_ZLIB_SHUFFLE": {"raw", "zlib", "shuffle4-zlib"},
            "ALL": set(TRANSFORMS),
        }.get(family)
        actual_candidates = set(segment.get("candidate_bytes", {}))
        if expected_candidates is None or actual_candidates != expected_candidates:
            raise IndependentReconstructionError(f"T candidate plan was not consumed at segment {index}")
        candidate_sizes = segment["candidate_bytes"]
        expected_decision_fields = {
            "raw_bytes": candidate_sizes["raw"],
            "has_zlib": "zlib" in candidate_sizes,
            "zlib_bytes": candidate_sizes.get("zlib", candidate_sizes["raw"]),
            "has_delta8": "delta8-zlib" in candidate_sizes,
            "delta8_zlib_bytes": candidate_sizes.get("delta8-zlib", candidate_sizes["raw"]),
            "has_xor_prev": "xor-prev-zlib" in candidate_sizes,
            "xor_prev_zlib_bytes": candidate_sizes.get("xor-prev-zlib", candidate_sizes["raw"]),
            "has_shuffle4": "shuffle4-zlib" in candidate_sizes,
            "shuffle4_zlib_bytes": candidate_sizes.get("shuffle4-zlib", candidate_sizes["raw"]),
        }
        if any(decision_input.get(key) != value for key, value in expected_decision_fields.items()):
            raise IndependentReconstructionError(f"T candidate evidence differs at segment {index}")
        if decision_result.get("kind") != "ok" or decision_result.get("value") != segment.get("transform"):
            raise IndependentReconstructionError(f"T selection was not consumed at segment {index}")
    if previous != authority.get("receipt_chain_head"):
        raise IndependentReconstructionError("T receipt chain head differs")
    return len(receipts), previous


def _validate_plan(plan: object) -> list[dict[str, Any]]:
    if not isinstance(plan, dict) or plan.get("schema") != "casulo.reversible-transform-ir/1.0":
        raise IndependentReconstructionError("unsupported transform IR")
    expected_top = {"schema", "plan_sha256", "source", "base", "dynamics", "residual", "segments", "authority", "primitives", "probe"}
    if set(plan) != expected_top:
        raise IndependentReconstructionError("transform IR fields differ")
    seed = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if _canonical_hash(seed) != _hash(plan.get("plan_sha256"), "plan_sha256"):
        raise IndependentReconstructionError("canonical transform IR hash differs")
    source = plan.get("source")
    authority = plan.get("authority")
    segments = plan.get("segments")
    if not isinstance(source, dict) or not isinstance(authority, dict) or not isinstance(segments, list) or not segments:
        raise IndependentReconstructionError("transform IR core objects invalid")
    source_size = _integer(source.get("bytes"), "source bytes")
    _hash(source.get("sha256"), "source sha256")
    if authority.get("causal") is not True:
        raise IndependentReconstructionError("T authority not causal")
    for key in (
        "t_source_sha256",
        "t_ir_sha256",
        "tcap_sha256",
        "receipt_chain_head",
        "receipt_log_sha256",
        "decision_trace_sha256",
    ):
        _hash(authority.get(key), key)
    offset = 0
    identifiers: set[str] = set()
    lanes: dict[str, set[str]] = {}
    for lane in ("base", "dynamics", "residual"):
        value = plan.get(lane)
        if not isinstance(value, dict) or not isinstance(value.get("segment_ids"), list):
            raise IndependentReconstructionError(f"invalid lane: {lane}")
        lanes[lane] = set(value["segment_ids"])
        if len(lanes[lane]) != len(value["segment_ids"]):
            raise IndependentReconstructionError(f"duplicate segment in lane: {lane}")
    if lanes["base"] & lanes["dynamics"] or lanes["base"] & lanes["residual"] or lanes["dynamics"] & lanes["residual"]:
        raise IndependentReconstructionError("base/dynamics/residual overlap")
    for index, segment in enumerate(segments):
        expected_segment_fields = {
            "index", "segment_id", "source_offset", "source_length", "source_sha256",
            "kind", "lane", "transform", "inverse", "payload_path", "payload_sha256",
            "payload_bytes", "candidate_bytes", "primitive", "authority_receipt_hash",
        }
        if not isinstance(segment, dict) or set(segment) != expected_segment_fields or segment.get("index") != index:
            raise IndependentReconstructionError("segment index sequence differs")
        if _integer(segment.get("source_offset"), "segment offset") != offset:
            raise IndependentReconstructionError("segment gap or overlap")
        length = _integer(segment.get("source_length"), "segment length", minimum=1)
        if length > 4 * 1024 * 1024:
            raise IndependentReconstructionError("segment exceeds decoder memory contract")
        offset += length
        identity = segment.get("segment_id")
        lane = segment.get("lane")
        transform = segment.get("transform")
        if not isinstance(identity, str) or identity in identifiers or lane not in lanes or identity not in lanes[lane]:
            raise IndependentReconstructionError("segment identity/lane differs")
        identifiers.add(identity)
        if transform not in TRANSFORMS or segment.get("inverse") != transform:
            raise IndependentReconstructionError("segment inverse differs")
        match = PAYLOAD.fullmatch(str(segment.get("payload_path")))
        if match is None or match.group(1) != segment.get("payload_sha256"):
            raise IndependentReconstructionError("segment payload path is not content-addressed")
        _hash(segment.get("source_sha256"), "segment source hash")
        _hash(segment.get("authority_receipt_hash"), "authority receipt hash")
        _integer(segment.get("payload_bytes"), "payload bytes")
        if segment["payload_bytes"] > 8 * 1024 * 1024:
            raise IndependentReconstructionError("payload exceeds decoder memory contract")
        candidates = segment.get("candidate_bytes")
        if not isinstance(candidates, dict) or "raw" not in candidates:
            raise IndependentReconstructionError("segment candidate map differs")
        for candidate_name, candidate_bytes in candidates.items():
            if candidate_name not in TRANSFORMS:
                raise IndependentReconstructionError("unknown candidate transform")
            _integer(candidate_bytes, "candidate bytes")
        if candidates["raw"] != length:
            raise IndependentReconstructionError("raw candidate does not preserve source length")
        if candidates.get(transform) != segment["payload_bytes"]:
            raise IndependentReconstructionError("selected candidate size differs from payload")
        kind = segment.get("kind")
        if kind == "box_header" and (lane != "base" or transform != "raw"):
            raise IndependentReconstructionError("box header escaped immutable base")
        if kind != "box_header" and lane == "base":
            raise IndependentReconstructionError("non-header bytes mislabeled as immutable base")
        if transform == "raw" and lane not in {"base", "residual"}:
            raise IndependentReconstructionError("raw bytes mislabeled as dynamics")
        if transform != "raw" and lane != "dynamics":
            raise IndependentReconstructionError("transformed bytes absent from dynamics")
    if offset != source_size or set().union(*lanes.values()) != identifiers:
        raise IndependentReconstructionError("IR does not exactly partition source")
    return segments


def reconstruct_independently(
    archive_path: str | Path,
    destination: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    source_archive = Path(archive_path).resolve()
    target = None if destination is None else Path(destination).resolve()
    if target is not None and target.exists() and not overwrite:
        raise IndependentReconstructionError(f"destination already exists: {target}")
    with zipfile.ZipFile(source_archive, "r", allowZip64=True) as archive:
        names = [entry.filename for entry in archive.infolist()]
        if len(names) != len(set(names)) or len(names) > 200_000:
            raise IndependentReconstructionError("duplicate or excessive archive members")
        if any(name.startswith(("/", "\\")) or ".." in Path(name).parts for name in names):
            raise IndependentReconstructionError("unsafe archive path")
        required = {
            "plan.json",
            "work-accounting.json",
            "authority/policy.t",
            "authority/receipts.jsonl",
            "authority/decisions.jsonl",
            "authority/tcap/MANIFEST.json",
        }
        if not required.issubset(names):
            raise IndependentReconstructionError("required archive member missing")
        if any(entry.compress_type != zipfile.ZIP_STORED for entry in archive.infolist()):
            raise IndependentReconstructionError("archive must use stored transport only")
        plan = _load_json(archive, "plan.json", maximum=128 * 1024 * 1024)
        segments = _validate_plan(plan)
        _validate_tcap(archive, plan["authority"])
        receipt_count, chain_head = _validate_receipts(archive, plan)
        temporary: Path | None = None
        output: BinaryIO | None = None
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".partial", dir=target.parent)
            os.close(descriptor)
            temporary = Path(temporary_name)
            output = temporary.open("wb", buffering=4 * 1024 * 1024)
        digest = hashlib.sha256()
        written = 0
        try:
            for segment in segments:
                try:
                    info = archive.getinfo(segment["payload_path"])
                except KeyError as exc:
                    raise IndependentReconstructionError("content-addressed payload missing") from exc
                if info.file_size != segment["payload_bytes"]:
                    raise IndependentReconstructionError("payload byte count differs")
                payload = archive.read(info)
                if hashlib.sha256(payload).hexdigest() != segment["payload_sha256"]:
                    raise IndependentReconstructionError("payload hash differs")
                restored = _inverse(segment["inverse"], payload, segment["source_length"])
                if hashlib.sha256(restored).hexdigest() != segment["source_sha256"]:
                    raise IndependentReconstructionError("restored segment hash differs")
                digest.update(restored)
                written += len(restored)
                if output is not None:
                    output.write(restored)
            if output is not None:
                output.flush()
                os.fsync(output.fileno())
                output.close()
                output = None
            if written != plan["source"]["bytes"] or digest.hexdigest() != plan["source"]["sha256"]:
                raise IndependentReconstructionError("whole-source reconstruction differs")
            if temporary is not None and target is not None:
                os.replace(temporary, target)
                temporary = None
        finally:
            if output is not None:
                output.close()
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return {
        "schema": "casulo.independent-reconstruction/1.0",
        "status": "PASS",
        "archive": str(source_archive),
        "destination": None if target is None else str(target),
        "source_bytes": written,
        "source_sha256": digest.hexdigest(),
        "segments": len(segments),
        "t_receipts": receipt_count,
        "t_receipt_chain_head": chain_head,
        "decoder_dependency": "stdlib-only; no encoder, transform, or T runtime import",
    }
