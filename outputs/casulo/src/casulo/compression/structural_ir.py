from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


IR_SCHEMA = "casulo.reversible-transform-ir/1.0"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PAYLOAD_RE = re.compile(r"payloads/[0-9a-f]{64}\.bin")
LANES = frozenset({"base", "dynamics", "residual"})
TRANSFORMS = frozenset(
    {"raw", "zlib", "delta8-zlib", "xor-prev-zlib", "shuffle4-zlib"}
)


class StructuralIRError(ValueError):
    """A transformação não é total, reversível ou contabilizável."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise StructuralIRError(f"{field} precisa ser SHA-256 minusculo")
    return value


def _require_int(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StructuralIRError(f"{field} precisa ser inteiro >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class SegmentIR:
    index: int
    segment_id: str
    source_offset: int
    source_length: int
    source_sha256: str
    kind: str
    lane: str
    transform: str
    inverse: str
    payload_path: str
    payload_sha256: str
    payload_bytes: int
    candidate_bytes: Mapping[str, int]
    primitive: str
    authority_receipt_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "segment_id": self.segment_id,
            "source_offset": self.source_offset,
            "source_length": self.source_length,
            "source_sha256": self.source_sha256,
            "kind": self.kind,
            "lane": self.lane,
            "transform": self.transform,
            "inverse": self.inverse,
            "payload_path": self.payload_path,
            "payload_sha256": self.payload_sha256,
            "payload_bytes": self.payload_bytes,
            "candidate_bytes": dict(sorted(self.candidate_bytes.items())),
            "primitive": self.primitive,
            "authority_receipt_hash": self.authority_receipt_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SegmentIR":
        expected = {
            "index",
            "segment_id",
            "source_offset",
            "source_length",
            "source_sha256",
            "kind",
            "lane",
            "transform",
            "inverse",
            "payload_path",
            "payload_sha256",
            "payload_bytes",
            "candidate_bytes",
            "primitive",
            "authority_receipt_hash",
        }
        if set(value) != expected:
            raise StructuralIRError("campos de segmento ausentes ou inesperados")
        candidates = value["candidate_bytes"]
        if not isinstance(candidates, dict):
            raise StructuralIRError("candidate_bytes precisa ser mapa")
        return cls(
            index=_require_int(value["index"], "segment.index"),
            segment_id=str(value["segment_id"]),
            source_offset=_require_int(value["source_offset"], "segment.source_offset"),
            source_length=_require_int(value["source_length"], "segment.source_length"),
            source_sha256=_require_hash(value["source_sha256"], "segment.source_sha256"),
            kind=str(value["kind"]),
            lane=str(value["lane"]),
            transform=str(value["transform"]),
            inverse=str(value["inverse"]),
            payload_path=str(value["payload_path"]),
            payload_sha256=_require_hash(value["payload_sha256"], "segment.payload_sha256"),
            payload_bytes=_require_int(value["payload_bytes"], "segment.payload_bytes"),
            candidate_bytes={
                str(name): _require_int(size, f"candidate_bytes.{name}")
                for name, size in candidates.items()
            },
            primitive=str(value["primitive"]),
            authority_receipt_hash=_require_hash(
                value["authority_receipt_hash"], "segment.authority_receipt_hash"
            ),
        )


def build_ir(
    *,
    source: Mapping[str, Any],
    structure: Mapping[str, Any],
    segments: Sequence[SegmentIR],
    authority: Mapping[str, Any],
    primitives: Sequence[Mapping[str, Any]],
    probe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ordered = [segment.to_dict() for segment in segments]
    seed: dict[str, Any] = {
        "schema": IR_SCHEMA,
        "source": dict(source),
        "base": {
            "role": "immutable format and byte structure",
            "structure": dict(structure),
            "segment_ids": [item["segment_id"] for item in ordered if item["lane"] == "base"],
        },
        "dynamics": {
            "role": "reversible transformed information",
            "segment_ids": [
                item["segment_id"] for item in ordered if item["lane"] == "dynamics"
            ],
        },
        "residual": {
            "role": "literal information not removed by the model",
            "segment_ids": [
                item["segment_id"] for item in ordered if item["lane"] == "residual"
            ],
        },
        "segments": ordered,
        "authority": dict(authority),
        "primitives": [dict(item) for item in primitives],
        "probe": None if probe is None else dict(probe),
    }
    document = {**seed, "plan_sha256": canonical_sha256(seed)}
    validate_ir(document)
    return document


def validate_ir(document: Mapping[str, Any]) -> tuple[SegmentIR, ...]:
    expected = {
        "schema",
        "plan_sha256",
        "source",
        "base",
        "dynamics",
        "residual",
        "segments",
        "authority",
        "primitives",
        "probe",
    }
    if set(document) != expected or document.get("schema") != IR_SCHEMA:
        raise StructuralIRError("schema ou campos da IR incompatíveis")
    plan_hash = _require_hash(document.get("plan_sha256"), "plan_sha256")
    seed = {key: value for key, value in document.items() if key != "plan_sha256"}
    if canonical_sha256(seed) != plan_hash:
        raise StructuralIRError("hash canônico da IR diverge")
    source = document.get("source")
    if not isinstance(source, dict):
        raise StructuralIRError("source precisa ser objeto")
    source_size = _require_int(source.get("bytes"), "source.bytes")
    _require_hash(source.get("sha256"), "source.sha256")
    if not isinstance(source.get("name"), str) or not source["name"]:
        raise StructuralIRError("source.name inválido")

    raw_segments = document.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise StructuralIRError("IR precisa conter segmentos")
    segments = tuple(SegmentIR.from_dict(item) for item in raw_segments)
    offset = 0
    identities: set[str] = set()
    for expected_index, segment in enumerate(segments):
        if segment.index != expected_index:
            raise StructuralIRError("índices de segmento não são contíguos")
        if segment.source_offset != offset:
            raise StructuralIRError("segmentos possuem lacuna ou sobreposição")
        offset += segment.source_length
        if not segment.segment_id or segment.segment_id in identities:
            raise StructuralIRError("segment_id ausente ou duplicado")
        identities.add(segment.segment_id)
        if segment.lane not in LANES:
            raise StructuralIRError("lane desconhecida")
        if segment.transform not in TRANSFORMS or segment.inverse != segment.transform:
            raise StructuralIRError("transform/inverse incompatível")
        if PAYLOAD_RE.fullmatch(segment.payload_path) is None:
            raise StructuralIRError("payload_path não é content-addressed")
        if segment.payload_path != f"payloads/{segment.payload_sha256}.bin":
            raise StructuralIRError("payload_path diverge do hash")
        if segment.transform not in segment.candidate_bytes:
            raise StructuralIRError("transform escolhido não aparece nos candidatos")
        if segment.candidate_bytes[segment.transform] != segment.payload_bytes:
            raise StructuralIRError("payload_bytes diverge do candidato escolhido")
        if segment.transform == "raw" and segment.lane == "dynamics":
            raise StructuralIRError("bytes raw não podem fingir dinâmica transformada")
        if segment.kind == "box_header" and segment.lane != "base":
            raise StructuralIRError("header estrutural precisa pertencer à base")
    if offset != source_size:
        raise StructuralIRError("segmentos não cobrem a fonte integral")

    partition: dict[str, set[str]] = {}
    for lane in LANES:
        value = document.get(lane)
        if not isinstance(value, dict) or not isinstance(value.get("segment_ids"), list):
            raise StructuralIRError(f"partição {lane} inválida")
        partition[lane] = set(value["segment_ids"])
        if len(partition[lane]) != len(value["segment_ids"]):
            raise StructuralIRError(f"partição {lane} possui duplicatas")
    if any(partition[left] & partition[right] for left in LANES for right in LANES if left < right):
        raise StructuralIRError("base, dynamics e residual se sobrepõem")
    if set().union(*partition.values()) != identities:
        raise StructuralIRError("partições não cobrem todos os segmentos")
    for segment in segments:
        if segment.segment_id not in partition[segment.lane]:
            raise StructuralIRError("lane do segmento diverge da partição")

    authority = document.get("authority")
    if not isinstance(authority, dict):
        raise StructuralIRError("authority precisa ser objeto")
    for field in (
        "t_source_sha256",
        "t_ir_sha256",
        "tcap_sha256",
        "receipt_chain_head",
        "receipt_log_sha256",
        "decision_trace_sha256",
    ):
        _require_hash(authority.get(field), f"authority.{field}")
    if authority.get("causal") is not True:
        raise StructuralIRError("IR estrutural exige autoridade T causal")
    if not isinstance(document.get("primitives"), list) or not document["primitives"]:
        raise StructuralIRError("fronteiras primitivas precisam ser manifestadas")
    return segments
