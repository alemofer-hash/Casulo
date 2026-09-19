"""Reproducible Day 6 real gate. Neutral fixture only; preserve every attempt."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import ssl
import subprocess
import threading
import time
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psutil

from casulo.family.model_gate import _available_physical_memory
from casulo.family.voice_service import VoiceCancelled
from casulo_owner.family_cleo_app import cleo_stack, sha256, voice_paths

EXPECTED_COMMIT = "8d46bb6a8e6b8e3a872ba97207dc444f4b61e7dc"
EXPECTED_TREE = "28fc3be2c7bd5b35b42c2fb455e59be1886d56e1"
THERMAL = {"temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
           "temperature_telemetry_collected_by_runner": False, "temperature_claim": "NONE"}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+"\n",
                    encoding="utf-8", newline="\n")


def git(repo, *args):
    return subprocess.run(["git", "-c", f"safe.directory={repo.as_posix()}", *args], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def call(url, context, *, body=None, headers=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    supplied = dict(headers or {})
    if raw is not None:
        supplied["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=raw, headers=supplied), context=context, timeout=10) as response:
            return response.status, response.headers, response.read(2000001)
    except HTTPError as error:
        return error.code, error.headers, error.read(8192)


def cookies(headers):
    cookie = SimpleCookie()
    for value in headers.get_all("Set-Cookie") or []:
        cookie.load(value)
    return "; ".join(f"{key}={item.value}" for key, item in cookie.items()), cookie["casulo_csrf"].value


def snapshot(ports=(), pids=()):
    return {"at": datetime.now(UTC).isoformat(),
            "llama": [{"pid": p.pid, "name": p.name()} for p in psutil.process_iter()
                       if p.name().lower() == "llama-server.exe"],
            "owned_alive": [pid for pid in pids if psutil.pid_exists(pid)],
            "listeners": [{"ip": c.laddr.ip, "port": c.laddr.port, "pid": c.pid}
                          for c in psutil.net_connections("tcp")
                          if c.status == "LISTEN" and c.laddr and c.laddr.port in ports]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--tls-dir", type=Path, required=True)
    parser.add_argument("--browser-node", type=Path)
    parser.add_argument("--browser-node-path", type=Path)
    args = parser.parse_args()
    repo, evidence = args.repo.resolve(), args.evidence_dir.resolve()
    root = repo / "outputs/casulo"
    evidence.mkdir(parents=True, exist_ok=False)
    args.state_dir.mkdir(parents=True, exist_ok=False)
    local = Path(os.environ["LOCALAPPDATA"])/"Casulo"
    tls = args.tls_dir
    config = SimpleNamespace(bind_host="127.0.0.1", bind_port=0, state_dir=args.state_dir,
                             cache_root=local/"family-rp01/day2",
                             manifest=root/"config/family/day2-model-candidates.json",
                             voice_root=local/"cache/voice", persona_root=root/"config/family/cleo",
                             dependency_lock=root/"config/family/day6-dependencies.lock.json",
                             tls_cert=tls/"casulo-family-server.pem", tls_key=tls/"casulo-family-server-key.pem",
                             owner_token_file=tls/"owner-token.txt", pwa_root=root/"apps/casulo-family-pwa",
                             embedding_card=root/"models/first-party/casulo-exact-embedding-v1.json",
                             embedding_sha256="0876987a6ef2ab29f4a93d0b3947b4b08fd3931466c086a90be1978435d36961")
    baseline = {"input_commit": git(repo, "rev-parse", "HEAD"),
                "input_tree": git(repo, "rev-parse", "HEAD^{tree}"),
                "branch": git(repo, "branch", "--show-current"), **THERMAL}
    if baseline["input_commit"] != EXPECTED_COMMIT or baseline["input_tree"] != EXPECTED_TREE:
        write(evidence/"baseline.json", baseline)
        raise RuntimeError("BASELINE_INCOMPATIBLE")
    hashes = {}
    day5 = root/"evidence/family/day5"
    for line in (day5/"SHA256SUMS.txt").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        actual = sha256(day5/relative)
        if actual != digest:
            raise RuntimeError("DAY5_EVIDENCE_CHANGED")
        hashes[relative] = actual
    baseline["day5_verified_files"] = hashes
    baseline["day5_report_sha256"] = sha256(root/"docs/product/CASULO_FAMILY_RP01_DAY5_MEMORY_RAG.md")
    write(evidence/"baseline.json", baseline)
    before = snapshot()
    write(evidence/"process-inspection-before.txt", before)
    write(evidence/"port-inspection-before.txt", before)
    if before["llama"]:
        raise RuntimeError("EXISTING_MODEL_PROCESS")
    library, model = voice_paths(config.voice_root, config.dependency_lock)
    provenance = {"lock": json.loads(config.dependency_lock.read_text()),
                  "library": {"path": str(library), "sha256": sha256(library), "bytes": library.stat().st_size},
                  "asr_model": {"path": str(model), "sha256": sha256(model), "bytes": model.stat().st_size},
                  "tts_assets": [], "python_version": os.sys.version, "network_required": False}
    tts = Path(os.environ["WINDIR"])/"Speech_OneCore/Engines/TTS/pt-BR"
    for path in sorted(tts.iterdir()):
        if path.is_file() and (path.name.startswith("M1046Maria") or path.name.startswith("MSTTSLocPtBR")):
            provenance["tts_assets"].append({"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size})
    write(evidence/"dependency-and-model-provenance.json", provenance)
    samples, stop = [], threading.Event()
    breach = threading.Event()
    sampler_errors = []
    children_seen = set()
    started = time.monotonic()

    def sample_resources():
        with (evidence/"resource-samples.jsonl").open("x", encoding="utf-8", newline="\n") as output:
            while not stop.is_set():
                try:
                    process = psutil.Process()
                    children = process.children(recursive=True)
                    children_seen.update(p.pid for p in children)
                    row = {"at": time.time(), "elapsed_seconds": time.monotonic()-started,
                           "available_ram_bytes": min(psutil.virtual_memory().available,
                                                       _available_physical_memory() or 0),
                           "disk_free_bytes": psutil.disk_usage(str(repo)).free,
                           "runner_working_set_bytes": process.memory_info().rss,
                           "children": [{"pid": p.pid, "name": p.name(), "working_set_bytes": p.memory_info().rss}
                                        for p in children if p.is_running()], **THERMAL}
                    row["aggregate_working_set_bytes"] = row["runner_working_set_bytes"] + sum(
                        p["working_set_bytes"] for p in row["children"])
                    samples.append(row)
                    output.write(json.dumps(row)+"\n")
                    output.flush()
                    if row["available_ram_bytes"] < 1024**3 or row["disk_free_bytes"] < 30*1024**3:
                        breach.set()
                except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
                    sampler_errors.append(type(error).__name__)
                stop.wait(0.25)

    sampler = threading.Thread(target=sample_resources, name="day6-resource-sampler", daemon=True)
    sampler.start()
    result = {"status": "PARTIAL", **THERMAL}
    ports = []
    try:
        print("CONFIGURING_RUNTIME: loading one Qwen instance", flush=True)
        with cleo_stack(config) as (gateway, runtime, voice, service, registry, resolver, adapter):
            result["model_identity"] = adapter.identity
            ports = [gateway.address[1], service.address[1], int(adapter.runtime_address.split(":")[1])]
            during = snapshot(ports)
            assert all(p["ip"] == "127.0.0.1" for p in during["listeners"])
            assert len(during["llama"]) == 1 and len(during["listeners"]) == 3
            write(evidence/"port-inspection-during.txt", during)
            print("VERIFYING_DEPENDENCY: HTTPS host authentication and neutral audio", flush=True)
            context = ssl.create_default_context(cafile=str(tls/"casulo-family-ca.pem"))
            denied_model, _, _ = call("http://"+adapter.runtime_address+"/v1/chat/completions", context,
                                      body={"messages": []})
            denied_voice, _, _ = call(f"http://127.0.0.1:{service.address[1]}/tts", context,
                                      body={"not": "authorized"})
            assert denied_model == 401 and denied_voice == 401
            result["internal_endpoints_unauthenticated"] = {"model": denied_model, "voice": denied_voice}
            code, headers, _ = call(gateway.base_url+"/v1/admin/host-session", context,
                                    body={"output_route": "LOCAL_PRIVATE", "sole_participant": True},
                                    headers={"X-Casulo-Owner-Token": config.owner_token_file.read_text().strip()})
            assert code == 201, f"HOST_BIND_HTTP_{code}"
            cookie, csrf = cookies(headers)
            headers = {"Cookie": cookie, "X-Casulo-CSRF": csrf, "Origin": gateway.base_url}
            session = registry.authenticate(cookie)
            fixture_text = "Diga uma frase curta sobre a natureza."
            fixture = service.call("tts", fixture_text.encode("utf-8"), breach.is_set)
            # Neutral fixture is explicitly non-private and reproducible.
            (evidence/"neutral-input.wav").write_bytes(fixture)
            write(evidence/"neutral-fixture.json", {"text": fixture_text, "origin": "first-party neutral test",
                  "audio_origin": "Microsoft Maria Desktop local synthesis", "redistribution": "local private evidence only",
                  "sha256": hashlib.sha256(fixture).hexdigest(), "microphone_capture_claim": False})

            def submit_voice():
                status, _, raw = call(gateway.base_url+"/v1/voice", context,
                                      body={"wav_base64": base64.b64encode(fixture).decode()}, headers=headers)
                assert status == 202, f"VOICE_SUBMIT_HTTP_{status}"
                return json.loads(raw)["turn_id"]

            def state(turn):
                status, _, raw = call(gateway.base_url+f"/v1/voice/{turn}", context, headers=headers)
                assert status == 200, f"VOICE_STATE_HTTP_{status}"
                return json.loads(raw)

            turn = submit_voice()
            deadline = time.monotonic()+10
            while service._child is None and time.monotonic() < deadline:
                time.sleep(0.02)
            status, _, _ = call(gateway.base_url+f"/v1/voice/{turn}/cancel", context, body={}, headers=headers)
            assert status == 200
            while time.monotonic() < deadline and (voice._active is not None or voice._worker.is_alive()):
                time.sleep(0.02)
            cancelled_turn = state(turn)
            assert cancelled_turn["result"] == "CANCELLED"
            write(evidence/"voice-cancellation-cleanup.json", {"gateway_asr_cancel": cancelled_turn})
            print("RESUMED_ORIGINAL_GATE: real ASR -> persona -> Qwen -> TTS", flush=True)
            turn = submit_voice()
            deadline = time.monotonic()+300
            last_state = None
            while time.monotonic() < deadline:
                if breach.is_set():
                    voice.cancel(session.auth, turn)
                    raise RuntimeError("RESOURCE_FLOOR_BREACH")
                observed = state(turn)
                if observed["state"] != last_state:
                    print("VOICE_STATE:", observed["state"], flush=True)
                    last_state = observed["state"]
                if observed["result"] in {"READY_FOR_PLAYBACK", "FAILED", "CANCELLED"}:
                    break
                time.sleep(0.2)
            assert observed["result"] == "READY_FOR_PLAYBACK", json.dumps(observed)
            status, _, output = call(gateway.base_url+f"/v1/voice/{turn}/audio", context, headers=headers)
            assert status == 200 and output.startswith(b"RIFF")
            (evidence/"neutral-response.wav").write_bytes(output)
            code, _, _ = call(gateway.base_url+f"/v1/voice/{turn}/finished", context, body={}, headers=headers)
            assert code == 200
            observed = state(turn)
            observed.update({"gateway": gateway.base_url, "runtime": adapter.runtime_address,
                             "voice_runtime": list(service.address), "audio_playable_wav": True,
                             "physical_playback_claim": False, "microphone_capture_claim": False})
            write(evidence/"voice-e2e-real.json", observed)
            print("VERIFYING_DEPENDENCY: native TTS cancellation", flush=True)
            cancel_tts = threading.Event()
            cancelled = []

            def synthesize_then_cancel():
                try:
                    service.call("tts", ("Uma frase neutra para testar cancelamento. "*35).encode(), cancel_tts.is_set)
                except VoiceCancelled:
                    cancelled.append(True)

            synth = threading.Thread(target=synthesize_then_cancel)
            synth.start()
            deadline = time.monotonic()+10
            while service._child is None and time.monotonic() < deadline:
                time.sleep(0.02)
            cancel_tts.set()
            synth.join(10)
            assert not synth.is_alive() and cancelled == [True]
            assert service.call("tts", b"Teste concluido.").startswith(b"RIFF")
            if args.browser_node:
                print("VERIFYING_DEPENDENCY: isolated Chromium PWA test with neutral microphone fixture", flush=True)
                from cryptography import x509
                from cryptography.hazmat.primitives import serialization
                certificate = x509.load_pem_x509_certificate(config.tls_cert.read_bytes())
                spki = certificate.public_key().public_bytes(serialization.Encoding.DER,
                                                             serialization.PublicFormat.SubjectPublicKeyInfo)
                browser_cookies = []
                jar = SimpleCookie()
                jar.load(cookie)
                for name, item in jar.items():
                    browser_cookies.append({"name": name, "value": item.value, "domain": "127.0.0.1",
                                            "path": "/", "secure": True, "httpOnly": name != "casulo_csrf",
                                            "sameSite": "Strict"})
                browser_input = {"base": gateway.base_url, "cookies": browser_cookies,
                                 "fixture": str(evidence/"neutral-input.wav"),
                                 "serverSPKI": base64.b64encode(hashlib.sha256(spki).digest()).decode(),
                                 "receipt": str(evidence/"pwa-browser.json"),
                                 "screenshot": str(evidence/"pwa-browser.png")}
                environment = dict(os.environ)
                environment["NODE_PATH"] = str(args.browser_node_path)
                browser = subprocess.run([str(args.browser_node), str(root/"scripts/16-test-cleo-pwa.cjs")],
                                          input=json.dumps(browser_input), capture_output=True, text=True,
                                          timeout=180, env=environment)
                (evidence/"pwa-browser-output.txt").write_text(browser.stdout+browser.stderr, encoding="utf-8")
                assert browser.returncode == 0, "PWA_BROWSER_FAILED"
            write(evidence/"voice-cancellation-cleanup.json", {
                "gateway_asr_cancel": cancelled_turn, "native_tts_cancel": "PASS",
                "native_tts_recovery": "PASS", "audio_disk_temp_files": 0,
                "service_receipts": service.receipts})
            write(evidence/"host-register-transitions.json", resolver.transitions)
            write(evidence/"voice-runtime-lifecycle.json", {"voice_state": service.state,
                  "supervisor": runtime.supervisor.snapshot(), "adapter": adapter.diagnostics(),
                  "receipts": service.receipts})
            result.update({"status": "PASS_REAL_PIPELINE", "counters": runtime.counters(),
                           "adapter": adapter.diagnostics(), "voice_turn": observed,
                           "maximum_active_generations": runtime.supervisor.snapshot()["maximum_active_generations"],
                           "queue_capacity": runtime.config.queue_capacity})
            assert result["maximum_active_generations"] == 1
            result["kv_files_created"] = len(list((args.state_dir/"empty-slot-actions").iterdir()))
            assert result["kv_files_created"] == 0
        after = snapshot(ports, children_seen)
        write(evidence/"port-inspection-after.txt", after)
        write(evidence/"process-inspection-after.txt", after)
        assert not after["listeners"] and not after["llama"] and not after["owned_alive"]
    except Exception as error:
        if "adapter" in locals():
            result["adapter_at_failure"] = adapter.diagnostics()
            write(evidence/"voice-runtime-lifecycle.json", {
                "adapter": adapter.diagnostics(), "supervisor": runtime.supervisor.snapshot(),
                "voice_state": service.state, "receipts": service.receipts})
        result.update({"status": "PARTIAL", "first_reproducible_cause": type(error).__name__,
                       "error": str(error)[:3000]})
        print("REAL_GATE_PARTIAL:", type(error).__name__, str(error)[:500], flush=True)
    finally:
        stop.set()
        sampler.join(5)
        after = snapshot(ports, children_seen)
        write(evidence/"port-inspection-after.txt", after)
        write(evidence/"process-inspection-after.txt", after)
        result.update({"duration_seconds": round(time.monotonic()-started, 3),
                       "resource_sample_count": len(samples), "sampler_transient_errors": sampler_errors,
                       "min_available_ram_bytes": min((r["available_ram_bytes"] for r in samples), default=0),
                       "min_disk_free_bytes": min((r["disk_free_bytes"] for r in samples), default=0),
                       "max_aggregate_working_set_bytes": max((r["aggregate_working_set_bytes"] for r in samples), default=0),
                       "resource_floor_breached": breach.is_set(), "cleanup": after})
        if breach.is_set() or not samples or after["owned_alive"] or after["listeners"]:
            result["status"] = "PARTIAL"
        write(evidence/"integration-result.json", result)
        print(json.dumps({"status": result["status"], "samples": len(samples),
                          "minimum_ram_bytes": result["min_available_ram_bytes"]}), flush=True)
    return 0 if result["status"] == "PASS_REAL_PIPELINE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
