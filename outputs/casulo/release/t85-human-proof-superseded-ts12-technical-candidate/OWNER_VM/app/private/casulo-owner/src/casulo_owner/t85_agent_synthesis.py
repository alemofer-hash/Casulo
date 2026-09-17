from __future__ import annotations

import re
import hashlib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from casulo.product.engine_contracts import CancellationToken
from casulo.t.productive import ProductiveTCall, ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Build, TcapV2Builder

from .generative_forge import StructuredGenerationError, generate_structured
from .local_model_runtime import (
    ChatMessage,
    LocalModelRuntime,
    SamplingPolicy,
    StochasticTrace,
    initial_sampling_policies,
)


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
_ERROR_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,47}$")


ARCHITECTURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,31}$"},
        "summary": {"type": "string", "minLength": 20, "maxLength": 512},
        "module_suffixes": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,31}$"},
        },
        "constraints": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "minLength": 3, "maxLength": 96},
                    "field_name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,31}$"},
                    "error_code": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,47}$"},
                },
                "required": ["requirement_id", "field_name", "error_code"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["agent_id", "summary", "module_suffixes", "constraints"],
    "additionalProperties": False,
}


class T85SynthesisError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class T85AgentPlan:
    case_id: str
    request: str
    agent_id: str
    summary: str
    module_suffixes: tuple[str, str, str]
    constraints: tuple[Mapping[str, str], Mapping[str, str], Mapping[str, str]]
    trace: StochasticTrace
    raw_sha256: str
    rejected_candidates: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class T85AgentBuild:
    plan: T85AgentPlan
    sources: tuple[Path, Path, Path]
    tcap: TcapV2Build


@dataclass(frozen=True, slots=True)
class T85AgentRun:
    calls: tuple[ProductiveTCall, ...]
    final_value: str

    @property
    def receipt_chain(self) -> tuple[str, ...]:
        return tuple(item.receipt["receipt_hash"] for item in self.calls)


class T85AgentSynthesizer:
    """Neural architecture proposal plus deterministic verified T/2.0 lowering."""

    def __init__(self, runtime: LocalModelRuntime, *, candidate_budget: int = 3) -> None:
        if not 1 <= candidate_budget <= 3:
            raise T85SynthesisError("candidate budget must be between one and three")
        self.runtime = runtime
        self.candidate_budget = candidate_budget
        base = initial_sampling_policies()["code"]
        self.policy = SamplingPolicy(
            "casulo-t85-architecture-v1", base.temperature, base.top_p,
            base.top_k, base.min_p, base.repeat_penalty, 1536,
        )

    def propose(
        self,
        *,
        case_id: str,
        request: str,
        hard_requirements: tuple[str, str, str],
        cancellation: CancellationToken,
    ) -> T85AgentPlan:
        rejected: list[Mapping[str, Any]] = []
        diagnostic = "none"
        schema = deepcopy(ARCHITECTURE_SCHEMA)
        schema["properties"]["constraints"]["items"]["properties"]["requirement_id"]["enum"] = list(hard_requirements)
        for attempt in range(self.candidate_budget):
            prompt = (
                "Projete uma arquitetura inédita para este agente local. Sua saída é um plano, não grants nem aprovação. "
                "Escolha um agent_id e três sufixos de módulos que reflitam o domínio. Para cada requisito HARD, crie "
                "exatamente uma flag booleana distinta e um erro fail-closed. O compilador deriva o evento positivo "
                "diretamente do requirement_id selado; não gere success_value. Não use nomes "
                "genéricos como foo, demo ou test. Não declare cumprimento; apenas represente a obrigação.\n\n"
                f"case_id: {case_id}\npedido: {request}\nrequisitos HARD exatos: {list(hard_requirements)}\n"
                f"diagnóstico da tentativa anterior: {diagnostic}"
            )
            try:
                generated = generate_structured(
                    self.runtime,
                    operation_id=f"t85:{case_id}:architecture:{attempt}",
                    messages=(
                        ChatMessage("system", "/no_think\nVocê projeta agentes T; compilador, verifier e T runtime têm autoridade final."),
                        ChatMessage("user", prompt),
                    ),
                    policy=self.policy,
                    schema=schema,
                    cancellation=cancellation,
                )
            except StructuredGenerationError as error:
                diagnostic = str(error)
                rejected.append({
                    "attempt": attempt, "diagnostic": diagnostic,
                    "raw_sha256": error.raw_sha256, "stochastic_trace": error.trace.to_dict(),
                })
                continue
            try:
                return self._validate(case_id, request, hard_requirements, generated.payload, generated.trace, generated.raw_sha256, tuple(rejected))
            except T85SynthesisError as error:
                diagnostic = str(error)
                rejected.append({
                    "attempt": attempt, "diagnostic": diagnostic,
                    "raw_sha256": generated.raw_sha256,
                    "stochastic_trace": generated.trace.to_dict(),
                    "candidate": generated.payload,
                })
        raise T85SynthesisError(f"architecture candidates exhausted: {rejected}")

    @staticmethod
    def _validate(case_id, request, hard_requirements, value, trace, raw_sha256, rejected) -> T85AgentPlan:
        if set(value) != {"agent_id", "summary", "module_suffixes", "constraints"}:
            raise T85SynthesisError("architecture fields diverge")
        agent_id = value["agent_id"]
        suffixes = value["module_suffixes"]
        constraints = value["constraints"]
        if not _IDENTIFIER.fullmatch(agent_id) or len(suffixes) != 3 or len(set(suffixes)) != 3:
            raise T85SynthesisError("agent/module identities are invalid")
        if any(not _IDENTIFIER.fullmatch(item) for item in suffixes):
            raise T85SynthesisError("module suffix is invalid")
        if not isinstance(constraints, list) or len(constraints) != 3:
            raise T85SynthesisError("exactly three constraints are required")
        observed_requirements = {item.get("requirement_id") for item in constraints}
        if observed_requirements != set(hard_requirements):
            raise T85SynthesisError(
                f"neural plan did not cover exact HARD requirements: expected={sorted(hard_requirements)!r} observed={sorted(str(item) for item in observed_requirements)!r}"
            )
        fields = [item.get("field_name") for item in constraints]
        if len(set(fields)) != 3 or any(not _IDENTIFIER.fullmatch(str(item)) for item in fields):
            raise T85SynthesisError("constraint fields are invalid or duplicated")
        normalized_constraints: list[dict[str, str]] = []
        for item in constraints:
            if set(item) != {"requirement_id", "field_name", "error_code"}:
                raise T85SynthesisError("constraint fields diverge from the neural schema")
            if not _ERROR_IDENTIFIER.fullmatch(str(item.get("error_code", ""))):
                raise T85SynthesisError("constraint diagnostic is invalid")
            normalized_constraints.append({**item, "success_value": _success_event(str(item["requirement_id"]))})
        summary = value["summary"]
        if not isinstance(summary, str) or not 20 <= len(summary) <= 512:
            raise T85SynthesisError("architecture summary is invalid")
        return T85AgentPlan(
            case_id, request, agent_id, summary,
            tuple(suffixes), tuple(normalized_constraints),
            trace, raw_sha256, rejected,
        )

    def build(self, plan: T85AgentPlan, output: Path) -> T85AgentBuild:
        if output.exists():
            raise T85SynthesisError("agent output already exists")
        output.mkdir(parents=True)
        texts = lower_agent_plan(plan)
        source_paths: list[Path] = []
        for module, source in texts:
            path = output / f"{module}.t"
            path.write_text(source, encoding="utf-8", newline="\n")
            source_paths.append(path)
        first_module = f"owner.agent.{plan.agent_id}.{plan.module_suffixes[0]}"
        built = TcapV2Builder().build(
            source_paths,
            output / "agent.tcap",
            entry_module=first_module,
            entry_function="decide",
            tests={
                "properties": [
                    *[f"hard:{item['requirement_id']}" for item in plan.constraints],
                    "cancel_is_fail_closed", "effect_requires_grant", "project_bleed_denied",
                ]
            },
            foreign_boundaries=(
                {"name": "simulation_runtime", "kind": "foreign_primitive", "decision_authority": False},
            ),
        )
        return T85AgentBuild(plan, tuple(source_paths), built)


def _success_event(requirement_id: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "_", requirement_id.upper()).strip("_")
    suffix = "_SATISFIED"
    if len(base) + len(suffix) > 48:
        base = f"{base[:27]}_{hashlib.sha256(requirement_id.encode('utf-8')).hexdigest()[:8].upper()}"
    return base + suffix


def lower_agent_plan(plan: T85AgentPlan) -> tuple[tuple[str, str], ...]:
    policy, workflow, publish = (
        f"owner.agent.{plan.agent_id}.{suffix}" for suffix in plan.module_suffixes
    )
    fields = "\n".join(f"  member {item['field_name']}: Bool" for item in plan.constraints)
    individual = "\n\n".join(
        f"fn verify_{item['field_name']}(input: PolicyInput) -> Result<Text,Text>\n"
        f"  requires input.{item['field_name']} else \"{item['error_code']}\"\n"
        f"  return ok \"{item['success_value']}\""
        for item in plan.constraints
    )
    combined = "\n".join(
        f"  requires input.{item['field_name']} else \"{item['error_code']}\""
        for item in plan.constraints
    )
    policy_source = f'''language T/2.0
module {policy}
budget steps 4096
budget deadline_ms 3000
schema version 1

record PolicyInput
  member confirmed: Bool
  member project_match: Bool
  member evidence_statuses: List<Text,32>
{fields}
  member cancelled: Bool

enum PolicyDecision
  case READY
  case BLOCKED

state accepted: Int = 0

{individual}

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
{combined}
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
'''
    workflow_source = f'''language T/2.0
module {workflow}
use {policy}
budget steps 4096
budget deadline_ms 3000
schema version 1

record WorkflowInput
  member previous: Text
  member evidence_result: Text
  member evidence_statuses: List<Text,32>
  member cancelled: Bool

enum WorkflowDecision
  case PLANNED
  case EVIDENCE_OK
  case WORKFLOW_READY

state transitions: Int = 0

fn plan(input: WorkflowInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "READY" else "policy_not_ready"
  spawn job prepare using input.evidence_statuses limit 32
  join job prepare
  return ok "PLANNED"

fn check(input: WorkflowInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires len(input.evidence_statuses) != 0 else "evidence_missing"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  return ok "EVIDENCE_OK"

fn combine(input: WorkflowInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "PLANNED" else "plan_missing"
  requires input.evidence_result == "EVIDENCE_OK" else "evidence_check_missing"
  set state.transitions = add(state.transitions, 1)
  return ok "WORKFLOW_READY"
'''
    publish_source = f'''language T/2.0
module {publish}
use {workflow}
budget steps 2048
budget deadline_ms 3000
schema version 1
capability simulation

record PublishInput
  member previous: Text
  member simulated: Bool
  member approved: Bool
  member cancelled: Bool

enum PublishDecision
  case SIMULATED
  case COMMITTED
  case AUDITED

fn simulate(input: PublishInput) -> Result<Text,Text>
  effects [simulation]
  cancel if input.cancelled
  requires input.previous == "WORKFLOW_READY" else "workflow_not_ready"
  requires input.simulated else "simulation_failed"
  request effect simulation
  return ok "SIMULATED"

fn commit(input: PublishInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "SIMULATED" else "simulation_receipt_missing"
  requires input.approved else "human_approval_required"
  return ok "COMMITTED"

fn inspect(input: PublishInput) -> Result<Text,Text>
  requires input.previous == "COMMITTED" else "commit_receipt_missing"
  return ok "AUDITED"
'''
    return ((policy, policy_source), (workflow, workflow_source), (publish, publish_source))


def execute_agent(build: T85AgentBuild, runtime: Path, scratch: Path) -> T85AgentRun:
    executor = ProductiveTExecutor(runtime, build.tcap.directory, scratch)
    policy, workflow, publish = (
        f"owner.agent.{build.plan.agent_id}.{suffix}" for suffix in build.plan.module_suffixes
    )
    flags = {item["field_name"]: True for item in build.plan.constraints}
    policy_input = {"confirmed": True, "project_match": True, "evidence_statuses": ["PASS"] * 3, **flags, "cancelled": False}
    calls: list[ProductiveTCall] = []
    previous = "0" * 64

    def run(module, function, payload, expected, grants=()):
        nonlocal previous
        call = executor.execute(
            module, function, payload,
            call_id=f"{build.plan.agent_id}.step{len(calls):02d}",
            surface_id="agent_behavior", scope_id=f"agent:{build.plan.case_id}",
            grants=tuple(grants), previous_receipt_hash=previous,
        )
        if call.observable.get("result") != {"kind": "ok", "value": expected}:
            raise T85SynthesisError(f"agent execution denied at {module}::{function}")
        calls.append(call)
        previous = call.receipt["receipt_hash"]

    for item in build.plan.constraints:
        run(policy, f"verify_{item['field_name']}", policy_input, item["success_value"])
    run(policy, "branch", policy_input, "CONFIRMED")
    run(policy, "decide", policy_input, "READY")
    run(workflow, "plan", {"previous": "READY", "evidence_result": "", "evidence_statuses": ["PASS"] * 3, "cancelled": False}, "PLANNED")
    run(workflow, "check", {"previous": "PLANNED", "evidence_result": "", "evidence_statuses": ["PASS"] * 3, "cancelled": False}, "EVIDENCE_OK")
    run(workflow, "combine", {"previous": "PLANNED", "evidence_result": "EVIDENCE_OK", "evidence_statuses": ["PASS"] * 3, "cancelled": False}, "WORKFLOW_READY")
    run(publish, "simulate", {"previous": "WORKFLOW_READY", "simulated": True, "approved": False, "cancelled": False}, "SIMULATED", ("simulation",))
    run(publish, "commit", {"previous": "SIMULATED", "simulated": True, "approved": True, "cancelled": False}, "COMMITTED")
    run(publish, "inspect", {"previous": "COMMITTED", "simulated": True, "approved": True, "cancelled": False}, "AUDITED")
    return T85AgentRun(tuple(calls), "AUDITED")
