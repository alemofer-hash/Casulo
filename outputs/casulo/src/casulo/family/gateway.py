from __future__ import annotations

import json
import re
import select
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .config import FamilyConfig
from .contracts import (
    AuthContext,
    ChatRequest,
    FamilyAuthorizationError,
    FamilyBackpressureError,
    FamilyContractError,
    FamilyResourceError,
    FamilyUnavailableError,
)
from .runtime import FamilyRuntime


JOB_EVENTS_RE = re.compile(r"^/v1/jobs/([a-f0-9]{32})/events$")
JOB_CANCEL_RE = re.compile(r"^/v1/jobs/([a-f0-9]{32})/cancel$")


class FamilyGateway:
    def __init__(self, *, config: FamilyConfig, runtime: FamilyRuntime) -> None:
        self.config = config
        self.runtime = runtime
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CasuloFamilyDay3/1.0"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                gateway._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                gateway._handle_post(self)

        self._server = ThreadingHTTPServer(
            (config.bind_host, config.bind_port), Handler
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="casulo-family-day1-gateway",
            daemon=True,
        )

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    @property
    def base_url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            raise RuntimeError("gateway não encerrou")

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlsplit(handler.path).path
        if path == "/v1/health":
            health = self.runtime.health()
            status = HTTPStatus.OK if health["status"] == "ok" else HTTPStatus.SERVICE_UNAVAILABLE
            self._json(handler, status, health)
            return
        match = JOB_EVENTS_RE.fullmatch(path)
        if match:
            try:
                auth = self._auth(handler)
                self._sse(
                    handler,
                    auth,
                    match.group(1),
                    timeout=self.config.stream_wait_seconds,
                )
            except FamilyAuthorizationError as error:
                self._json(handler, HTTPStatus.FORBIDDEN, {"error": str(error)})
            except KeyError:
                self._json(handler, HTTPStatus.NOT_FOUND, {"error": "job ausente"})
            return
        self._json(handler, HTTPStatus.NOT_FOUND, {"error": "rota ausente"})

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlsplit(handler.path).path
        try:
            auth = self._auth(handler)
            if path == "/v1/chat":
                request = ChatRequest.from_mapping(self._read_json(handler))
                job = self.runtime.submit(auth, request)
                self._json(
                    handler,
                    HTTPStatus.ACCEPTED,
                    {
                        "job_id": job.job_id,
                        "correlation_id": job.correlation_id,
                        "status": job.status.value,
                        "mock_only": bool(self.runtime.supervisor.engine.mock_only),
                        "queue_position": self.runtime.store.queue_position(job.job_id),
                        "queue_capacity": self.config.queue_capacity,
                    },
                )
                return
            match = JOB_CANCEL_RE.fullmatch(path)
            if match:
                event = self.runtime.cancel(auth, match.group(1))
                self._json(
                    handler,
                    HTTPStatus.OK,
                    {"cancelled": event is not None, "job_id": match.group(1)},
                )
                return
            self._json(handler, HTTPStatus.NOT_FOUND, {"error": "rota ausente"})
        except FamilyAuthorizationError as error:
            self._json(handler, HTTPStatus.FORBIDDEN, {"error": str(error)})
        except FamilyBackpressureError:
            self._json(
                handler,
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": "QUEUE_CAPACITY_EXCEEDED", "retry_safe": True},
                headers={"Retry-After": "1"},
            )
        except FamilyResourceError:
            self._json(
                handler,
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "RESOURCE_FLOOR_NOT_PRESERVED", "retry_safe": True},
                headers={"Retry-After": "5"},
            )
        except FamilyUnavailableError:
            self._json(
                handler,
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "SUPERVISOR_NOT_READY", "retry_safe": True},
                headers={"Retry-After": "1"},
            )
        except (FamilyContractError, json.JSONDecodeError, UnicodeDecodeError) as error:
            self._json(handler, HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except KeyError:
            self._json(handler, HTTPStatus.NOT_FOUND, {"error": "job ausente"})

    def _auth(self, handler: BaseHTTPRequestHandler) -> AuthContext:
        user_id = handler.headers.get("X-Casulo-User", "")
        device_id = handler.headers.get("X-Casulo-Device", "")
        try:
            return AuthContext(user_id=user_id, device_id=device_id)
        except FamilyContractError as error:
            raise FamilyAuthorizationError("contexto sintético ausente") from error

    def _read_json(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        raw_length = handler.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdecimal():
            raise FamilyContractError("Content-Length obrigatório")
        length = int(raw_length)
        if length <= 0 or length > self.config.max_request_bytes:
            raise FamilyContractError("corpo fora do limite")
        body = handler.rfile.read(length)
        document = json.loads(body.decode("utf-8"))
        if not isinstance(document, dict):
            raise FamilyContractError("payload deve ser objeto")
        return document

    @staticmethod
    def _json(
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        handler.send_response(status.value)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(body)

    def _sse(
        self,
        handler: BaseHTTPRequestHandler,
        auth: AuthContext,
        job_id: str,
        *,
        timeout: float,
    ) -> None:
        handler.send_response(HTTPStatus.OK.value)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        monitor_stop = threading.Event()

        def monitor_client() -> None:
            while not monitor_stop.wait(0.05):
                if self._client_disconnected(handler):
                    self.runtime.disconnect(auth, job_id)
                    return

        monitor = threading.Thread(
            target=monitor_client,
            name=f"family-disconnect-{job_id[:8]}",
            daemon=True,
        )
        monitor.start()
        try:
            for item in self.runtime.stream_events(auth, job_id, timeout=timeout):
                if self._client_disconnected(handler):
                    self.runtime.disconnect(auth, job_id)
                    return
                event = item.to_dict()
                document = json.dumps(
                    event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                chunk = (
                    f"id: {event['sequence']}\nevent: {event['kind']}\n"
                    f"data: {document}\n\n"
                ).encode("utf-8")
                handler.wfile.write(chunk)
                handler.wfile.flush()
                if self._client_disconnected(handler):
                    self.runtime.disconnect(auth, job_id)
                    return
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.runtime.disconnect(auth, job_id)
        finally:
            monitor_stop.set()
            monitor.join(timeout=1.0)

    @staticmethod
    def _client_disconnected(handler: BaseHTTPRequestHandler) -> bool:
        """Detect a closed peer without consuming request bytes."""
        connection = handler.connection
        try:
            readable, _, _ = select.select([connection], [], [], 0)
            if not readable:
                return False
            return connection.recv(1, socket.MSG_PEEK) == b""
        except (BlockingIOError, InterruptedError):
            return False
        except OSError:
            return True
