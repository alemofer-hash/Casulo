from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from .capabilities import Effect
from .domain import CreationSpec, CreationState, canonical_json, canonical_sha256
from .platform_contracts import PlatformError


MAX_SIMULATION_STEPS = 128
MAX_SIMULATION_PAYLOAD_BYTES = 64 * 1024


class SimulationError(PlatformError):
    pass


@dataclass(frozen=True, slots=True)
class SimulatedResponse:
    ok: bool
    value: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.ok and self.error is not None:
            raise SimulationError("resposta simulada aprovada não pode conter erro")
        if not self.ok and not self.error:
            raise SimulationError("falha simulada exige descrição")
        canonical_json(self.value)


@dataclass(frozen=True, slots=True)
class SimulationStep:
    step_id: str
    effect: Effect
    action: str
    payload: Mapping[str, Any]
    dependencies: tuple[str, ...]
    affected_paths: tuple[tuple[str, ...], ...]
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.step_id or not self.action.strip() or not self.source_event_ids:
            raise SimulationError("passo de simulação exige identidade e proveniência")
        if self.step_id in self.dependencies or len(set(self.dependencies)) != len(self.dependencies):
            raise SimulationError("dependências do passo são inválidas")
        if not self.affected_paths or any(not path for path in self.affected_paths):
            raise SimulationError("passo exige caminhos de correção")
        payload = dict(self.payload)
        if len(canonical_json(payload)) > MAX_SIMULATION_PAYLOAD_BYTES:
            raise SimulationError("payload de simulação excede 64 KiB")
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True)
class SimulationPlan:
    simulation_id: str
    creation_id: str
    steps: tuple[SimulationStep, ...]
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.simulation_id or not self.creation_id or not self.source_event_ids:
            raise SimulationError("plano de simulação exige identidade e proveniência")
        if not self.steps or len(self.steps) > MAX_SIMULATION_STEPS:
            raise SimulationError("plano precisa de 1 a 128 passos")


@dataclass(frozen=True, slots=True)
class SimulationAttempt:
    step_id: str
    effect: Effect
    action: str
    payload_sha256: str
    response: SimulatedResponse


class SimulationCapabilityDouble:
    """Static scripted double. It has no callback and therefore no path to I/O."""

    simulation_only = True

    def __init__(self, effect: Effect, responses: tuple[SimulatedResponse, ...]) -> None:
        if not responses:
            raise SimulationError("double precisa de respostas pré-registradas")
        self.effect = effect
        self._responses = list(responses)
        self.attempts: list[SimulationAttempt] = []

    def invoke(self, step: SimulationStep) -> SimulatedResponse:
        if step.effect is not self.effect:
            raise SimulationError("double recebeu efeito divergente")
        if not self._responses:
            raise SimulationError("double esgotou respostas pré-registradas")
        response = self._responses.pop(0)
        self.attempts.append(
            SimulationAttempt(
                step.step_id,
                step.effect,
                step.action,
                hashlib.sha256(canonical_json(step.payload)).hexdigest(),
                response,
            )
        )
        return response


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    sequence: int
    event_id: str
    step_id: str
    status: str
    response: SimulatedResponse
    source_event_ids: tuple[str, ...]
    previous_hash: str | None
    event_hash: str

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        simulation_id: str,
        step: SimulationStep,
        response: SimulatedResponse,
        previous_hash: str | None,
    ) -> "SimulationEvent":
        status = "SIMULATED" if response.ok else "FAILED"
        unsigned = {
            "schema": "casulo.simulation-event/1.0",
            "sequence": sequence,
            "event_id": f"{simulation_id}:{sequence}",
            "step_id": step.step_id,
            "status": status,
            "response": {"ok": response.ok, "value": response.value, "error": response.error},
            "source_event_ids": list(step.source_event_ids),
            "previous_hash": previous_hash,
        }
        return cls(
            sequence,
            unsigned["event_id"],
            step.step_id,
            status,
            response,
            step.source_event_ids,
            previous_hash,
            canonical_sha256(unsigned),
        )


@dataclass(frozen=True, slots=True)
class SimulationReceipt:
    simulation_id: str
    creation_id: str
    status: str
    events: tuple[SimulationEvent, ...]
    correction_paths: tuple[tuple[str, ...], ...]
    head_hash: str
    real_effects_executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.simulation-receipt/1.0",
            "simulation_id": self.simulation_id,
            "creation_id": self.creation_id,
            "status": self.status,
            "events": [
                {
                    "sequence": event.sequence,
                    "event_id": event.event_id,
                    "step_id": event.step_id,
                    "status": event.status,
                    "response": {
                        "ok": event.response.ok,
                        "value": event.response.value,
                        "error": event.response.error,
                    },
                    "source_event_ids": list(event.source_event_ids),
                    "previous_hash": event.previous_hash,
                    "event_hash": event.event_hash,
                }
                for event in self.events
            ],
            "correction_paths": [list(path) for path in self.correction_paths],
            "head_hash": self.head_hash,
            "real_effects_executed": self.real_effects_executed,
        }


@dataclass(frozen=True, slots=True)
class SimulationCheckpoint:
    simulation_id: str
    creation_id: str
    creation_sha256: str
    plan_sha256: str
    next_step_index: int
    events: tuple[SimulationEvent, ...]
    head_hash: str
    virtual_ticks: int
    real_effects_executed: bool = False


class SimulationRuntime:
    def __init__(self, adapters: Mapping[Effect, SimulationCapabilityDouble]) -> None:
        self.adapters = dict(adapters)
        if any(
            not isinstance(adapter, SimulationCapabilityDouble)
            or adapter.effect is not effect
            or adapter.simulation_only is not True
            for effect, adapter in self.adapters.items()
        ):
            raise SimulationError("runtime aceita somente doubles first-party simulation_only")

    def run(self, creation: CreationSpec, plan: SimulationPlan) -> SimulationReceipt:
        order, by_id = self._preflight(creation, plan)
        events, previous, correction_paths = self._execute(
            plan, order, by_id, start_index=0, end_index=len(order), events=[]
        )
        return SimulationReceipt(
            simulation_id=plan.simulation_id,
            creation_id=creation.creation_id,
            status="PASS" if not correction_paths else "CORRECTION_REQUIRED",
            events=tuple(events),
            correction_paths=correction_paths,
            head_hash=previous,
        )

    def pause(
        self,
        creation: CreationSpec,
        plan: SimulationPlan,
        *,
        after_steps: int,
    ) -> SimulationCheckpoint:
        order, by_id = self._preflight(creation, plan)
        if not 1 <= after_steps < len(order):
            raise SimulationError("pause exige budget entre 1 e total-1")
        events, previous, correction_paths = self._execute(
            plan, order, by_id, start_index=0, end_index=after_steps, events=[]
        )
        if correction_paths:
            raise SimulationError("simulacao falhou antes do checkpoint")
        return SimulationCheckpoint(
            plan.simulation_id,
            creation.creation_id,
            creation.sha256,
            _plan_sha256(plan),
            after_steps,
            tuple(events),
            previous,
            len(events),
        )

    def resume(
        self,
        creation: CreationSpec,
        plan: SimulationPlan,
        checkpoint: SimulationCheckpoint,
    ) -> SimulationReceipt:
        order, by_id = self._preflight(creation, plan)
        if (
            checkpoint.simulation_id != plan.simulation_id
            or checkpoint.creation_id != creation.creation_id
            or checkpoint.creation_sha256 != creation.sha256
            or checkpoint.plan_sha256 != _plan_sha256(plan)
            or checkpoint.real_effects_executed
            or checkpoint.next_step_index != len(checkpoint.events)
        ):
            raise SimulationError("checkpoint diverge da simulacao")
        _validate_event_chain(checkpoint.events, checkpoint.head_hash)
        events, previous, correction_paths = self._execute(
            plan,
            order,
            by_id,
            start_index=checkpoint.next_step_index,
            end_index=len(order),
            events=list(checkpoint.events),
        )
        return SimulationReceipt(
            plan.simulation_id,
            creation.creation_id,
            "PASS" if not correction_paths else "CORRECTION_REQUIRED",
            tuple(events),
            correction_paths,
            previous,
        )

    @staticmethod
    def replay(receipt: SimulationReceipt) -> dict[str, Any]:
        _validate_event_chain(receipt.events, receipt.head_hash)
        return {
            "schema": "casulo.simulation-replay/1.0",
            "simulation_id": receipt.simulation_id,
            "creation_id": receipt.creation_id,
            "events": len(receipt.events),
            "head_hash": receipt.head_hash,
            "status": receipt.status,
            "real_effects_executed": False,
            "passed": True,
        }

    @staticmethod
    def compare_versions(previous: SimulationReceipt, current: SimulationReceipt) -> dict[str, Any]:
        if previous.creation_id != current.creation_id:
            raise SimulationError("comparacao exige a mesma criacao")
        return {
            "schema": "casulo.simulation-comparison/1.0",
            "creation_id": current.creation_id,
            "previous_simulation_id": previous.simulation_id,
            "current_simulation_id": current.simulation_id,
            "status_changed": previous.status != current.status,
            "previous_status": previous.status,
            "current_status": current.status,
            "event_count_delta": len(current.events) - len(previous.events),
            "head_hash_changed": previous.head_hash != current.head_hash,
            "real_effects_executed": False,
        }

    def _execute(
        self,
        plan: SimulationPlan,
        order: tuple[str, ...],
        by_id: dict[str, SimulationStep],
        *,
        start_index: int,
        end_index: int,
        events: list[SimulationEvent],
    ) -> tuple[list[SimulationEvent], str, tuple[tuple[str, ...], ...]]:
        previous = events[-1].event_hash if events else None
        correction_paths: tuple[tuple[str, ...], ...] = ()
        for index in range(start_index, end_index):
            step = by_id[order[index]]
            response = self.adapters[step.effect].invoke(step)
            event = SimulationEvent.create(
                sequence=len(events) + 1,
                simulation_id=plan.simulation_id,
                step=step,
                response=response,
                previous_hash=previous,
            )
            events.append(event)
            previous = event.event_hash
            if not response.ok:
                correction_paths = step.affected_paths
                break
        if previous is None:
            raise SimulationError("simulacao nao executou passos")
        return events, previous, correction_paths

    def _preflight(
        self,
        creation: CreationSpec,
        plan: SimulationPlan,
    ) -> tuple[tuple[str, ...], dict[str, SimulationStep]]:
        if creation.state not in {CreationState.CONFIRMATION, CreationState.SIMULATION}:
            raise SimulationError("simulação exige criação em CONFIRMATION ou SIMULATION")
        if plan.creation_id != creation.creation_id:
            raise SimulationError("plano pertence a outra criação")
        by_id = {step.step_id: step for step in plan.steps}
        if len(by_id) != len(plan.steps):
            raise SimulationError("step_id duplicado")
        for step in plan.steps:
            if step.effect.value not in creation.capabilities:
                raise SimulationError(f"efeito não declarado na criação: {step.effect.value}")
            if step.effect not in self.adapters:
                raise SimulationError(f"double ausente para {step.effect.value}")
            if set(step.dependencies) - set(by_id):
                raise SimulationError(f"dependência ausente em {step.step_id}")
        pending = {step_id: set(step.dependencies) for step_id, step in by_id.items()}
        order: list[str] = []
        while pending:
            ready = sorted(step_id for step_id, dependencies in pending.items() if not dependencies)
            if not ready:
                raise SimulationError("ciclo no plano de simulação")
            order.extend(ready)
            for step_id in ready:
                pending.pop(step_id)
            for dependencies in pending.values():
                dependencies.difference_update(ready)
        return tuple(order), by_id


def _plan_sha256(plan: SimulationPlan) -> str:
    return canonical_sha256(
        {
            "simulation_id": plan.simulation_id,
            "creation_id": plan.creation_id,
            "source_event_ids": plan.source_event_ids,
            "steps": [
                {
                    "step_id": step.step_id,
                    "effect": step.effect.value,
                    "action": step.action,
                    "payload": dict(step.payload),
                    "dependencies": step.dependencies,
                    "affected_paths": step.affected_paths,
                    "source_event_ids": step.source_event_ids,
                }
                for step in plan.steps
            ],
        }
    )


def _validate_event_chain(events: tuple[SimulationEvent, ...], head_hash: str) -> None:
    if not events:
        raise SimulationError("replay exige eventos")
    previous: str | None = None
    for sequence, event in enumerate(events, start=1):
        unsigned = {
            "schema": "casulo.simulation-event/1.0",
            "sequence": sequence,
            "event_id": event.event_id,
            "step_id": event.step_id,
            "status": event.status,
            "response": {
                "ok": event.response.ok,
                "value": event.response.value,
                "error": event.response.error,
            },
            "source_event_ids": list(event.source_event_ids),
            "previous_hash": previous,
        }
        expected = canonical_sha256(unsigned)
        if event.sequence != sequence or event.previous_hash != previous or event.event_hash != expected:
            raise SimulationError("hash chain da simulacao diverge")
        previous = event.event_hash
    if previous != head_hash:
        raise SimulationError("head hash da simulacao diverge")
