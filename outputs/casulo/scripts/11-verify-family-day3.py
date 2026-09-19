from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from casulo.family.audit import AuditLog
from casulo.family.config import FamilyConfig
from casulo.family.contracts import AuthContext, ChatRequest, EventKind, JobStatus
from casulo.family.gateway import FamilyGateway
from casulo.family.memory import MockFamilyMemory
from casulo.family.runtime import FamilyRuntime
from casulo.family.scheduler import FamilyJobStore
from casulo.family.supervisor import FamilySupervisor, SupervisorState
from casulo_owner.family_model_adapter import FamilyLocalModelAdapter


EXPECTED_COMMIT = "be19c85df370277fb2a71915e57f7e883e0508e6"
EXPECTED_TREE = "29bd537b005f336677059f4205b1353aa0033d29"
AUTH = AuthContext("owner", "day3-real-validation")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def git(repo: Path, *args: str) -> str:
    command = [
        "git",
        "-c",
        f"safe.directory={repo.as_posix()}",
        "-C",
        str(repo),
        *args,
    ]
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def process_snapshot() -> str:
    rows = [f"timestamp_utc={utc_now()}"]
    matches = []
    for process in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            name = str(process.info.get("name") or "")
            if name.casefold() == "llama-server.exe":
                matches.append(
                    (process.info["pid"], name, process.info.get("create_time"))
                )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    rows.append(f"llama_server_processes={len(matches)}")
    for pid, name, created in sorted(matches):
        rows.append(f"pid={pid} name={name} create_time={created}")
    return "\n".join(rows) + "\n"


def port_snapshot(*, expected_ports: set[int] | None = None) -> str:
    expected = expected_ports or set()
    rows = [f"timestamp_utc={utc_now()}"]
    observed = []
    for connection in psutil.net_connections(kind="tcp"):
        try:
            if connection.status != psutil.CONN_LISTEN or not connection.laddr:
                continue
            host, port = connection.laddr.ip, connection.laddr.port
            if port in expected or (
                connection.pid
                and psutil.Process(connection.pid).name().casefold()
                == "llama-server.exe"
            ):
                observed.append((host, port, connection.pid))
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    rows.append(f"matching_listeners={len(observed)}")
    for host, port, pid in sorted(observed):
        rows.append(f"host={host} port={port} pid={pid}")
    return "\n".join(rows) + "\n"


def submit(base_url: str, message: str) -> tuple[int, dict[str, Any], dict[str, str]]:
    body = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url + "/v1/chat",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Casulo-User": AUTH.user_id,
            "X-Casulo-Device": AUTH.device_id,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read()), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read()), dict(error.headers)


def cancel(base_url: str, job_id: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        base_url + f"/v1/jobs/{job_id}/cancel",
        data=b"",
        method="POST",
        headers={
            "X-Casulo-User": AUTH.user_id,
            "X-Casulo-Device": AUTH.device_id,
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read())


def event_summary(event: dict[str, Any], received_ns: int) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    result: dict[str, Any] = {
        "sequence": event.get("sequence"),
        "kind": event.get("kind"),
        "received_monotonic_ns": received_ns,
    }
    text = payload.get("text")
    if isinstance(text, str):
        result["text_chars"] = len(text)
        result["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for key in (
        "requested_by",
        "reason_code",
        "stream_events",
        "time_to_first_fragment_ms",
        "duration_ms",
    ):
        if key in payload:
            result[key] = payload[key]
    return result


class StreamCapture:
    def __init__(self, address: tuple[str, int], job_id: str) -> None:
        self.address = address
        self.job_id = job_id
        self.events: list[dict[str, Any]] = []
        self.first_delta = threading.Event()
        self.done = threading.Event()
        self._aborted = threading.Event()
        self.error: str | None = None
        self._socket: socket.socket | None = None
        self._stream_file: Any | None = None
        self._thread = threading.Thread(target=self._run, name=f"stream-{job_id}")

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise RuntimeError(f"stream {self.job_id} não encerrou")
        if self.error:
            raise RuntimeError(self.error)

    def abort_connection(self) -> None:
        stream_socket = self._socket
        if stream_socket is None:
            raise RuntimeError("socket de stream indisponível")
        self._aborted.set()
        if self._stream_file is not None:
            self._stream_file.close()
            self._stream_file = None
        stream_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0)
        )
        stream_socket.close()

    def _run(self) -> None:
        stream_socket = socket.create_connection(self.address, timeout=10)
        stream_socket.settimeout(300)
        self._socket = stream_socket
        stream_file = stream_socket.makefile("rb")
        self._stream_file = stream_file
        try:
            request = (
                f"GET /v1/jobs/{self.job_id}/events HTTP/1.1\r\n"
                f"Host: {self.address[0]}:{self.address[1]}\r\n"
                f"X-Casulo-User: {AUTH.user_id}\r\n"
                f"X-Casulo-Device: {AUTH.device_id}\r\n"
                "Connection: close\r\n\r\n"
            )
            stream_socket.sendall(request.encode("ascii"))
            status_line = stream_file.readline().decode("iso-8859-1").strip()
            if " 200 " not in status_line:
                raise RuntimeError(f"stream respondeu {status_line}")
            while stream_file.readline() not in {b"\r\n", b"\n", b""}:
                pass
            while True:
                line = stream_file.readline()
                if not line:
                    break
                if not line.startswith(b"data: "):
                    continue
                document = json.loads(line[6:])
                summary = event_summary(document, time.monotonic_ns())
                self.events.append(summary)
                if summary["kind"] == EventKind.DELTA.value:
                    self.first_delta.set()
                if summary["kind"] in {
                    EventKind.COMPLETED.value,
                    EventKind.CANCELLED.value,
                    EventKind.FAILED.value,
                }:
                    break
        except (
            OSError,
            ValueError,
            http.client.HTTPException,
            json.JSONDecodeError,
        ) as error:
            if not self._aborted.is_set() and not self.done.is_set():
                self.error = f"{type(error).__name__}: {error}"
        finally:
            self.done.set()
            if self._stream_file is not None:
                self._stream_file.close()
                self._stream_file = None
            stream_socket.close()


def wait_status(
    runtime: FamilyRuntime, job_id: str, status: JobStatus, timeout: float = 30
) -> None:
    if not runtime.wait_status(job_id, status, timeout=timeout):
        raise RuntimeError(f"job {job_id} não alcançou {status.value}")


def wait_supervisor_ready(supervisor: FamilySupervisor, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (
            supervisor.state == SupervisorState.READY
            and supervisor.active_generations == 0
        ):
            return
        time.sleep(0.01)
    raise RuntimeError("supervisor não retornou a READY sem geração ativa")


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo Family Day 3 real gate")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve()
    evidence = args.evidence_dir.resolve()
    state = args.state_dir.resolve()
    if evidence.exists() and any(evidence.iterdir()):
        raise RuntimeError("diretório de evidência Day 3 não está vazio")
    evidence.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=False)

    input_commit = git(repo, "rev-parse", "HEAD")
    input_tree = git(repo, "rev-parse", "HEAD^{tree}")
    if input_commit != EXPECTED_COMMIT or input_tree != EXPECTED_TREE:
        raise RuntimeError("baseline Git incompatível")
    baseline = {
        "schema": "casulo.family.day3-baseline/1.0",
        "timestamp_utc": utc_now(),
        "branch": git(repo, "branch", "--show-current"),
        "input_commit": input_commit,
        "input_tree": input_tree,
        "expected_commit": EXPECTED_COMMIT,
        "expected_tree": EXPECTED_TREE,
        "initial_working_tree_clean": True,
        "origin": "https://github.com/alemofer-hash/Casulo.git",
        "origin_visibility": "PRIVATE",
        "day2_evidence_preserved": True,
        "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
        "temperature_telemetry_collected_by_runner": False,
        "temperature_claim": "NONE",
        "psutil_version": psutil.__version__,
    }
    write_json(evidence / "baseline.json", baseline)
    (evidence / "process-inspection-before.txt").write_text(
        process_snapshot(), encoding="utf-8", newline="\n"
    )
    (evidence / "port-inspection-before.txt").write_text(
        port_snapshot(), encoding="utf-8", newline="\n"
    )
    if "llama_server_processes=0" not in process_snapshot():
        raise RuntimeError("llama-server já existia antes do gate")

    adapter = FamilyLocalModelAdapter(
        cache_root=args.cache_root,
        manifest=args.manifest,
        max_generated_tokens=256,
    )
    config = FamilyConfig(
        stream_wait_seconds=300,
        queue_capacity=2,
        max_stream_chunk_chars=2_048,
        max_stream_events=512,
        mock_only=False,
    )
    supervisor = FamilySupervisor(
        adapter,
        minimum_available_ram_bytes=config.minimum_available_ram_bytes,
        minimum_disk_free_bytes=config.minimum_disk_free_bytes,
    )
    samples_path = evidence / "resource-samples.jsonl"
    stop_samples = threading.Event()
    floor_violation = threading.Event()

    def sample_resources() -> None:
        with samples_path.open("a", encoding="utf-8", newline="\n") as stream:
            while not stop_samples.is_set():
                sample = {
                    "timestamp_utc": utc_now(),
                    **adapter.diagnostics(),
                }
                sample["supervisor_state"] = supervisor.state.value
                stream.write(
                    json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n"
                )
                stream.flush()
                ram = sample.get("available_ram_bytes")
                disk = sample.get("disk_free_bytes")
                if (
                    isinstance(ram, int)
                    and ram < config.minimum_available_ram_bytes
                ) or (
                    isinstance(disk, int)
                    and disk < config.minimum_disk_free_bytes
                ):
                    floor_violation.set()
                stop_samples.wait(0.5)

    sampler = threading.Thread(
        target=sample_resources, name="casulo-day3-resource-sampler", daemon=True
    )
    sampler.start()
    runtime: FamilyRuntime | None = None
    gateway: FamilyGateway | None = None
    gateway_port = 0
    runtime_port = 0
    result: dict[str, Any] = {
        "schema": "casulo.family.day3-real-integration/1.0",
        "started_utc": utc_now(),
        "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
        "temperature_telemetry_collected_by_runner": False,
        "temperature_claim": "NONE",
    }
    try:
        runtime = FamilyRuntime(
            store=FamilyJobStore(state / "jobs.sqlite3"),
            audit=AuditLog(state / "audit.jsonl"),
            memory=MockFamilyMemory(state / "memory.sqlite3"),
            supervisor=supervisor,
            authorized_contexts=(AUTH,),
            config=config,
        )
        if supervisor.state != SupervisorState.READY:
            raise RuntimeError("supervisor não ficou READY")
        gateway = FamilyGateway(config=config, runtime=runtime)
        gateway.start()
        gateway_port = gateway.address[1]
        runtime_address = adapter.runtime_address
        if runtime_address is None:
            raise RuntimeError("listener do runtime ausente")
        runtime_port = int(runtime_address.rsplit(":", 1)[1])
        if gateway.address[0] != "127.0.0.1" or not runtime_address.startswith(
            "127.0.0.1:"
        ):
            raise RuntimeError("listener não-loopback detectado")
        (evidence / "port-inspection-during.txt").write_text(
            port_snapshot(expected_ports={gateway_port, runtime_port}),
            encoding="utf-8",
            newline="\n",
        )

        long_prompt = (
            "Gere uma lista longa, numerada e incremental de recomendações para "
            "organizar uma biblioteca doméstica. Continue até receber cancelamento."
        )
        status, active_doc, _ = submit(gateway.base_url, long_prompt)
        if status != 202:
            raise RuntimeError(f"job ativo recusado: HTTP {status}")
        active_id = str(active_doc["job_id"])
        active_stream = StreamCapture(gateway.address, active_id)
        active_stream.start()
        if not active_stream.first_delta.wait(180):
            raise RuntimeError("primeiro fragmento do job ativo não chegou")
        wait_status(runtime, active_id, JobStatus.RUNNING)

        status, queued_one, _ = submit(gateway.base_url, "Responda apenas: fila um.")
        if status != 202:
            raise RuntimeError("primeiro item de fila recusado")
        status, queued_two, _ = submit(gateway.base_url, "Responda apenas: fila dois.")
        if status != 202:
            raise RuntimeError("segundo item de fila recusado")
        rejected_status, rejected, rejected_headers = submit(
            gateway.base_url, "esta requisição deve sofrer backpressure"
        )
        if rejected_status != 429:
            raise RuntimeError("requisição excedente não recebeu 429")
        queued_one_id = str(queued_one["job_id"])
        queued_two_id = str(queued_two["job_id"])
        queue_before_cancel = list(runtime.store.job_ids(JobStatus.QUEUED))
        cancel(gateway.base_url, queued_one_id)
        status, replacement, _ = submit(
            gateway.base_url, "Responda apenas: vaga reutilizada."
        )
        if status != 202:
            raise RuntimeError("vaga cancelada não foi reutilizada")
        replacement_id = str(replacement["job_id"])
        queue_after_replacement = list(runtime.store.job_ids(JobStatus.QUEUED))
        cancel(gateway.base_url, replacement_id)

        cancel(gateway.base_url, active_id)
        active_stream.join(30)
        active_events = runtime.wait_terminal(AUTH, active_id, timeout=30)
        if not active_events or active_events[-1].kind != EventKind.CANCELLED:
            raise RuntimeError("job ativo cancelado não terminou CANCELLED")
        if any(event.kind == EventKind.COMPLETED for event in active_events):
            raise RuntimeError("resposta parcial cancelada virou COMPLETED")

        recovery_stream = StreamCapture(gateway.address, queued_two_id)
        recovery_stream.start()
        recovery_stream.join(300)
        recovery_events = runtime.wait_terminal(AUTH, queued_two_id, timeout=30)
        if not recovery_events or recovery_events[-1].kind != EventKind.COMPLETED:
            raise RuntimeError("fila não avançou após cancelamento")

        status, final_doc, _ = submit(
            gateway.base_url, "Responda em uma frase curta: recuperação concluída."
        )
        if status != 202:
            raise RuntimeError("job curto de recuperação recusado")
        final_id = str(final_doc["job_id"])
        final_stream = StreamCapture(gateway.address, final_id)
        final_stream.start()
        final_stream.join(300)
        final_events = runtime.wait_terminal(AUTH, final_id, timeout=30)
        if not final_events or final_events[-1].kind != EventKind.COMPLETED:
            raise RuntimeError("job curto pós-cancelamento falhou")

        status, disconnect_doc, _ = submit(gateway.base_url, long_prompt)
        if status != 202:
            raise RuntimeError("job de disconnect recusado")
        disconnect_id = str(disconnect_doc["job_id"])
        disconnect_stream = StreamCapture(gateway.address, disconnect_id)
        disconnect_stream.start()
        if not disconnect_stream.first_delta.wait(180):
            raise RuntimeError("job de disconnect não emitiu fragmento")
        disconnect_stream.abort_connection()
        disconnect_events = runtime.wait_terminal(AUTH, disconnect_id, timeout=30)
        if not disconnect_events or disconnect_events[-1].kind != EventKind.CANCELLED:
            raise RuntimeError("disconnect não cancelou o job")
        disconnect_stream.join(5)
        wait_supervisor_ready(supervisor)

        if floor_violation.is_set():
            raise RuntimeError("piso de RAM ou disco violado")
        if supervisor.snapshot()["maximum_active_generations"] != 1:
            raise RuntimeError("concorrência ativa diferente de um")
        if adapter.diagnostics()["adapter_maximum_active_requests"] != 1:
            raise RuntimeError("adapter executou concorrência diferente de um")

        result.update(
            {
                "status": "PASS",
                "ended_utc": utc_now(),
                "runtime_address": runtime_address,
                "gateway_address": f"127.0.0.1:{gateway_port}",
                "queue_capacity": config.queue_capacity,
                "queue_before_cancel": queue_before_cancel,
                "queue_after_replacement": queue_after_replacement,
                "rejected_http_status": rejected_status,
                "rejected_error": rejected.get("error"),
                "rejected_retry_after": rejected_headers.get("Retry-After"),
                "counters": runtime.counters(),
                "supervisor": supervisor.snapshot(),
                "active_job_id": active_id,
                "queued_cancelled_job_id": queued_one_id,
                "fifo_completed_job_id": queued_two_id,
                "replacement_cancelled_job_id": replacement_id,
                "post_cancel_success_job_id": final_id,
                "disconnect_cancelled_job_id": disconnect_id,
            }
        )
        write_json(
            evidence / "streaming.json",
            {
                "schema": "casulo.family.day3-streaming/1.0",
                "active_cancelled_stream": active_stream.events,
                "fifo_completed_stream": recovery_stream.events,
                "post_cancel_completed_stream": final_stream.events,
                "incremental_before_terminal": any(
                    item["kind"] == "DELTA" for item in recovery_stream.events[:-1]
                ),
                "ordered": all(
                    [item["sequence"] for item in capture.events]
                    == sorted(item["sequence"] for item in capture.events)
                    for capture in (active_stream, recovery_stream, final_stream)
                ),
                "terminal_kinds": [
                    active_stream.events[-1]["kind"],
                    recovery_stream.events[-1]["kind"],
                    final_stream.events[-1]["kind"],
                ],
                "content_logged": False,
            },
        )
        write_json(
            evidence / "cancellation.json",
            {
                "schema": "casulo.family.day3-cancellation/1.0",
                "voluntary_active": event_summary(
                    active_events[-1].to_dict(), time.monotonic_ns()
                ),
                "queued": event_summary(
                    runtime.events(AUTH, queued_one_id)[-1].to_dict(),
                    time.monotonic_ns(),
                ),
                "replacement_queued": event_summary(
                    runtime.events(AUTH, replacement_id)[-1].to_dict(),
                    time.monotonic_ns(),
                ),
                "disconnect": event_summary(
                    disconnect_events[-1].to_dict(), time.monotonic_ns()
                ),
                "partial_presented_as_complete": False,
                "supervisor_returned_ready": supervisor.state
                == SupervisorState.READY,
            },
        )
        write_json(
            evidence / "queue-backpressure.json",
            {
                "schema": "casulo.family.day3-queue-backpressure/1.0",
                "policy": "FIFO",
                "capacity": config.queue_capacity,
                "queue_before_cancel": queue_before_cancel,
                "queue_after_replacement": queue_after_replacement,
                "excess_http_status": rejected_status,
                "retry_after": rejected_headers.get("Retry-After"),
                "rejected_started_inference": False,
                "fifo_advanced_after_active_cancel": recovery_events[-1].kind
                == EventKind.COMPLETED,
                "maximum_active_generations": supervisor.snapshot()[
                    "maximum_active_generations"
                ],
                "counters": runtime.counters(),
            },
        )
        write_json(
            evidence / "supervisor-lifecycle.json",
            {
                "schema": "casulo.family.day3-supervisor-lifecycle/1.0",
                "current_state": supervisor.state.value,
                "states_required": [item.value for item in SupervisorState],
                "transitions": [
                    item.to_dict() for item in supervisor.transitions
                ],
                "snapshot": supervisor.snapshot(),
            },
        )
    except Exception as error:
        result.update(
            {
                "status": "FAIL",
                "ended_utc": utc_now(),
                "failure_type": type(error).__name__,
                "failure_message": str(error),
            }
        )
        write_json(evidence / "integration-result.json", result)
        raise
    finally:
        if gateway is not None:
            gateway.close()
        if runtime is not None:
            runtime.close()
        elif supervisor.state != SupervisorState.STOPPED:
            supervisor.stop()
        stop_samples.set()
        sampler.join(5)
        if sampler.is_alive():
            result["sampler_cleanup"] = "FAILED"
        else:
            result["sampler_cleanup"] = "PASS"
        expected_ports = {item for item in (gateway_port, runtime_port) if item}
        (evidence / "port-inspection-after.txt").write_text(
            port_snapshot(expected_ports=expected_ports),
            encoding="utf-8",
            newline="\n",
        )
        (evidence / "process-inspection-after.txt").write_text(
            process_snapshot(), encoding="utf-8", newline="\n"
        )
        result["process_cleanup"] = (
            "PASS"
            if "llama_server_processes=0" in process_snapshot()
            else "FAIL"
        )
        result["port_cleanup"] = (
            "PASS"
            if "matching_listeners=0"
            in port_snapshot(expected_ports=expected_ports)
            else "FAIL"
        )
        write_json(
            evidence / "supervisor-lifecycle.json",
            {
                "schema": "casulo.family.day3-supervisor-lifecycle/1.0",
                "current_state": supervisor.state.value,
                "states_required": [item.value for item in SupervisorState],
                "transitions": [item.to_dict() for item in supervisor.transitions],
                "snapshot": supervisor.snapshot(),
            },
        )
        write_json(evidence / "integration-result.json", result)

    if any(
        result.get(key) != "PASS"
        for key in ("status", "sampler_cleanup", "process_cleanup", "port_cleanup")
    ):
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "evidence": str(evidence),
                "runtime": result["runtime_address"],
                "counters": result["counters"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
