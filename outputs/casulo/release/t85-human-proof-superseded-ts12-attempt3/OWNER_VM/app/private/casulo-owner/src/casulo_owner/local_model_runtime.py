from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from casulo.product.engine_contracts import CancellationToken

from .generative_model import GenerativeCandidate, GenerativeModelError, adoption_doctor


_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
MAX_MESSAGE_CHARS = 131_072
MAX_STREAM_EVENT_CHARS = 16_384
DEFAULT_INFERENCE_IDLE_TIMEOUT_SECONDS = 180.0


class LocalModelRuntimeError(RuntimeError):
    pass


class ModelStreamKind(StrEnum):
    STARTED = "STARTED"
    TOKEN = "TOKEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SamplingPolicy:
    policy_id: str
    temperature: float
    top_p: float
    top_k: int
    min_p: float
    repeat_penalty: float
    max_generated_tokens: int
    seed: int | None = None
    debug_fixed_seed: bool = False

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.policy_id):
            raise LocalModelRuntimeError("sampling policy id inválido")
        if not 0.05 <= self.temperature <= 2.0:
            raise LocalModelRuntimeError("temperature precisa manter sampling não degenerado")
        if not 0.1 <= self.top_p <= 1.0 or not 1 <= self.top_k <= 200:
            raise LocalModelRuntimeError("top-p/top-k inválido")
        if not 0.0 <= self.min_p <= 1.0 or not 0.5 <= self.repeat_penalty <= 2.0:
            raise LocalModelRuntimeError("min-p/repeat penalty inválido")
        if not 1 <= self.max_generated_tokens <= 4096:
            raise LocalModelRuntimeError("limite de geração inválido")
        if self.seed is not None and not self.debug_fixed_seed:
            raise LocalModelRuntimeError("seed fixa só é permitida em modo debug")
        if self.debug_fixed_seed and self.seed is None:
            raise LocalModelRuntimeError("modo debug reproduzível exige seed")

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "min_p": self.min_p,
            "repeat_penalty": self.repeat_penalty,
            "max_tokens": self.max_generated_tokens,
        }
        if self.seed is not None:
            result["seed"] = self.seed
        return result


def initial_sampling_policies() -> dict[str, SamplingPolicy]:
    """Initial product policies; owner inspection may tune them later."""
    return {
        "dialogue": SamplingPolicy("casulo-sampling-dialogue-v1", 0.70, 0.90, 40, 0.05, 1.10, 512),
        "planning": SamplingPolicy("casulo-sampling-planning-v1", 0.45, 0.90, 30, 0.05, 1.10, 768),
        "code": SamplingPolicy("casulo-sampling-code-v1", 0.25, 0.90, 40, 0.02, 1.05, 1024),
    }


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"} or not self.content.strip():
            raise LocalModelRuntimeError("mensagem de modelo inválida")


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    operation_id: str
    messages: tuple[ChatMessage, ...]
    policy: SamplingPolicy
    json_schema: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.operation_id) or not self.messages:
            raise LocalModelRuntimeError("request generativo inválido")
        if sum(len(item.content) for item in self.messages) > MAX_MESSAGE_CHARS:
            raise LocalModelRuntimeError("contexto generativo excede o limite")
        if self.json_schema is not None:
            try:
                encoded = json.dumps(
                    self.json_schema,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError) as error:
                raise LocalModelRuntimeError("JSON Schema generativo inválido") from error
            if len(encoded) > 64 * 1024:
                raise LocalModelRuntimeError("JSON Schema generativo grande demais")

    @property
    def context_digest(self) -> str:
        raw = json.dumps(
            {
                "messages": [{"role": item.role, "content": item.content} for item in self.messages],
                "json_schema": self.json_schema,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class StochasticTrace:
    operation_id: str
    model_id: str
    model_sha256: str
    sampling_policy_id: str
    seed: int | None
    context_digest: str
    output_sha256: str
    stream_events: int
    finish_reason: str
    started_monotonic_ns: int
    ended_monotonic_ns: int
    external_network_used: bool = False
    commercial_ai_api_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo-stochastic-trace/1.0",
            "operation_id": self.operation_id,
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
            "sampling_policy_id": self.sampling_policy_id,
            "seed_if_available": self.seed,
            "context_digest": self.context_digest,
            "output_sha256": self.output_sha256,
            "stream_events": self.stream_events,
            "finish_reason": self.finish_reason,
            "started_monotonic_ns": self.started_monotonic_ns,
            "ended_monotonic_ns": self.ended_monotonic_ns,
            "external_network_used": self.external_network_used,
            "commercial_ai_api_used": self.commercial_ai_api_used,
        }


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    operation_id: str
    sequence: int
    kind: ModelStreamKind
    content: str = ""
    trace: StochasticTrace | None = None


class LlamaServerProcess:
    """Verified local process boundary. It never invokes a command shell."""

    def __init__(
        self,
        executable: Path,
        model: Path,
        *,
        context_size: int = 8192,
        threads: int = 4,
        startup_timeout: float = 180.0,
    ) -> None:
        if not executable.is_file() or executable.is_symlink():
            raise LocalModelRuntimeError("llama-server verificado ausente")
        if not model.is_file() or model.is_symlink():
            raise LocalModelRuntimeError("peso verificado ausente")
        if not 1024 <= context_size <= 32768 or not 1 <= threads <= 12:
            raise LocalModelRuntimeError("limites de contexto/threads inválidos")
        if not 5.0 <= startup_timeout <= 300.0:
            raise LocalModelRuntimeError("timeout de startup inválido")
        self.executable = executable.resolve()
        self.model = model.resolve()
        self.context_size = context_size
        self.threads = threads
        self.startup_timeout = startup_timeout
        self.port: int | None = None
        self.process: subprocess.Popen[bytes] | None = None

    def argv(self, port: int) -> tuple[str, ...]:
        if not 1024 <= port <= 65535:
            raise LocalModelRuntimeError("porta local inválida")
        return (
            str(self.executable),
            "--model", str(self.model),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--ctx-size", str(self.context_size),
            "--threads", str(self.threads),
            "--reasoning", "off",
            "--no-webui",
            "--log-disable",
        )

    def start(self) -> None:
        if self.process is not None:
            raise LocalModelRuntimeError("runtime já iniciado")
        port = _reserve_loopback_port()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            self.argv(port),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
        )
        self.port = port
        self.process = process
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.close()
                raise LocalModelRuntimeError("llama-server encerrou durante carga")
            try:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
                connection.request("GET", "/health")
                response = connection.getresponse()
                response.read(64 * 1024)
                connection.close()
                if response.status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.1)
        self.close()
        raise LocalModelRuntimeError("timeout ao carregar o modelo local")

    def close(self) -> None:
        process, self.process = self.process, None
        self.port = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class LocalModelRuntime:
    def __init__(
        self,
        candidate: GenerativeCandidate,
        cache_root: str | Path,
        *,
        context_size: int = 8192,
        threads: int = 4,
        inference_idle_timeout: float = DEFAULT_INFERENCE_IDLE_TIMEOUT_SECONDS,
    ) -> None:
        if not 30.0 <= inference_idle_timeout <= 600.0:
            raise LocalModelRuntimeError("timeout ocioso de inferÃªncia invÃ¡lido")
        self.candidate = candidate
        self.cache_root = Path(cache_root).expanduser().resolve(strict=False)
        self.context_size = context_size
        self.threads = threads
        self.inference_idle_timeout = inference_idle_timeout
        self.server: LlamaServerProcess | None = None

    def doctor(self) -> dict[str, Any]:
        report = adoption_doctor(self.candidate, self.cache_root)
        return {
            **report,
            "runtime_contract": "llama-server-loopback-stream/1.0",
            "context_size": self.context_size,
            "threads": self.threads,
            "inference_idle_timeout_seconds": self.inference_idle_timeout,
            "reasoning_mode": "off",
            "endpoint_scope": "127.0.0.1-only",
            "shell_used": False,
        }

    def start(self) -> None:
        report = self.doctor()
        if not report["ready"]:
            raise GenerativeModelError("modelo/runtime ainda não adotados e verificados")
        if self.server is not None:
            raise LocalModelRuntimeError("runtime já iniciado")
        server = LlamaServerProcess(
            Path(str(report["runtime_executable"])),
            Path(str(report["model_file"])),
            context_size=self.context_size,
            threads=self.threads,
        )
        server.start()
        self.server = server

    def close(self) -> None:
        if self.server is not None:
            self.server.close()
            self.server = None

    def __enter__(self) -> "LocalModelRuntime":
        self.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def stream_chat(
        self,
        request: GenerationRequest,
        cancellation: CancellationToken,
    ) -> Iterable[ModelStreamEvent]:
        if self.server is None or self.server.port is None:
            raise LocalModelRuntimeError("runtime local não iniciado")
        started = time.monotonic_ns()
        sequence = 1
        yield ModelStreamEvent(request.operation_id, sequence, ModelStreamKind.STARTED)
        sequence += 1
        if cancellation.cancelled:
            yield ModelStreamEvent(request.operation_id, sequence, ModelStreamKind.CANCELLED)
            return
        payload = {
            "model": self.candidate.candidate_id,
            "messages": [{"role": item.role, "content": item.content} for item in request.messages],
            "stream": True,
            **request.policy.payload(),
        }
        if request.json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.operation_id.replace(":", "_").replace("-", "_")[:64],
                    "strict": True,
                    "schema": request.json_schema,
                },
            }
        # Em CPU local, prompt evaluation e a primeira emissÃ£o podem exceder
        # 30 s sem que o processo esteja travado. O limite continua finito e Ã©
        # aplicado como timeout ocioso de socket, nÃ£o como autorizaÃ§Ã£o para um
        # job sem prazo.
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.port, timeout=self.inference_idle_timeout
        )
        output: list[str] = []
        finish_reason = "unknown"
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
            )
            response = connection.getresponse()
            if response.status != 200:
                response.read(64 * 1024)
                raise LocalModelRuntimeError(f"runtime local respondeu HTTP {response.status}")
            while True:
                if cancellation.cancelled:
                    connection.close()
                    yield ModelStreamEvent(request.operation_id, sequence, ModelStreamKind.CANCELLED)
                    return
                raw = response.readline(MAX_STREAM_EVENT_CHARS + 1)
                if not raw:
                    break
                if len(raw) > MAX_STREAM_EVENT_CHARS:
                    raise LocalModelRuntimeError("evento de stream grande demais")
                parsed = parse_chat_sse_line(raw)
                if parsed is None:
                    continue
                if parsed is _DONE:
                    break
                content, reason = parsed
                if reason:
                    finish_reason = reason
                if content:
                    output.append(content)
                    yield ModelStreamEvent(request.operation_id, sequence, ModelStreamKind.TOKEN, content)
                    sequence += 1
            ended = time.monotonic_ns()
            joined = "".join(output)
            if not joined.strip():
                raise LocalModelRuntimeError("runtime concluiu sem conteÃºdo visÃ­vel")
            trace = StochasticTrace(
                request.operation_id,
                self.candidate.candidate_id,
                self.candidate.model.sha256,
                request.policy.policy_id,
                request.policy.seed,
                request.context_digest,
                hashlib.sha256(joined.encode("utf-8")).hexdigest(),
                len(output),
                finish_reason,
                started,
                ended,
            )
            yield ModelStreamEvent(request.operation_id, sequence, ModelStreamKind.COMPLETED, trace=trace)
        except (OSError, http.client.HTTPException, UnicodeError, json.JSONDecodeError, LocalModelRuntimeError) as error:
            connection.close()
            yield ModelStreamEvent(
                request.operation_id,
                sequence,
                ModelStreamKind.FAILED,
                content=f"Falha local segura: {type(error).__name__}",
            )
        finally:
            connection.close()


class _Done:
    pass


_DONE = _Done()


def parse_chat_sse_line(raw: bytes) -> tuple[str, str | None] | _Done | None:
    try:
        line = raw.decode("utf-8").strip()
    except UnicodeError as error:
        raise LocalModelRuntimeError("stream local não é UTF-8") from error
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    value = line[5:].strip()
    if value == "[DONE]":
        return _DONE
    payload = json.loads(value)
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LocalModelRuntimeError("evento SSE sem choices")
    first = choices[0]
    delta = first.get("delta")
    content = ""
    if isinstance(delta, dict) and delta.get("content") is not None:
        content = str(delta["content"])
    finish = first.get("finish_reason")
    return content, str(finish) if finish is not None else None


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])
