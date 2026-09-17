from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from casulo.product.engine_contracts import CancellationToken
from casulo_owner.generative_model import GenerativeCandidate
from casulo_owner.local_model_runtime import (
    ChatMessage,
    GenerationRequest,
    LlamaServerProcess,
    LocalModelRuntime,
    LocalModelRuntimeError,
    ModelStreamKind,
    SamplingPolicy,
    initial_sampling_policies,
    parse_chat_sse_line,
)


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json"


def _candidate() -> GenerativeCandidate:
    return GenerativeCandidate.load(CANDIDATE)


def test_normal_sampling_is_non_degenerate_and_fixed_seed_is_debug_only() -> None:
    policies = initial_sampling_policies()
    assert set(policies) == {"dialogue", "planning", "code"}
    assert all(item.temperature > 0 and item.seed is None for item in policies.values())
    with pytest.raises(LocalModelRuntimeError, match="seed fixa"):
        SamplingPolicy("bad", 0.5, 0.9, 20, 0.0, 1.0, 10, seed=7)
    debug = SamplingPolicy("debug", 0.5, 0.9, 20, 0.0, 1.0, 10, seed=7, debug_fixed_seed=True)
    assert debug.payload()["seed"] == 7


def test_context_digest_is_content_addressed_and_context_is_bounded() -> None:
    request = GenerationRequest(
        "operation:1",
        (ChatMessage("system", "Restrições duras"), ChatMessage("user", "Crie algo novo")),
        initial_sampling_policies()["dialogue"],
    )
    assert len(request.context_digest) == 64
    with pytest.raises(LocalModelRuntimeError, match="excede"):
        GenerationRequest(
            "operation:large",
            (ChatMessage("user", "x" * 131_073),),
            initial_sampling_policies()["dialogue"],
        )


def test_structured_request_carries_bounded_json_schema_to_local_runtime(tmp_path: Path) -> None:
    server, thread = _serve()
    try:
        runtime = LocalModelRuntime(_candidate(), tmp_path / "cache")
        runtime.server = SimpleNamespace(port=server.server_port)
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
        request = GenerationRequest(
            "operation:json",
            (ChatMessage("user", "Responda como JSON."),),
            initial_sampling_policies()["planning"],
            json_schema=schema,
        )
        tuple(runtime.stream_chat(request, CancellationToken()))
        response_format = server.seen_payload["response_format"]  # type: ignore[attr-defined]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        assert response_format["json_schema"]["schema"] == schema
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_runtime_doctor_is_read_only_and_refuses_missing_adoption(tmp_path: Path) -> None:
    cache = tmp_path / "never-created"
    runtime = LocalModelRuntime(_candidate(), cache)
    report = runtime.doctor()
    assert report["ready"] is False
    assert report["endpoint_scope"] == "127.0.0.1-only"
    assert report["shell_used"] is False
    assert report["inference_idle_timeout_seconds"] == 180.0
    assert report["reasoning_mode"] == "off"
    assert not cache.exists()
    with pytest.raises(Exception, match="não adotados"):
        runtime.start()


def test_llama_process_uses_argv_loopback_and_no_shell_text(tmp_path: Path) -> None:
    executable = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    executable.write_bytes(b"exe")
    model.write_bytes(b"model")
    process = LlamaServerProcess(executable, model, context_size=4096, threads=2)
    argv = process.argv(29123)
    assert argv[0] == str(executable.resolve())
    assert "127.0.0.1" in argv
    assert "--no-webui" in argv and "--log-disable" in argv
    assert argv[argv.index("--reasoning") + 1] == "off"
    assert all("http://" not in part and "https://" not in part for part in argv)


def test_sse_parser_accepts_tokens_done_and_rejects_malformed_stream() -> None:
    token = parse_chat_sse_line(b'data: {"choices":[{"delta":{"content":"Oi"},"finish_reason":null}]}\n')
    assert token == ("Oi", None)
    assert parse_chat_sse_line(b"data: [DONE]\n") is not None
    with pytest.raises(LocalModelRuntimeError, match="choices"):
        parse_chat_sse_line(b'data: {"unexpected":true}\n')


class _StreamingHandler(BaseHTTPRequestHandler):
    status = 200

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.server.seen_payload = payload  # type: ignore[attr-defined]
        self.send_response(self.status)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if self.status != 200:
            return
        for content, finish in (("Olá", None), (", Guilherme.", "stop")):
            event = {"choices": [{"delta": {"content": content}, "finish_reason": finish}]}
            self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _serve(status: int = 200):
    handler = type("Handler", (_StreamingHandler,), {"status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_stream_contract_emits_fragments_trace_and_no_external_api(tmp_path: Path) -> None:
    server, thread = _serve()
    try:
        runtime = LocalModelRuntime(_candidate(), tmp_path / "cache")
        runtime.server = SimpleNamespace(port=server.server_port)  # contract-only test double
        request = GenerationRequest(
            "operation:stream",
            (ChatMessage("user", "Converse em português."),),
            initial_sampling_policies()["dialogue"],
        )
        events = tuple(runtime.stream_chat(request, CancellationToken()))
        assert [event.kind for event in events] == [
            ModelStreamKind.STARTED,
            ModelStreamKind.TOKEN,
            ModelStreamKind.TOKEN,
            ModelStreamKind.COMPLETED,
        ]
        assert "".join(event.content for event in events if event.kind is ModelStreamKind.TOKEN) == "Olá, Guilherme."
        trace = events[-1].trace
        assert trace is not None
        assert trace.output_sha256 == hashlib.sha256("Olá, Guilherme.".encode()).hexdigest()
        assert trace.seed is None
        assert trace.external_network_used is False
        assert trace.commercial_ai_api_used is False
        assert server.seen_payload["stream"] is True  # type: ignore[attr-defined]
        assert server.seen_payload.get("seed") is None  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_precancelled_request_never_contacts_runtime(tmp_path: Path) -> None:
    runtime = LocalModelRuntime(_candidate(), tmp_path / "cache")
    runtime.server = SimpleNamespace(port=9)
    token = CancellationToken()
    token.cancel()
    request = GenerationRequest(
        "operation:cancel",
        (ChatMessage("user", "Pare."),),
        initial_sampling_policies()["dialogue"],
    )
    events = tuple(runtime.stream_chat(request, token))
    assert [event.kind for event in events] == [ModelStreamKind.STARTED, ModelStreamKind.CANCELLED]


def test_runtime_failure_is_terminal_and_does_not_echo_server_body(tmp_path: Path) -> None:
    server, thread = _serve(status=500)
    try:
        runtime = LocalModelRuntime(_candidate(), tmp_path / "cache")
        runtime.server = SimpleNamespace(port=server.server_port)
        request = GenerationRequest(
            "operation:failure",
            (ChatMessage("user", "SEGREDO"),),
            initial_sampling_policies()["dialogue"],
        )
        events = tuple(runtime.stream_chat(request, CancellationToken()))
        assert events[-1].kind is ModelStreamKind.FAILED
        assert "SEGREDO" not in events[-1].content
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_runtime_rejects_invisible_completion(tmp_path: Path) -> None:
    class EmptyHandler(_StreamingHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            )
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), EmptyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        runtime = LocalModelRuntime(_candidate(), tmp_path / "cache")
        runtime.server = SimpleNamespace(port=server.server_port)
        request = GenerationRequest(
            "operation:empty",
            (ChatMessage("user", "Responda."),),
            initial_sampling_policies()["dialogue"],
        )
        events = tuple(runtime.stream_chat(request, CancellationToken()))
        assert [item.kind for item in events] == [
            ModelStreamKind.STARTED,
            ModelStreamKind.FAILED,
        ]
        assert events[-1].content == "Falha local segura: LocalModelRuntimeError"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
