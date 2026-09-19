from __future__ import annotations

import http.client
import json
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from casulo.family.audit import AuditLog
from casulo.family.config import FamilyConfig
from casulo.family.contracts import (
    AuthContext,
    ChatRequest,
    EventKind,
    FamilyBackpressureError,
    FamilyResourceError,
    FamilyUnavailableError,
    JobStatus,
)
from casulo.family.gateway import FamilyGateway
from casulo.family.memory import MockFamilyMemory
from casulo.family.runtime import FamilyRuntime
from casulo.family.scheduler import FamilyJobStore
from casulo.family.supervisor import FamilySupervisor, SupervisorState


AUTH = AuthContext("owner", "day3-device")


class ControlledEngine:
    def __init__(self, *, mock_only: bool = True) -> None:
        self.mock_only = mock_only
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0
        self.recover_calls = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.entered = threading.Event()
        self.first_fragment = threading.Event()
        self.release = threading.Event()
        self.fail_start = False
        self.fail_once = True
        self.available_ram_bytes = 2 * 1_024**3
        self.disk_free_bytes = 40 * 1_024**3

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_start:
            raise RuntimeError("synthetic start failure")
        self.started = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.started = False

    def is_ready(self) -> bool:
        return self.started

    def recover(self) -> bool:
        self.recover_calls += 1
        return self.started

    def diagnostics(self) -> dict[str, object]:
        return {
            "runtime_listener": "127.0.0.1:39999" if self.started else None,
            "runtime_loopback_only": True,
            "runtime_instances": int(self.started),
            "available_ram_bytes": self.available_ram_bytes,
            "disk_free_bytes": self.disk_free_bytes,
            "process_working_set_bytes": 512 * 1_024**2,
        }

    def generate(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.entered.set()
        try:
            if request.message == "error-once" and self.fail_once:
                self.fail_once = False
                raise RuntimeError("synthetic adapter failure")
            if request.message in {"hold", "before-first"}:
                while not self.release.wait(0.005):
                    if cancelled():
                        return
                if cancelled():
                    return
                yield "liberado"
                return
            if request.message in {"stream-hold", "disconnect"}:
                yield "primeiro"
                self.first_fragment.set()
                while not self.release.wait(0.005):
                    if cancelled():
                        return
                if cancelled():
                    return
                yield "segundo-" * 2_000 if request.message == "disconnect" else "segundo"
                return
            if request.message == "cancel-error":
                yield "primeiro"
                self.first_fragment.set()
                while not cancelled():
                    time.sleep(0.005)
                raise RuntimeError("transport closed after cancellation")
            if request.message == "too-many":
                for number in range(9):
                    if cancelled():
                        return
                    yield str(number)
                return
            for chunk in ("um", "dois", "três"):
                if cancelled():
                    return
                time.sleep(0.005)
                yield chunk
        finally:
            with self.lock:
                self.active -= 1


def build_runtime(
    tmp_path: Path,
    engine: ControlledEngine,
    *,
    queue_capacity: int = 2,
    max_stream_events: int = 512,
    stream_wait_seconds: float = 3.0,
) -> tuple[FamilyRuntime, FamilyConfig]:
    config = FamilyConfig(
        queue_capacity=queue_capacity,
        max_stream_events=max_stream_events,
        stream_wait_seconds=stream_wait_seconds,
        mock_only=engine.mock_only,
    )
    supervisor = FamilySupervisor(
        engine,
        minimum_available_ram_bytes=config.minimum_available_ram_bytes,
        minimum_disk_free_bytes=config.minimum_disk_free_bytes,
    )
    runtime = FamilyRuntime(
        store=FamilyJobStore(tmp_path / "jobs.sqlite3"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        memory=MockFamilyMemory(tmp_path / "memory.sqlite3"),
        supervisor=supervisor,
        authorized_contexts=(AUTH,),
        config=config,
    )
    return runtime, config


def terminal(runtime: FamilyRuntime, job_id: str, timeout: float = 3.0):
    events = runtime.wait_terminal(AUTH, job_id, timeout=timeout)
    assert events and events[-1].terminal
    return events


def post_json(url: str, message: str) -> tuple[int, dict[str, object], dict[str, str]]:
    raw = json.dumps({"message": message}).encode()
    request = urllib.request.Request(
        url,
        method="POST",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Casulo-User": AUTH.user_id,
            "X-Casulo-Device": AUTH.device_id,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read()), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read()), dict(error.headers)


def post_action(url: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        method="POST",
        data=b"",
        headers={
            "X-Casulo-User": AUTH.user_id,
            "X-Casulo-Device": AUTH.device_id,
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_supervisor_lifecycle_readiness_and_second_instance_protection() -> None:
    engine = ControlledEngine()
    supervisor = FamilySupervisor(engine)
    assert supervisor.state == SupervisorState.STOPPED
    assert supervisor.start() is True
    assert supervisor.state == SupervisorState.READY
    assert supervisor.start() is True
    assert engine.start_calls == 1
    assert list(supervisor.respond(ChatRequest("normal"), lambda: False)) == [
        "um",
        "dois",
        "três",
    ]
    assert supervisor.state == SupervisorState.READY
    assert supervisor.snapshot()["maximum_active_generations"] == 1
    supervisor.stop()
    assert supervisor.state == SupervisorState.STOPPED
    assert [item.current for item in supervisor.transitions] == [
        SupervisorState.STARTING,
        SupervisorState.READY,
        SupervisorState.BUSY,
        SupervisorState.DRAINING,
        SupervisorState.READY,
        SupervisorState.DRAINING,
        SupervisorState.STOPPED,
    ]


def test_runtime_unavailable_fails_closed() -> None:
    engine = ControlledEngine()
    engine.fail_start = True
    supervisor = FamilySupervisor(engine)
    assert supervisor.start() is False
    assert supervisor.state == SupervisorState.FAILED
    with pytest.raises(FamilyUnavailableError):
        supervisor.admission_sample()


def test_stream_is_incremental_ordered_and_has_one_normal_terminal(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, _ = build_runtime(tmp_path, engine)
    try:
        job = runtime.submit(AUTH, ChatRequest("stream-hold"))
        observed = []

        def consume() -> None:
            observed.extend(runtime.stream_events(AUTH, job.job_id, timeout=3))

        reader = threading.Thread(target=consume)
        reader.start()
        assert engine.first_fragment.wait(1)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not any(
            item.kind == EventKind.DELTA for item in observed
        ):
            time.sleep(0.005)
        assert [item.payload.get("text") for item in observed if item.kind == EventKind.DELTA] == [
            "primeiro"
        ]
        assert reader.is_alive()
        engine.release.set()
        reader.join(2)
        assert not reader.is_alive()
        assert [item.sequence for item in observed] == list(range(1, len(observed) + 1))
        assert [item.payload.get("text") for item in observed if item.kind == EventKind.DELTA] == [
            "primeiro",
            "segundo",
        ]
        assert observed[-1].kind == EventKind.COMPLETED
        assert sum(item.terminal for item in observed) == 1
        assert observed[-1].payload["time_to_first_fragment_ms"] >= 0
    finally:
        runtime.close()


def test_cancel_before_first_fragment_and_recover(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, _ = build_runtime(tmp_path, engine)
    try:
        job = runtime.submit(AUTH, ChatRequest("before-first"))
        assert engine.entered.wait(1)
        runtime.cancel(AUTH, job.job_id)
        events = terminal(runtime, job.job_id)
        assert events[-1].kind == EventKind.CANCELLED
        assert not any(item.kind == EventKind.DELTA for item in events)
        engine.release.set()
        assert runtime.supervisor.state in {SupervisorState.BUSY, SupervisorState.READY}
        followup = runtime.submit(AUTH, ChatRequest("normal"))
        assert terminal(runtime, followup.job_id)[-1].kind == EventKind.COMPLETED
    finally:
        runtime.close()


def test_cancel_during_stream_never_becomes_completed(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, _ = build_runtime(tmp_path, engine)
    try:
        job = runtime.submit(AUTH, ChatRequest("stream-hold"))
        assert engine.first_fragment.wait(1)
        runtime.cancel(AUTH, job.job_id)
        events = terminal(runtime, job.job_id)
        engine.release.set()
        assert events[-1].kind == EventKind.CANCELLED
        assert any(item.kind == EventKind.DELTA for item in events)
        assert not any(item.kind == EventKind.COMPLETED for item in events)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and runtime.supervisor.state != SupervisorState.READY:
            time.sleep(0.005)
        assert runtime.supervisor.state == SupervisorState.READY
        assert engine.active == 0
    finally:
        runtime.close()


def test_fifo_queue_saturation_backpressure_and_cancelled_slot(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, _ = build_runtime(tmp_path, engine, queue_capacity=2)
    try:
        active = runtime.submit(AUTH, ChatRequest("hold"))
        assert engine.entered.wait(1)
        second = runtime.submit(AUTH, ChatRequest("normal"))
        third = runtime.submit(AUTH, ChatRequest("normal"))
        assert runtime.store.job_ids(JobStatus.QUEUED) == (second.job_id, third.job_id)
        with pytest.raises(FamilyBackpressureError):
            runtime.submit(AUTH, ChatRequest("excess"))
        assert engine.max_active == 1
        runtime.cancel(AUTH, second.job_id)
        replacement = runtime.submit(AUTH, ChatRequest("normal"))
        assert runtime.store.job_ids(JobStatus.QUEUED) == (
            third.job_id,
            replacement.job_id,
        )
        runtime.cancel(AUTH, replacement.job_id)
        engine.release.set()
        assert terminal(runtime, active.job_id)[-1].kind == EventKind.COMPLETED
        assert terminal(runtime, third.job_id)[-1].kind == EventKind.COMPLETED
        counters = runtime.counters()
        assert counters == {
            "accepted": 4,
            "enqueued": 4,
            "rejected": 1,
            "cancelled": 2,
            "completed": 2,
            "failed": 0,
        }
    finally:
        runtime.close()


def test_gateway_returns_429_and_exposes_diagnostics(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, config = build_runtime(tmp_path, engine, queue_capacity=1)
    gateway = FamilyGateway(config=config, runtime=runtime)
    gateway.start()
    try:
        assert gateway.address[0] == "127.0.0.1"
        first_status, first, _ = post_json(gateway.base_url + "/v1/chat", "hold")
        assert first_status == 202
        assert engine.entered.wait(1)
        second_status, _, _ = post_json(gateway.base_url + "/v1/chat", "normal")
        assert second_status == 202
        rejected_status, rejected, headers = post_json(
            gateway.base_url + "/v1/chat", "excess"
        )
        assert rejected_status == 429
        assert rejected["error"] == "QUEUE_CAPACITY_EXCEEDED"
        assert headers["Retry-After"] == "1"
        assert runtime.store.counts()[JobStatus.RUNNING.value] == 1
        assert runtime.store.counts()[JobStatus.QUEUED.value] == 1
        assert runtime.store.status(str(first["job_id"])) == JobStatus.RUNNING
        health = runtime.health()
        assert health["queue_capacity"] == 1
        assert health["temperature_monitoring"] == "EXTERNAL_MANUAL_HWINFO"
        assert health["temperature_telemetry_collected_by_runner"] is False
        assert health["temperature_claim"] == "NONE"
    finally:
        engine.release.set()
        gateway.close()
        runtime.close()


def test_gateway_streams_incrementally_and_cancel_crosses_all_layers(
    tmp_path: Path,
) -> None:
    engine = ControlledEngine()
    runtime, config = build_runtime(tmp_path, engine, stream_wait_seconds=5)
    gateway = FamilyGateway(config=config, runtime=runtime)
    gateway.start()
    connection = http.client.HTTPConnection(*gateway.address, timeout=5)
    try:
        status, accepted, _ = post_json(gateway.base_url + "/v1/chat", "stream-hold")
        assert status == 202
        job_id = str(accepted["job_id"])
        connection.request(
            "GET",
            f"/v1/jobs/{job_id}/events",
            headers={
                "X-Casulo-User": AUTH.user_id,
                "X-Casulo-Device": AUTH.device_id,
            },
        )
        response = connection.getresponse()
        assert response.status == 200
        observed: list[dict[str, object]] = []
        while not any(item["kind"] == "DELTA" for item in observed):
            line = response.readline()
            assert line
            if line.startswith(b"data: "):
                observed.append(json.loads(line[6:]))
        assert engine.release.is_set() is False
        assert observed[-1]["payload"] == {"text": "primeiro"}
        cancel_status, cancel = post_action(
            gateway.base_url + f"/v1/jobs/{job_id}/cancel"
        )
        assert cancel_status == 200 and cancel["cancelled"] is True
        while not observed[-1].get("kind") in {"COMPLETED", "CANCELLED", "FAILED"}:
            line = response.readline()
            assert line
            if line.startswith(b"data: "):
                observed.append(json.loads(line[6:]))
        assert observed[-1]["kind"] == "CANCELLED"
        assert not any(item["kind"] == "COMPLETED" for item in observed)
        engine.release.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and runtime.supervisor.state != SupervisorState.READY:
            time.sleep(0.005)
        assert runtime.supervisor.state == SupervisorState.READY
    finally:
        connection.close()
        engine.release.set()
        gateway.close()
        runtime.close()


def test_adapter_error_recovers_and_next_job_completes(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, _ = build_runtime(tmp_path, engine)
    try:
        failed = runtime.submit(AUTH, ChatRequest("error-once"))
        assert terminal(runtime, failed.job_id)[-1].kind == EventKind.FAILED
        assert engine.recover_calls == 1
        assert runtime.supervisor.state == SupervisorState.READY
        recovered = runtime.submit(AUTH, ChatRequest("normal"))
        assert terminal(runtime, recovered.job_id)[-1].kind == EventKind.COMPLETED
    finally:
        runtime.close()


def test_ram_floor_rejects_admission_without_creating_job(tmp_path: Path) -> None:
    engine = ControlledEngine(mock_only=False)
    engine.available_ram_bytes = 1_024**3 - 1
    runtime, _ = build_runtime(tmp_path, engine)
    try:
        with pytest.raises(FamilyResourceError, match="1 GiB"):
            runtime.submit(AUTH, ChatRequest("não deve entrar"))
        assert runtime.store.counts()[JobStatus.QUEUED.value] == 0
        assert runtime.counters()["rejected"] == 1
    finally:
        runtime.close()


def test_stream_event_bound_fails_closed_and_recovers(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, _ = build_runtime(tmp_path, engine, max_stream_events=8)
    try:
        oversized = runtime.submit(AUTH, ChatRequest("too-many"))
        assert terminal(runtime, oversized.job_id)[-1].kind == EventKind.FAILED
        assert runtime.supervisor.state == SupervisorState.READY
        followup = runtime.submit(AUTH, ChatRequest("normal"))
        assert terminal(runtime, followup.job_id)[-1].kind == EventKind.COMPLETED
    finally:
        runtime.close()


def test_disconnect_policy_cancels_active_job(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, _ = build_runtime(tmp_path, engine)
    try:
        job = runtime.submit(AUTH, ChatRequest("disconnect"))
        assert engine.first_fragment.wait(1)
        event = runtime.disconnect(AUTH, job.job_id)
        assert event is not None
        events = terminal(runtime, job.job_id)
        assert events[-1].kind == EventKind.CANCELLED
        assert events[-1].payload["requested_by"] == "disconnect"
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and (
            runtime.supervisor.state != SupervisorState.READY
            or runtime.supervisor.active_generations != 0
        ):
            time.sleep(0.005)
        assert runtime.supervisor.state == SupervisorState.READY
        assert not any(
            item.current == SupervisorState.DEGRADED
            for item in runtime.supervisor.transitions
        )
        engine.release.set()
    finally:
        runtime.close()


def test_transport_exception_after_cancel_is_not_adapter_failure(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, _ = build_runtime(tmp_path, engine)
    try:
        job = runtime.submit(AUTH, ChatRequest("cancel-error"))
        assert engine.first_fragment.wait(1)
        runtime.cancel(AUTH, job.job_id)
        events = terminal(runtime, job.job_id)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and (
            runtime.supervisor.state != SupervisorState.READY
            or runtime.supervisor.active_generations != 0
        ):
            time.sleep(0.005)
        assert events[-1].kind == EventKind.CANCELLED
        assert runtime.supervisor.state == SupervisorState.READY
        assert engine.recover_calls == 0
        assert not any(
            item.current == SupervisorState.DEGRADED
            for item in runtime.supervisor.transitions
        )
    finally:
        runtime.close()


def test_gateway_detects_abandoned_stream_and_cancels_job(tmp_path: Path) -> None:
    engine = ControlledEngine()
    runtime, config = build_runtime(tmp_path, engine, stream_wait_seconds=5)
    gateway = FamilyGateway(config=config, runtime=runtime)
    gateway.start()
    stream_socket: socket.socket | None = None
    stream_file = None
    try:
        status, accepted, _ = post_json(gateway.base_url + "/v1/chat", "disconnect")
        assert status == 202
        job_id = str(accepted["job_id"])
        stream_socket = socket.create_connection(gateway.address, timeout=5)
        stream_file = stream_socket.makefile("rb")
        request = (
            f"GET /v1/jobs/{job_id}/events HTTP/1.1\r\n"
            f"Host: {gateway.address[0]}:{gateway.address[1]}\r\n"
            f"X-Casulo-User: {AUTH.user_id}\r\n"
            f"X-Casulo-Device: {AUTH.device_id}\r\n"
            "Connection: close\r\n\r\n"
        )
        stream_socket.sendall(request.encode("ascii"))
        observed_delta = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not observed_delta:
            line = stream_file.readline()
            assert line
            if line.startswith(b"data: "):
                observed_delta = json.loads(line[6:])["kind"] == "DELTA"
        assert observed_delta
        stream_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0)
        )
        stream_file.close()
        stream_file = None
        stream_socket.close()
        stream_socket = None
        events = terminal(runtime, job_id)
        assert events[-1].kind == EventKind.CANCELLED
        assert events[-1].payload["requested_by"] == "disconnect"
    finally:
        if stream_file is not None:
            stream_file.close()
        if stream_socket is not None:
            stream_socket.close()
        engine.release.set()
        gateway.close()
        runtime.close()


def test_non_loopback_gateway_and_undersized_resource_config_are_rejected() -> None:
    with pytest.raises(ValueError, match="loopback"):
        FamilyConfig(bind_host="0.0.0.0")
    with pytest.raises(ValueError, match="RAM"):
        FamilyConfig(minimum_available_ram_bytes=1_024**3 - 1)
    with pytest.raises(ValueError, match="30 GiB"):
        FamilyConfig(minimum_disk_free_bytes=30 * 1_024**3 - 1)
