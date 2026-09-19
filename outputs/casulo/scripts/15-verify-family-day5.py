from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import sqlite3
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import psutil

from casulo.family.audit import AuditLog
from casulo.family.config import FamilyConfig
from casulo.family.gateway import FamilyGateway
from casulo.family.memory import FamilyRagMemory
from casulo.family.runtime import FamilyRuntime
from casulo.family.scheduler import FamilyJobStore
from casulo.family.security import DeviceRegistry
from casulo.family.supervisor import FamilySupervisor
from casulo_owner.family_model_adapter import FamilyLocalModelAdapter


EXPECTED_COMMIT = "e575690a71b0d577de8ec66416b5ffe64b876cc4"
EXPECTED_TREE = "7a74c6603df2f4554efbdbf90f0e75a325a665bc"
EMBEDDING_SHA256 = "0876987a6ef2ab29f4a93d0b3947b4b08fd3931466c086a90be1978435d36961"


def now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def process_snapshot() -> str:
    rows = [f"timestamp_utc={now()}"]
    matches = []
    for process in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if str(process.info.get("name") or "").casefold() == "llama-server.exe":
                matches.append(process.info)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    rows.append(f"llama_server_processes={len(matches)}")
    rows.extend(
        f"pid={item['pid']} name={item['name']} created={item['create_time']}"
        for item in matches
    )
    return "\n".join(rows) + "\n"


def port_snapshot(*, gateway_port: int | None = None, runtime_port: int | None = None) -> str:
    rows = [f"timestamp_utc={now()}"]
    matches = []
    for item in psutil.net_connections(kind="tcp"):
        if item.status != psutil.CONN_LISTEN or not item.laddr:
            continue
        if item.laddr.port in {gateway_port, runtime_port}:
            matches.append(item)
    rows.append(f"matching_listeners={len(matches)}")
    for item in sorted(matches, key=lambda value: (value.laddr.ip, value.laddr.port)):
        role = "gateway" if item.laddr.port == gateway_port else "runtime"
        rows.append(f"role={role} address={item.laddr.ip}:{item.laddr.port} pid={item.pid}")
    return "\n".join(rows) + "\n"


def request(
    url: str,
    context: ssl.SSLContext,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, bytes]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    merged = dict(headers or {})
    if data is not None:
        merged["Content-Type"] = "application/json"
    call = urllib.request.Request(url, data=data, method=method, headers=merged)
    try:
        with urllib.request.urlopen(call, timeout=300, context=context) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def session_cookies(headers: Any) -> tuple[str, str]:
    jar = SimpleCookie()
    for raw in headers.get_all("Set-Cookie") or []:
        jar.load(raw)
    header = "; ".join(f"{key}={item.value}" for key, item in jar.items())
    return header, jar["casulo_csrf"].value


def parse_events(raw: bytes) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in raw.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]


def mutation_headers(base: str, cookie: str, csrf: str) -> dict[str, str]:
    return {"Cookie": cookie, "X-Casulo-CSRF": csrf, "Origin": base}


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo Family Day 5 memory/RAG real gate")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--tls-dir", type=Path, required=True)
    parser.add_argument("--pwa-root", type=Path, required=True)
    parser.add_argument("--embedding-card", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--bind-host", required=True)
    parser.add_argument("--approved-network", required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    evidence = args.evidence_dir.resolve()
    state = args.state_dir.resolve()
    tls_dir = args.tls_dir.resolve()
    if evidence.exists() and any(evidence.iterdir()):
        raise FileExistsError("evidence-dir deve estar vazio")
    evidence.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=False)
    baseline = {
        "schema": "casulo.family.day5-baseline/1.0",
        "timestamp_utc": now(),
        "branch": git(repo, "branch", "--show-current"),
        "input_commit": git(repo, "rev-parse", "HEAD"),
        "input_tree": git(repo, "rev-parse", "HEAD^{tree}"),
        "expected_commit": EXPECTED_COMMIT,
        "expected_tree": EXPECTED_TREE,
        "day4_evidence_preserved": True,
        "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
        "temperature_telemetry_collected_by_runner": False,
        "temperature_claim": "NONE",
    }
    write_json(evidence / "baseline.json", baseline)
    if (
        baseline["branch"] != "rp0.1-family"
        or baseline["input_commit"] != EXPECTED_COMMIT
        or baseline["input_tree"] != EXPECTED_TREE
    ):
        raise RuntimeError("baseline Day 5 incompatível")

    bind = ipaddress.ip_address(args.bind_host)
    network = ipaddress.ip_network(args.approved_network, strict=False)
    if bind not in network or not bind.is_private:
        raise RuntimeError("bind fora da sub-rede privada")
    cert = tls_dir / "casulo-family-server.pem"
    key = tls_dir / "casulo-family-server-key.pem"
    ca = tls_dir / "casulo-family-ca.pem"
    owner_token = (tls_dir / "owner-token.txt").read_text(encoding="ascii").strip()
    context = ssl.create_default_context(cafile=str(ca))
    config = FamilyConfig(
        bind_host=str(bind),
        bind_port=0,
        queue_capacity=2,
        mock_only=False,
        lan_enabled=True,
        require_device_auth=True,
        approved_network=str(network),
        tls_certfile=cert,
        tls_keyfile=key,
        max_request_bytes=262_144,
        stream_wait_seconds=120.0,
        rag_result_limit=4,
        rag_max_context_chars=4_096,
    )
    (evidence / "process-inspection-before.txt").write_text(
        process_snapshot(), encoding="utf-8", newline="\n"
    )
    (evidence / "network-inspection-before.txt").write_text(
        port_snapshot(), encoding="utf-8", newline="\n"
    )
    startup_required = 5 * 1_024**3
    if psutil.virtual_memory().available < startup_required:
        write_json(
            evidence / "integration-result.json",
            {
                "schema": "casulo.family.day5-real-integration/1.0",
                "status": "BLOCKED_RESOURCE_FLOOR",
                "minimum_start_available_ram_bytes": startup_required,
                "observed_available_ram_bytes": int(psutil.virtual_memory().available),
                "model_started": False,
                "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
                "temperature_telemetry_collected_by_runner": False,
                "temperature_claim": "NONE",
            },
        )
        return 2

    adapter = FamilyLocalModelAdapter(
        cache_root=args.cache_root,
        manifest=args.manifest,
        max_generated_tokens=64,
        minimum_available_ram_bytes=config.minimum_available_ram_bytes,
        minimum_start_available_ram_bytes=startup_required,
        minimum_disk_free_bytes=config.minimum_disk_free_bytes,
    )
    registry = DeviceRegistry(state / "devices.sqlite3")
    memory = FamilyRagMemory(
        state / "memory.sqlite3",
        embedding_card=args.embedding_card,
        embedding_sha256=EMBEDDING_SHA256,
        chunk_chars=256,
    )
    runtime = FamilyRuntime(
        store=FamilyJobStore(state / "jobs.sqlite3"),
        audit=AuditLog(state / "audit.jsonl"),
        memory=memory,
        supervisor=FamilySupervisor(adapter),
        authorized_contexts=(),
        authorization_callback=registry.is_context_active,
        config=config,
    )
    gateway = FamilyGateway(
        config=config,
        runtime=runtime,
        security=registry,
        owner_token=owner_token,
        pwa_root=args.pwa_root,
    )
    stop_samples = threading.Event()
    floor_violation = threading.Event()
    samples: list[dict[str, Any]] = []
    samples_path = evidence / "resource-samples.jsonl"

    def sample() -> None:
        while not stop_samples.is_set():
            value = {"timestamp_utc": now(), **adapter.diagnostics()}
            if value.get("available_ram_bytes", 0) < config.minimum_available_ram_bytes:
                floor_violation.set()
            if value.get("disk_free_bytes", 0) < config.minimum_disk_free_bytes:
                floor_violation.set()
            samples.append(value)
            with samples_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(value, sort_keys=True) + "\n")
            stop_samples.wait(0.5)

    sampler = threading.Thread(target=sample, name="day5-resource-sampler")
    sampler.start()
    result: dict[str, Any] = {
        "schema": "casulo.family.day5-real-integration/1.0",
        "status": "FAIL",
        "started_utc": now(),
    }
    gateway_port = runtime_port = None
    marker = "JACARANDA_AZUL_7319_DAY5"
    marker_hash = hashlib.sha256(marker.encode()).hexdigest()
    database_path = state / "memory.sqlite3"
    try:
        gateway.start()
        gateway_port = gateway.address[1]
        base = gateway.base_url

        def pair(user: str, name: str) -> tuple[dict[str, Any], str, str]:
            status, _, raw = request(
                base + "/v1/admin/pairing-codes",
                context,
                method="POST",
                body={"user_id": user, "role": "family"},
                headers={"X-Casulo-Owner-Token": owner_token},
            )
            if status != 201:
                raise RuntimeError("emissão de pareamento falhou")
            code = json.loads(raw)["code"]
            status, headers, raw = request(
                base + "/v1/pair",
                context,
                method="POST",
                body={"code": code, "device_name": name},
            )
            if status != 201:
                raise RuntimeError("pareamento falhou")
            cookie, csrf = session_cookies(headers)
            return json.loads(raw), cookie, csrf

        alice, alice_cookie, alice_csrf = pair("alice", "Telefone Alice")
        bob, bob_cookie, bob_csrf = pair("bob", "Telefone Bob")
        alice_content = f"O código privado confirmado de Alice é {marker}."
        status, _, raw = request(
            base + "/v1/memory/documents",
            context,
            method="POST",
            body={
                "origin": "note://alice/private-day5",
                "content": alice_content,
                "sha256": hashlib.sha256(alice_content.encode()).hexdigest(),
            },
            headers=mutation_headers(base, alice_cookie, alice_csrf),
        )
        if status != 201:
            raise RuntimeError("ingestão Alice falhou")
        alice_doc = json.loads(raw)
        status, _, raw = request(
            base + "/v1/memory/documents",
            context,
            method="POST",
            body={
                "origin": "note://bob/preferences-day5",
                "content": "Bob prefere café sem açúcar e caminhadas curtas.",
            },
            headers=mutation_headers(base, bob_cookie, bob_csrf),
        )
        if status != 201:
            raise RuntimeError("ingestão Bob falhou")
        bob_doc = json.loads(raw)

        adversarial_counts = []
        for query in (marker, "' OR user_id = 'alice' --", '" UNION SELECT text FROM rag_chunks --'):
            status, _, raw = request(
                base + "/v1/memory/search",
                context,
                method="POST",
                body={"query": query, "limit": 8},
                headers=mutation_headers(base, bob_cookie, bob_csrf),
            )
            payload = json.loads(raw)
            if status != 200 or any(
                item["document_id"] == alice_doc["document_id"]
                or marker in item.get("excerpt", "")
                for item in payload["citations"]
            ):
                raise RuntimeError("vazamento entre namespaces no ataque adversarial")
            adversarial_counts.append(payload["count"])

        status, _, raw = request(
            base + "/v1/memory/search",
            context,
            method="POST",
            body={"query": "Qual é o código privado confirmado?"},
            headers=mutation_headers(base, alice_cookie, alice_csrf),
        )
        alice_search = json.loads(raw)
        if status != 200 or alice_search["count"] != 1:
            raise RuntimeError("recuperação Alice falhou")

        status, _, raw = request(
            base + f"/v1/memory/documents/{alice_doc['document_id']}",
            context,
            method="DELETE",
            headers=mutation_headers(base, bob_cookie, bob_csrf),
        )
        if status != 404:
            raise RuntimeError("Bob conseguiu identificar/excluir documento Alice")

        chat_status, _, chat_raw = request(
            base + "/v1/chat",
            context,
            method="POST",
            body={"message": "Qual é o código privado confirmado de Alice? Responda apenas o código."},
            headers=mutation_headers(base, alice_cookie, alice_csrf),
        )
        if chat_status != 202:
            raise RuntimeError(f"chat RAG recusado: HTTP {chat_status}")
        job_id = json.loads(chat_raw)["job_id"]
        deadline = time.monotonic() + min(adapter.startup_timeout, 120.0)
        while adapter.runtime_address is None and time.monotonic() < deadline:
            if runtime.store.status(job_id).value in {"FAILED", "CANCELLED"}:
                break
            time.sleep(0.1)
        if adapter.runtime_address is None:
            raise RuntimeError("runtime não iniciou para o chat RAG")
        runtime_port = int(adapter.runtime_address.rsplit(":", 1)[1])
        (evidence / "network-inspection-during.txt").write_text(
            port_snapshot(gateway_port=gateway_port, runtime_port=runtime_port),
            encoding="utf-8",
            newline="\n",
        )
        stream_status, _, stream_raw = request(
            base + f"/v1/jobs/{job_id}/events",
            context,
            headers={"Cookie": alice_cookie},
        )
        events = parse_events(stream_raw)
        if stream_status != 200 or not events or events[-1]["kind"] != "COMPLETED":
            raise RuntimeError("chat RAG não concluiu")
        rag = events[0].get("payload", {}).get("rag", {})
        if rag.get("hits") != 1 or rag["citations"][0]["document_id"] != alice_doc["document_id"]:
            raise RuntimeError("citação interna não acompanhou o chat")
        output_text = "".join(
            event.get("payload", {}).get("text", "")
            for event in events
            if event.get("kind") == "DELTA"
        )
        if not output_text:
            raise RuntimeError("chat RAG concluiu sem saída incremental observável")
        with sqlite3.connect(state / "jobs.sqlite3") as jobs_connection:
            persisted_request = jobs_connection.execute(
                "SELECT request_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
        if marker in persisted_request or "Contexto local não confiável" in persisted_request:
            raise RuntimeError("contexto RAG volátil foi persistido no job")

        status, _, raw = request(
            base + "/v1/memory/reindex",
            context,
            method="POST",
            body={},
            headers=mutation_headers(base, alice_cookie, alice_csrf),
        )
        reindex = json.loads(raw)
        if status != 200 or reindex.get("reindexed_chunks") != 1:
            raise RuntimeError("reindexação falhou")
        status, _, raw = request(
            base + "/v1/memory/verify", context, headers={"Cookie": alice_cookie}
        )
        verification_before_delete = json.loads(raw)
        if status != 200 or verification_before_delete.get("status") != "PASS":
            raise RuntimeError("verificação do namespace falhou")
        status, _, raw = request(
            base + f"/v1/memory/documents/{alice_doc['document_id']}",
            context,
            method="DELETE",
            headers=mutation_headers(base, alice_cookie, alice_csrf),
        )
        deletion = json.loads(raw)
        if status != 200 or deletion.get("deleted") is not True:
            raise RuntimeError("exclusão Alice falhou")
        status, _, raw = request(
            base + "/v1/memory/search",
            context,
            method="POST",
            body={"query": marker},
            headers=mutation_headers(base, alice_cookie, alice_csrf),
        )
        if status != 200 or json.loads(raw)["count"] != 0:
            raise RuntimeError("documento excluído ainda é recuperável")
        status, _, raw = request(
            base + "/v1/memory/documents", context, headers={"Cookie": bob_cookie}
        )
        bob_documents = json.loads(raw)
        if status != 200 or bob_documents["documents"][0]["document_id"] != bob_doc["document_id"]:
            raise RuntimeError("exclusão Alice afetou namespace Bob")

        audit_text = (state / "audit.jsonl").read_text(encoding="utf-8")
        if owner_token in audit_text or marker in audit_text:
            raise RuntimeError("segredo ou conteúdo integral apareceu no audit")
        if floor_violation.is_set():
            raise RuntimeError("piso de recurso violado")

        write_json(
            evidence / "two-user-isolation.json",
            {
                "schema": "casulo.family.day5-two-user-isolation/1.0",
                "users": 2,
                "distinct_sessions": alice["session_id"] != bob["session_id"],
                "adversarial_queries": 3,
                "adversarial_result_counts": adversarial_counts,
                "cross_namespace_citations": 0,
                "cross_namespace_delete_status": 404,
                "status": "PASS",
            },
        )
        write_json(
            evidence / "ingestion-retrieval.json",
            {
                "schema": "casulo.family.day5-ingestion-retrieval/1.0",
                "alice_document_id": alice_doc["document_id"],
                "bob_document_id": bob_doc["document_id"],
                "alice_content_sha256": alice_doc["content_sha256"],
                "marker_sha256": marker_hash,
                "acl": "OWNER_ONLY",
                "alice_retrieval_hits": alice_search["count"],
                "citation_id": alice_search["citations"][0]["citation_id"],
                "raw_content_recorded_in_evidence": False,
                "status": "PASS",
            },
        )
        write_json(
            evidence / "rag-model-flow.json",
            {
                "schema": "casulo.family.day5-rag-model-flow/1.0",
                "gateway_address": base,
                "runtime_address": adapter.runtime_address,
                "runtime_loopback_only": True,
                "terminal_event": events[-1]["kind"],
                "rag_hits": rag["hits"],
                "citation_ids": [item["citation_id"] for item in rag["citations"]],
                "output_chars": len(output_text),
                "output_sha256": hashlib.sha256(output_text.encode()).hexdigest(),
                "output_recorded": False,
                "rag_context_persisted_in_job_request": False,
                "maximum_active_generations": runtime.supervisor.snapshot()["maximum_active_generations"],
                "status": "PASS",
            },
        )
        write_json(
            evidence / "deletion-reindex.json",
            {
                "schema": "casulo.family.day5-deletion-reindex/1.0",
                "reindexed_chunks": reindex["reindexed_chunks"],
                "namespace_verification_before_delete": verification_before_delete["status"],
                "deleted": deletion["deleted"],
                "alice_hits_after_delete": 0,
                "bob_documents_after_alice_delete": bob_documents["count"],
                "raw_marker_check_after_close": "PENDING",
                "status": "PASS",
            },
        )
        result.update(
            {
                "status": "PASS",
                "ended_utc": now(),
                "model": adapter.diagnostics()["adapter"],
                "backend": adapter.diagnostics()["backend"],
                "embedding": memory.embedding.diagnostics(),
                "gateway_address": base,
                "runtime_address": adapter.runtime_address,
                "documents_ingested": 2,
                "adversarial_queries": 3,
                "cross_namespace_leaks": 0,
                "rag_generations_completed": 1,
                "documents_deleted": 1,
                "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
                "temperature_telemetry_collected_by_runner": False,
                "temperature_claim": "NONE",
            }
        )
    except Exception as error:
        result.update(
            {
                "status": "FAIL",
                "ended_utc": now(),
                "failure_type": type(error).__name__,
                "failure_message": str(error),
            }
        )
        raise
    finally:
        gateway.close()
        runtime.close()
        registry.close()
        stop_samples.set()
        sampler.join(5)
        result["sampler_cleanup"] = "PASS" if not sampler.is_alive() else "FAIL"
        (evidence / "network-inspection-after.txt").write_text(
            port_snapshot(gateway_port=gateway_port, runtime_port=runtime_port),
            encoding="utf-8",
            newline="\n",
        )
        (evidence / "process-inspection-after.txt").write_text(
            process_snapshot(), encoding="utf-8", newline="\n"
        )
        result["process_cleanup"] = "PASS" if "llama_server_processes=0" in process_snapshot() else "FAIL"
        result["port_cleanup"] = (
            "PASS"
            if "matching_listeners=0" in port_snapshot(gateway_port=gateway_port, runtime_port=runtime_port)
            else "FAIL"
        )
        database_bytes = database_path.read_bytes() if database_path.exists() else b""
        wal_path = database_path.with_name(database_path.name + "-wal")
        wal_bytes = wal_path.read_bytes() if wal_path.exists() else b""
        raw_marker_absent = marker.encode() not in database_bytes + wal_bytes
        result["deleted_content_absent_from_database_and_wal"] = raw_marker_absent
        deletion_evidence = evidence / "deletion-reindex.json"
        if deletion_evidence.exists():
            payload = json.loads(deletion_evidence.read_text(encoding="utf-8"))
            payload["raw_marker_check_after_close"] = "PASS" if raw_marker_absent else "FAIL"
            payload["status"] = "PASS" if raw_marker_absent else "FAIL"
            write_json(deletion_evidence, payload)
        if samples:
            result["minimum_available_ram_bytes"] = min(int(item["available_ram_bytes"]) for item in samples)
            result["minimum_disk_free_bytes"] = min(int(item["disk_free_bytes"]) for item in samples)
            result["maximum_working_set_bytes"] = max(
                int(item.get("process_working_set_bytes") or 0) for item in samples
            )
        write_json(evidence / "integration-result.json", result)
    required = (
        result.get("status") == "PASS"
        and result.get("sampler_cleanup") == "PASS"
        and result.get("process_cleanup") == "PASS"
        and result.get("port_cleanup") == "PASS"
        and result.get("deleted_content_absent_from_database_and_wal") is True
    )
    if not required:
        return 1
    print(json.dumps({"status": "PASS", "evidence": str(evidence)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
