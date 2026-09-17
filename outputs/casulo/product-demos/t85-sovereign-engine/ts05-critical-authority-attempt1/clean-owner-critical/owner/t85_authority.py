from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from casulo.t.productive import ProductiveTCall, ProductiveTError, ProductiveTExecutor


class T85AuthorityDenied(PermissionError):
    """A critical owner decision was denied by T or could not be executed."""


CommittedValue = TypeVar("CommittedValue")


@dataclass(frozen=True, slots=True)
class CriticalDecisionBundle:
    intent: ProductiveTCall
    capabilities: ProductiveTCall
    fulfillment: ProductiveTCall
    publish: ProductiveTCall

    @property
    def committed(self) -> bool:
        return self.publish.passed and self.publish.observable["result"]["value"] == "COMMIT"

    @property
    def receipt_chain(self) -> tuple[str, ...]:
        return tuple(
            item.receipt["receipt_hash"]
            for item in (self.intent, self.capabilities, self.fulfillment, self.publish)
        )


@dataclass(frozen=True, slots=True)
class AuthorizedCriticalEffect:
    decisions: CriticalDecisionBundle
    value: Any


class T85OwnerCriticalAuthority:
    """Single fail-closed authority for the four critical owner decisions.

    Python validates the transport envelope in ProductiveTExecutor. It never
    reconstructs an affirmative decision. Foreign primitives may execute only
    after ``committed`` is true and the complete T receipt chain is retained.
    """

    def __init__(self, runtime: str | Path, tcap: str | Path, scratch: str | Path) -> None:
        self._executor = ProductiveTExecutor(runtime, tcap, scratch)

    def decide(
        self,
        *,
        decision_id: str,
        creation_id: str,
        model_proposed: bool,
        human_confirmed: bool,
        material: bool,
        requested_capabilities: tuple[str, ...],
        granted_capabilities: tuple[str, ...],
        consent_valid: bool,
        hard_statuses: tuple[str, ...],
        evidence_receipt_ids: tuple[str, ...],
        safety_pass: bool,
        unsupported_claims: tuple[str, ...],
        simulation_status: str,
        human_publish_approval: bool,
        cancelled: bool = False,
    ) -> CriticalDecisionBundle:
        scope = f"creation:{creation_id}"
        try:
            intent = self._required(
                self._executor.execute(
                    "owner.critical.intent", "decide",
                    {
                        "model_proposed": model_proposed,
                        "human_confirmed": human_confirmed,
                        "material": material,
                        "cancelled": cancelled,
                    },
                    call_id=f"{decision_id}.intent", surface_id="material_intent", scope_id=scope,
                ),
                "MATERIAL",
            )
            capabilities = self._required(
                self._executor.execute(
                    "owner.critical.capabilities", "decide",
                    {
                        "previous": intent.observable["result"]["value"],
                        "requested": list(requested_capabilities),
                        "granted": list(granted_capabilities),
                        "consent_valid": consent_valid,
                        "cancelled": cancelled,
                    },
                    call_id=f"{decision_id}.capabilities", surface_id="capabilities_effects",
                    scope_id=scope, previous_receipt_hash=intent.receipt["receipt_hash"],
                ),
                "AUTHORIZED",
            )
            fulfillment = self._required(
                self._executor.execute(
                    "owner.critical.fulfillment", "decide",
                    {
                        "previous": capabilities.observable["result"]["value"],
                        "hard_statuses": list(hard_statuses),
                        "evidence_receipts": list(evidence_receipt_ids),
                        "safety_pass": safety_pass,
                        "unsupported_claims": list(unsupported_claims),
                        "cancelled": cancelled,
                    },
                    call_id=f"{decision_id}.fulfillment", surface_id="hard_requirement_fulfillment",
                    scope_id=scope, previous_receipt_hash=capabilities.receipt["receipt_hash"],
                ),
                "FULFILLED",
            )
            publish = self._required(
                self._executor.execute(
                    "owner.critical.publish", "decide",
                    {
                        "previous": fulfillment.observable["result"]["value"],
                        "human_approved": human_publish_approval,
                        "simulation_status": simulation_status,
                        "cancelled": cancelled,
                    },
                    call_id=f"{decision_id}.publish", surface_id="publish_commit", scope_id=scope,
                    grants=("manifest",), previous_receipt_hash=fulfillment.receipt["receipt_hash"],
                ),
                "COMMIT",
            )
        except ProductiveTError as error:
            raise T85AuthorityDenied(f"critical T authority unavailable: {error}") from error
        return CriticalDecisionBundle(intent, capabilities, fulfillment, publish)

    def authorize_and_execute(
        self,
        primitive: Callable[[CriticalDecisionBundle], CommittedValue],
        **decision_inputs: Any,
    ) -> AuthorizedCriticalEffect:
        """Run a foreign effect only after T returned the causal COMMIT receipt."""
        decisions = self.decide(**decision_inputs)
        if not decisions.committed:
            # Defensive only: ``decide`` already fails closed on a non-COMMIT.
            raise T85AuthorityDenied("T did not authorize the critical effect")
        return AuthorizedCriticalEffect(decisions, primitive(decisions))

    @staticmethod
    def _required(call: ProductiveTCall, expected: str) -> ProductiveTCall:
        result: Mapping[str, Any] = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") != expected:
            raise T85AuthorityDenied(f"T denied critical decision: {result.get('value', 'UNKNOWN')}")
        return call
