from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from casulo.t.productive import ProductiveTCall, ProductiveTError, ProductiveTExecutor

from .policy import MODULES, POLICY_SURFACES


class InterlocutionAuthorityDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class AuthorityGrant:
    config: Mapping[str, Any]
    calls: tuple[ProductiveTCall, ...]

    @property
    def receipt_chain(self) -> tuple[str, ...]:
        return tuple(str(item.receipt["receipt_hash"]) for item in self.calls)


class TrainingAuthority:
    """Fail-closed transport from T decisions to a foreign training primitive."""

    def __init__(self, runtime: str | Path, tcap: str | Path, scratch: str | Path) -> None:
        self._executor = ProductiveTExecutor(runtime, tcap, scratch)

    @staticmethod
    def _required(call: ProductiveTCall) -> Mapping[str, Any]:
        result = call.observable.get("result", {})
        value = result.get("value")
        if result.get("kind") != "ok" or not isinstance(value, Mapping):
            raise InterlocutionAuthorityDenied(
                f"T denied training authority: {value or 'UNKNOWN'}"
            )
        return value

    def authorize(
        self,
        *,
        dataset_sha256: str,
        records: int,
        input_features: int,
        initialization_sha256: str,
        cases_unique: bool,
        nonces_unique: bool,
        capabilities: Mapping[str, bool],
        cancelled: bool = False,
    ) -> AuthorityGrant:
        scope = "training:flood-surrogate-full-v1"
        calls: list[ProductiveTCall] = []
        config: dict[str, Any] = {}
        previous = "0" * 64
        specifications = (
            ("dataset_identity_integrity", "decide", {"observed_sha256":dataset_sha256,"records":records,"input_features":input_features,"cancelled":cancelled}),
            ("initialization_bundle", "decide", {"observed_sha256":initialization_sha256,"cases_unique":cases_unique,"nonces_unique":nonces_unique,"cancelled":cancelled}),
            ("numerical_precision", "decide", {"float64_supported":bool(capabilities.get("float64_supported")),"cancelled":cancelled}),
            ("loss_function", "decide", {"mse_supported":bool(capabilities.get("mse_supported")),"cancelled":cancelled}),
            ("update_rule", "decide", {"sgd_supported":bool(capabilities.get("sgd_supported")),"cancelled":cancelled}),
            ("optimizer_state", "decide", {"reset_supported":bool(capabilities.get("reset_supported")),"no_cross_case_state":bool(capabilities.get("no_cross_case_state")),"cancelled":cancelled}),
            ("working_set", "decide", {"available_records":records,"selection_supported":bool(capabilities.get("selection_supported")),"cancelled":cancelled}),
            ("stopping", "decide", {"fixed_epoch_supported":bool(capabilities.get("fixed_epoch_supported")),"counter_supported":bool(capabilities.get("counter_supported")),"cancelled":cancelled}),
            ("equivalence_acceptance", "policy", {"independent_verifier_available":bool(capabilities.get("independent_verifier_available")),"publisher_requires_t":bool(capabilities.get("publisher_requires_t")),"cancelled":cancelled}),
        )
        try:
            for index, (surface, function, payload) in enumerate(specifications, 1):
                call = self._executor.execute(
                    MODULES[surface],
                    function,
                    payload,
                    call_id=f"policy-{index:02d}-{surface}",
                    surface_id=surface,
                    scope_id=scope,
                    previous_receipt_hash=previous,
                )
                output = dict(self._required(call))
                overlap = set(config) & set(output)
                if overlap:
                    raise InterlocutionAuthorityDenied(
                        f"T outputs collide across surfaces: {sorted(overlap)}"
                    )
                config.update(output)
                calls.append(call)
                previous = str(call.receipt["receipt_hash"])
        except ProductiveTError as error:
            raise InterlocutionAuthorityDenied(f"T authority unavailable: {error}") from error
        if tuple(item.receipt["surface_id"] for item in calls) != POLICY_SURFACES:
            raise InterlocutionAuthorityDenied("T authority surface sequence is incomplete")
        return AuthorityGrant(config=config, calls=tuple(calls))

    def judge(
        self,
        evidence: Mapping[str, Any],
        *,
        previous_receipt_hash: str,
        call_id: str = "final-judgment",
    ) -> ProductiveTCall:
        payload = {
            "equivalence_status": str(evidence.get("equivalence_status", "UNKNOWN")),
            "counter_status": str(evidence.get("counter_status", "UNKNOWN")),
            "receipt_status": str(evidence.get("receipt_status", "UNKNOWN")),
            "semantic_status": str(evidence.get("semantic_status", "UNKNOWN")),
            "human_contract_confirmed": bool(evidence.get("human_contract_confirmed", False)),
            "cancelled": bool(evidence.get("cancelled", False)),
        }
        try:
            call = self._executor.execute(
                MODULES["equivalence_acceptance"],
                "judge",
                payload,
                call_id=call_id,
                surface_id="equivalence_acceptance",
                scope_id="training:flood-surrogate-full-v1",
                previous_receipt_hash=previous_receipt_hash,
            )
        except ProductiveTError as error:
            raise InterlocutionAuthorityDenied(f"T judge unavailable: {error}") from error
        value = self._required(call)
        if value.get("decision") != "PUBLISH":
            raise InterlocutionAuthorityDenied("T judge did not authorize publication")
        return call

