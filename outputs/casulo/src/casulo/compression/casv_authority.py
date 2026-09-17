from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from casulo.t.authority import canonical_sha256
from casulo.t.productive import ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder, verify_tcap_v2


class CASVAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CASVStorageDecision:
    storage_mode: str
    receipt: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CASVCostDecision:
    verdict: str
    receipt: Mapping[str, Any]


class CASVTAuthority:
    """T/2 authority for candidate selection and whole-file cost judgement."""

    module = "compression.casv"
    storage_modes = {"GENERATIVE_EXACT", "CANONICAL_ZLIB", "CANONICAL_RAW"}

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
            raise CASVAuthorityError(f"authority work root already exists: {self.work_root}")
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
                    "candidate_selection_precedes_archive_commit",
                    "exact_media_is_required",
                    "foreign_video_bitstreams_are_forbidden",
                    "whole_archive_cost_is_judged_after_independent_decode",
                ]
            },
            foreign_boundaries=(
                {
                    "name": "casv-visual-primitives",
                    "role": (
                        "render RGB8 scene when available and encode exact canonical "
                        "fallback selected by T"
                    ),
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
            runtime_path,
            self.build.directory,
            self.work_root / "calls",
        )
        self.receipt_path = self.work_root / "receipts.jsonl"
        self.trace_path = self.work_root / "decisions.jsonl"
        self.previous_receipt_hash = "0" * 64
        self.receipt_count = 0
        self.storage_decision_count = 0
        self.cost_judgement_count = 0

    def _record(
        self,
        receipt: Mapping[str, Any],
        *,
        phase: str,
        payload: Mapping[str, Any],
        observable: Mapping[str, Any],
    ) -> dict[str, Any]:
        stored = dict(receipt)
        claimed = stored.get("receipt_hash")
        if claimed != canonical_sha256(
            {key: value for key, value in stored.items() if key != "receipt_hash"}
        ):
            raise CASVAuthorityError("T receipt hash differs")
        if stored.get("previous_receipt_hash") != self.previous_receipt_hash:
            raise CASVAuthorityError("T receipt chain differs")
        with self.receipt_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(stored, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )
        trace = {
            "schema": "casulo.casv-t-decision-trace/0.1",
            "phase": phase,
            "input": dict(payload),
            "observable": dict(observable),
            "receipt_hash": claimed,
        }
        with self.trace_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(trace, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )
        self.previous_receipt_hash = str(claimed)
        self.receipt_count += 1
        return stored

    def decide(
        self,
        *,
        generative_candidate_available: bool,
        exact_generative_reconstruction: bool,
        no_foreign_bitstream: bool,
        generative_bytes: int,
        direct_zlib_bytes: int,
        raw_bytes: int,
        segment_index: int,
        canonical_sha256: str,
    ) -> CASVStorageDecision:
        if (
            min(generative_bytes, direct_zlib_bytes, raw_bytes) < 0
            or raw_bytes <= 0
            or type(segment_index) is not int
            or segment_index < 0
            or not isinstance(canonical_sha256, str)
            or len(canonical_sha256) != 64
            or any(character not in "0123456789abcdef" for character in canonical_sha256)
        ):
            raise CASVAuthorityError("invalid CASV candidate accounting")
        payload = {
            "segment_index": segment_index,
            "canonical_sha256": canonical_sha256,
            "generative_candidate_available": generative_candidate_available,
            "exact_generative_reconstruction": exact_generative_reconstruction,
            "no_foreign_bitstream": no_foreign_bitstream,
            "generative_bytes": generative_bytes,
            "direct_zlib_bytes": direct_zlib_bytes,
            "raw_bytes": raw_bytes,
            "cancelled": False,
        }
        call = self.executor.execute(
            self.module,
            "decide",
            payload,
            call_id=f"decide-{self.storage_decision_count:08d}",
            surface_id="compression_casv_storage_selection",
            scope_id="casv:canonical-media",
            previous_receipt_hash=self.previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        selected = result.get("value")
        if result.get("kind") != "ok" or selected not in self.storage_modes:
            raise CASVAuthorityError(f"T refused CASV candidate selection: {result}")
        receipt = self._record(
            call.receipt,
            phase="decide",
            payload=payload,
            observable=call.observable,
        )
        self.storage_decision_count += 1
        return CASVStorageDecision(str(selected), receipt)

    def judge(
        self,
        *,
        exact_reconstruction: bool,
        no_foreign_bitstream: bool,
        source_bytes: int,
        archive_bytes: int,
        partition_exact: bool,
    ) -> CASVCostDecision:
        payload = {
            "exact_reconstruction": exact_reconstruction,
            "no_foreign_bitstream": no_foreign_bitstream,
            "source_bytes": source_bytes,
            "archive_bytes": archive_bytes,
            "partition_exact": partition_exact,
            "cancelled": False,
        }
        call = self.executor.execute(
            self.module,
            "judge",
            payload,
            call_id=f"judge-{self.cost_judgement_count:08d}",
            surface_id="compression_casv_cost_acceptance",
            scope_id="casv:archive",
            previous_receipt_hash=self.previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") not in {"ACCEPT", "REJECT"}:
            raise CASVAuthorityError(f"T refused CASV cost judgement: {result}")
        receipt = self._record(
            call.receipt,
            phase="judge",
            payload=payload,
            observable=call.observable,
        )
        self.cost_judgement_count += 1
        return CASVCostDecision(str(result["value"]), receipt)

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": "casulo.casv-t-authority/0.1",
            "module": self.module,
            "causal_scope": ["storage_selection", "whole_archive_cost_judgement"],
            "not_yet_governed_by_t": [
                "scene_proposal",
                "object_tracking",
                "material_inference",
                "renderer_primitive_implementation",
            ],
            "selection_consumed_before_archive_commit": True,
            "t_source_sha256": self.t_source_sha256,
            "t_ir_sha256": self.t_ir_sha256,
            "tcap_sha256": self.tcap_sha256,
            "receipt_chain_head": self.previous_receipt_hash,
            "receipt_count": self.receipt_count,
            "storage_decision_count": self.storage_decision_count,
            "cost_judgement_count": self.cost_judgement_count,
            "receipt_log_sha256": hashlib.sha256(
                self.receipt_path.read_bytes() if self.receipt_path.is_file() else b""
            ).hexdigest(),
            "decision_trace_sha256": hashlib.sha256(
                self.trace_path.read_bytes() if self.trace_path.is_file() else b""
            ).hexdigest(),
        }


__all__ = [
    "CASVAuthorityError",
    "CASVCostDecision",
    "CASVStorageDecision",
    "CASVTAuthority",
]
