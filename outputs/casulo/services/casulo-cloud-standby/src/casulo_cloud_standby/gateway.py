from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Protocol

from casulo.product.engine_contracts import (
    CancellationToken,
    EngineEvent,
    EngineEventKind,
    EngineRequest,
    payload_sha256,
)


RELEASE_STATE = "RELEASE_LOCKED"


class ReleaseLockedError(RuntimeError):
    pass


class CloudAuthError(PermissionError):
    pass


class CloudPolicyError(PermissionError):
    pass


class CloudBackpressureError(RuntimeError):
    pass


class CloudReplayError(RuntimeError):
    pass


class CloudReleaseLock:
    """Compiled fail-closed lock; client/env/runtime identity cannot unlock it."""

    @property
    def state(self) -> str:
        return RELEASE_STATE

    def require_test_mode(self) -> None:
        if self.state != "RELEASE_LOCKED":
            raise ReleaseLockedError("estado Cloud desconhecido; bloqueio fail-closed")

    def production_bind(self, *_args, **_kwargs) -> None:
        raise ReleaseLockedError(
            "Casulo Cloud está RELEASE_LOCKED; bind de produção é proibido"
        )


@dataclass(frozen=True, slots=True)
class CloudPrincipal:
    principal_id: str
    scopes: frozenset[str]
    test_only: bool


class CloudAuthenticator(Protocol):
    def authenticate(self, credential: str) -> CloudPrincipal: ...


class InMemoryTestAuthenticator:
    test_only = True

    def __init__(self, credentials: Mapping[str, CloudPrincipal] | None = None) -> None:
        self._credentials = dict(
            credentials
            or {
                "casulo-test-harness": CloudPrincipal(
                    "principal:test-harness",
                    frozenset({"engine.submit"}),
                    True,
                )
            }
        )
        if any(not principal.test_only for principal in self._credentials.values()):
            raise CloudAuthError("authenticator in-memory aceita somente principals de teste")

    def authenticate(self, credential: str) -> CloudPrincipal:
        principal = self._credentials.get(credential)
        if principal is None or "engine.submit" not in principal.scopes:
            raise CloudAuthError("credencial de teste inválida ou sem escopo")
        return principal


@dataclass(frozen=True, slots=True)
class CloudPolicy:
    max_context_refs: int = 8
    max_context_ref_bytes: int = 256
    training_with_user_content: bool = False

    def validate(self, request: EngineRequest, principal: CloudPrincipal) -> None:
        if not principal.test_only:
            raise CloudPolicyError("standby aceita somente principal de teste")
        if self.training_with_user_content:
            raise CloudPolicyError("treino com conteúdo do usuário é negado")
        if len(request.context_refs) > self.max_context_refs:
            raise CloudPolicyError("contexto remoto excede limite")
        if any(
            not ref
            or len(ref.encode("utf-8")) > self.max_context_ref_bytes
            or "\n" in ref
            for ref in request.context_refs
        ):
            raise CloudPolicyError("context_ref inválida")


@dataclass(slots=True)
class CloudMetrics:
    accepted: int = 0
    completed: int = 0
    cancelled: int = 0
    failed: int = 0
    replayed: int = 0
    rejected_auth: int = 0
    rejected_policy: int = 0
    backpressure: int = 0

    def snapshot(self) -> dict[str, int | str | bool]:
        return {
            "schema": "casulo-cloud-metrics/1.0",
            "release_state": RELEASE_STATE,
            "accepted": self.accepted,
            "completed": self.completed,
            "cancelled": self.cancelled,
            "failed": self.failed,
            "replayed": self.replayed,
            "rejected_auth": self.rejected_auth,
            "rejected_policy": self.rejected_policy,
            "backpressure": self.backpressure,
            "contains_user_content": False,
        }


@dataclass(slots=True)
class InMemoryJob:
    request: EngineRequest
    request_sha256: str
    principal_id: str
    status: str = "ACCEPTED"
    events: list[EngineEvent] = field(default_factory=list)


class CloudTestHarness:
    """Gateway/auth/job broker in-memory; never presents itself as production."""

    def __init__(
        self,
        result_factory: Callable[[EngineRequest], object] | None = None,
        *,
        authenticator: CloudAuthenticator | None = None,
        credential: str = "casulo-test-harness",
        policy: CloudPolicy | None = None,
        max_inflight: int = 4,
    ) -> None:
        if max_inflight < 1 or max_inflight > 1024:
            raise ValueError("max_inflight precisa estar entre 1 e 1024")
        self.release_lock = CloudReleaseLock()
        self.release_lock.require_test_mode()
        self.jobs: dict[str, InMemoryJob] = {}
        self.result_factory = result_factory or (
            lambda request: {
                "creation_id": request.creation_id,
                "version": request.base_version + 1,
            }
        )
        self.authenticator = authenticator or InMemoryTestAuthenticator()
        self.credential = credential
        self.policy = policy or CloudPolicy()
        self.max_inflight = max_inflight
        self.metrics = CloudMetrics()
        self._inflight = 0

    def submit(
        self, request: EngineRequest, cancellation: CancellationToken
    ) -> Iterable[EngineEvent]:
        principal = self._authenticate()
        self._authorize(request, principal)
        request_hash = payload_sha256(
            {
                "request_id": request.request_id,
                "creation_id": request.creation_id,
                "base_version": request.base_version,
                "intent_delta_sha256": request.intent_delta_sha256,
                "context_refs": request.context_refs,
            }
        )
        existing = self.jobs.get(request.request_id)
        if existing is not None:
            if existing.request_sha256 != request_hash:
                raise CloudReplayError("request_id reutilizado com payload divergente")
            if existing.status not in {"COMPLETED", "CANCELLED", "FAILED"}:
                raise CloudReplayError("request idempotente ainda está em execução")
            self.metrics.replayed += 1
            yield from tuple(existing.events)
            return
        if self._inflight >= self.max_inflight:
            self.metrics.backpressure += 1
            raise CloudBackpressureError("fila Cloud de teste está cheia")

        job = InMemoryJob(request, request_hash, principal.principal_id)
        self.jobs[request.request_id] = job
        self._inflight += 1
        try:
            yield self._event(job, EngineEventKind.ACCEPTED, "Job aceito pelo broker in-memory")
            self.metrics.accepted += 1
            if cancellation.cancelled:
                job.status = "CANCELLED"
                self.metrics.cancelled += 1
                yield self._event(job, EngineEventKind.CANCELLED, "Cancelado antes da execução")
                return
            job.status = "STARTED"
            yield self._event(job, EngineEventKind.STARTED, "Engine de teste iniciou")
            yield self._event(job, EngineEventKind.MILESTONE, "Contrato e policy validados")
            if cancellation.cancelled:
                job.status = "CANCELLED"
                self.metrics.cancelled += 1
                yield self._event(job, EngineEventKind.CANCELLED, "Cancelado cooperativamente")
                return
            try:
                result = self.result_factory(request)
            except Exception as error:
                job.status = "FAILED"
                self.metrics.failed += 1
                yield self._event(job, EngineEventKind.FAILED, f"Engine de teste falhou: {type(error).__name__}")
                return
            job.status = "COMPLETED"
            self.metrics.completed += 1
            yield self._event(
                job,
                EngineEventKind.COMPLETED,
                "Resultado de teste pronto",
                payload_sha256(result),
            )
        finally:
            self._inflight -= 1
            if job.status not in {"COMPLETED", "CANCELLED", "FAILED"}:
                job.status = "ABANDONED"

    def observability_snapshot(self) -> dict[str, int | str | bool]:
        return self.metrics.snapshot()

    def _authenticate(self) -> CloudPrincipal:
        try:
            return self.authenticator.authenticate(self.credential)
        except CloudAuthError:
            self.metrics.rejected_auth += 1
            raise

    def _authorize(self, request: EngineRequest, principal: CloudPrincipal) -> None:
        try:
            self.policy.validate(request, principal)
        except CloudPolicyError:
            self.metrics.rejected_policy += 1
            raise

    @staticmethod
    def _event(
        job: InMemoryJob,
        kind: EngineEventKind,
        message: str,
        digest: str | None = None,
    ) -> EngineEvent:
        event = EngineEvent(
            job.request.request_id,
            len(job.events) + 1,
            kind,
            message,
            digest,
        )
        job.events.append(event)
        return event
