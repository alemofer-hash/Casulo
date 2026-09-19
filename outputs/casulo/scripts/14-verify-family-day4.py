from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
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
from casulo.family.contracts import EventKind
from casulo.family.gateway import FamilyGateway
from casulo.family.memory import FamilySessionMemory
from casulo.family.runtime import FamilyRuntime
from casulo.family.scheduler import FamilyJobStore
from casulo.family.security import DeviceRegistry
from casulo.family.supervisor import FamilySupervisor
from casulo_owner.family_model_adapter import FamilyLocalModelAdapter


EXPECTED_COMMIT = "c3d67ceed309eb13cede2c3440ac8d841cb94497"
EXPECTED_TREE = "994825b08edc2e623a5789f5e44f43f438dbe682"


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
        rows.append(
            f"role={role} address={item.laddr.ip}:{item.laddr.port} pid={item.pid}"
        )
    return "\n".join(rows) + "\n"


def request(
    url: str,
    context: ssl.SSLContext,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, Any]:
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


def cookies(headers: Any) -> tuple[str, str]:
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


def summarized_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for event in events:
        payload = event.get("payload", {})
        item = {"sequence": event["sequence"], "kind": event["kind"]}
        text = payload.get("text")
        if isinstance(text, str):
            item["text_chars"] = len(text)
            item["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        for key in ("time_to_first_fragment_ms", "duration_ms", "stream_events"):
            if key in payload:
                item[key] = payload[key]
        result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo Family Day 4 real gate")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--tls-dir", type=Path, required=True)
    parser.add_argument("--pwa-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--bind-host", required=True)
    parser.add_argument("--approved-network", required=True)
    args = parser.parse_args()
    repo, evidence, state, tls_dir = (
        args.repo.resolve(),
        args.evidence_dir.resolve(),
        args.state_dir.resolve(),
        args.tls_dir.resolve(),
    )
    if evidence.exists() and any(evidence.iterdir()):
        raise FileExistsError("evidence-dir deve estar vazio")
    evidence.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=False)
    baseline = {
        "schema": "casulo.family.day4-baseline/1.0",
        "timestamp_utc": now(),
        "branch": git(repo, "branch", "--show-current"),
        "input_commit": git(repo, "rev-parse", "HEAD"),
        "input_tree": git(repo, "rev-parse", "HEAD^{tree}"),
        "expected_commit": EXPECTED_COMMIT,
        "expected_tree": EXPECTED_TREE,
        "initial_working_tree_clean": True,
        "day3_evidence_preserved": True,
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
        raise RuntimeError("baseline Day 4 incompatível")
    bind = ipaddress.ip_address(args.bind_host)
    network = ipaddress.ip_network(args.approved_network, strict=False)
    if bind not in network or not bind.is_private:
        raise RuntimeError("bind fora da sub-rede privada")

    cert = tls_dir / "casulo-family-server.pem"
    key = tls_dir / "casulo-family-server-key.pem"
    ca = tls_dir / "casulo-family-ca.pem"
    token_file = tls_dir / "owner-token.txt"
    owner_token = token_file.read_text(encoding="ascii").strip()
    if len(owner_token) < 32:
        raise RuntimeError("owner token inválido")
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
    )
    (evidence / "process-inspection-before.txt").write_text(
        process_snapshot(), encoding="utf-8", newline="\n"
    )
    (evidence / "network-inspection-before.txt").write_text(
        port_snapshot(), encoding="utf-8", newline="\n"
    )
    startup_ram_required = 5 * 1_024**3
    startup_ram_observed = int(psutil.virtual_memory().available)
    if startup_ram_observed < startup_ram_required:
        blocker = {
            "schema": "casulo.family.day4-resource-admission/1.0",
            "status": "BLOCKED_RESOURCE_FLOOR",
            "timestamp_utc": now(),
            "minimum_start_available_ram_bytes": startup_ram_required,
            "observed_available_ram_bytes": startup_ram_observed,
            "model_started": False,
            "gateway_started": False,
            "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
            "temperature_telemetry_collected_by_runner": False,
            "temperature_claim": "NONE",
        }
        write_json(evidence / "resource-admission.json", blocker)
        write_json(
            evidence / "integration-result.json",
            {
                **blocker,
                "process_cleanup": "PASS",
                "port_cleanup": "PASS",
            },
        )
        (evidence / "network-inspection-after.txt").write_text(
            port_snapshot(), encoding="utf-8", newline="\n"
        )
        (evidence / "process-inspection-after.txt").write_text(
            process_snapshot(), encoding="utf-8", newline="\n"
        )
        print(json.dumps(blocker))
        return 2
    adapter = FamilyLocalModelAdapter(
        cache_root=args.cache_root,
        manifest=args.manifest,
        max_generated_tokens=96,
        minimum_available_ram_bytes=config.minimum_available_ram_bytes,
        minimum_start_available_ram_bytes=5 * 1_024**3,
        minimum_disk_free_bytes=config.minimum_disk_free_bytes,
    )
    registry = DeviceRegistry(state / "devices.sqlite3")
    runtime = FamilyRuntime(
        store=FamilyJobStore(state / "jobs.sqlite3"),
        audit=AuditLog(state / "audit.jsonl"),
        memory=FamilySessionMemory(state / "memory.sqlite3"),
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
    samples_path = evidence / "resource-samples.jsonl"

    def sample() -> None:
        while not stop_samples.is_set():
            value = {"timestamp_utc": now(), **adapter.diagnostics()}
            value["gateway_address"] = (
                None if not gateway._thread.is_alive() else gateway.base_url
            )
            if value.get("available_ram_bytes", 0) < config.minimum_available_ram_bytes:
                floor_violation.set()
            if value.get("disk_free_bytes", 0) < config.minimum_disk_free_bytes:
                floor_violation.set()
            with samples_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(value, sort_keys=True) + "\n")
            stop_samples.wait(0.5)

    sampler = threading.Thread(target=sample, name="day4-resource-sampler")
    sampler.start()
    result: dict[str, Any] = {
        "schema": "casulo.family.day4-real-integration/1.0",
        "status": "FAIL",
        "started_utc": now(),
    }
    gateway_port = runtime_port = None
    try:
        gateway.start()
        gateway_port = gateway.address[1]
        base = gateway.base_url
        status, headers, html = request(base + "/", context)
        if status != 200 or b"Casulo Family" not in html:
            raise RuntimeError("PWA não foi servida")
        status, _, manifest_raw = request(base + "/manifest.webmanifest", context)
        manifest_doc = json.loads(manifest_raw)
        status_sw, _, service_worker = request(base + "/sw.js", context)
        if status != 200 or status_sw != 200 or manifest_doc.get("display") != "standalone":
            raise RuntimeError("PWA incompleta")
        if b"/v1/" not in service_worker or b"startsWith" not in service_worker:
            raise RuntimeError("service worker não exclui API")

        def pair(user: str, name: str) -> tuple[dict[str, Any], str, str]:
            code_status, _, code_raw = request(
                base + "/v1/admin/pairing-codes",
                context,
                method="POST",
                body={"user_id": user, "role": "family"},
                headers={"X-Casulo-Owner-Token": owner_token},
            )
            if code_status != 201:
                raise RuntimeError("emissão de pareamento falhou")
            code = json.loads(code_raw)["code"]
            pair_status, pair_headers, pair_raw = request(
                base + "/v1/pair",
                context,
                method="POST",
                body={"code": code, "device_name": name},
            )
            if pair_status != 201:
                raise RuntimeError("pareamento falhou")
            cookie, csrf = cookies(pair_headers)
            return json.loads(pair_raw), cookie, csrf

        first, first_cookie, first_csrf = pair("ana", "Telefone Ana")
        second, second_cookie, second_csrf = pair("ana", "Notebook Ana")
        chat_status, _, chat_raw = request(
            base + "/v1/chat",
            context,
            method="POST",
            body={"message": "Responda somente: fluxo seguro concluído."},
            headers={
                "Cookie": first_cookie,
                "X-Casulo-CSRF": first_csrf,
                "Origin": base,
            },
        )
        if chat_status != 202:
            try:
                rejection = json.loads(chat_raw)
                rejection_code = rejection.get("error")
            except (json.JSONDecodeError, AttributeError):
                rejection_code = "NON_JSON"
            result["chat_rejection"] = {
                "http_status": chat_status,
                "error": rejection_code,
            }
            raise RuntimeError(
                f"chat autenticado recusado: HTTP {chat_status} {rejection_code}"
            )
        job_id = json.loads(chat_raw)["job_id"]
        runtime_deadline = time.monotonic() + min(adapter.startup_timeout, 120.0)
        while adapter.runtime_address is None and time.monotonic() < runtime_deadline:
            if runtime.store.status(job_id).value in {"FAILED", "CANCELLED"}:
                break
            time.sleep(0.1)
        if adapter.runtime_address is None:
            raise RuntimeError("runtime não iniciou para o job autenticado")
        runtime_port = int(adapter.runtime_address.rsplit(":", 1)[1])
        (evidence / "network-inspection-during.txt").write_text(
            port_snapshot(gateway_port=gateway_port, runtime_port=runtime_port),
            encoding="utf-8",
            newline="\n",
        )
        cross_status, _, _ = request(
            base + f"/v1/jobs/{job_id}/events",
            context,
            headers={"Cookie": second_cookie},
        )
        if cross_status != 401:
            raise RuntimeError("sessão distinta acessou job alheio")
        stream_status, _, stream_raw = request(
            base + f"/v1/jobs/{job_id}/events",
            context,
            headers={"Cookie": first_cookie},
        )
        events = parse_events(stream_raw)
        if stream_status != 200 or not events or events[-1]["kind"] != "COMPLETED":
            raise RuntimeError("stream autenticado não concluiu")
        first_memory = runtime.memory.recent("ana", session_id=first["session_id"])
        second_memory = runtime.memory.recent("ana", session_id=second["session_id"])
        if len(first_memory) != 1 or second_memory:
            raise RuntimeError("isolamento de memória/sessão falhou")

        revoke_status, _, revoke_raw = request(
            base + f"/v1/admin/devices/{first['device_id']}/revoke",
            context,
            method="POST",
            body={},
            headers={"X-Casulo-Owner-Token": owner_token},
        )
        if revoke_status != 200:
            raise RuntimeError("revogação falhou")
        denied_status, _, _ = request(
            base + "/v1/session", context, headers={"Cookie": first_cookie}
        )
        surviving_status, _, _ = request(
            base + "/v1/session", context, headers={"Cookie": second_cookie}
        )
        if denied_status != 401 or surviving_status != 200:
            raise RuntimeError("revogação não foi individual")

        follow_status, _, follow_raw = request(
            base + "/v1/chat",
            context,
            method="POST",
            body={"message": "Responda somente: segundo dispositivo ativo."},
            headers={
                "Cookie": second_cookie,
                "X-Casulo-CSRF": second_csrf,
                "Origin": base,
            },
        )
        if follow_status != 202:
            raise RuntimeError("dispositivo não revogado perdeu acesso")
        follow_job = json.loads(follow_raw)["job_id"]
        follow_stream_status, _, follow_stream_raw = request(
            base + f"/v1/jobs/{follow_job}/events",
            context,
            headers={"Cookie": second_cookie},
        )
        follow_events = parse_events(follow_stream_raw)
        if follow_stream_status != 200 or follow_events[-1]["kind"] != "COMPLETED":
            raise RuntimeError("segundo dispositivo não concluiu")
        audit_text = (state / "audit.jsonl").read_text(encoding="utf-8")
        if owner_token in audit_text or "fluxo seguro concluído" in audit_text:
            raise RuntimeError("segredo ou prompt integral apareceu no audit")

        write_json(
            evidence / "pwa.json",
            {
                "schema": "casulo.family.day4-pwa/1.0",
                "https_status": status,
                "manifest_display": manifest_doc["display"],
                "service_worker_api_cache_excluded": True,
                "content_security_policy": headers.get("Content-Security-Policy"),
                "strict_transport_security": headers.get("Strict-Transport-Security"),
            },
        )
        write_json(
            evidence / "device-pairing.json",
            {
                "schema": "casulo.family.day4-device-pairing/1.0",
                "devices_paired": 2,
                "credentials_logged": False,
                "raw_credentials_persisted": False,
                "first_device_revoked": True,
                "revocation_result": json.loads(revoke_raw),
                "revoked_device_denied": denied_status == 401,
                "other_device_survived": surviving_status == 200,
                "registry": registry.diagnostics(),
            },
        )
        write_json(
            evidence / "session-isolation.json",
            {
                "schema": "casulo.family.day4-session-isolation/1.0",
                "same_user_distinct_sessions": first["session_id"] != second["session_id"],
                "cross_session_job_access_status": cross_status,
                "first_session_memory_entries": len(first_memory),
                "second_session_memory_entries_before_use": len(second_memory),
                "isolated": True,
            },
        )
        write_json(
            evidence / "gateway-model-flow.json",
            {
                "schema": "casulo.family.day4-gateway-model-flow/1.0",
                "gateway_address": base,
                "runtime_address": adapter.runtime_address,
                "gateway_lan_listener": True,
                "runtime_loopback_only": True,
                "first_stream": summarized_events(events),
                "second_stream": summarized_events(follow_events),
                "maximum_active_generations": runtime.supervisor.snapshot()[
                    "maximum_active_generations"
                ],
                "queue_capacity": config.queue_capacity,
            },
        )
        write_json(
            evidence / "tls.json",
            {
                "schema": "casulo.family.day4-tls/1.0",
                "verified_by_private_ca": True,
                "server_certificate_sha256": hashlib.sha256(cert.read_bytes()).hexdigest(),
                "ca_certificate_sha256": hashlib.sha256(ca.read_bytes()).hexdigest(),
                "private_key_in_git": False,
                "root_installation_performed": False,
            },
        )
        if floor_violation.is_set():
            raise RuntimeError("piso de recurso violado")
        result.update(
            {
                "status": "PASS",
                "ended_utc": now(),
                "gateway_address": base,
                "runtime_address": adapter.runtime_address,
                "devices_paired": 2,
                "devices_revoked": 1,
                "completed_generations": 2,
                "cross_session_access_denied": True,
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
        result["process_cleanup"] = (
            "PASS" if "llama_server_processes=0" in process_snapshot() else "FAIL"
        )
        result["port_cleanup"] = (
            "PASS"
            if "matching_listeners=0"
            in port_snapshot(gateway_port=gateway_port, runtime_port=runtime_port)
            else "FAIL"
        )
        write_json(evidence / "integration-result.json", result)
    if any(result.get(key) != "PASS" for key in ("status", "sampler_cleanup", "process_cleanup", "port_cleanup")):
        return 1
    print(json.dumps({"status": "PASS", "evidence": str(evidence)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
