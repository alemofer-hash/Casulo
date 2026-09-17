from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from casulo.product.domain import CreationAggregate, CreationSpec, canonical_sha256
from casulo.product.engine_contracts import (
    CancellationToken,
    EngineEvent,
    EngineEventKind,
    EngineRequest,
)
from casulo.product.intent_engine import IntentEngine
from casulo_cloud_standby import (
    CloudAuthError,
    CloudBackpressureError,
    CloudPolicyError,
    CloudReleaseLock,
    CloudReplayError,
    CloudTestHarness,
    ReleaseLockedError,
)
from casulo_owner import AuthorizedIntent, LocalOwnerMotor, OwnerEngineAdapter
from casulo_public import CloudEngineClient, PublicCloudUnavailable


ROOT = Path(__file__).resolve().parents[2]


def request(identifier: str = "request:1") -> EngineRequest:
    return EngineRequest(identifier, "creation:1", 0, "a" * 64)


class FakeOwnerMotor:
    def run_direct(self, item, cancellation):
        assert not cancellation.cancelled
        yield EngineEvent(item.request_id, 1, EngineEventKind.STARTED, "Owner direto")
        yield EngineEvent(item.request_id, 2, EngineEventKind.COMPLETED, "Owner completo", "b" * 64)


def test_owner_adapter_calls_direct_motor_without_cloud() -> None:
    events = OwnerEngineAdapter(FakeOwnerMotor()).execute(request(), CancellationToken())
    assert [event.kind for event in events] == [EngineEventKind.STARTED, EngineEventKind.COMPLETED]


def test_real_owner_motor_compiles_confirmed_intent_directly_without_cloud() -> None:
    aggregate = CreationAggregate(CreationSpec("creation:owner"))
    interpreted = IntentEngine().interpret(
        aggregate,
        source_event_id="voice:owner-proposal",
        utterance="defina behavior.tone como preciso",
    )
    assert interpreted.delta is not None
    delta = interpreted.delta
    digest = canonical_sha256(delta.to_dict())
    motor = LocalOwnerMotor(
        aggregate,
        {digest: AuthorizedIntent(delta, "voice:owner-confirm", True)},
    )
    item = EngineRequest("request:owner-real", aggregate.current.creation_id, 0, digest)
    events = OwnerEngineAdapter(motor).execute(item, CancellationToken())
    assert [event.kind for event in events] == [
        EngineEventKind.STARTED,
        EngineEventKind.MILESTONE,
        EngineEventKind.COMPLETED,
    ]
    assert aggregate.current.version == 1
    assert aggregate.current.content["behavior"]["tone"] == "preciso"
    assert "casulo_cloud" not in (ROOT / "private/casulo-owner/src/casulo_owner/motor.py").read_text(encoding="utf-8")


def test_public_client_uses_harness_with_real_progress_and_cancel() -> None:
    harness = CloudTestHarness()
    events = CloudEngineClient(harness).execute(request(), CancellationToken())
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert events[-1].kind is EngineEventKind.COMPLETED
    token = CancellationToken()
    token.cancel()
    cancelled = CloudEngineClient(harness).execute(request("request:2"), token)
    assert cancelled[-1].kind is EngineEventKind.CANCELLED


def test_public_fails_honestly_when_cloud_is_unavailable() -> None:
    with pytest.raises(PublicCloudUnavailable, match="nenhuma geração local owner"):
        CloudEngineClient().execute(request(), CancellationToken())


def test_cloud_production_is_release_locked_fail_closed() -> None:
    lock = CloudReleaseLock()
    assert lock.state == "RELEASE_LOCKED"
    with pytest.raises(ReleaseLockedError, match="RELEASE_LOCKED"):
        lock.production_bind("0.0.0.0", 443)


def test_public_source_tree_has_no_private_engine_components() -> None:
    spec = importlib.util.spec_from_file_location(
        "audit_public_artifact", ROOT / "tools/audit_public_artifact.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.audit(ROOT / "editions/casulo-public")
    assert report["private_components_absent"] is True
    assert report["forbidden_findings"] == []


def test_build_manifests_are_mutually_exclusive() -> None:
    public = (ROOT / "editions/casulo-public/pyproject.toml").read_text(encoding="utf-8")
    owner = (ROOT / "private/casulo-owner/pyproject.toml").read_text(encoding="utf-8")
    cloud = (ROOT / "services/casulo-cloud-standby/pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "casulo-public"' in public and "casulo_owner" not in public
    assert 'name = "casulo-owner"' in owner and "CloudEngineClient" not in owner
    assert 'name = "casulo-cloud-standby"' in cloud


def test_cloud_harness_auth_and_context_policy_fail_before_job_creation() -> None:
    denied = CloudTestHarness(credential="invalid-test-credential")
    with pytest.raises(CloudAuthError, match="credencial"):
        tuple(denied.submit(request(), CancellationToken()))
    assert denied.jobs == {}
    assert denied.observability_snapshot()["rejected_auth"] == 1

    excessive = EngineRequest(
        "request:context",
        "creation:1",
        0,
        "a" * 64,
        tuple(f"ref:{index}" for index in range(9)),
    )
    harness = CloudTestHarness()
    with pytest.raises(CloudPolicyError, match="contexto remoto"):
        tuple(harness.submit(excessive, CancellationToken()))
    assert harness.jobs == {}
    assert harness.observability_snapshot()["rejected_policy"] == 1


def test_cloud_backpressure_is_bounded_and_observable() -> None:
    harness = CloudTestHarness(max_inflight=1)
    first = iter(harness.submit(request("request:held"), CancellationToken()))
    assert next(first).kind is EngineEventKind.ACCEPTED
    with pytest.raises(CloudBackpressureError, match="fila"):
        tuple(harness.submit(request("request:blocked"), CancellationToken()))
    assert harness.observability_snapshot()["backpressure"] == 1
    first.close()


def test_idempotent_replay_returns_same_sealed_stream_and_rejects_collision() -> None:
    harness = CloudTestHarness()
    original = tuple(harness.submit(request("request:idempotent"), CancellationToken()))
    replay = tuple(harness.submit(request("request:idempotent"), CancellationToken()))
    assert replay == original
    assert harness.observability_snapshot()["replayed"] == 1
    collision = EngineRequest("request:idempotent", "creation:other", 0, "a" * 64)
    with pytest.raises(CloudReplayError, match="divergente"):
        tuple(harness.submit(collision, CancellationToken()))


def test_cloud_failure_is_terminal_and_does_not_leak_exception_text() -> None:
    def fail(_request):
        raise RuntimeError("SECRET USER PAYLOAD")

    harness = CloudTestHarness(result_factory=fail)
    events = tuple(harness.submit(request("request:failed"), CancellationToken()))
    assert events[-1].kind is EngineEventKind.FAILED
    assert "SECRET USER PAYLOAD" not in events[-1].message
    metrics = harness.observability_snapshot()
    assert metrics["failed"] == 1
    assert metrics["contains_user_content"] is False
    assert set(metrics) == {
        "schema", "release_state", "accepted", "completed", "cancelled",
        "failed", "replayed", "rejected_auth", "rejected_policy",
        "backpressure", "contains_user_content",
    }


def test_no_environment_or_identity_value_can_unlock_production(monkeypatch) -> None:
    monkeypatch.setenv("CASULO_CLOUD_RELEASE", "UNLOCKED")
    monkeypatch.setenv("CASULO_OWNER", "Guilherme")
    with pytest.raises(ReleaseLockedError, match="RELEASE_LOCKED"):
        CloudReleaseLock().production_bind("127.0.0.1", 443)
