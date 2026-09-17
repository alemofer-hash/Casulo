from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from casulo.t.authority import canonical_sha256
from casulo.t.productive import (
    ProductiveTBatchRequest,
    ProductiveTExecutor,
)
from casulo.t.v2_tcap import TcapV2Builder, verify_tcap_v2

from .casv_tile_ir import TILE_MODES
from .casv_temporal_ir import TEMPORAL_TILE_MODES


class CASVTileAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CASVTileDecision:
    storage_mode: str
    receipt: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CASVTileCostDecision:
    verdict: str
    receipt: Mapping[str, Any]


class CASVTileTAuthority:
    """Causal T authority over every tile selection and archive verdict."""

    module = "compression.casv_tile"
    authority_schema = "casulo.casv-tile-authority/0.4"
    trace_schema = "casulo.casv-tile-decision-trace/0.4"
    judge_scope = "casv:tiled-archive"
    judge_verdicts = frozenset({"ACCEPT", "REJECT"})
    cost_verdict_baseline = "RAW_CANONICAL_BYTES"
    causal_scope = ("per_tile_storage_selection", "archive_cost_judgement")
    storage_modes = frozenset(TILE_MODES)

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
            raise CASVTileAuthorityError(
                f"authority work root already exists: {self.work_root}"
            )
        self.work_root.mkdir(parents=True)
        repository = Path(__file__).resolve().parents[3]
        runtime_path = (
            Path(runtime).resolve()
            if runtime is not None
            else repository
            / "t-runtime"
            / "target"
            / "release"
            / "casulo-t-runtime.exe"
        )
        self.build = TcapV2Builder().build(
            (self.policy_source,),
            self.work_root / "policy.tcap",
            entry_module=self.module,
            entry_function="decide",
            tests={
                "properties": [
                    "each_tile_selection_precedes_strip_commit",
                    "all_candidates_are_exact",
                    "foreign_video_bitstreams_are_forbidden",
                    "batching_removes_process_startup_not_semantic_decisions",
                    "whole_archive_cost_is_judged_after_independent_decode",
                ]
            },
            foreign_boundaries=(
                {
                    "name": "casv-tile-primitives",
                    "role": "construct exact bounded predictor candidates selected by T",
                    "decision_owner": "T",
                },
            ),
        )
        _root, manifest, typed = verify_tcap_v2(self.build.directory)
        module_ir = next(
            item for item in typed["modules"] if item["module"] == self.module
        )
        self.t_source_sha256 = hashlib.sha256(
            self.policy_source.read_bytes()
        ).hexdigest()
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
        self.physical_batch_invocations = 0

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
            raise CASVTileAuthorityError("T receipt hash differs")
        if stored.get("previous_receipt_hash") != self.previous_receipt_hash:
            raise CASVTileAuthorityError("T receipt chain differs")
        with self.receipt_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(stored, sort_keys=True, separators=(",", ":")) + "\n"
            )
        trace = {
            "schema": self.trace_schema,
            "phase": phase,
            "input": dict(payload),
            "observable": dict(observable),
            "receipt_hash": claimed,
        }
        with self.trace_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n"
            )
        self.previous_receipt_hash = str(claimed)
        self.receipt_count += 1
        return stored

    @staticmethod
    def _validate_payload(payload: Mapping[str, Any]) -> None:
        integer_fields = (
            "tile_index",
            "frame_index",
            "plane_index",
            "dc_xor_bytes",
            "paeth_bytes",
            "direct_zlib_bytes",
            "raw_bytes",
        )
        if any(type(payload.get(field)) is not int for field in integer_fields):
            raise CASVTileAuthorityError("tile candidate accounting is not integral")
        if any(payload[field] < 0 for field in integer_fields[:3]):
            raise CASVTileAuthorityError("tile coordinate is negative")
        if any(payload[field] <= 0 for field in integer_fields[3:]):
            raise CASVTileAuthorityError("tile candidate cost is not positive")
        digest = payload.get("canonical_sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise CASVTileAuthorityError("tile canonical hash is invalid")
        if payload.get("exact_candidate_reconstruction") is not True:
            raise CASVTileAuthorityError("tile candidates are not independently exact")
        if payload.get("no_foreign_bitstream") is not True:
            raise CASVTileAuthorityError(
                "foreign video bitstream reached tile authority"
            )

    def decide_tiles(
        self,
        payloads: Sequence[Mapping[str, Any]],
        *,
        record_index: int,
    ) -> tuple[CASVTileDecision, ...]:
        if not payloads:
            raise CASVTileAuthorityError("tile authority batch is empty")
        requests: list[ProductiveTBatchRequest] = []
        normalized: list[dict[str, Any]] = []
        for payload in payloads:
            value = {**dict(payload), "cancelled": False}
            self._validate_payload(value)
            normalized.append(value)
            requests.append(
                ProductiveTBatchRequest(
                    call_id=f"tile-{self.storage_decision_count + len(requests):08d}",
                    payload=value,
                    surface_id="compression_casv_tile_selection",
                    scope_id="casv:canonical-tile",
                )
            )
        calls = self.executor.execute_batch(
            self.module,
            "decide",
            tuple(requests),
            batch_id=f"strip-{record_index:08d}",
            previous_receipt_hash=self.previous_receipt_hash,
        )
        self.physical_batch_invocations += 1
        decisions: list[CASVTileDecision] = []
        for payload, call in zip(normalized, calls, strict=True):
            result = call.observable.get("result", {})
            selected = result.get("value")
            if result.get("kind") != "ok" or selected not in self.storage_modes:
                raise CASVTileAuthorityError(f"T refused tile selection: {result}")
            receipt = self._record(
                call.receipt,
                phase="decide",
                payload=payload,
                observable=call.observable,
            )
            decisions.append(CASVTileDecision(str(selected), receipt))
            self.storage_decision_count += 1
        return tuple(decisions)

    def judge(
        self,
        *,
        exact_reconstruction: bool,
        source_bytes: int,
        archive_bytes: int,
        partition_exact: bool,
        reference_zlib_bytes: int | None = None,
    ) -> CASVTileCostDecision:
        payload = {
            "exact_reconstruction": exact_reconstruction,
            "no_foreign_bitstream": True,
            "source_bytes": source_bytes,
            "archive_bytes": archive_bytes,
            "partition_exact": partition_exact,
            "cancelled": False,
        }
        if reference_zlib_bytes is not None:
            if type(reference_zlib_bytes) is not int or reference_zlib_bytes <= 0:
                raise CASVTileAuthorityError("reference zlib cost is not positive")
            payload["reference_zlib_bytes"] = reference_zlib_bytes
        call = self.executor.execute(
            self.module,
            "judge",
            payload,
            call_id=f"judge-{self.cost_judgement_count:08d}",
            surface_id="compression_casv_cost_acceptance",
            scope_id=self.judge_scope,
            previous_receipt_hash=self.previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") not in self.judge_verdicts:
            raise CASVTileAuthorityError(f"T refused archive judgement: {result}")
        receipt = self._record(
            call.receipt,
            phase="judge",
            payload=payload,
            observable=call.observable,
        )
        self.cost_judgement_count += 1
        return CASVTileCostDecision(str(result["value"]), receipt)

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": self.authority_schema,
            "module": self.module,
            "causal_scope": list(self.causal_scope),
            "cost_verdict_baseline": self.cost_verdict_baseline,
            "selection_consumed_before_strip_commit": True,
            "semantic_decisions": self.storage_decision_count,
            "physical_batch_invocations": self.physical_batch_invocations,
            "batching_semantics": "PROCESS_STARTUP_AMORTIZED_DECISIONS_REMAIN_INDEPENDENT",
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


class CASVCompactTAuthority(CASVTileTAuthority):
    """T authority whose final judgement compares the complete compact archive."""

    module = "compression.casv_compact"
    authority_schema = "casulo.casv-compact-authority/0.5"
    trace_schema = "casulo.casv-compact-decision-trace/0.5"
    judge_scope = "casv:compact-archive"
    judge_verdicts = frozenset({"ACCEPT_BEATS_REFERENCE", "ACCEPT_RAW_ONLY", "REJECT"})
    cost_verdict_baseline = "DIRECT_WHOLE_STREAM_ZLIB_THEN_RAW_CANONICAL"
    causal_scope = (
        "per_tile_storage_selection",
        "complete_archive_reference_judgement",
    )


class CASVTemporalTAuthority(CASVCompactTAuthority):
    """T authority over spatial/temporal selection and final publication."""

    module = "compression.casv_temporal"
    authority_schema = "casulo.casv-temporal-authority/0.6"
    trace_schema = "casulo.casv-temporal-decision-trace/0.6"
    judge_scope = "casv:temporal-archive"
    storage_modes = frozenset(TEMPORAL_TILE_MODES)
    causal_scope = (
        "per_tile_spatial_or_temporal_selection",
        "keyframe_reference_eligibility",
        "complete_archive_reference_judgement",
    )

    @staticmethod
    def _validate_payload(payload: Mapping[str, Any]) -> None:
        integer_fields = (
            "tile_index",
            "frame_index",
            "plane_index",
            "dc_xor_bytes",
            "paeth_bytes",
            "direct_zlib_bytes",
            "raw_bytes",
            "temporal_xor_bytes",
            "temporal_sub_bytes",
        )
        if any(type(payload.get(field)) is not int for field in integer_fields):
            raise CASVTileAuthorityError(
                "temporal candidate accounting is not integral"
            )
        if any(payload[field] < 0 for field in integer_fields[:3]):
            raise CASVTileAuthorityError("temporal tile coordinate is negative")
        if any(payload[field] <= 0 for field in integer_fields[3:]):
            raise CASVTileAuthorityError("temporal candidate cost is not positive")
        if type(payload.get("temporal_available")) is not bool:
            raise CASVTileAuthorityError("temporal availability is not boolean")
        digest = payload.get("canonical_sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise CASVTileAuthorityError("temporal tile canonical hash is invalid")
        reference = payload.get("temporal_reference_sha256")
        if payload["temporal_available"]:
            if (
                not isinstance(reference, str)
                or len(reference) != 64
                or any(character not in "0123456789abcdef" for character in reference)
            ):
                raise CASVTileAuthorityError("temporal reference hash is invalid")
        elif reference != "0" * 64:
            raise CASVTileAuthorityError(
                "keyframe carries an unexpected reference hash"
            )
        if payload.get("exact_candidate_reconstruction") is not True:
            raise CASVTileAuthorityError(
                "temporal candidates are not independently exact"
            )
        if payload.get("no_foreign_bitstream") is not True:
            raise CASVTileAuthorityError(
                "foreign video bitstream reached temporal authority"
            )


__all__ = [
    "CASVTileAuthorityError",
    "CASVCompactTAuthority",
    "CASVTemporalTAuthority",
    "CASVTileCostDecision",
    "CASVTileDecision",
    "CASVTileTAuthority",
]
