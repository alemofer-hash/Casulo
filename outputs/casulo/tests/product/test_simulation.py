from __future__ import annotations

import pytest

from casulo.product.capabilities import Effect
from casulo.product.creation_pipeline import CreationPipeline
from casulo.product.domain import CreationAggregate, CreationSpec, CreationState
from casulo.product.simulation import (
    SimulatedResponse,
    SimulationCapabilityDouble,
    SimulationError,
    SimulationPlan,
    SimulationRuntime,
    SimulationStep,
)


def creation(*effects: Effect) -> CreationSpec:
    return CreationSpec(
        "creation:simulation",
        state=CreationState.CONFIRMATION,
        capabilities=frozenset(effect.value for effect in effects),
    )


def step(
    step_id: str,
    effect: Effect,
    *,
    dependencies: tuple[str, ...] = (),
    path: tuple[str, ...] = ("behavior", "tone"),
) -> SimulationStep:
    return SimulationStep(
        step_id=step_id,
        effect=effect,
        action="simulate",
        payload={"message": step_id},
        dependencies=dependencies,
        affected_paths=(path,),
        source_event_ids=("voice:simulation",),
    )


def plan(*steps: SimulationStep) -> SimulationPlan:
    return SimulationPlan(
        "simulation:1",
        "creation:simulation",
        tuple(steps),
        ("voice:simulation",),
    )


def test_runtime_rejects_arbitrary_or_real_provider() -> None:
    class RealProvider:
        simulation_only = False

    with pytest.raises(SimulationError, match="doubles first-party"):
        SimulationRuntime({Effect.NETWORK_CONNECT: RealProvider()})  # type: ignore[arg-type]


def test_preflight_denies_undeclared_effect_before_any_attempt() -> None:
    network = SimulationCapabilityDouble(
        Effect.NETWORK_CONNECT,
        (SimulatedResponse(True, {"status": 200}),),
    )
    storage = SimulationCapabilityDouble(
        Effect.FILESYSTEM_WRITE,
        (SimulatedResponse(True, {"written": True}),),
    )
    runtime = SimulationRuntime(
        {Effect.NETWORK_CONNECT: network, Effect.FILESYSTEM_WRITE: storage}
    )
    with pytest.raises(SimulationError, match="não declarado"):
        runtime.run(
            creation(Effect.NETWORK_CONNECT),
            plan(
                step("connect", Effect.NETWORK_CONNECT),
                step("write", Effect.FILESYSTEM_WRITE, dependencies=("connect",)),
            ),
        )
    assert network.attempts == [] and storage.attempts == []


def test_success_uses_only_scripted_doubles_and_hash_chains_events() -> None:
    network = SimulationCapabilityDouble(
        Effect.NETWORK_CONNECT,
        (SimulatedResponse(True, {"status": 202}),),
    )
    storage = SimulationCapabilityDouble(
        Effect.FILESYSTEM_WRITE,
        (SimulatedResponse(True, {"path": "virtual/output"}),),
    )
    receipt = SimulationRuntime(
        {Effect.NETWORK_CONNECT: network, Effect.FILESYSTEM_WRITE: storage}
    ).run(
        creation(Effect.NETWORK_CONNECT, Effect.FILESYSTEM_WRITE),
        plan(
            step("connect", Effect.NETWORK_CONNECT),
            step("write", Effect.FILESYSTEM_WRITE, dependencies=("connect",)),
        ),
    )
    assert receipt.status == "PASS"
    assert receipt.real_effects_executed is False
    assert receipt.events[1].previous_hash == receipt.events[0].event_hash
    assert receipt.head_hash == receipt.events[-1].event_hash
    assert len(network.attempts) == len(storage.attempts) == 1


def test_failure_stops_dependents_and_returns_only_local_correction_paths() -> None:
    network = SimulationCapabilityDouble(
        Effect.NETWORK_CONNECT,
        (SimulatedResponse(False, error="timeout virtual"),),
    )
    storage = SimulationCapabilityDouble(
        Effect.FILESYSTEM_WRITE,
        (SimulatedResponse(True, {"written": True}),),
    )
    receipt = SimulationRuntime(
        {Effect.NETWORK_CONNECT: network, Effect.FILESYSTEM_WRITE: storage}
    ).run(
        creation(Effect.NETWORK_CONNECT, Effect.FILESYSTEM_WRITE),
        plan(
            step("connect", Effect.NETWORK_CONNECT, path=("behavior", "retry")),
            step("write", Effect.FILESYSTEM_WRITE, dependencies=("connect",)),
        ),
    )
    assert receipt.status == "CORRECTION_REQUIRED"
    assert receipt.correction_paths == (("behavior", "retry"),)
    assert len(receipt.events) == 1
    assert storage.attempts == []


def test_correction_after_simulation_reuses_unaffected_forge_unit() -> None:
    aggregate = CreationAggregate(creation(Effect.NETWORK_CONNECT))
    pipeline = CreationPipeline(aggregate)
    initial = pipeline.bootstrap()
    runtime = SimulationRuntime(
        {
            Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
                Effect.NETWORK_CONNECT,
                (SimulatedResponse(False, error="resposta virtual inválida"),),
            )
        }
    )
    receipt = runtime.run(
        aggregate.current,
        plan(step("connect", Effect.NETWORK_CONNECT, path=("behavior", "tone"))),
    )
    assert receipt.correction_paths == (("behavior", "tone"),)
    pipeline.propose(
        source_event_id="voice:correction",
        utterance="defina behavior.tone como resiliente",
    )
    decision = pipeline.decide(
        human_event_id="voice:confirm",
        accepted=True,
        explicit_human_approval=True,
    )
    assert decision.forge_receipt is not None
    assert decision.forge_receipt.rebuilt_units == ("behavior", "interface")
    before = {item.unit_id: item.artifact_sha256 for item in initial.artifacts}
    after = {item.unit_id: item.artifact_sha256 for item in decision.forge_receipt.artifacts}
    assert before["identity"] == after["identity"]


def test_cycle_and_payload_bounds_fail_before_execution() -> None:
    double = SimulationCapabilityDouble(
        Effect.NETWORK_CONNECT,
        (SimulatedResponse(True, {}),),
    )
    runtime = SimulationRuntime({Effect.NETWORK_CONNECT: double})
    with pytest.raises(SimulationError, match="ciclo"):
        runtime.run(
            creation(Effect.NETWORK_CONNECT),
            plan(
                step("a", Effect.NETWORK_CONNECT, dependencies=("b",)),
                step("b", Effect.NETWORK_CONNECT, dependencies=("a",)),
            ),
        )
    with pytest.raises(SimulationError, match="64 KiB"):
        SimulationStep(
            "large",
            Effect.NETWORK_CONNECT,
            "simulate",
            {"value": "x" * (64 * 1024)},
            (),
            (("behavior",),),
            ("voice:1",),
        )
    assert double.attempts == []


def test_virtual_pause_resume_replay_and_version_comparison() -> None:
    network = SimulationCapabilityDouble(
        Effect.NETWORK_CONNECT,
        (SimulatedResponse(True, {"status": 202}),),
    )
    storage = SimulationCapabilityDouble(
        Effect.FILESYSTEM_WRITE,
        (SimulatedResponse(True, {"virtual": True}),),
    )
    runtime = SimulationRuntime(
        {Effect.NETWORK_CONNECT: network, Effect.FILESYSTEM_WRITE: storage}
    )
    current_plan = plan(
        step("connect", Effect.NETWORK_CONNECT),
        step("write", Effect.FILESYSTEM_WRITE, dependencies=("connect",)),
    )
    current_creation = creation(Effect.NETWORK_CONNECT, Effect.FILESYSTEM_WRITE)
    checkpoint = runtime.pause(current_creation, current_plan, after_steps=1)
    assert checkpoint.virtual_ticks == 1
    assert len(network.attempts) == 1 and storage.attempts == []
    receipt = runtime.resume(current_creation, current_plan, checkpoint)
    assert receipt.status == "PASS" and len(receipt.events) == 2
    replay = runtime.replay(receipt)
    assert replay["passed"] is True and replay["real_effects_executed"] is False

    failed = SimulationRuntime(
        {
            Effect.NETWORK_CONNECT: SimulationCapabilityDouble(
                Effect.NETWORK_CONNECT,
                (SimulatedResponse(False, error="virtual failure"),),
            )
        }
    ).run(creation(Effect.NETWORK_CONNECT), plan(step("connect", Effect.NETWORK_CONNECT)))
    comparison = runtime.compare_versions(failed, receipt)
    assert comparison["status_changed"] is True
    assert comparison["real_effects_executed"] is False
