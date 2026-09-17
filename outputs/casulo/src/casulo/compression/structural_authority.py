from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from casulo.t.authority import canonical_sha256
from casulo.t.productive import ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder, verify_tcap_v2

from .reversible_transforms import TransformCandidate


class StructuralAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    transform: str
    receipt: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AuthorityPlan:
    candidate_family: str
    receipt: Mapping[str, Any]


class StructuralTAuthority:
    """Compiles a T policy and consumes its decisions before payload emission."""

    module = "compression.structural"
    function = "decide"

    def __init__(
        self,
        policy_source: str | Path,
        work_root: str | Path,
        *,
        runtime: str | Path | None = None,
    ) -> None:
        self.policy_source = Path(policy_source).resolve()
        self.work_root = Path(work_root).resolve()
        if self.work_root.exists():
            raise StructuralAuthorityError(f"authority work root already exists: {self.work_root}")
        self.work_root.mkdir(parents=True)
        repository = Path(__file__).resolve().parents[3]
        runtime_path = (
            Path(runtime).resolve()
            if runtime is not None
            else repository / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
        )
        self.build = TcapV2Builder().build(
            (self.policy_source,),
            self.work_root / "policy.tcap",
            entry_module=self.module,
            entry_function=self.function,
            tests={
                "properties": [
                    "headers_are_literal_base",
                    "candidate_must_roundtrip",
                    "smallest_payload_wins_with_frozen_tie_order",
                ]
            },
            foreign_boundaries=(
                {
                    "name": "compression-primitives",
                    "role": "execute reversible transforms selected by T",
                    "decision_owner": "T",
                },
            ),
        )
        _root, manifest, typed = verify_tcap_v2(self.build.directory)
        module_ir = next(item for item in typed["modules"] if item["module"] == self.module)
        self.t_source_sha256 = hashlib.sha256(self.policy_source.read_bytes()).hexdigest()
        self.t_ir_sha256 = canonical_sha256(module_ir)
        self.tcap_sha256 = manifest["tcap_hash"]
        self.executor = ProductiveTExecutor(runtime_path, self.build.directory, self.work_root / "calls")
        self.receipt_path = self.work_root / "receipts.jsonl"
        self.trace_path = self.work_root / "decisions.jsonl"
        self.previous_receipt_hash = "0" * 64
        self.receipt_count = 0

    def _record(
        self,
        receipt: Mapping[str, Any],
        *,
        phase: str,
        segment_index: int,
        payload: Mapping[str, Any],
        observable: Mapping[str, Any],
    ) -> dict[str, Any]:
        stored = dict(receipt)
        if stored.get("receipt_hash") != canonical_sha256(
            {key: value for key, value in stored.items() if key != "receipt_hash"}
        ):
            raise StructuralAuthorityError("T receipt hash diverges")
        with self.receipt_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(stored, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        trace = {
            "schema": "casulo.structural-t-decision-trace/1.0",
            "phase": phase,
            "segment_index": segment_index,
            "input": dict(payload),
            "observable": dict(observable),
            "receipt_hash": stored["receipt_hash"],
        }
        with self.trace_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(trace, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        self.previous_receipt_hash = str(stored["receipt_hash"])
        self.receipt_count += 1
        return stored

    def plan(
        self,
        *,
        segment_index: int,
        kind: str,
        source_bytes: int,
        entropy_millibits_per_byte: int,
    ) -> AuthorityPlan:
        if segment_index < 0 or source_bytes <= 0 or not 0 <= entropy_millibits_per_byte <= 8000:
            raise StructuralAuthorityError("invalid segment planning evidence")
        payload = {
            "segment_kind": kind,
            "source_bytes": source_bytes,
            "high_entropy": entropy_millibits_per_byte >= 7500,
            "cancelled": False,
        }
        call = self.executor.execute(
            self.module,
            "plan",
            payload,
            call_id=f"plan-{segment_index:08d}",
            surface_id="compression_candidate_plan",
            scope_id=f"archive:segment-{segment_index:08d}",
            previous_receipt_hash=self.previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") not in {
            "RAW_ONLY",
            "RAW_ZLIB_SHUFFLE",
            "ALL",
        }:
            raise StructuralAuthorityError(f"T refused candidate planning: {result}")
        return AuthorityPlan(
            str(result["value"]),
            self._record(
                call.receipt,
                phase="plan",
                segment_index=segment_index,
                payload=payload,
                observable=call.observable,
            ),
        )

    def decide(
        self,
        *,
        segment_index: int,
        kind: str,
        candidates: Mapping[str, TransformCandidate],
    ) -> AuthorityDecision:
        if segment_index < 0 or not candidates:
            raise StructuralAuthorityError("invalid candidate decision request")
        if any(not item.roundtrip for item in candidates.values()):
            raise StructuralAuthorityError("non-roundtripping candidate reached T")
        raw_size = candidates["raw"].payload_bytes

        def size(name: str) -> int:
            return candidates[name].payload_bytes if name in candidates else raw_size

        payload = {
            "source_hash_valid": len({item.source_sha256 for item in candidates.values()}) == 1,
            "candidates_roundtrip": all(item.roundtrip for item in candidates.values()),
            "segment_kind": kind,
            "raw_bytes": raw_size,
            "has_zlib": "zlib" in candidates,
            "zlib_bytes": size("zlib"),
            "has_delta8": "delta8-zlib" in candidates,
            "delta8_zlib_bytes": size("delta8-zlib"),
            "has_xor_prev": "xor-prev-zlib" in candidates,
            "xor_prev_zlib_bytes": size("xor-prev-zlib"),
            "has_shuffle4": "shuffle4-zlib" in candidates,
            "shuffle4_zlib_bytes": size("shuffle4-zlib"),
            "cancelled": False,
        }
        call = self.executor.execute(
            self.module,
            self.function,
            payload,
            call_id=f"decide-{segment_index:08d}",
            surface_id="compression_transform",
            scope_id=f"archive:segment-{segment_index:08d}",
            previous_receipt_hash=self.previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        if result.get("kind") != "ok" or not isinstance(result.get("value"), str):
            raise StructuralAuthorityError(f"T refused transform selection: {result}")
        selected = result["value"]
        if selected not in candidates:
            raise StructuralAuthorityError(f"T selected unavailable transform: {selected}")
        receipt = self._record(
            call.receipt,
            phase="decide",
            segment_index=segment_index,
            payload=payload,
            observable=call.observable,
        )
        return AuthorityDecision(selected, receipt)

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": "casulo.structural-t-authority/1.0",
            "module": self.module,
            "function": self.function,
            "decision_protocol": ["plan", "decide"],
            "receipts_per_segment": 2,
            "causal": True,
            "decision_consumed_before_payload_commit": True,
            "t_source_sha256": self.t_source_sha256,
            "t_ir_sha256": self.t_ir_sha256,
            "tcap_sha256": self.tcap_sha256,
            "receipt_chain_head": self.previous_receipt_hash,
            "receipt_count": self.receipt_count,
            "receipt_log_sha256": (
                hashlib.sha256(self.receipt_path.read_bytes()).hexdigest()
                if self.receipt_path.is_file()
                else hashlib.sha256(b"").hexdigest()
            ),
            "decision_trace_sha256": (
                hashlib.sha256(self.trace_path.read_bytes()).hexdigest()
                if self.trace_path.is_file()
                else hashlib.sha256(b"").hexdigest()
            ),
        }
