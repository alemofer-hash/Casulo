from __future__ import annotations

import json
import re
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
    FamilyContractError,
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
            server_version = "CasuloFamilyDay1/1.0"

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
            self._json(handler, HTTPStatus.OK, self.runtime.health())
            return
        match = JOB_EVENTS_RE.fullmatch(path)
        if match:
            try:
                auth = self._auth(handler)
                events = self.runtime.wait_terminal(
                    auth, match.group(1), timeout=self.config.stream_wait_seconds
                )
                self._sse(handler, [event.to_dict() for event in events])
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
                        "mock_only": True,
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
        handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: dict[str, Any]
    ) -> None:
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        handler.send_response(status.value)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    @staticmethod
    def _sse(handler: BaseHTTPRequestHandler, events: list[dict[str, Any]]) -> None:
        chunks: list[bytes] = []
        for event in events:
            document = json.dumps(
                event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            chunks.append(
                f"id: {event['sequence']}\nevent: {event['kind']}\ndata: {document}\n\n".encode(
                    "utf-8"
                )
            )
        body = b"".join(chunks)
        handler.send_response(HTTPStatus.OK.value)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)
