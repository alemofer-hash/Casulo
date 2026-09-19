from __future__ import annotations

import hashlib
import json
import hmac
import ipaddress
import re
import select
import socket
import ssl
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
from .memory import DELETE_ALL_CONFIRMATION, FamilyRagMemory
from .runtime import FamilyRuntime
from .security import DeviceRegistry, PairedSession
from .scheduler import utc_now
from .bounded_http import discard_unread_body


JOB_EVENTS_RE = re.compile(r"^/v1/jobs/([a-f0-9]{32})/events$")
JOB_CANCEL_RE = re.compile(r"^/v1/jobs/([a-f0-9]{32})/cancel$")
DEVICE_REVOKE_RE = re.compile(r"^/v1/admin/devices/([a-z0-9._-]{1,64})/revoke$")
MEMORY_DOCUMENT_RE = re.compile(r"^/v1/memory/documents/(doc-[0-9a-f]{32})$")

PWA_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}


class FamilyGateway:
    def __init__(
        self,
        *,
        config: FamilyConfig,
        runtime: FamilyRuntime,
        security: DeviceRegistry | None = None,
        owner_token: str | None = None,
        pwa_root: Path | None = None,
        server_class=ThreadingHTTPServer,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.security = security
        self.owner_token = owner_token
        self.pwa_root = pwa_root.resolve() if pwa_root is not None else None
        if config.require_device_auth and security is None:
            raise FamilyAuthorizationError("registry obrigatório")
        if owner_token is not None and len(owner_token) < 32:
            raise FamilyAuthorizationError("owner token deve ter ao menos 32 caracteres")
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CasuloFamilyDay5/1.0"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                gateway._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                gateway._handle_post(self)

            def do_DELETE(self) -> None:  # noqa: N802
                gateway._handle_delete(self)

            def do_OPTIONS(self) -> None:  # noqa: N802
                gateway._json(self, HTTPStatus.METHOD_NOT_ALLOWED, {"error": "CORS_DISABLED"})

        self._server = server_class(
            (config.bind_host, config.bind_port), Handler
        )
        self._server.daemon_threads = True
        if config.tls_certfile is not None and config.tls_keyfile is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(config.tls_certfile, config.tls_keyfile)
            self._server.socket = context.wrap_socket(
                self._server.socket, server_side=True,
                do_handshake_on_connect=not getattr(self._server, "defer_tls_handshake", False),
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
        scheme = "https" if self.config.tls_certfile is not None else "http"
        return f"{scheme}://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            raise RuntimeError("gateway não encerrou")

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._client_allowed(handler):
            self._json(handler, HTTPStatus.FORBIDDEN, {"error": "NETWORK_DENIED"})
            return
        path = urlsplit(handler.path).path
        if path in PWA_FILES and self.pwa_root is not None:
            self._serve_pwa(handler, path)
            return
        if path == "/v1/health":
            health = self.runtime.health()
            if self.security is not None:
                health = {
                    **health,
                    "gateway_mode": "DAY4_PAIRED_DEVICE",
                    "tls": self.config.tls_certfile is not None,
                    "lan_enabled": self.config.lan_enabled,
                    "security": self.security.diagnostics(),
                }
            status = HTTPStatus.OK if health["status"] == "ok" else HTTPStatus.SERVICE_UNAVAILABLE
            self._json(handler, status, health)
            return
        if path == "/v1/session":
            try:
                session = self._session(handler)
                self._json(
                    handler,
                    HTTPStatus.OK,
                    {
                        "user_id": session.auth.user_id,
                        "device_id": session.auth.device_id,
                        "session_id": session.auth.session_id,
                        "role": session.role,
                    },
                )
            except FamilyAuthorizationError as error:
                self._json(handler, HTTPStatus.UNAUTHORIZED, {"error": str(error)})
            return
        if path in {"/v1/memory/documents", "/v1/memory/verify"}:
            try:
                auth = self._auth(handler)
                memory = self._rag_memory()
                if path == "/v1/memory/documents":
                    documents = memory.list_documents(auth)
                    self._json(
                        handler,
                        HTTPStatus.OK,
                        {"documents": list(documents), "count": len(documents)},
                    )
                else:
                    self._json(handler, HTTPStatus.OK, memory.verify_namespace(auth))
            except FamilyAuthorizationError as error:
                self._json(handler, HTTPStatus.UNAUTHORIZED, {"error": str(error)})
            except FamilyUnavailableError as error:
                self._json(
                    handler, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)}
                )
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
                status = (
                    HTTPStatus.UNAUTHORIZED
                    if self.security is not None
                    else HTTPStatus.FORBIDDEN
                )
                self._json(handler, status, {"error": str(error)})
            except KeyError:
                self._json(handler, HTTPStatus.NOT_FOUND, {"error": "job ausente"})
            return
        self._json(handler, HTTPStatus.NOT_FOUND, {"error": "rota ausente"})

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._client_allowed(handler):
            self._json(handler, HTTPStatus.FORBIDDEN, {"error": "NETWORK_DENIED"})
            return
        path = urlsplit(handler.path).path
        try:
            if path == "/v1/admin/pairing-codes":
                self._require_owner(handler)
                if self.security is None:
                    raise FamilyUnavailableError("registry indisponível")
                payload = self._read_json(handler)
                if set(payload) - {"user_id", "role"}:
                    raise FamilyContractError("campos de pareamento inválidos")
                pairing = self.security.issue_pairing_code(
                    str(payload.get("user_id", "")),
                    role=str(payload.get("role", "family")),
                )
                self._audit_security(
                    "PAIRING_CODE_ISSUED",
                    user_id=pairing.user_id,
                    device_id="owner-local",
                    session_id="default",
                    fields={"role": pairing.role, "expires_utc": pairing.expires_utc},
                )
                self._json(
                    handler,
                    HTTPStatus.CREATED,
                    {
                        "code": pairing.code,
                        "user_id": pairing.user_id,
                        "role": pairing.role,
                        "expires_utc": pairing.expires_utc,
                        "single_use": True,
                    },
                )
                return
            if path == "/v1/pair":
                if self.security is None:
                    raise FamilyUnavailableError("registry indisponível")
                payload = self._read_json(handler)
                if set(payload) != {"code", "device_name"}:
                    raise FamilyContractError("payload de pareamento inválido")
                paired = self.security.pair(
                    str(payload["code"]),
                    str(payload["device_name"]),
                    source=str(handler.client_address[0]),
                )
                self._audit_security(
                    "DEVICE_PAIRED",
                    user_id=paired.auth.user_id,
                    device_id=paired.auth.device_id,
                    session_id=paired.auth.session_id,
                    fields={"role": paired.role},
                )
                self._json(
                    handler,
                    HTTPStatus.CREATED,
                    {
                        "user_id": paired.auth.user_id,
                        "device_id": paired.auth.device_id,
                        "session_id": paired.auth.session_id,
                        "role": paired.role,
                    },
                    cookies=paired.set_cookie_headers(
                        max_age_seconds=self.security.session_ttl_seconds
                    ),
                )
                return
            revoke_match = DEVICE_REVOKE_RE.fullmatch(path)
            if revoke_match:
                self._require_owner(handler)
                if self.security is None:
                    raise FamilyUnavailableError("registry indisponível")
                device_id = revoke_match.group(1)
                auths = self.runtime.store.auth_contexts_for_device(device_id)
                sessions = self.security.revoke_device(device_id)
                cancelled = sum(
                    self.runtime.revoke_device(auth.user_id, device_id)
                    for auth in auths[:1]
                )
                self._audit_security(
                    "DEVICE_REVOKED",
                    user_id=auths[0].user_id if auths else "unknown",
                    device_id=device_id,
                    session_id="default",
                    fields={
                        "sessions_revoked": sessions,
                        "jobs_cancelled": cancelled,
                    },
                )
                self._json(
                    handler,
                    HTTPStatus.OK,
                    {
                        "device_id": device_id,
                        "revoked": True,
                        "sessions_revoked": sessions,
                        "jobs_cancelled": cancelled,
                    },
                )
                return
            auth = self._auth(handler)
            if self.security is not None:
                session = self._session(handler)
                self._require_same_origin(handler)
                self.security.verify_csrf(
                    session, handler.headers.get("X-Casulo-CSRF")
                )
            if path == "/v1/session/revoke":
                if self.security is None:
                    raise FamilyUnavailableError("registry indisponível")
                revoked = self.security.revoke_session(auth)
                self._audit_security(
                    "SESSION_REVOKED",
                    user_id=auth.user_id,
                    device_id=auth.device_id,
                    session_id=auth.session_id,
                    fields={"revoked": revoked},
                )
                self._json(
                    handler,
                    HTTPStatus.OK,
                    {"revoked": revoked},
                    cookies=self._expired_cookies(),
                )
                return
            if path == "/v1/memory/documents":
                memory = self._rag_memory()
                payload = self._read_json(handler)
                if set(payload) - {"origin", "content", "sha256"}:
                    raise FamilyContractError("campos de ingestão inválidos")
                if "origin" not in payload or "content" not in payload:
                    raise FamilyContractError("origin e content são obrigatórios")
                result = memory.ingest(
                    auth,
                    origin=payload["origin"],
                    content=payload["content"],
                    expected_sha256=payload.get("sha256"),
                )
                self._audit_security(
                    "MEMORY_DOCUMENT_INGESTED",
                    user_id=auth.user_id,
                    device_id=auth.device_id,
                    session_id=auth.session_id,
                    fields={
                        "document_id": result["document_id"],
                        "content_sha256": result["content_sha256"],
                        "content_chars": result["content_chars"],
                        "chunk_count": result["chunk_count"],
                        "receipt_id": result["receipt"]["receipt_id"],
                    },
                )
                self._json(handler, HTTPStatus.CREATED, result)
                return
            if path == "/v1/memory/search":
                memory = self._rag_memory()
                payload = self._read_json(handler)
                if set(payload) - {"query", "limit"} or "query" not in payload:
                    raise FamilyContractError("payload de busca inválido")
                if not isinstance(payload["query"], str):
                    raise FamilyContractError("query deve ser texto")
                limit_value = payload.get("limit", self.config.rag_result_limit)
                if not isinstance(limit_value, int) or isinstance(limit_value, bool):
                    raise FamilyContractError("limit de busca inválido")
                hits = memory.retrieve(
                    auth,
                    payload["query"],
                    limit=limit_value,
                )
                query_hash = hashlib.sha256(
                    payload["query"].encode("utf-8")
                ).hexdigest()
                self._audit_security(
                    "MEMORY_SEARCHED",
                    user_id=auth.user_id,
                    device_id=auth.device_id,
                    session_id=auth.session_id,
                    fields={
                        "query_sha256": query_hash,
                        "query_chars": len(payload["query"]),
                        "hits": len(hits),
                        "citation_ids": [hit.citation.citation_id for hit in hits],
                    },
                )
                self._json(
                    handler,
                    HTTPStatus.OK,
                    {
                        "query_sha256": query_hash,
                        "count": len(hits),
                        "citations": [hit.citation.to_dict() for hit in hits],
                    },
                )
                return
            if path == "/v1/memory/reindex":
                memory = self._rag_memory()
                payload = self._read_json(handler)
                if payload:
                    raise FamilyContractError("reindex não aceita parâmetros")
                result = memory.reindex(auth)
                self._audit_security(
                    "MEMORY_REINDEXED",
                    user_id=auth.user_id,
                    device_id=auth.device_id,
                    session_id=auth.session_id,
                    fields={
                        "reindexed_chunks": result["reindexed_chunks"],
                        "state_sha256": result["state_sha256"],
                        "receipt_id": result["receipt"]["receipt_id"],
                    },
                )
                self._json(handler, HTTPStatus.OK, result)
                return
            if path == "/v1/memory/delete-all":
                memory = self._rag_memory()
                payload = self._read_json(handler)
                if set(payload) != {"confirmation"}:
                    raise FamilyContractError("payload de exclusão total inválido")
                if payload["confirmation"] != DELETE_ALL_CONFIRMATION:
                    raise FamilyContractError("confirmação de exclusão total inválida")
                result = memory.delete_all(auth, str(payload["confirmation"]))
                self._audit_security(
                    "MEMORY_NAMESPACE_DELETED",
                    user_id=auth.user_id,
                    device_id=auth.device_id,
                    session_id=auth.session_id,
                    fields={
                        "deleted_documents": result["deleted_documents"],
                        "deleted_chunks": result["deleted_chunks"],
                        "receipt_id": result["receipt"]["receipt_id"],
                    },
                )
                self._json(handler, HTTPStatus.OK, result)
                return
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
            status = (
                HTTPStatus.UNAUTHORIZED
                if self.security is not None
                else HTTPStatus.FORBIDDEN
            )
            self._json(handler, status, {"error": str(error)})
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

    def _handle_delete(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._client_allowed(handler):
            self._json(handler, HTTPStatus.FORBIDDEN, {"error": "NETWORK_DENIED"})
            return
        path = urlsplit(handler.path).path
        match = MEMORY_DOCUMENT_RE.fullmatch(path)
        if match is None:
            self._json(handler, HTTPStatus.NOT_FOUND, {"error": "rota ausente"})
            return
        try:
            auth = self._auth(handler)
            if self.security is not None:
                session = self._session(handler)
                self._require_same_origin(handler)
                self.security.verify_csrf(
                    session, handler.headers.get("X-Casulo-CSRF")
                )
            result = self._rag_memory().delete_document(auth, match.group(1))
            self._audit_security(
                "MEMORY_DOCUMENT_DELETED",
                user_id=auth.user_id,
                device_id=auth.device_id,
                session_id=auth.session_id,
                fields={
                    "document_id": result["document_id"],
                    "content_sha256": result["content_sha256"],
                    "deleted_chunks": result["deleted_chunks"],
                    "receipt_id": result["receipt"]["receipt_id"],
                },
            )
            self._json(handler, HTTPStatus.OK, result)
        except FamilyAuthorizationError as error:
            status = (
                HTTPStatus.UNAUTHORIZED
                if self.security is not None
                else HTTPStatus.FORBIDDEN
            )
            self._json(handler, status, {"error": str(error)})
        except FamilyUnavailableError:
            self._json(
                handler,
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "MEMORY_NOT_READY", "retry_safe": True},
            )
        except FamilyContractError as error:
            self._json(handler, HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except KeyError:
            self._json(handler, HTTPStatus.NOT_FOUND, {"error": "documento ausente"})

    def _auth(self, handler: BaseHTTPRequestHandler) -> AuthContext:
        if self.security is not None:
            return self._session(handler).auth
        user_id = handler.headers.get("X-Casulo-User", "")
        device_id = handler.headers.get("X-Casulo-Device", "")
        try:
            return AuthContext(user_id=user_id, device_id=device_id)
        except FamilyContractError as error:
            raise FamilyAuthorizationError("contexto sintético ausente") from error

    def _session(self, handler: BaseHTTPRequestHandler) -> PairedSession:
        if self.security is None:
            raise FamilyAuthorizationError("autenticação de dispositivo desabilitada")
        return self.security.authenticate(handler.headers.get("Cookie"))

    def _rag_memory(self) -> FamilyRagMemory:
        if not isinstance(self.runtime.memory, FamilyRagMemory):
            raise FamilyUnavailableError("RAG indisponível")
        return self.runtime.memory

    def _require_owner(self, handler: BaseHTTPRequestHandler) -> None:
        if self.owner_token is None:
            raise FamilyAuthorizationError("admin local desabilitado")
        source = ipaddress.ip_address(str(handler.client_address[0]))
        bind = ipaddress.ip_address(self.config.bind_host)
        if not source.is_loopback and source != bind:
            raise FamilyAuthorizationError("admin permitido somente no owner host")
        provided = handler.headers.get("X-Casulo-Owner-Token", "")
        if not hmac.compare_digest(provided, self.owner_token):
            raise FamilyAuthorizationError("owner token inválido")

    def _require_same_origin(self, handler: BaseHTTPRequestHandler) -> None:
        origin = handler.headers.get("Origin")
        if origin is None:
            return
        scheme = "https" if self.config.tls_certfile is not None else "http"
        expected = f"{scheme}://{handler.headers.get('Host', '')}"
        if origin != expected:
            raise FamilyAuthorizationError("origin recusada")

    def _client_allowed(self, handler: BaseHTTPRequestHandler) -> bool:
        source = ipaddress.ip_address(str(handler.client_address[0]))
        if source.is_loopback:
            return True
        if not self.config.lan_enabled or self.config.approved_network is None:
            return False
        return source in ipaddress.ip_network(
            self.config.approved_network, strict=False
        )

    def _audit_security(
        self,
        event_type: str,
        *,
        user_id: str,
        device_id: str,
        session_id: str,
        fields: dict[str, Any],
    ) -> None:
        self.runtime.audit.append(
            timestamp_utc=utc_now(),
            event_type=event_type,
            correlation_id=uuid.uuid4().hex,
            user_id=user_id,
            device_id=device_id,
            session_id=session_id,
            fields=fields,
        )

    def _read_json(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        raw_length = handler.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdecimal():
            raise FamilyContractError("Content-Length obrigatório")
        length = int(raw_length)
        if length <= 0 or length > self.config.max_request_bytes:
            raise FamilyContractError("corpo fora do limite")
        body = handler.rfile.read(length)
        handler._body_consumed = True
        document = json.loads(body.decode("utf-8"))
        if not isinstance(document, dict):
            raise FamilyContractError("payload deve ser objeto")
        return document

    def _json(
        self,
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        cookies: tuple[str, ...] = (),
    ) -> None:
        discard_unread_body(handler, self.config.max_request_bytes)
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        handler.send_response(status.value)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        self._security_headers(handler)
        for key, value in (headers or {}).items():
            handler.send_header(key, value)
        for cookie in cookies:
            handler.send_header("Set-Cookie", cookie)
        handler.end_headers()
        handler.wfile.write(body)

    def _serve_pwa(self, handler: BaseHTTPRequestHandler, path: str) -> None:
        assert self.pwa_root is not None
        name, content_type = PWA_FILES[path]
        target = (self.pwa_root / name).resolve()
        if target.parent != self.pwa_root or not target.is_file():
            self._json(handler, HTTPStatus.NOT_FOUND, {"error": "asset ausente"})
            return
        body = target.read_bytes()
        handler.send_response(HTTPStatus.OK.value)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header(
            "Cache-Control",
            "no-cache" if name in {"index.html", "sw.js"} else "public, max-age=3600",
        )
        self._security_headers(handler)
        handler.end_headers()
        handler.wfile.write(body)

    def _security_headers(self, handler: BaseHTTPRequestHandler) -> None:
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        if self.config.tls_certfile is not None:
            handler.send_header("Strict-Transport-Security", "max-age=31536000")

    @staticmethod
    def _expired_cookies() -> tuple[str, ...]:
        return tuple(
            f"{name}=; Path=/; Max-Age=0; Secure; SameSite=Strict; HttpOnly"
            for name in ("casulo_device", "casulo_session")
        ) + ("casulo_csrf=; Path=/; Max-Age=0; Secure; SameSite=Strict",)

    def _sse(
        self,
        handler: BaseHTTPRequestHandler,
        auth: AuthContext,
        job_id: str,
        *,
        timeout: float,
    ) -> None:
        # Authorize ownership before committing the HTTP 200 SSE headers.  If
        # this check happened only inside stream_events(), a cross-session
        # caller would observe an empty 200 response even though access was
        # denied after the headers had already been sent.
        self.runtime.events(auth, job_id)
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
