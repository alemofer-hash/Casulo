from __future__ import annotations

import json
import hashlib
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from casulo.family.model_gate import (
    LoopbackLlamaServer,
    ModelGateError,
    ModelProfile,
    run_functional_probes,
    run_soak,
)
from casulo.family.model_gate_cli import PROFILE_CHOICES, _load_profile


def _profile(tmp_path: Path) -> ModelProfile:
    executable = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    executable.write_bytes(b"exe")
    model.write_bytes(b"model")
    return ModelProfile("qwen3-8b-q4km-vulkan", executable, model)


def test_profile_rejects_missing_or_unfrozen_assets(tmp_path: Path) -> None:
    with pytest.raises(ModelGateError, match="ausente"):
        ModelProfile("missing", tmp_path / "missing.exe", tmp_path / "missing.gguf")
    profile = _profile(tmp_path)
    with pytest.raises(ModelGateError, match="device"):
        ModelProfile(profile.profile_id, profile.executable, profile.model, device="network-gpu")


def test_server_argv_is_loopback_only_without_shell_material(tmp_path: Path) -> None:
    server = LoopbackLlamaServer(_profile(tmp_path))
    argv = server.argv(29123)
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("--ctx-size") + 1] == "8192"
    assert argv[argv.index("--device") + 1] == "Vulkan0"
    assert argv[argv.index("--gpu-layers") + 1] == "99"
    assert argv[argv.index("--cache-type-k") + 1] == "q4_0"
    assert argv[argv.index("--cache-type-v") + 1] == "q4_0"
    assert argv[argv.index("--batch-size") + 1] == "128"
    assert argv[argv.index("--ubatch-size") + 1] == "64"
    assert argv[argv.index("--flash-attn") + 1] == "on"
    assert argv[argv.index("--parallel") + 1] == "1"
    assert argv[argv.index("--cache-ram") + 1] == "0"
    assert "--no-cache-idle-slots" in argv
    assert "--no-cont-batching" in argv
    assert "--no-host" in argv
    assert "--no-webui" in argv and "--log-disable" in argv
    assert all("http://" not in item and "https://" not in item for item in argv)


def test_qwen25_profiles_verify_every_frozen_shard(tmp_path: Path) -> None:
    assert {"qwen25-q4-vulkan", "qwen25-q3-vulkan", "qwen25-q2-vulkan", "qwen25-q2-cpu"}.issubset(PROFILE_CHOICES)
    runtime = tmp_path / "runtimes" / "vulkan"
    model_dir = tmp_path / "models" / "qwen2.5-7b-instruct"
    runtime.mkdir(parents=True)
    model_dir.mkdir(parents=True)
    (runtime / "llama-server.exe").write_bytes(b"exe")
    assets = {
        "first.gguf": b"first shard",
        "second.gguf": b"second shard",
        "fallback.gguf": b"fallback",
        "smallest.gguf": b"smallest",
    }
    for name, content in assets.items():
        (model_dir / name).write_bytes(content)

    def frozen(name: str) -> dict[str, object]:
        content = assets[name]
        return {
            "file": name,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "casulo.family.day2-model-candidates/1.0",
                "context_tokens": 8192,
                "runtime": {"commit": "frozen"},
                "resource_fit_model": {
                    "repository": "Qwen/Qwen2.5-7B-Instruct-GGUF",
                    "revision": "frozen-revision",
                    "license": "Apache-2.0",
                    "candidates": {
                        "q4_k_m": {
                            "entry_file": "first.gguf",
                            "files": [frozen("first.gguf"), frozen("second.gguf")],
                        },
                        "q3_k_m": {
                            "entry_file": "fallback.gguf",
                            "files": [frozen("fallback.gguf")],
                        },
                        "q2_k": {
                            "entry_file": "smallest.gguf",
                            "files": [frozen("smallest.gguf")],
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    profile, identity = _load_profile("qwen25-q4-vulkan", tmp_path, manifest)
    assert profile.model == model_dir / "first.gguf"
    assert profile.cache_type_k == profile.cache_type_v == "f16"
    assert len(identity["model_files"]) == 2
    (model_dir / "second.gguf").write_bytes(b"tampered")
    with pytest.raises(ModelGateError, match="diverge"):
        _load_profile("qwen25-q4-vulkan", tmp_path, manifest)


class _ProbeHandler(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        type(self).calls += 1
        if "tools" in payload:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "consultar_hora_local",
                            "arguments": '{"cidade":"Porto Alegre"}',
                        },
                    }
                ],
            }
        elif "response_format" in payload:
            name = payload["response_format"]["json_schema"]["name"]
            content = '{"status":"recuperado"}' if name == "casulo_cancel_recovery" else '{"idioma":"pt-BR","status":"ok"}'
            message = {"role": "assistant", "content": content}
        elif payload["messages"][0]["content"] == "Responda apenas: estável":
            message = {"role": "assistant", "content": "estável"}
        elif "Corrija a função" in payload["messages"][0]["content"]:
            message = {"role": "assistant", "content": "def somar(a, b):\n    return a + b"}
        else:
            message = {"role": "assistant", "content": "Uma rede local conecta dispositivos próximos."}
        body = json.dumps(
            {
                "choices": [{"message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def test_functional_probes_validate_portuguese_json_and_tool_call(tmp_path: Path) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        server = LoopbackLlamaServer(_profile(tmp_path))
        server.port = httpd.server_port
        server.process = SimpleNamespace(poll=lambda: None, pid=os.getpid())  # type: ignore[assignment]
        report = run_functional_probes(server)
        assert report["pass"] is True
        assert set(report) == {
            "portuguese",
            "json_schema",
            "tool_call",
            "code_edit",
            "cancellation_recovery",
            "pass",
        }
        assert all("output_sha256" in report[key] for key in ("portuguese", "json_schema", "tool_call", "code_edit"))
        assert "cancelled_prefix_sha256" in report["cancellation_recovery"]

        checkpoints: list[dict[str, object]] = []
        soak = run_soak(
            server,
            duration_seconds=1,
            interval_seconds=1,
            minimum_disk_free_bytes=0,
            minimum_available_ram_bytes=0,
            checkpoint=checkpoints.append,
        )
        assert soak["pass"] is True
        assert soak["state"] == "COMPLETE"
        assert checkpoints and all(item["state"] == "RUNNING" for item in checkpoints)
        assert "process_commit_bytes" in soak["samples"][0]
        assert soak["listener"].startswith("127.0.0.1:")
        assert len(soak["samples"]) >= 2
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
