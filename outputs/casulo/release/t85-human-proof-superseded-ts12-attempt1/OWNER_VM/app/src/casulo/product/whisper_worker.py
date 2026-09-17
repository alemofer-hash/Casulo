from __future__ import annotations

import argparse
import base64
import binascii
import ctypes
import json
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, Sequence

from .platform_contracts import PlatformError
from .voice_bridge import MAX_PROTOCOL_LINE


SAMPLE_RATE = 16_000
MAX_UTTERANCE_SECONDS = 120
MAX_PCM_BYTES = SAMPLE_RATE * 2 * MAX_UTTERANCE_SECONDS
TRANSCRIPT_BUFFER_BYTES = 1024 * 1024


class TranscriptionBackend(Protocol):
    def transcribe(self, samples: array[float]) -> str: ...

    def close(self) -> None: ...


class WhisperNativeBackend:
    def __init__(
        self,
        library_path: str | Path,
        model_path: str | Path,
        *,
        threads: int = 1,
        use_gpu: bool = False,
    ) -> None:
        library = Path(library_path).resolve(strict=True)
        model = Path(model_path).resolve(strict=True)
        if threads <= 0:
            raise PlatformError("threads do ASR precisam ser positivas")
        self._library = ctypes.CDLL(str(library))
        self._bind()
        self._handle = self._library.casulo_whisper_create(
            str(model).encode("utf-8"), threads, int(use_gpu)
        )
        if not self._handle:
            raise PlatformError("bridge nativo recusou engine/modelo")

    def _bind(self) -> None:
        self._library.casulo_whisper_create.argtypes = [
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._library.casulo_whisper_create.restype = ctypes.c_void_p
        self._library.casulo_whisper_destroy.argtypes = [ctypes.c_void_p]
        self._library.casulo_whisper_destroy.restype = None
        self._library.casulo_whisper_last_error.argtypes = [ctypes.c_void_p]
        self._library.casulo_whisper_last_error.restype = ctypes.c_char_p
        self._library.casulo_whisper_transcribe_pt_br.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._library.casulo_whisper_transcribe_pt_br.restype = ctypes.c_int

    def transcribe(self, samples: array[float]) -> str:
        if not samples:
            return ""
        native_samples = (ctypes.c_float * len(samples)).from_buffer(samples)
        output = ctypes.create_string_buffer(TRANSCRIPT_BUFFER_BYTES)
        output_size = ctypes.c_size_t()
        result = self._library.casulo_whisper_transcribe_pt_br(
            self._handle,
            native_samples,
            len(samples),
            output,
            len(output),
            ctypes.byref(output_size),
        )
        if result != 0:
            raw_error = self._library.casulo_whisper_last_error(self._handle)
            message = raw_error.decode("utf-8", "replace") if raw_error else "unknown"
            raise PlatformError(f"inferência ASR falhou ({result}): {message}")
        return output.raw[: output_size.value].decode("utf-8")

    def close(self) -> None:
        if getattr(self, "_handle", None):
            self._library.casulo_whisper_destroy(self._handle)
            self._handle = None


@dataclass
class WorkerSession:
    backend: TranscriptionBackend
    partial_interval_samples: int = SAMPLE_RATE * 2
    sequence: int = 0

    def __post_init__(self) -> None:
        if self.partial_interval_samples <= 0:
            raise ValueError("intervalo parcial precisa ser positivo")
        self._pcm = bytearray()
        self._next_partial = self.partial_interval_samples
        self._last_partial = ""

    def accept_audio(self, command: dict[str, object]) -> dict[str, object] | None:
        if command.get("sample_rate") != SAMPLE_RATE or command.get("channels") != 1:
            raise PlatformError("worker ASR aceita somente PCM16 mono em 16 kHz")
        encoded = command.get("pcm_s16le_b64")
        if not isinstance(encoded, str):
            raise PlatformError("frame ASR sem PCM base64")
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise PlatformError("PCM base64 inválido") from error
        if len(pcm) % 2:
            raise PlatformError("PCM16 precisa ter quantidade par de bytes")
        if len(self._pcm) + len(pcm) > MAX_PCM_BYTES:
            raise PlatformError("fala excede limite de 120 segundos")
        self._pcm.extend(pcm)
        sample_count = len(self._pcm) // 2
        if sample_count < self._next_partial:
            return None
        self._next_partial += self.partial_interval_samples
        text = self.backend.transcribe(_pcm_to_float(self._pcm)).strip()
        if not text or text == self._last_partial:
            return None
        self._last_partial = text
        return self._event(text, final=False)

    def finalize(self) -> dict[str, object]:
        text = self.backend.transcribe(_pcm_to_float(self._pcm)).strip()
        event = self._event(text, final=True)
        self.reset()
        return event

    def reset(self) -> None:
        self._pcm.clear()
        self._next_partial = self.partial_interval_samples
        self._last_partial = ""

    def _event(self, text: str, *, final: bool) -> dict[str, object]:
        if final:
            self.sequence += 1
        identifier = f"voice:{self.sequence + (0 if final else 1)}"
        return {
            "schema": "casulo-asr-event/1.0",
            "transcript_id": identifier,
            "text": text,
            "locale": "pt-BR",
            "final": final,
            "confidence": None,
        }


def serve(
    source: BinaryIO,
    destination: BinaryIO,
    backend: TranscriptionBackend,
    *,
    partial_interval_samples: int = SAMPLE_RATE * 2,
) -> int:
    session = WorkerSession(backend, partial_interval_samples)
    try:
        while True:
            line = source.readline(MAX_PROTOCOL_LINE + 1)
            if not line:
                return 0
            if len(line) > MAX_PROTOCOL_LINE or not line.endswith(b"\n"):
                raise PlatformError("comando do parent excede limite")
            try:
                command = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise PlatformError("comando do parent não é JSON UTF-8 válido") from error
            if not isinstance(command, dict) or command.get("schema") != "casulo-asr-command/1.0":
                raise PlatformError("schema de comando ASR não suportado")
            op = command.get("op")
            if op == "audio":
                event = session.accept_audio(command)
            elif op == "finalize":
                event = session.finalize()
            elif op == "reset":
                session.reset()
                event = None
            elif op == "shutdown":
                return 0
            else:
                raise PlatformError("operação ASR desconhecida")
            if event is not None:
                destination.write(
                    json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    + b"\n"
                )
                destination.flush()
    finally:
        backend.close()


def _pcm_to_float(pcm: bytes | bytearray) -> array[float]:
    values = array("h")
    values.frombytes(pcm)
    if sys.byteorder != "little":
        values.byteswap()
    return array("f", (value / 32768.0 for value in values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casulo-whisper-worker")
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--partial-ms", type=int, default=2000)
    parser.add_argument("--use-gpu", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.partial_ms <= 0:
        raise SystemExit("--partial-ms precisa ser positivo")
    backend = WhisperNativeBackend(
        args.library,
        args.model,
        threads=args.threads,
        use_gpu=args.use_gpu,
    )
    try:
        return serve(
            sys.stdin.buffer,
            sys.stdout.buffer,
            backend,
            partial_interval_samples=SAMPLE_RATE * args.partial_ms // 1000,
        )
    except PlatformError as error:
        print(f"casulo-whisper-worker: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
