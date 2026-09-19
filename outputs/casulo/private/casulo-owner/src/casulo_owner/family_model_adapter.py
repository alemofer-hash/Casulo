from __future__ import annotations

import http.client
import json
import secrets
import shutil
import socket
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from casulo.family.contracts import ChatRequest
from casulo.family.model_gate import (
    LoopbackLlamaServer,
    ModelGateError,
    _available_physical_memory,
    _process_memory,
)
from casulo.family.model_gate_cli import _load_profile


class FamilyModelAdapterError(RuntimeError):
    pass


class FamilyLocalModelAdapter:
    """Owner-only Qwen adapter; the llama.cpp listener never leaves loopback."""

    mock_only = False

    def __init__(
        self,
        *,
        cache_root: str | Path,
        manifest: str | Path,
        profile_id: str = "qwen25-q2-vulkan",
        max_generated_tokens: int = 256,
        minimum_available_ram_bytes: int = 1_024**3,
        minimum_start_available_ram_bytes: int | None = None,
        minimum_disk_free_bytes: int = 30 * 1_024**3,
        startup_timeout: float = 300.0,
        slot_action_path: Path | None = None,
    ) -> None:
        if not 16 <= max_generated_tokens <= 1_024:
            raise FamilyModelAdapterError("max_generated_tokens inválido")
        self.cache_root = Path(cache_root).expanduser().resolve()
        self.manifest = Path(manifest).resolve()
        self.profile, self.identity = _load_profile(
            profile_id, self.cache_root, self.manifest
        )
        self.max_generated_tokens = max_generated_tokens
        self.minimum_available_ram_bytes = minimum_available_ram_bytes
        self.minimum_start_available_ram_bytes = (
            minimum_available_ram_bytes
            if minimum_start_available_ram_bytes is None
            else minimum_start_available_ram_bytes
        )
        if self.minimum_start_available_ram_bytes < self.minimum_available_ram_bytes:
            raise FamilyModelAdapterError("margem de startup abaixo do piso operacional")
        self.minimum_disk_free_bytes = minimum_disk_free_bytes
        self.startup_timeout = startup_timeout
        self.slot_action_path = slot_action_path
        self._lock = threading.RLock()
        self._server: LoopbackLlamaServer | None = None
        self._active_requests = 0
        self._maximum_active_requests = 0
        self._startup_count = 0
        self._cache_clean = True
        self._cache_erases = 0
        self._cache_erase_status = None

    @property
    def runtime_address(self) -> str | None:
        with self._lock:
            if self._server is None or self._server.port is None:
                return None
            return f"127.0.0.1:{self._server.port}"

    def start(self) -> None:
        with self._lock:
            if self._server is not None:
                raise FamilyModelAdapterError("segunda instância do runtime recusada")
        self._assert_resource_floor(startup=True)
        options = {}
        if self.slot_action_path is not None:
            if not self.slot_action_path.is_dir() or any(self.slot_action_path.iterdir()):
                raise FamilyModelAdapterError("slot action directory must be empty")
            options = {"slot_action_path": self.slot_action_path,
                       "api_key": secrets.token_urlsafe(32)}
        server = LoopbackLlamaServer(self.profile, startup_timeout=self.startup_timeout, **options)
        server.start()
        with self._lock:
            if self._server is not None:
                server.close()
                raise FamilyModelAdapterError("corrida de segunda instância recusada")
            self._server = server
            self._startup_count += 1
            self._cache_clean = True

    def stop(self) -> None:
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            server.close()

    close = stop

    def is_ready(self) -> bool:
        with self._lock:
            server = self._server
            process = None if server is None else server.process
        return bool(
            server is not None
            and server.port is not None
            and process is not None
            and process.poll() is None
            and self._cache_clean
        )

    def recover(self) -> bool:
        with self._lock:
            server = self._server
        if server is None or not self.is_ready():
            return False
        try:
            status, _ = server.request("GET", "/health", None, timeout=3.0)
            return status == 200
        except (OSError, ModelGateError):
            return False

    def generate(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]:
        with self._lock:
            if not self.is_ready() or self._server is None or self._server.port is None:
                raise FamilyModelAdapterError("runtime local indisponível")
            if self._active_requests:
                raise FamilyModelAdapterError("concorrência do adapter recusada")
            self._active_requests = 1
            self._maximum_active_requests = max(
                self._maximum_active_requests, self._active_requests
            )
            port = self._server.port
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=240.0)
        monitor_done = threading.Event()

        def monitor_cancel() -> None:
            while not monitor_done.wait(0.01):
                if cancelled():
                    connection.close()
                    return

        monitor = threading.Thread(
            target=monitor_cancel,
            name="casulo-family-model-cancel-monitor",
            daemon=True,
        )
        monitor.start()
        try:
            if cancelled():
                return
            if request.persona_instance_id:
                self._erase_slot()
            payload = {
                "model": self.profile.profile_id,
                "messages": [
                    {
                        "role": "system",
                        "content": request.system_prompt or (
                            "Responda em português do Brasil, diretamente, sem expor "
                            "raciocínio oculto."
                        ),
                    },
                    {"role": "user", "content": request.message},
                ],
                "stream": True,
                "temperature": 0.2,
                "top_p": 0.9,
                "max_tokens": self.max_generated_tokens,
                "cache_prompt": False,
                "id_slot": 0,
            }
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    **({"Authorization": "Bearer " + self._server.api_key}
                       if getattr(self._server, "api_key", None) else {}),
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                response.read(64 * 1024)
                raise FamilyModelAdapterError(
                    f"runtime local respondeu HTTP {response.status}"
                )
            event_count = 0
            visible_chars = 0
            while True:
                if cancelled():
                    connection.close()
                    return
                raw = response.readline(16_385)
                if not raw:
                    break
                if len(raw) > 16_384:
                    raise FamilyModelAdapterError("evento SSE do modelo excede limite")
                parsed = self._parse_sse(raw)
                if parsed is None:
                    continue
                if parsed is False:
                    break
                event_count += 1
                if event_count > 4_096:
                    raise FamilyModelAdapterError("stream do modelo excede limite")
                visible_chars += len(parsed)
                if visible_chars > 65_536:
                    raise FamilyModelAdapterError("resposta do modelo excede limite")
                for offset in range(0, len(parsed), 2_048):
                    yield parsed[offset : offset + 2_048]
            if event_count == 0:
                raise FamilyModelAdapterError("runtime encerrou sem fragmentos")
        except (
            OSError,
            ValueError,
            socket.timeout,
            http.client.HTTPException,
        ) as error:
            if cancelled():
                return
            raise FamilyModelAdapterError(
                f"falha de transporte local: {type(error).__name__}"
            ) from error
        finally:
            monitor_done.set()
            connection.close()
            monitor.join(timeout=2.0)
            if monitor.is_alive():
                raise FamilyModelAdapterError("monitor de cancelamento não encerrou")
            with self._lock:
                self._active_requests = 0
            if request.persona_instance_id:
                self._erase_slot()

    def _erase_slot(self) -> None:
        # A failed erasure makes readiness fail closed; never reuse that slot.
        server = self._server
        self._cache_clean = False
        if self.slot_action_path is not None and any(self.slot_action_path.iterdir()):
            raise FamilyModelAdapterError("UNEXPECTED_KV_FILE")
        if server is None:
            raise FamilyModelAdapterError("cache erase without runtime")
        for attempt in range(50):
            status, receipt = server.request("POST", "/slots/0?action=erase", {}, timeout=3)
            self._cache_erase_status = {"http_status": status, "fields": sorted(receipt)}
            if status == 200 and receipt.get("id_slot") == 0:
                self._cache_clean = True
                self._cache_erases += 1
                return
            if status not in {400, 503}:
                break
            time.sleep(0.1)
        raise FamilyModelAdapterError("KV_CACHE_ERASE_UNCONFIRMED")

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            server = self._server
            process = None if server is None else server.process
            pid = None if process is None or process.poll() is not None else process.pid
            listener = self.runtime_address
            active = self._active_requests
            maximum = self._maximum_active_requests
            starts = self._startup_count
        memory = {} if pid is None else _process_memory(pid)
        return {
            "adapter": "Qwen2.5-7B-Q2_K-Vulkan",
            "backend": "llama.cpp-vulkan",
            "runtime_listener": listener,
            "runtime_loopback_only": listener is None or listener.startswith("127.0.0.1:"),
            "runtime_pid": pid,
            "runtime_instances": int(pid is not None),
            "startup_count": starts,
            "cache_clean": self._cache_clean,
            "cache_erases": self._cache_erases,
            "cache_erase_status": self._cache_erase_status,
            "adapter_active_requests": active,
            "adapter_maximum_active_requests": maximum,
            "available_ram_bytes": _available_physical_memory(),
            "disk_free_bytes": shutil.disk_usage(self.profile.model).free,
            "process_working_set_bytes": memory.get("working_set_bytes"),
            "process_commit_bytes": memory.get("commit_bytes"),
            "process_peak_working_set_bytes": memory.get("peak_working_set_bytes"),
            "minimum_start_available_ram_bytes": self.minimum_start_available_ram_bytes,
            "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
            "temperature_telemetry_collected_by_runner": False,
            "temperature_claim": "NONE",
        }

    def _assert_resource_floor(self, *, startup: bool = False) -> None:
        ram = _available_physical_memory()
        required_ram = (
            self.minimum_start_available_ram_bytes
            if startup
            else self.minimum_available_ram_bytes
        )
        if ram is None or ram < required_ram:
            label = "margem de startup" if startup else "piso operacional"
            raise FamilyModelAdapterError(
                f"{label} de RAM não preservada: required={required_ram}"
            )
        if shutil.disk_usage(self.profile.model).free < self.minimum_disk_free_bytes:
            raise FamilyModelAdapterError("reserva de disco de 30 GiB não preservada")

    @staticmethod
    def _parse_sse(raw: bytes) -> str | bool | None:
        try:
            line = raw.decode("utf-8").strip()
        except UnicodeError as error:
            raise FamilyModelAdapterError("SSE do runtime não é UTF-8") from error
        if not line or line.startswith(":") or not line.startswith("data:"):
            return None
        value = line[5:].strip()
        if value == "[DONE]":
            return False
        document = json.loads(value)
        choices = document.get("choices") if isinstance(document, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise FamilyModelAdapterError("evento SSE sem choices")
        delta = choices[0].get("delta")
        if not isinstance(delta, dict) or delta.get("content") is None:
            return None
        return str(delta["content"])
