from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from casulo.product.domain import canonical_sha256
from casulo.product.math_boundary import (
    DenseSignedCosine,
    KernelEquivalenceReceipt,
    KernelProfile,
    SimilarityKernel,
    SparseSignedCosine,
    mathematical_boundary_inventory,
    profile_similarity_kernels,
    verify_similarity_equivalence,
)
from casulo.t.productive import ProductiveTCall, ProductiveTError, ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder


@dataclass(frozen=True, slots=True)
class MathKernelSelection:
    schema: str
    selected_kernel: str
    specialized_adopted: bool
    reason: str
    equivalence: Mapping[str, Any]
    profile: Mapping[str, Any]
    inventory_hash: str
    t_call: ProductiveTCall | None
    selection_hash: str

    def kernel(self) -> SimilarityKernel:
        return SparseSignedCosine() if self.specialized_adopted else DenseSignedCosine()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.t_call is not None:
            value["t_call"] = {
                "module": self.t_call.module,
                "function": self.t_call.function,
                "observable": dict(self.t_call.observable),
                "receipt": dict(self.t_call.receipt),
            }
        return value


class OwnerMathBoundary:
    """T owns adoption; Python only measures and executes the selected primitive."""

    def __init__(self, runtime: str | Path, tcap: str | Path, scratch: str | Path) -> None:
        self.scratch = Path(scratch).resolve()
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.executor = ProductiveTExecutor(runtime, tcap, self.scratch / "t-inputs")

    @staticmethod
    def build_policy(source: str | Path, output: str | Path) -> Path:
        target = Path(output).resolve()
        if target.exists():
            return target
        return TcapV2Builder().build(
            (source,), target,
            entry_module="owner.math.boundary_policy",
            entry_function="decide",
            tests={
                "properties": [
                    "equivalence_required",
                    "measurement_required",
                    "traffic_reduction_required",
                    "frozen_threshold_required",
                    "safe_fallback_required",
                    "cancel_fail_closed",
                ]
            },
        ).directory

    def decide(
        self,
        equivalence: KernelEquivalenceReceipt,
        profile: KernelProfile,
        *,
        call_id: str = "math.boundary.00000001",
        cancelled: bool = False,
    ) -> MathKernelSelection:
        inventory = mathematical_boundary_inventory()
        call = self.executor.execute(
            "owner.math.boundary_policy",
            "decide",
            {
                "equivalence_pass": equivalence.passed,
                "candidate_measured": profile.rounds >= 3 and profile.pairs_per_round > 0,
                "candidate_wins": profile.candidate_wins,
                "traffic_reduced": profile.traffic_reduced,
                "fallback_available": True,
                "implementation_declared": True,
                "cancelled": cancelled,
            },
            call_id=call_id,
            surface_id="math_kernel_adoption",
            scope_id="product:living_memory",
        )
        result = call.observable.get("result", {})
        adopted = result.get("kind") == "ok" and result.get("value") == "ADOPT_SPECIALIZED"
        reason = "T_ADOPTED_SPECIALIZED" if adopted else f"T_DENIED:{result.get('value', 'UNKNOWN')}"
        selected = SparseSignedCosine.kernel_id if adopted else DenseSignedCosine.kernel_id
        seed = {
            "schema": "casulo.owner-math-kernel-selection/1.0",
            "selected_kernel": selected,
            "specialized_adopted": adopted,
            "reason": reason,
            "equivalence": equivalence.to_dict(),
            "profile": profile.to_dict(),
            "inventory_hash": canonical_sha256(inventory),
            "t_receipt_hash": call.receipt["receipt_hash"],
        }
        selection = MathKernelSelection(
            schema=seed["schema"],
            selected_kernel=selected,
            specialized_adopted=adopted,
            reason=reason,
            equivalence=seed["equivalence"],
            profile=seed["profile"],
            inventory_hash=seed["inventory_hash"],
            t_call=call,
            selection_hash=canonical_sha256(seed),
        )
        self._persist(selection, call_id)
        return selection

    def qualify_and_decide(self, *, call_id: str = "math.boundary.00000001") -> MathKernelSelection:
        return self.decide(verify_similarity_equivalence(), profile_similarity_kernels(), call_id=call_id)

    def _persist(self, selection: MathKernelSelection, call_id: str) -> None:
        target = self.scratch / f"{call_id}.selection.json"
        if target.exists():
            raise ProductiveTError("seleção matemática duplicada")
        encoded = (json.dumps(selection.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, target)


def select_safe_reference_when_t_unavailable(error: BaseException) -> MathKernelSelection:
    """Loss of T can never synthesize an affirmative specialized decision."""

    equivalence = verify_similarity_equivalence()
    profile = profile_similarity_kernels(rounds=3, repetitions=20)
    inventory = mathematical_boundary_inventory()
    reason = f"T_UNAVAILABLE_REFERENCE_FALLBACK:{type(error).__name__}"
    seed = {
        "schema": "casulo.owner-math-kernel-selection/1.0",
        "selected_kernel": DenseSignedCosine.kernel_id,
        "specialized_adopted": False,
        "reason": reason,
        "equivalence": equivalence.to_dict(),
        "profile": profile.to_dict(),
        "inventory_hash": canonical_sha256(inventory),
        "t_receipt_hash": None,
    }
    return MathKernelSelection(
        schema=seed["schema"],
        selected_kernel=seed["selected_kernel"],
        specialized_adopted=False,
        reason=reason,
        equivalence=seed["equivalence"],
        profile=seed["profile"],
        inventory_hash=seed["inventory_hash"],
        t_call=None,
        selection_hash=canonical_sha256(seed),
    )
