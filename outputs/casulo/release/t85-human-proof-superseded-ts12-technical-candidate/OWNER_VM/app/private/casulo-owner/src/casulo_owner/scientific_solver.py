from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from casulo.product.engine_contracts import CancellationToken

from .generative_forge import generate_structured
from .local_model_runtime import ChatMessage, LocalModelRuntime, StochasticTrace, initial_sampling_policies


REQUIRED_INPUTS = (
    "metric",
    "coordinates",
    "constants",
    "energy_momentum_tensor",
    "initial_conditions",
    "boundary_conditions",
    "tolerances",
    "conventions",
)
REQUIRED_OUTPUTS = (
    "inverse_metric",
    "connection",
    "ricci_tensor",
    "ricci_scalar",
    "einstein_tensor",
    "field_equation_residual",
)

SCIENTIFIC_SOLVER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 4, "maxLength": 100},
        "purpose": {"type": "string", "minLength": 30, "maxLength": 700},
        "inputs": {
            "type": "array", "minItems": 7, "maxItems": 12, "uniqueItems": True,
            "items": {"type": "string"},
        },
        "outputs": {
            "type": "array", "minItems": 5, "maxItems": 10, "uniqueItems": True,
            "items": {"type": "string"},
        },
        "supported_scope": {"type": "string", "minLength": 30, "maxLength": 700},
        "refusals": {
            "type": "array", "minItems": 3, "maxItems": 10,
            "items": {"type": "string", "minLength": 8, "maxLength": 300},
        },
        "numerical_method": {"type": "string", "minLength": 20, "maxLength": 500},
    },
    "required": ["name", "purpose", "inputs", "outputs", "supported_scope", "refusals", "numerical_method"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ScientificSolverPlan:
    payload: dict[str, Any]
    trace: StochasticTrace
    diagnostics: tuple[dict[str, Any], ...]
    attempts: int
    payload_sha256: str


def validate_solver_plan(value: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    diagnostics: list[dict[str, Any]] = []
    missing_inputs = sorted(set(REQUIRED_INPUTS) - set(value.get("inputs", ())))
    missing_outputs = sorted(set(REQUIRED_OUTPUTS) - set(value.get("outputs", ())))
    if missing_inputs:
        diagnostics.append({"code": "SCI_REQUIRED_INPUTS_MISSING", "missing": missing_inputs})
    if missing_outputs:
        diagnostics.append({"code": "SCI_REQUIRED_GEOMETRY_OUTPUTS_MISSING", "missing": missing_outputs})
    refusals = " ".join(str(item) for item in value.get("refusals", ())).casefold()
    if not any(term in refusals for term in ("global", "arbitr", "pde", "geral")):
        diagnostics.append({"code": "SCI_GLOBAL_CLAIM_NOT_REFUSED"})
    scope = str(value.get("supported_scope", "")).casefold()
    if not all(term in scope for term in ("4", "local")):
        diagnostics.append({"code": "SCI_SCOPE_MUST_BE_LOCAL_4D"})
    return tuple(diagnostics)


class ScientificSolverPlanner:
    def __init__(self, runtime: LocalModelRuntime, *, repair_budget: int = 3) -> None:
        self.runtime = runtime
        self.repair_budget = repair_budget

    def propose(self, idea: str, *, cancellation: CancellationToken) -> ScientificSolverPlan:
        diagnostics_history: list[dict[str, Any]] = []
        feedback = ""
        last = None
        for attempt in range(self.repair_budget + 1):
            prompt = f"""Projete um solver científico honesto para esta ideia humana:
{idea}

O produto implementado avalia localmente uma métrica Lorentziana 4D declarada
pelo usuário usando diferenças finitas centrais. Declare todas as entradas e
saídas necessárias. Não alegue integrar ou solucionar genericamente o problema
global de valor inicial/fronteira de Einstein; inclua recusas explícitas.
{feedback}
Responda apenas conforme o schema JSON."""
            generated = generate_structured(
                self.runtime,
                operation_id=f"einstein-plan-{attempt}",
                messages=(
                    ChatMessage("system", "/no_think\nVocê especifica software científico; segurança e validação têm precedência sobre persuasão."),
                    ChatMessage("user", prompt),
                ),
                policy=initial_sampling_policies()["planning"],
                schema=SCIENTIFIC_SOLVER_SCHEMA,
                cancellation=cancellation,
            )
            last = generated
            diagnostics = validate_solver_plan(generated.payload)
            diagnostics_history.append(
                {
                    "attempt": attempt,
                    "diagnostics": list(diagnostics),
                    "trace": generated.trace.to_dict(),
                    "raw_sha256": generated.raw_sha256,
                }
            )
            if not diagnostics:
                payload_sha = hashlib.sha256(
                    json.dumps(generated.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                return ScientificSolverPlan(generated.payload, generated.trace, tuple(diagnostics_history), attempt + 1, payload_sha)
            feedback = "\nDiagnostics reais da tentativa anterior; repare somente o necessário:\n" + json.dumps(
                diagnostics, ensure_ascii=False, sort_keys=True
            )
        assert last is not None
        raise RuntimeError("scientific solver plan exhausted diagnostic repair budget")
