from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path

import pytest

from casulo.family.audit import AuditLog
from casulo.family.config import FamilyConfig
from casulo.family.contracts import AuthContext, ChatRequest, EventKind, FamilyContractError
from casulo.family.gateway import FamilyGateway
from casulo.family.memory import (
    DELETE_ALL_CONFIRMATION,
    FamilyExactEmbedding,
    FamilyRagMemory,
)
from casulo.family.runtime import FamilyRuntime
from casulo.family.scheduler import FamilyJobStore
from casulo.family.security import DeviceRegistry
from casulo.family.supervisor import FamilySupervisor


ROOT = Path(__file__).parents[2]
EMBEDDING_CARD = ROOT / "models" / "first-party" / "casulo-exact-embedding-v1.json"
EMBEDDING_SHA256 = "0876987a6ef2ab29f4a93d0b3947b4b08fd3931466c086a90be1978435d36961"
OWNER_TOKEN = "day5-owner-test-token-with-32-bytes-minimum"
PWA_ROOT = ROOT / "apps" / "casulo-family-pwa"


def memory_at(tmp_path: Path) -> FamilyRagMemory:
    return FamilyRagMemory(
        tmp_path / "memory.sqlite3",
        embedding_card=EMBEDDING_CARD,
        embedding_sha256=EMBEDDING_SHA256,
        chunk_chars=256,
    )


@dataclass(slots=True)
class CapturingEngine:
    mock_only: bool = True
    requests: list[str] = field(default_factory=list)

    def generate(self, request: ChatRequest, cancelled):
        self.requests.append(request.message)
        if not cancelled():
            yield "resposta com contexto local"


def build_runtime(tmp_path: Path, memory: FamilyRagMemory):
    alice = AuthContext("alice", "alice-phone", "alice-session")
    bob = AuthContext("bob", "bob-phone", "bob-session")
    engine = CapturingEngine()
    runtime = FamilyRuntime(
        store=FamilyJobStore(tmp_path / "jobs.sqlite3"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        memory=memory,
        supervisor=FamilySupervisor(engine),
        authorized_contexts=(alice, bob),
        config=FamilyConfig(mock_only=True),
    )
    return runtime, engine, alice, bob


def http_request(
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
    request = urllib.request.Request(url, data=data, method=method, headers=merged)
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        return response.status, response.headers, response.read()


def pair(gateway: FamilyGateway, user_id: str) -> tuple[dict, str, str]:
    _, _, raw = http_request(
        gateway.base_url + "/v1/admin/pairing-codes",
        method="POST",
        body={"user_id": user_id, "role": "family"},
        headers={"X-Casulo-Owner-Token": OWNER_TOKEN},
    )
    code = json.loads(raw)["code"]
    _, headers, raw = http_request(
        gateway.base_url + "/v1/pair",
        method="POST",
        body={"code": code, "device_name": f"Telefone {user_id}"},
    )
    cookies = SimpleCookie()
    for value in headers.get_all("Set-Cookie"):
        cookies.load(value)
    cookie = "; ".join(f"{key}={item.value}" for key, item in cookies.items())
    return json.loads(raw), cookie, cookies["casulo_csrf"].value


def mutation_headers(gateway: FamilyGateway, cookie: str, csrf: str) -> dict[str, str]:
    return {"Cookie": cookie, "X-Casulo-CSRF": csrf, "Origin": gateway.base_url}


def test_embedding_card_is_pinned_and_offline(tmp_path: Path) -> None:
    embedding = FamilyExactEmbedding(EMBEDDING_CARD, EMBEDDING_SHA256)
    assert embedding.embed("memória local") == embedding.embed("memória local")
    assert embedding.diagnostics() == {
        "model_id": "casulo-exact-embedding-v1",
        "dimensions": 64,
        "card_sha256": EMBEDDING_SHA256,
        "network_required": False,
        "weights_required": False,
    }
    with pytest.raises(FamilyContractError, match="hash"):
        FamilyExactEmbedding(EMBEDDING_CARD, "0" * 64)


def test_adversarial_two_user_isolation_and_acl(tmp_path: Path) -> None:
    memory = memory_at(tmp_path)
    alice = AuthContext("alice", "alice-phone", "alice-session")
    bob = AuthContext("bob", "bob-phone", "bob-session")
    alice_secret = "A senha mnemônica da horta é jacarandá azul 7319."
    bob_note = "Bob prefere café sem açúcar e caminhadas curtas."
    try:
        alice_doc = memory.ingest(
            alice, origin="note://alice/private", content=alice_secret
        )
        bob_doc = memory.ingest(bob, origin="note://bob/preferences", content=bob_note)
        alice_hits = memory.retrieve(alice, "qual é a senha da horta?")
        assert alice_hits and alice_hits[0].citation.document_id == alice_doc["document_id"]
        assert "jacarandá" in alice_hits[0].text

        for hostile_query in (
            alice_secret,
            "' OR user_id = 'alice' --",
            '" UNION SELECT text FROM rag_chunks --',
        ):
            bob_hits = memory.retrieve(bob, hostile_query, limit=8)
            assert all(hit.citation.document_id == bob_doc["document_id"] for hit in bob_hits)
            assert all("jacarandá" not in hit.text for hit in bob_hits)

        with pytest.raises(KeyError):
            memory.delete_document(bob, alice_doc["document_id"])
        assert len(memory.list_documents(alice)) == 1
        assert len(memory.list_documents(bob)) == 1
        assert memory.verify_namespace(alice)["status"] == "PASS"
        assert memory.verify_namespace(bob)["status"] == "PASS"
    finally:
        memory.close()


def test_reindex_delete_and_secure_content_purge_are_verifiable(tmp_path: Path) -> None:
    memory = memory_at(tmp_path)
    alice = AuthContext("alice", "alice-phone", "alice-session")
    marker = "SEGREDO_EXCLUSAO_9f44c05a"
    try:
        created = memory.ingest(
            alice,
            origin="note://alice/delete-me",
            content=f"Documento temporário contendo {marker} e dados descartáveis.",
        )
        with memory._lock, memory._connection:
            memory._connection.execute(
                "UPDATE rag_chunks SET embedding_sha256 = ? WHERE user_id = ?",
                ("0" * 64, alice.user_id),
            )
            memory._connection.execute(
                "DELETE FROM rag_chunks_fts WHERE user_id = ?", (alice.user_id,)
            )
        assert memory.verify_namespace(alice)["status"] == "FAIL"
        reindexed = memory.reindex(alice)
        assert reindexed["reindexed_chunks"] == 1
        assert memory.verify_namespace(alice)["status"] == "PASS"
        assert memory.retrieve(alice, marker)

        deleted = memory.delete_document(alice, created["document_id"])
        assert deleted["deleted"] is True
        assert memory.retrieve(alice, marker) == ()
        assert memory.list_documents(alice) == ()
        assert memory.verify_namespace(alice)["status"] == "PASS"
    finally:
        memory.close()
    database_bytes = (tmp_path / "memory.sqlite3").read_bytes()
    wal = tmp_path / "memory.sqlite3-wal"
    assert marker.encode("utf-8") not in database_bytes
    assert not wal.exists() or marker.encode("utf-8") not in wal.read_bytes()


def test_delete_all_only_purges_authenticated_namespace(tmp_path: Path) -> None:
    memory = memory_at(tmp_path)
    alice = AuthContext("alice", "alice-phone", "alice-session")
    bob = AuthContext("bob", "bob-phone", "bob-session")
    try:
        memory.ingest(alice, origin="note://alice/a", content="conteúdo exclusivo Alice")
        memory.ingest(bob, origin="note://bob/b", content="conteúdo exclusivo Bob")
        with pytest.raises(FamilyContractError, match="confirmação"):
            memory.delete_all(alice, "DELETE")
        result = memory.delete_all(alice, DELETE_ALL_CONFIRMATION)
        assert result["deleted_documents"] == 1
        assert memory.list_documents(alice) == ()
        assert len(memory.list_documents(bob)) == 1
        assert memory.retrieve(bob, "conteúdo exclusivo")
    finally:
        memory.close()


def test_runtime_injects_bounded_rag_and_emits_internal_citations(tmp_path: Path) -> None:
    memory = memory_at(tmp_path)
    runtime, engine, alice, bob = build_runtime(tmp_path, memory)
    marker = "orquídea âmbar 4821"
    try:
        memory.ingest(
            alice,
            origin="note://alice/rag",
            content=f"A lembrança confirmada de Alice é {marker}.",
        )
        alice_job = runtime.submit(alice, ChatRequest("qual é a lembrança confirmada?"))
        alice_events = runtime.wait_terminal(alice, alice_job.job_id, timeout=3)
        accepted = alice_events[0]
        assert accepted.kind == EventKind.ACCEPTED
        assert accepted.payload["rag"]["hits"] == 1
        assert accepted.payload["rag"]["citations"][0]["citation_id"].startswith("cite-")
        assert "excerpt" not in accepted.payload["rag"]["citations"][0]
        assert marker in engine.requests[0]
        assert "Contexto local não confiável" in engine.requests[0]
        jobs_bytes = (tmp_path / "jobs.sqlite3").read_bytes()
        assert marker.encode("utf-8") not in jobs_bytes

        bob_job = runtime.submit(bob, ChatRequest(marker))
        bob_events = runtime.wait_terminal(bob, bob_job.job_id, timeout=3)
        assert bob_events[0].payload["rag"]["hits"] == 0
        assert marker in engine.requests[1]
        assert "note://alice/rag" not in engine.requests[1]
        audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert marker not in audit
    finally:
        runtime.close()


def test_gateway_memory_api_is_authenticated_scoped_and_redacted(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "devices.sqlite3")
    memory = memory_at(tmp_path)
    config = FamilyConfig(
        mock_only=True,
        require_device_auth=True,
        max_request_bytes=262_144,
    )
    runtime = FamilyRuntime(
        store=FamilyJobStore(tmp_path / "jobs.sqlite3"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        memory=memory,
        supervisor=FamilySupervisor(CapturingEngine()),
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
    gateway.start()
    marker = "MEMORIA_GATEWAY_PRIVADA_7712"
    try:
        _, alice_cookie, alice_csrf = pair(gateway, "alice")
        _, bob_cookie, bob_csrf = pair(gateway, "bob")
        with pytest.raises(urllib.error.HTTPError) as forged_namespace:
            http_request(
                gateway.base_url + "/v1/memory/documents",
                method="POST",
                body={
                    "user_id": "bob",
                    "origin": "note://alice/api",
                    "content": marker,
                },
                headers=mutation_headers(gateway, alice_cookie, alice_csrf),
            )
        assert forged_namespace.value.code == 400

        content_hash = hashlib.sha256(marker.encode("utf-8")).hexdigest()
        status, _, raw = http_request(
            gateway.base_url + "/v1/memory/documents",
            method="POST",
            body={
                "origin": "note://alice/api",
                "content": marker,
                "sha256": content_hash,
            },
            headers=mutation_headers(gateway, alice_cookie, alice_csrf),
        )
        assert status == 201
        document_id = json.loads(raw)["document_id"]

        status, _, raw = http_request(
            gateway.base_url + "/v1/memory/search",
            method="POST",
            body={"query": marker},
            headers=mutation_headers(gateway, bob_cookie, bob_csrf),
        )
        assert status == 200 and json.loads(raw)["count"] == 0
        with pytest.raises(urllib.error.HTTPError) as cross_delete:
            http_request(
                gateway.base_url + f"/v1/memory/documents/{document_id}",
                method="DELETE",
                headers=mutation_headers(gateway, bob_cookie, bob_csrf),
            )
        assert cross_delete.value.code == 404

        status, _, raw = http_request(
            gateway.base_url + "/v1/memory/search",
            method="POST",
            body={"query": marker},
            headers=mutation_headers(gateway, alice_cookie, alice_csrf),
        )
        assert status == 200 and json.loads(raw)["count"] == 1
        status, _, raw = http_request(
            gateway.base_url + "/v1/memory/reindex",
            method="POST",
            body={},
            headers=mutation_headers(gateway, alice_cookie, alice_csrf),
        )
        assert status == 200 and json.loads(raw)["reindexed_chunks"] == 1
        status, _, raw = http_request(
            gateway.base_url + f"/v1/memory/documents/{document_id}",
            method="DELETE",
            headers=mutation_headers(gateway, alice_cookie, alice_csrf),
        )
        assert status == 200 and json.loads(raw)["deleted"] is True
        status, _, raw = http_request(
            gateway.base_url + "/v1/memory/verify",
            headers={"Cookie": alice_cookie},
        )
        assert status == 200 and json.loads(raw)["status"] == "PASS"
        audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert marker not in audit
    finally:
        gateway.close()
        runtime.close()
        registry.close()


def test_ingest_hash_and_bounds_fail_closed(tmp_path: Path) -> None:
    memory = memory_at(tmp_path)
    alice = AuthContext("alice", "alice-phone", "alice-session")
    try:
        with pytest.raises(FamilyContractError, match="hash"):
            memory.ingest(
                alice,
                origin="note://alice/hash",
                content="conteúdo",
                expected_sha256="0" * 64,
            )
        with pytest.raises(FamilyContractError, match="limite"):
            memory.ingest(
                alice,
                origin="note://alice/large",
                content="x" * (memory.max_document_chars + 1),
            )
        with pytest.raises(FamilyContractError, match="query"):
            memory.retrieve(alice, "x" * 2_049)
    finally:
        memory.close()
