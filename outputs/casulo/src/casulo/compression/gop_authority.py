from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from casulo.t.authority import canonical_sha256
from casulo.t.productive import ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder, verify_tcap_v2

from .gop_transforms import GOPTransformCandidate


class GOPAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GOPCandidatePlan:
    candidate_family: str
    receipt: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GOPTransformDecision:
    transform: str
    receipt: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GOPCostDecision:
    verdict: str
    receipt: Mapping[str, Any]


class GOPTAuthority:
    """Compile and execute the HEVC GOP policy through the general T/2 path."""

    module = "compression.hevc_gop"

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
            raise GOPAuthorityError(f"authority work root already exists: {self.work_root}")
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
            entry_function="decide",
            tests={
                "properties": [
                    "candidate_family_precedes_execution",
                    "candidate_must_roundtrip",
                    "cost_judge_requires_independent_reconstruction",
                ]
            },
            foreign_boundaries=(
                {
                    "name": "hevc-gop-primitives",
                    "role": "execute reversible NAL transforms selected by T",
                    "decision_owner": "T",
                },
            ),
        )
        _root, manifest, typed = verify_tcap_v2(self.build.directory)
        module_ir = next(item for item in typed["modules"] if item["module"] == self.module)
        self.t_source_sha256 = hashlib.sha256(self.policy_source.read_bytes()).hexdigest()
        self.t_ir_sha256 = canonical_sha256(module_ir)
        self.tcap_sha256 = manifest["tcap_hash"]
        self.executor = ProductiveTExecutor(
            runtime_path, self.build.directory, self.work_root / "calls"
        )
        self.receipt_path = self.work_root / "receipts.jsonl"
        self.trace_path = self.work_root / "decisions.jsonl"
        self.previous_receipt_hash = "0" * 64
        self.receipt_count = 0

    def _record(
        self,
        receipt: Mapping[str, Any],
        *,
        phase: str,
        unit_index: int,
        payload: Mapping[str, Any],
        observable: Mapping[str, Any],
    ) -> dict[str, Any]:
        stored = dict(receipt)
        claimed = stored.get("receipt_hash")
        if claimed != canonical_sha256(
            {key: value for key, value in stored.items() if key != "receipt_hash"}
        ):
            raise GOPAuthorityError("T receipt hash differs")
        if stored.get("previous_receipt_hash") != self.previous_receipt_hash:
            raise GOPAuthorityError("T receipt chain differs")
        with self.receipt_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(
                    stored,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        trace = {
            "schema": "casulo.gop-t-decision-trace/1.0",
            "phase": phase,
            "unit_index": unit_index,
            "input": dict(payload),
            "observable": dict(observable),
            "receipt_hash": claimed,
        }
        with self.trace_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(
                    trace,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        self.previous_receipt_hash = str(claimed)
        self.receipt_count += 1
        return stored

    def plan(
        self,
        *,
        unit_index: int,
        nal_class: str,
        source_bytes: int,
        high_entropy: bool,
        reference_available: bool,
    ) -> GOPCandidatePlan:
        if unit_index < 0 or source_bytes <= 0:
            raise GOPAuthorityError("invalid NAL planning evidence")
        payload = {
            "nal_class": nal_class,
            "source_bytes": source_bytes,
            "high_entropy": high_entropy,
            "reference_available": reference_available,
            "cancelled": False,
        }
        call = self.executor.execute(
            self.module,
            "plan",
            payload,
            call_id=f"plan-{unit_index:08d}",
            surface_id="compression_gop_candidate_plan",
            scope_id=f"gop:nal-{unit_index:08d}",
            previous_receipt_hash=self.previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") not in {
            "RAW_ONLY",
            "RAW_ZLIB",
            "RAW_ZLIB_XOR",
        }:
            raise GOPAuthorityError(f"T refused GOP candidate planning: {result}")
        receipt = self._record(
            call.receipt,
            phase="plan",
            unit_index=unit_index,
            payload=payload,
            observable=call.observable,
        )
        return GOPCandidatePlan(str(result["value"]), receipt)

    def decide(
        self,
        *,
        unit_index: int,
        candidates: Mapping[str, GOPTransformCandidate],
    ) -> GOPTransformDecision:
        if unit_index < 0 or "raw" not in candidates:
            raise GOPAuthorityError("invalid GOP candidate evidence")
        if any(not candidate.roundtrip for candidate in candidates.values()):
            raise GOPAuthorityError("non-roundtripping GOP candidate reached T")
        raw_bytes = candidates["raw"].payload_bytes
        payload = {
            "source_hash_valid": len(
                {candidate.source_sha256 for candidate in candidates.values()}
            )
            == 1,
            "candidates_roundtrip": all(
                candidate.roundtrip for candidate in candidates.values()
            ),
            "raw_bytes": raw_bytes,
            "has_zlib": "zlib" in candidates,
            "zlib_bytes": candidates.get("zlib", candidates["raw"]).payload_bytes,
            "has_xor_reference": "xor-reference-prefix-zlib" in candidates,
            "xor_reference_bytes": candidates.get(
                "xor-reference-prefix-zlib", candidates["raw"]
            ).payload_bytes,
            "cancelled": False,
        }
        call = self.executor.execute(
            self.module,
            "decide",
            payload,
            call_id=f"decide-{unit_index:08d}",
            surface_id="compression_gop_transform",
            scope_id=f"gop:nal-{unit_index:08d}",
            previous_receipt_hash=self.previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        selected = result.get("value")
        if result.get("kind") != "ok" or selected not in candidates:
            raise GOPAuthorityError(f"T selected an unavailable GOP transform: {result}")
        receipt = self._record(
            call.receipt,
            phase="decide",
            unit_index=unit_index,
            payload=payload,
            observable=call.observable,
        )
        return GOPTransformDecision(str(selected), receipt)

    def judge(
        self,
        *,
        exact_reconstruction: bool,
        source_bytes: int,
        archive_bytes: int,
        base_source_bytes: int,
        dynamics_source_bytes: int,
        residual_source_bytes: int,
    ) -> GOPCostDecision:
        payload = {
            "exact_reconstruction": exact_reconstruction,
            "source_bytes": source_bytes,
            "archive_bytes": archive_bytes,
            "base_source_bytes": base_source_bytes,
            "dynamics_source_bytes": dynamics_source_bytes,
            "residual_source_bytes": residual_source_bytes,
            "partition_exact": (
                base_source_bytes + dynamics_source_bytes + residual_source_bytes
                == source_bytes
            ),
            "cancelled": False,
        }
        call = self.executor.execute(
            self.module,
            "judge",
            payload,
            call_id="judge-00000000",
            surface_id="compression_gop_cost_acceptance",
            scope_id="gop:archive",
            previous_receipt_hash=self.previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") not in {
            "ACCEPT",
            "REJECT",
        }:
            raise GOPAuthorityError(f"T refused GOP cost judgement: {result}")
        receipt = self._record(
            call.receipt,
            phase="judge",
            unit_index=0,
            payload=payload,
            observable=call.observable,
        )
        return GOPCostDecision(str(result["value"]), receipt)

    def manifest(
        self,
        *,
        decision_protocol: list[str],
        unit: str,
        receipts_per_unit: int,
    ) -> dict[str, Any]:
        return {
            "schema": "casulo.gop-t-authority/1.0",
            "module": self.module,
            "decision_protocol": decision_protocol,
            "unit": unit,
            "receipts_per_unit": receipts_per_unit,
            "causal": True,
            "decision_consumed_before_payload_commit": unit == "nal_body",
            "t_source_sha256": self.t_source_sha256,
            "t_ir_sha256": self.t_ir_sha256,
            "tcap_sha256": self.tcap_sha256,
            "receipt_chain_head": self.previous_receipt_hash,
            "receipt_count": self.receipt_count,
            "receipt_log_sha256": hashlib.sha256(
                self.receipt_path.read_bytes() if self.receipt_path.is_file() else b""
            ).hexdigest(),
            "decision_trace_sha256": hashlib.sha256(
                self.trace_path.read_bytes() if self.trace_path.is_file() else b""
            ).hexdigest(),
        }


__all__ = [
    "GOPAuthorityError",
    "GOPCandidatePlan",
    "GOPCostDecision",
    "GOPTAuthority",
    "GOPTransformDecision",
]
