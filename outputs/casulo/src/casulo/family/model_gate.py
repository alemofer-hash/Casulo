from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


MINIMUM_DISK_FREE_BYTES = 30 * 1024**3
MINIMUM_AVAILABLE_RAM_BYTES = 1024**3


class ModelGateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelProfile:
    profile_id: str
    executable: Path
    model: Path
    context_tokens: int = 8192
    threads: int = 4
    device: str = "Vulkan0"
    gpu_layers: int = 99
    cache_type_k: str = "q4_0"
    cache_type_v: str = "q4_0"
    batch_size: int = 128
    ubatch_size: int = 64
    flash_attention: bool = True
    no_host: bool = True

    def __post_init__(self) -> None:
        if not self.executable.is_file() or self.executable.is_symlink():
            raise ModelGateError("llama-server regular ausente")
        if not self.model.is_file() or self.model.is_symlink():
            raise ModelGateError("modelo GGUF regular ausente")
        if not 1024 <= self.context_tokens <= 32768:
            raise ModelGateError("contexto fora do limite")
        if not 1 <= self.threads <= 12 or not 0 <= self.gpu_layers <= 999:
            raise ModelGateError("perfil de execução inválido")
        if self.device not in {"none", "Vulkan0"}:
            raise ModelGateError("device não congelado")
        if self.cache_type_k not in {"f16", "q8_0", "q4_0"} or self.cache_type_v not in {"f16", "q8_0", "q4_0"}:
            raise ModelGateError("tipo de KV cache não congelado")
        if not 32 <= self.ubatch_size <= self.batch_size <= 2048:
            raise ModelGateError("batch fora do limite")


class LoopbackLlamaServer:
    def __init__(self, profile: ModelProfile, *, startup_timeout: float = 300.0,
                 slot_action_path: Path | None = None, api_key: str | None = None) -> None:
        self.profile = profile
        self.startup_timeout = startup_timeout
        self.port: int | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.slot_action_path = slot_action_path
        self.api_key = api_key
        if slot_action_path is not None and (not api_key or len(api_key) < 32):
            raise ModelGateError("slot actions require internal authentication")

    def argv(self, port: int) -> tuple[str, ...]:
        if not 1024 <= port <= 65535:
            raise ModelGateError("porta inválida")
        profile = self.profile
        return (
            str(profile.executable.resolve()),
            "--model", str(profile.model.resolve()),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--ctx-size", str(profile.context_tokens),
            "--threads", str(profile.threads),
            "--device", profile.device,
            "--gpu-layers", str(profile.gpu_layers),
            "--cache-type-k", profile.cache_type_k,
            "--cache-type-v", profile.cache_type_v,
            "--batch-size", str(profile.batch_size),
            "--ubatch-size", str(profile.ubatch_size),
            "--flash-attn", "on" if profile.flash_attention else "off",
            "--parallel", "1",
            "--cache-ram", "0",
            "--no-cache-idle-slots",
            "--no-cont-batching",
            "--reasoning", "off",
            "--jinja",
            "--no-webui",
            "--log-disable",
            *(("--slot-save-path", str(self.slot_action_path), "--slots", "--no-cache-prompt")
              if self.slot_action_path is not None else ()),
            *(("--no-host",) if profile.no_host else ()),
        )

    def start(self) -> None:
        if self.process is not None:
            raise ModelGateError("servidor já iniciado")
        port = _reserve_loopback_port()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        environment = None
        if self.api_key:
            environment = {k: v for k, v in os.environ.items()
                           if not k.startswith(("LLAMA_", "GGML_", "AIP_"))}
            environment["LLAMA_API_KEY"] = self.api_key
        process = subprocess.Popen(
            self.argv(port),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
            env=environment,
        )
        self.port = port
        self.process = process
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.close()
                raise ModelGateError("llama-server encerrou durante a carga")
            try:
                status, _ = self.request("GET", "/health", None, timeout=2.0)
                if status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.25)
        self.close()
        raise ModelGateError("timeout ao carregar modelo")

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        *,
        timeout: float,
    ) -> tuple[int, dict[str, Any]]:
        if self.port is None:
            raise ModelGateError("servidor não iniciado")
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {} if body is None else {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024)
            document = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(document, dict):
                raise ModelGateError("resposta do runtime não é objeto JSON")
            return response.status, document
        finally:
            connection.close()

    def close(self) -> None:
        process, self.process = self.process, None
        self.port = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    def __enter__(self) -> "LoopbackLlamaServer":
        self.start()
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()


def run_functional_probes(server: LoopbackLlamaServer) -> dict[str, Any]:
    probes: dict[str, Any] = {}
    portuguese = _chat(
        server,
        {
            "messages": [
                {"role": "system", "content": "Responda somente em português do Brasil, sem raciocínio oculto."},
                {"role": "user", "content": "Em uma frase curta, explique o que é uma rede local."},
            ],
            "temperature": 0.1,
            "max_tokens": 96,
        },
    )
    text = _message(portuguese).get("content", "")
    language_markers = ("rede", "local", "disposit", "computador")
    probes["portuguese"] = _probe_receipt(
        portuguese,
        isinstance(text, str) and len(text.strip()) >= 12 and any(item in text.casefold() for item in language_markers),
        text if isinstance(text, str) else "",
    )

    schema = {
        "type": "object",
        "properties": {
            "idioma": {"type": "string", "const": "pt-BR"},
            "status": {"type": "string", "const": "ok"},
        },
        "required": ["idioma", "status"],
        "additionalProperties": False,
    }
    structured = _chat(
        server,
        {
            "messages": [{"role": "user", "content": "Retorne o estado solicitado."}],
            "temperature": 0.0,
            "max_tokens": 64,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "casulo_day2_probe", "strict": True, "schema": schema},
            },
        },
    )
    structured_text = _message(structured).get("content", "")
    try:
        parsed = json.loads(structured_text)
    except (TypeError, json.JSONDecodeError):
        parsed = None
    probes["json_schema"] = _probe_receipt(
        structured,
        parsed == {"idioma": "pt-BR", "status": "ok"},
        structured_text if isinstance(structured_text, str) else "",
    )

    called = _chat(
        server,
        {
            "messages": [{"role": "user", "content": "Consulte a hora local em Porto Alegre."}],
            "temperature": 0.0,
            "max_tokens": 96,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "consultar_hora_local",
                        "description": "Obtém a hora local de uma cidade.",
                        "parameters": {
                            "type": "object",
                            "properties": {"cidade": {"type": "string"}},
                            "required": ["cidade"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "consultar_hora_local"}},
        },
    )
    tool_calls = _message(called).get("tool_calls", [])
    tool_ok = False
    if isinstance(tool_calls, list) and len(tool_calls) == 1:
        function = tool_calls[0].get("function", {}) if isinstance(tool_calls[0], dict) else {}
        try:
            arguments = json.loads(function.get("arguments", ""))
        except (TypeError, json.JSONDecodeError):
            arguments = None
        tool_ok = function.get("name") == "consultar_hora_local" and isinstance(arguments, dict) and bool(arguments.get("cidade"))
    probes["tool_call"] = _probe_receipt(called, tool_ok, json.dumps(tool_calls, ensure_ascii=False))
    edited = _chat(
        server,
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Corrija a função abaixo. Responda somente com a função Python corrigida, sem markdown:\n"
                        "def somar(a, b):\n    return a - b"
                    ),
                }
            ],
            "temperature": 0.0,
            "max_tokens": 64,
        },
    )
    edited_text = str(_message(edited).get("content", ""))
    compact = "".join(edited_text.split())
    probes["code_edit"] = _probe_receipt(
        edited,
        "defsomar(a,b):" in compact and "returna+b" in compact and "returna-b" not in compact,
        edited_text,
    )
    probes["cancellation_recovery"] = _cancel_and_recover(server)
    probes["pass"] = all(item["pass"] for item in probes.values())
    return probes


def _cancel_and_recover(server: LoopbackLlamaServer) -> dict[str, Any]:
    if server.port is None:
        raise ModelGateError("servidor não iniciado")
    payload = {
        "model": server.profile.profile_id,
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": "Escreva uma lista numerada de 1 a 500, uma linha por item, sem abreviar.",
            }
        ],
        "temperature": 0.0,
        "max_tokens": 2048,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=60.0)
    prefix = b""
    status = 0
    try:
        connection.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        status = response.status
        prefix = response.read(256)
    finally:
        connection.close()
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "const": "recuperado"}},
        "required": ["status"],
        "additionalProperties": False,
    }
    recovered = _chat(
        server,
        {
            "messages": [{"role": "user", "content": "Confirme a recuperação solicitada."}],
            "temperature": 0.0,
            "max_tokens": 32,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "casulo_cancel_recovery", "strict": True, "schema": schema},
            },
        },
    )
    recovered_text = str(_message(recovered).get("content", ""))
    try:
        parsed = json.loads(recovered_text)
    except json.JSONDecodeError:
        parsed = None
    return {
        "pass": status == 200 and bool(prefix) and parsed == {"status": "recuperado"},
        "cancelled_http_status": status,
        "cancelled_prefix_sha256": hashlib.sha256(prefix).hexdigest(),
        "recovery_output_sha256": hashlib.sha256(recovered_text.encode("utf-8")).hexdigest(),
        "recovery_finish_reason": recovered.get("choices", [{}])[0].get("finish_reason"),
    }


def run_soak(
    server: LoopbackLlamaServer,
    *,
    duration_seconds: int,
    interval_seconds: int = 60,
    minimum_disk_free_bytes: int = MINIMUM_DISK_FREE_BYTES,
    minimum_available_ram_bytes: int = MINIMUM_AVAILABLE_RAM_BYTES,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if duration_seconds < 1 or interval_seconds < 1:
        raise ModelGateError("duração de soak inválida")
    started_utc = datetime.now(UTC).isoformat()
    started = time.monotonic()
    deadline = started + duration_seconds
    samples: list[dict[str, Any]] = []
    failures: list[str] = []

    def receipt(state: str, ended: float) -> dict[str, Any]:
        return {
            "schema": "casulo.family.day2-soak/1.0",
            "state": state,
            "started_utc": started_utc,
            "ended_utc": datetime.now(UTC).isoformat(),
            "profile_id": server.profile.profile_id,
            "listener": f"127.0.0.1:{server.port}",
            "requested_duration_seconds": duration_seconds,
            "observed_duration_seconds": round(ended - started, 3),
            "minimum_disk_free_bytes": minimum_disk_free_bytes,
            "minimum_available_ram_bytes": minimum_available_ram_bytes,
            "samples": list(samples),
            "failures": list(failures),
            "pass": state == "COMPLETE" and not failures and ended - started >= duration_seconds,
        }

    while True:
        process = server.process
        if process is None or process.poll() is not None:
            failures.append("llama-server deixou de executar")
            break
        sample_started = time.monotonic()
        try:
            response = _chat(
                server,
                {
                    "messages": [{"role": "user", "content": "Responda apenas: estável"}],
                    "temperature": 0.0,
                    "max_tokens": 16,
                },
            )
            content = str(_message(response).get("content", ""))
            inference_ok = "estável" in content.casefold() or "estavel" in content.casefold()
        except Exception as error:
            inference_ok = False
            content = ""
            failures.append(f"inferência: {type(error).__name__}")
        disk_free = shutil.disk_usage(server.profile.model).free
        ram_available = _available_physical_memory()
        process_memory = _process_memory(process.pid)
        sample = {
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "latency_seconds": round(time.monotonic() - sample_started, 3),
            "inference_pass": inference_ok,
            "output_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "disk_free_bytes": disk_free,
            "available_ram_bytes": ram_available,
            "process_working_set_bytes": process_memory.get("working_set_bytes"),
            "process_commit_bytes": process_memory.get("commit_bytes"),
            "process_peak_working_set_bytes": process_memory.get("peak_working_set_bytes"),
        }
        samples.append(sample)
        if not inference_ok:
            failures.append("resposta de estabilidade divergente")
        if disk_free < minimum_disk_free_bytes:
            failures.append("reserva de disco violada")
        if ram_available is not None and ram_available < minimum_available_ram_bytes:
            failures.append("reserva de RAM violada")
        if checkpoint is not None:
            checkpoint(receipt("RUNNING", time.monotonic()))
        if failures or time.monotonic() >= deadline:
            break
        time.sleep(min(interval_seconds, max(0.0, deadline - time.monotonic())))
    ended = time.monotonic()
    return receipt("COMPLETE", ended)


def _chat(server: LoopbackLlamaServer, fields: dict[str, Any]) -> dict[str, Any]:
    payload = {"model": server.profile.profile_id, "stream": False, **fields}
    status, document = server.request("POST", "/v1/chat/completions", payload, timeout=240.0)
    if status != 200:
        raise ModelGateError(f"runtime respondeu HTTP {status}")
    return document


def _message(document: dict[str, Any]) -> dict[str, Any]:
    choices = document.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ModelGateError("choices inválido")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ModelGateError("message inválida")
    return message


def _probe_receipt(document: dict[str, Any], passed: bool, material: str) -> dict[str, Any]:
    usage = document.get("usage") if isinstance(document.get("usage"), dict) else {}
    return {
        "pass": bool(passed),
        "finish_reason": document.get("choices", [{}])[0].get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "output_sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
    }


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _available_physical_memory() -> int | None:
    if os.name != "nt":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong),
            ("avail_phys", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("avail_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("avail_virtual", ctypes.c_ulonglong),
            ("avail_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.avail_phys)


def _process_memory(pid: int) -> dict[str, int | None]:
    if os.name != "nt":
        return {
            "working_set_bytes": None,
            "commit_bytes": None,
            "peak_working_set_bytes": None,
        }

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("page_fault_count", ctypes.c_ulong),
            ("peak_working_set", ctypes.c_size_t),
            ("working_set", ctypes.c_size_t),
            ("quota_peak_paged_pool", ctypes.c_size_t),
            ("quota_paged_pool", ctypes.c_size_t),
            ("quota_peak_non_paged_pool", ctypes.c_size_t),
            ("quota_non_paged_pool", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    process = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, pid)
    if not process:
        return {
            "working_set_bytes": None,
            "commit_bytes": None,
            "peak_working_set_bytes": None,
        }
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return {
                "working_set_bytes": None,
                "commit_bytes": None,
                "peak_working_set_bytes": None,
            }
        return {
            "working_set_bytes": int(counters.working_set),
            "commit_bytes": int(counters.pagefile_usage),
            "peak_working_set_bytes": int(counters.peak_working_set),
        }
    finally:
        ctypes.windll.kernel32.CloseHandle(process)
