from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


ALLOWED_DEGREES = frozenset({0.0, 0.25, 0.5, 0.75, 1.0})


class AuthorityError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise AuthorityError(f"{label} precisa ser SHA-256 minúsculo")


@dataclass(frozen=True, slots=True)
class AuthoritySurface:
    surface_id: str
    weight: int
    critical: bool

    def __post_init__(self) -> None:
        if not self.surface_id or self.weight <= 0:
            raise AuthorityError("superfície de autoridade inválida")


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    surface_id: str
    decision_id: str
    t_runtime_executed: bool
    t_result_consumed: bool
    foreign_recomputed: bool
    productive_fallback: bool
    clean_release_trace: bool
    mutation_changes_decision: bool
    bypass_fails_closed: bool
    execution_is_nontrivial_t: bool
    evidence_refs: tuple[str, ...] = ()

    def degree(self) -> float:
        if not self.t_runtime_executed:
            return 0.0
        if not self.t_result_consumed:
            return 0.25
        if self.foreign_recomputed:
            return 0.5
        if self.productive_fallback or not self.clean_release_trace:
            return 0.75
        if not self.mutation_changes_decision or not self.bypass_fails_closed:
            return 0.75
        return 1.0

    @property
    def execution_credit(self) -> float:
        return (
            1.0
            if self.t_runtime_executed
            and self.execution_is_nontrivial_t
            and self.t_result_consumed
            else 0.0
        )


@dataclass(frozen=True, slots=True)
class TDecisionReceipt:
    decision_id: str
    surface_id: str
    scope_id: str
    t_source_hash: str
    t_ir_hash: str
    tcap_hash: str
    runtime_function: str
    canonical_input_hash: str
    canonical_output_hash: str
    effects_requested: tuple[str, ...]
    grants_consumed: tuple[str, ...]
    foreign_calls: tuple[Mapping[str, Any], ...]
    result: str
    previous_receipt_hash: str
    monotonic_timestamp_ns: int
    runtime_id: str
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.decision_id or not self.surface_id or not self.scope_id:
            raise AuthorityError("receipt T sem identidade")
        for label, value in (
            ("t_source_hash", self.t_source_hash),
            ("t_ir_hash", self.t_ir_hash),
            ("tcap_hash", self.tcap_hash),
            ("canonical_input_hash", self.canonical_input_hash),
            ("canonical_output_hash", self.canonical_output_hash),
            ("previous_receipt_hash", self.previous_receipt_hash),
        ):
            _require_sha256(value, label)
        if not self.runtime_function or not self.runtime_id.startswith("t-runtime/"):
            raise AuthorityError("receipt não nasceu em runtime T identificado")
        if self.monotonic_timestamp_ns < 0:
            raise AuthorityError("timestamp monotônico inválido")
        payload = self.to_dict(include_hash=False)
        object.__setattr__(self, "receipt_hash", canonical_sha256(payload))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": "casulo.t-decision-receipt/2.0",
            "decision_id": self.decision_id,
            "surface_id": self.surface_id,
            "scope_id": self.scope_id,
            "t_source_hash": self.t_source_hash,
            "t_ir_hash": self.t_ir_hash,
            "tcap_hash": self.tcap_hash,
            "runtime_function": self.runtime_function,
            "canonical_input_hash": self.canonical_input_hash,
            "canonical_output_hash": self.canonical_output_hash,
            "effects_requested": list(self.effects_requested),
            "grants_consumed": list(self.grants_consumed),
            "foreign_calls": [dict(item) for item in self.foreign_calls],
            "result": self.result,
            "previous_receipt_hash": self.previous_receipt_hash,
            "monotonic_timestamp_ns": self.monotonic_timestamp_ns,
            "runtime_id": self.runtime_id,
        }
        if include_hash:
            result["receipt_hash"] = self.receipt_hash
        return result


@dataclass(frozen=True, slots=True)
class AuthorityAudit:
    surfaces: tuple[AuthoritySurface, ...]
    traces: tuple[DecisionTrace, ...]

    def __post_init__(self) -> None:
        expected = {surface.surface_id for surface in self.surfaces}
        observed = {trace.surface_id for trace in self.traces}
        if expected != observed or len(self.traces) != len(expected):
            raise AuthorityError("audit exige exatamente uma observação por superfície")

    def _trace(self, surface_id: str) -> DecisionTrace:
        return next(item for item in self.traces if item.surface_id == surface_id)

    @property
    def authority_score(self) -> float:
        total = sum(item.weight for item in self.surfaces)
        return sum(item.weight * self._trace(item.surface_id).degree() for item in self.surfaces) / total

    @property
    def execution_score(self) -> float:
        total = sum(item.weight for item in self.surfaces)
        return sum(item.weight * self._trace(item.surface_id).execution_credit for item in self.surfaces) / total

    @property
    def critical_coverage(self) -> float:
        critical = [item for item in self.surfaces if item.critical]
        if not critical:
            return 1.0
        return sum(1 for item in critical if self._trace(item.surface_id).degree() == 1.0) / len(critical)

    @property
    def python_authority(self) -> float:
        return sum(1 for item in self.traces if item.degree() < 1.0) / len(self.traces)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.t-authority-audit/2.0",
            "s_authority": self.authority_score,
            "s_execution": self.execution_score,
            "c_critical": self.critical_coverage,
            "p_authority": self.python_authority,
            "surfaces": [
                {
                    "id": surface.surface_id,
                    "weight": surface.weight,
                    "critical": surface.critical,
                    "degree": self._trace(surface.surface_id).degree(),
                    "execution_credit": self._trace(surface.surface_id).execution_credit,
                    "evidence_refs": list(self._trace(surface.surface_id).evidence_refs),
                }
                for surface in self.surfaces
            ],
        }


def load_surfaces(path: str | Path) -> tuple[AuthoritySurface, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    surfaces = tuple(
        AuthoritySurface(str(item["id"]), int(item["weight"]), bool(item["critical"]))
        for item in payload["surfaces"]
    )
    if sum(item.weight for item in surfaces) != int(payload["total_weight"]):
        raise AuthorityError("peso total da matriz diverge")
    return surfaces


def write_audit(path: str | Path, audit: AuthorityAudit) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(audit.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def traces_for_absent_authority(
    surfaces: Iterable[AuthoritySurface], evidence: Mapping[str, tuple[str, ...]]
) -> tuple[DecisionTrace, ...]:
    return tuple(
        DecisionTrace(
            surface_id=surface.surface_id,
            decision_id=f"baseline:{surface.surface_id}",
            t_runtime_executed=False,
            t_result_consumed=False,
            foreign_recomputed=True,
            productive_fallback=True,
            clean_release_trace=False,
            mutation_changes_decision=False,
            bypass_fails_closed=False,
            execution_is_nontrivial_t=False,
            evidence_refs=evidence.get(surface.surface_id, ()),
        )
        for surface in surfaces
    )
