from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from casulo.family.audit import AuditLog
from casulo.family.config import FamilyConfig
from casulo.family.contracts import (
    ChatRequest,
    EventKind,
    FamilyAuthorizationError,
    JobStatus,
)
from casulo.family.gateway import FamilyGateway
from casulo.family.memory import MockFamilyMemory
from casulo.family.runtime import FamilyRuntime
from casulo.family.scheduler import FamilyJobStore
from casulo.family.security import DeviceRegistry
from casulo.family.supervisor import DeterministicMockEngine, FamilySupervisor


OWNER_TOKEN = "owner-test-token-32-bytes-minimum-value"
PWA_ROOT = Path(__file__).parents[2] / "apps" / "casulo-family-pwa"


def build_secure(tmp_path: Path, *, tls: tuple[Path, Path] | None = None):
    registry = DeviceRegistry(tmp_path / "devices.sqlite3")
    config = FamilyConfig(
        require_device_auth=True,
        tls_certfile=None if tls is None else tls[0],
        tls_keyfile=None if tls is None else tls[1],
    )
    runtime = FamilyRuntime(
        store=FamilyJobStore(tmp_path / "jobs.sqlite3"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        memory=MockFamilyMemory(tmp_path / "memory.sqlite3"),
        supervisor=FamilySupervisor(DeterministicMockEngine()),
        authorized_contexts=(),
        authorization_callback=registry.is_context_active,
        config=config,
    )
    gateway = FamilyGateway(
        config=config,
        runtime=runtime,
        security=registry,
        owner_token=OWNER_TOKEN,
        pwa_root=PWA_ROOT,
    )
    return registry, runtime, gateway


def request(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    context: ssl.SSLContext | None = None,
):
    data = None if body is None else json.dumps(body).encode("utf-8")
    merged = dict(headers or {})
    if data is not None:
        merged["Content-Type"] = "application/json"
    call = urllib.request.Request(url, data=data, method=method, headers=merged)
    with urllib.request.urlopen(call, timeout=10, context=context) as response:
        return response.status, response.headers, response.read()


def cookie_bundle(headers) -> tuple[str, str]:
    cookies = SimpleCookie()
    raw = headers.get_all("Set-Cookie")
    assert raw and len(raw) == 3
    for item in raw:
        cookies.load(item)
    header = "; ".join(f"{key}={item.value}" for key, item in cookies.items())
    return header, cookies["casulo_csrf"].value


def pair_via_gateway(
    gateway: FamilyGateway,
    user: str = "ana",
    *,
    context: ssl.SSLContext | None = None,
):
    _, _, raw = request(
        gateway.base_url + "/v1/admin/pairing-codes",
        method="POST",
        body={"user_id": user, "role": "family"},
        headers={"X-Casulo-Owner-Token": OWNER_TOKEN},
        context=context,
    )
    code = json.loads(raw)["code"]
    status, headers, raw = request(
        gateway.base_url + "/v1/pair",
        method="POST",
        body={"code": code, "device_name": "Telefone da Ana"},
        context=context,
    )
    assert status == 201
    return json.loads(raw), cookie_bundle(headers), code, headers.get_all("Set-Cookie")


def test_pairing_is_single_use_hashed_and_cookie_flags_are_strict(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "registry.sqlite3")
    try:
        pairing = registry.issue_pairing_code("ana")
        paired = registry.pair(pairing.code, "Telefone", source="192.168.1.8")
        assert paired.auth.user_id == "ana"
        headers = paired.set_cookie_headers(max_age_seconds=3600)
        assert all("Secure" in item and "SameSite=Strict" in item for item in headers)
        assert "HttpOnly" in headers[0] and "HttpOnly" in headers[1]
        assert "HttpOnly" not in headers[2]
        with pytest.raises(FamilyAuthorizationError, match="inválido|utilizado"):
            registry.pair(pairing.code, "Outro", source="192.168.1.9")
        database = (tmp_path / "registry.sqlite3").read_bytes()
        assert pairing.code.encode() not in database
        assert paired.device_cookie.encode() not in database
        assert paired.session_cookie.encode() not in database
        assert paired.csrf_token.encode() not in database
    finally:
        registry.close()


def test_secure_gateway_pair_chat_csrf_origin_and_revoke(tmp_path: Path) -> None:
    registry, runtime, gateway = build_secure(tmp_path)
    gateway.start()
    try:
        paired, (cookies, csrf), code, set_cookies = pair_via_gateway(gateway)
        assert all("Secure" in value for value in set_cookies)
        with pytest.raises(urllib.error.HTTPError) as reused:
            request(
                gateway.base_url + "/v1/pair",
                method="POST",
                body={"code": code, "device_name": "Replay"},
            )
        assert reused.value.code == 401

        with pytest.raises(urllib.error.HTTPError) as missing_csrf:
            request(
                gateway.base_url + "/v1/chat",
                method="POST",
                body={"message": "Olá"},
                headers={"Cookie": cookies},
            )
        assert missing_csrf.value.code == 401
        with pytest.raises(urllib.error.HTTPError) as bad_origin:
            request(
                gateway.base_url + "/v1/chat",
                method="POST",
                body={"message": "Olá"},
                headers={
                    "Cookie": cookies,
                    "X-Casulo-CSRF": csrf,
                    "Origin": "https://attacker.invalid",
                },
            )
        assert bad_origin.value.code == 401

        status, _, raw = request(
            gateway.base_url + "/v1/chat",
            method="POST",
            body={"message": "Responda localmente"},
            headers={
                "Cookie": cookies,
                "X-Casulo-CSRF": csrf,
                "Origin": gateway.base_url,
            },
        )
        assert status == 202
        job_id = json.loads(raw)["job_id"]
        _, (other_cookies, _), _, _ = pair_via_gateway(gateway)
        with pytest.raises(urllib.error.HTTPError) as cross_session:
            request(
                gateway.base_url + f"/v1/jobs/{job_id}/events",
                headers={"Cookie": other_cookies},
            )
        assert cross_session.value.code == 401
        _, _, stream = request(
            gateway.base_url + f"/v1/jobs/{job_id}/events",
            headers={"Cookie": cookies},
        )
        assert b'"kind":"COMPLETED"' in stream
        status, _, raw = request(
            gateway.base_url + f"/v1/admin/devices/{paired['device_id']}/revoke",
            method="POST",
            body={},
            headers={"X-Casulo-Owner-Token": OWNER_TOKEN},
        )
        assert status == 200 and json.loads(raw)["revoked"] is True
        with pytest.raises(urllib.error.HTTPError) as revoked:
            request(gateway.base_url + "/v1/session", headers={"Cookie": cookies})
        assert revoked.value.code == 401
    finally:
        gateway.close()
        runtime.close()
        registry.close()


def test_sessions_and_memory_are_isolated_even_for_same_user(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "registry.sqlite3")
    runtime = FamilyRuntime(
        store=FamilyJobStore(tmp_path / "jobs.sqlite3"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        memory=MockFamilyMemory(tmp_path / "memory.sqlite3"),
        supervisor=FamilySupervisor(DeterministicMockEngine()),
        authorized_contexts=(),
        authorization_callback=registry.is_context_active,
    )
    try:
        first = registry.pair(
            registry.issue_pairing_code("ana").code, "Telefone", source="one"
        )
        second = registry.pair(
            registry.issue_pairing_code("ana").code, "Notebook", source="two"
        )
        job = runtime.submit(first.auth, ChatRequest("segredo da sessão um"))
        assert runtime.wait_terminal(first.auth, job.job_id, timeout=3)[-1].kind == EventKind.COMPLETED
        with pytest.raises(FamilyAuthorizationError):
            runtime.events(second.auth, job.job_id)
        assert len(runtime.memory.recent("ana", session_id=first.auth.session_id)) == 1
        assert runtime.memory.recent("ana", session_id=second.auth.session_id) == ()
    finally:
        runtime.close()
        registry.close()


def test_device_revocation_cancels_active_work_and_denies_reuse(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "registry.sqlite3")
    runtime = FamilyRuntime(
        store=FamilyJobStore(tmp_path / "jobs.sqlite3"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        memory=MockFamilyMemory(tmp_path / "memory.sqlite3"),
        supervisor=FamilySupervisor(DeterministicMockEngine(delay_seconds=0.5)),
        authorized_contexts=(),
        authorization_callback=registry.is_context_active,
    )
    try:
        paired = registry.pair(
            registry.issue_pairing_code("ana").code, "Perdido", source="one"
        )
        job = runtime.submit(paired.auth, ChatRequest("não deve concluir"))
        assert runtime.wait_status(job.job_id, JobStatus.RUNNING, timeout=2)
        assert registry.revoke_device(paired.auth.device_id) == 1
        assert runtime.revoke_device("ana", paired.auth.device_id) == 1
        assert runtime.store.status(job.job_id).value == "CANCELLED"
        with pytest.raises(FamilyAuthorizationError):
            runtime.submit(paired.auth, ChatRequest("reuso negado"))
    finally:
        runtime.close()
        registry.close()


def test_lan_configuration_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="específico"):
        FamilyConfig(
            bind_host="0.0.0.0",
            lan_enabled=True,
            require_device_auth=True,
            approved_network="192.168.1.0/24",
            tls_certfile=Path("cert.pem"),
            tls_keyfile=Path("key.pem"),
        )
    with pytest.raises(ValueError, match="TLS"):
        FamilyConfig(
            bind_host="192.168.1.10",
            lan_enabled=True,
            require_device_auth=True,
            approved_network="192.168.1.0/24",
        )
    accepted = FamilyConfig(
        bind_host="192.168.1.10",
        lan_enabled=True,
        require_device_auth=True,
        approved_network="192.168.1.0/24",
        tls_certfile=Path("cert.pem"),
        tls_keyfile=Path("key.pem"),
    )
    assert accepted.bind_port == 0


def write_test_certificate(root: Path) -> tuple[Path, Path, Path]:
    now = datetime.now(UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path, cert_path, ca_path = root / "key.pem", root / "cert.pem", root / "ca.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    cert_path.write_bytes(cert_bytes)
    ca_path.write_bytes(cert_bytes)
    return cert_path, key_path, ca_path


def test_gateway_serves_pwa_over_verified_https(tmp_path: Path) -> None:
    cert, key, ca = write_test_certificate(tmp_path)
    registry, runtime, gateway = build_secure(tmp_path / "state", tls=(cert, key))
    gateway.start()
    context = ssl.create_default_context(cafile=str(ca))
    try:
        status, headers, html = request(gateway.base_url + "/", context=context)
        assert status == 200 and b"Casulo Family" in html
        assert headers["Content-Security-Policy"].startswith("default-src 'self'")
        status, _, manifest = request(
            gateway.base_url + "/manifest.webmanifest", context=context
        )
        assert status == 200 and json.loads(manifest)["display"] == "standalone"
        paired, (cookie, csrf), _, _ = pair_via_gateway(
            gateway, context=context
        )
        status, _, raw = request(
            gateway.base_url + "/v1/chat",
            method="POST",
            body={"message": "fluxo HTTPS"},
            headers={
                "Cookie": cookie,
                "X-Casulo-CSRF": csrf,
                "Origin": gateway.base_url,
            },
            context=context,
        )
        assert status == 202
        job_id = json.loads(raw)["job_id"]
        status, _, stream = request(
            gateway.base_url + f"/v1/jobs/{job_id}/events",
            headers={"Cookie": cookie},
            context=context,
        )
        assert status == 200 and b'"kind":"COMPLETED"' in stream
        assert paired["user_id"] == "ana"
    finally:
        gateway.close()
        runtime.close()
        registry.close()
