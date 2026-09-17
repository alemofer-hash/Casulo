from __future__ import annotations

import base64
import json
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any, Sequence

from .platform_contracts import PlatformError
from .voice_candidate import VoiceCandidate, inspect_voice_cache
from .voice_duplex import AudioFrame, TranscriptEvent


MAX_PROTOCOL_LINE = 256 * 1024


@dataclass(slots=True)
class _Outbound:
    encoded: bytes
    stop_after: bool
    flushed: threading.Event


@dataclass(frozen=True, slots=True)
class BridgeTranscript:
    transcript_id: str
    text: str
    locale: str
    final: bool
    confidence: float | None

    @classmethod
    def parse(cls, payload: Any) -> "BridgeTranscript":
        if not isinstance(payload, dict):
            raise PlatformError("evento ASR precisa ser objeto JSON")
        if payload.get("schema") != "casulo-asr-event/1.0":
            raise PlatformError("schema do evento ASR não suportado")
        transcript_id = payload.get("transcript_id")
        text = payload.get("text")
        locale = payload.get("locale")
        final = payload.get("final")
        confidence = payload.get("confidence")
        if not isinstance(transcript_id, str) or not transcript_id:
            raise PlatformError("evento ASR sem transcript_id")
        if not isinstance(text, str):
            raise PlatformError("evento ASR sem texto")
        if locale != "pt-BR":
            raise PlatformError("bridge ASR em locale diferente de pt-BR")
        if not isinstance(final, bool):
            raise PlatformError("evento ASR sem marcador final booleano")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise PlatformError("confiança ASR fora do intervalo 0..1")
        return cls(
            transcript_id=transcript_id,
            text=text,
            locale=locale,
            final=final,
            confidence=None if confidence is None else float(confidence),
        )


class JsonLineAsrBridge:
    """Process boundary for an adopted ASR engine; never invokes a shell."""

    def __init__(self, command: Sequence[str], *, outbound_capacity: int = 512) -> None:
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("comando do bridge precisa ser argv explícito")
        if outbound_capacity <= 0:
            raise ValueError("capacidade outbound precisa ser positiva")
        self._process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        if self._process.stdin is None or self._process.stdout is None:
            raise PlatformError("bridge ASR não abriu pipes")
        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        self._events: queue.Queue[BridgeTranscript | BaseException] = queue.Queue()
        self._commands: queue.Queue[_Outbound] = queue.Queue(maxsize=outbound_capacity)
        self._closed = False
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._writer.start()
        self._reader.start()

    def send_frame(self, frame: AudioFrame) -> None:
        self._send(
            {
                "schema": "casulo-asr-command/1.0",
                "op": "audio",
                "sample_rate": frame.sample_rate,
                "channels": frame.channels,
                "pcm_s16le_b64": base64.b64encode(frame.pcm_s16le).decode("ascii"),
            }
        )

    def finalize(self) -> None:
        self._send({"schema": "casulo-asr-command/1.0", "op": "finalize"})

    def reset(self) -> None:
        self._send({"schema": "casulo-asr-command/1.0", "op": "reset"})

    def receive(self, timeout: float = 0.0) -> BridgeTranscript | None:
        try:
            item = self._events.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            if self._process.poll() is not None and not self._closed:
                raise PlatformError(f"bridge ASR encerrou com código {self._process.returncode}")
            return None
        if isinstance(item, BaseException):
            raise PlatformError(f"falha no protocolo ASR: {item}") from item
        return item

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._process.poll() is None:
                self._send(
                    {"schema": "casulo-asr-command/1.0", "op": "shutdown"},
                    wait_flushed=True,
                )
                try:
                    self._process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                        self._process.wait(timeout=1.0)
        finally:
            self._closed = True
            self._writer.join(timeout=1.0)
            if not self._stdin.closed:
                self._stdin.close()
            self._stdout.close()
            self._reader.join(timeout=1.0)

    def _send(self, payload: dict[str, Any], *, wait_flushed: bool = False) -> None:
        if self._closed or self._process.poll() is not None:
            raise PlatformError("bridge ASR não está ativo")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(encoded) > MAX_PROTOCOL_LINE:
            raise PlatformError("comando ASR excede limite do protocolo")
        outbound = _Outbound(
            encoded=encoded,
            stop_after=payload.get("op") == "shutdown",
            flushed=threading.Event(),
        )
        try:
            self._commands.put_nowait(outbound)
        except queue.Full as error:
            raise PlatformError("backpressure: fila do bridge ASR está cheia") from error
        if wait_flushed and not outbound.flushed.wait(timeout=1.0):
            raise PlatformError("timeout ao drenar comandos do bridge ASR")

    def _write_loop(self) -> None:
        while True:
            outbound = self._commands.get()
            try:
                self._stdin.write(outbound.encoded)
                self._stdin.flush()
            except BaseException as error:
                if not self._closed:
                    self._events.put(error)
                outbound.flushed.set()
                return
            outbound.flushed.set()
            if outbound.stop_after:
                return

    def _read_loop(self) -> None:
        try:
            while True:
                line = self._stdout.readline(MAX_PROTOCOL_LINE + 1)
                if not line:
                    return
                if len(line) > MAX_PROTOCOL_LINE or not line.endswith(b"\n"):
                    raise PlatformError("linha do bridge ASR excede limite")
                payload = json.loads(line.decode("utf-8"))
                self._events.put(BridgeTranscript.parse(payload))
        except BaseException as error:
            if not self._closed:
                self._events.put(error)

    def __enter__(self) -> "JsonLineAsrBridge":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class WhisperBridgeAsr:
    """Streaming ASR contract backed by the first-party bridge protocol."""

    locale = "pt-BR"

    def __init__(self, bridge: JsonLineAsrBridge, *, final_timeout_s: float = 10.0) -> None:
        if final_timeout_s <= 0:
            raise ValueError("timeout final precisa ser positivo")
        self.bridge = bridge
        self.final_timeout_s = final_timeout_s

    def accept(self, frame: AudioFrame) -> TranscriptEvent | None:
        self.bridge.send_frame(frame)
        return self.poll_partial()

    def poll_partial(self, *, timeout_s: float = 0.0) -> TranscriptEvent | None:
        """Read one ready partial without coupling inference latency to capture."""
        event = self.bridge.receive(timeout=timeout_s)
        if event is None:
            return None
        if event.final:
            raise PlatformError("bridge emitiu final antes do endpoint")
        return _to_transcript(event)

    def finalize(self) -> TranscriptEvent | None:
        self.bridge.finalize()
        while True:
            event = self.bridge.receive(timeout=self.final_timeout_s)
            if event is None:
                raise PlatformError("timeout aguardando transcript final")
            if event.final:
                return _to_transcript(event)

    def reset(self) -> None:
        self.bridge.reset()

    def close(self) -> None:
        self.bridge.close()


def create_cached_whisper_asr(
    candidate: VoiceCandidate,
    cache_root: str,
    *,
    threads: int = 1,
    partial_ms: int = 2000,
    use_gpu: bool = False,
    final_timeout_s: float = 10.0,
) -> WhisperBridgeAsr:
    if threads <= 0 or partial_ms <= 0:
        raise ValueError("threads e partial_ms precisam ser positivos")
    inspection = inspect_voice_cache(candidate, cache_root)
    if not inspection.ready:
        raise PlatformError("cache ASR não passou source/model/bridge verification")
    command = [
        sys.executable,
        "-u",
        "-m",
        "casulo.product.whisper_worker",
        "--library",
        str(inspection.bridge_path),
        "--model",
        str(inspection.model_path),
        "--threads",
        str(threads),
        "--partial-ms",
        str(partial_ms),
    ]
    if use_gpu:
        command.append("--use-gpu")
    return WhisperBridgeAsr(JsonLineAsrBridge(command), final_timeout_s=final_timeout_s)


def _to_transcript(event: BridgeTranscript) -> TranscriptEvent:
    return TranscriptEvent(
        transcript_id=event.transcript_id,
        text=event.text,
        locale=event.locale,
        final=event.final,
        confidence=event.confidence,
    )
