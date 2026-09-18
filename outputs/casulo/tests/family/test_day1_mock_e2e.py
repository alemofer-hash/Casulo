from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from casulo.family.audit import AuditLog
from casulo.family.config import FamilyConfig
from casulo.family.contracts import AuthContext, ChatRequest, EventKind
from casulo.family.gateway import FamilyGateway
from casulo.family.memory import MockFamilyMemory
from casulo.family.runtime import FamilyRuntime
from casulo.family.scheduler import FamilyJobStore
from casulo.family.supervisor import DeterministicMockEngine, FamilySupervisor


AUTH = AuthContext("owner", "device-test")


def build_runtime(
    tmp_path: Path,
    engine=None,
    authorized_contexts: tuple[AuthContext, ...] = (AUTH,),
) -> FamilyRuntime:
    return FamilyRuntime(
        store=FamilyJobStore(tmp_path / "family.sqlite3"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        memory=MockFamilyMemory(tmp_path / "memory.sqlite3"),
        supervisor=FamilySupervisor(engine or DeterministicMockEngine()),
        authorized_contexts=authorized_contexts,
    )


def request_json(url: str, *, body: dict | None = None, auth: AuthContext | None = AUTH):
    headers = {"Content-Type": "application/json"}
    if auth is not None:
        headers.update(
            {"X-Casulo-User": auth.user_id, "X-Casulo-Device": auth.device_id}
        )
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST" if body is not None else "GET", headers=headers
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.headers, response.read()


def parse_sse(raw: bytes) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in raw.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]


def test_mock_question_crosses_gateway_supervisor_and_audit(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    gateway = FamilyGateway(config=FamilyConfig(), runtime=runtime)
    gateway.start()
    prompt = "Qual é o estado local?"
    try:
        _, health_raw = request_json(gateway.base_url + "/v1/health", auth=None)
        health = json.loads(health_raw)
        assert health["status"] == "ok"
        assert health["mode"] == "DAY1_MOCK_ONLY"
        assert health["mock_memory"] is True
        _, raw = request_json(gateway.base_url + "/v1/chat", body={"message": prompt})
        accepted = json.loads(raw)
        headers, stream = request_json(
            gateway.base_url + f"/v1/jobs/{accepted['job_id']}/events"
        )
        events = parse_sse(stream)
        assert headers.get_content_type() == "text/event-stream"
        assert [event["kind"] for event in events] == [
            "ACCEPTED",
            "STARTED",
            "DELTA",
            "DELTA",
            "COMPLETED",
        ]
        assert [event["sequence"] for event in events] == list(range(1, 6))
        assert {event["correlation_id"] for event in events} == {
            accepted["correlation_id"]
        }
        assert "[MOCK LOCAL]" in "".join(
            event["payload"].get("text", "") for event in events
        )
        audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert prompt not in audit_text
        audit = [json.loads(line) for line in audit_text.splitlines()]
        assert {record["correlation_id"] for record in audit} == {
            accepted["correlation_id"]
        }
        assert all(record["record_hash"] for record in audit)
        memories = runtime.memory.recent(AUTH.user_id)
        assert [entry.correlation_id for entry in memories] == [
            accepted["correlation_id"]
        ]
    finally:
        gateway.close()
        runtime.close()


def test_gateway_rejects_missing_context_and_non_loopback(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        FamilyConfig(bind_host="0.0.0.0")
    runtime = build_runtime(tmp_path)
    gateway = FamilyGateway(config=FamilyConfig(), runtime=runtime)
    gateway.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as observed:
            request_json(
                gateway.base_url + "/v1/chat",
                body={"message": "sem contexto"},
                auth=None,
            )
        assert observed.value.code == 403
    finally:
        gateway.close()
        runtime.close()


class ProbeEngine:
    mock_only = True

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def generate(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            for _ in range(5):
                if cancelled():
                    return
                time.sleep(0.02)
            yield f"[MOCK LOCAL] {request.message}"
        finally:
            with self.lock:
                self.active -= 1


def test_scheduler_serializes_heavy_jobs_and_scopes_events(tmp_path: Path) -> None:
    engine = ProbeEngine()
    other = AuthContext("family", "device-test")
    runtime = build_runtime(tmp_path, engine, (AUTH, other))
    try:
        first = runtime.submit(AUTH, ChatRequest("primeira"))
        second = runtime.submit(AUTH, ChatRequest("segunda"))
        assert runtime.wait_terminal(AUTH, first.job_id, timeout=3)[-1].kind == EventKind.COMPLETED
        assert runtime.wait_terminal(AUTH, second.job_id, timeout=3)[-1].kind == EventKind.COMPLETED
        assert engine.max_active == 1
        with pytest.raises(PermissionError):
            runtime.events(other, first.job_id)
        assert len(runtime.memory.recent(AUTH.user_id)) == 2
        assert runtime.memory.recent(other.user_id) == ()
    finally:
        runtime.close()


def test_cancel_produces_one_terminal_event(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path, DeterministicMockEngine(delay_seconds=0.2))
    try:
        job = runtime.submit(AUTH, ChatRequest("cancelar"))
        event = runtime.cancel(AUTH, job.job_id)
        assert event is not None and event.kind == EventKind.CANCELLED
        events = runtime.wait_terminal(AUTH, job.job_id, timeout=2)
        assert sum(event.terminal for event in events) == 1
        assert events[-1].kind == EventKind.CANCELLED
        assert runtime.cancel(AUTH, job.job_id) is None
    finally:
        runtime.close()
