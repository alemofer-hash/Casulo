from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class PlatformError(RuntimeError):
    pass


@runtime_checkable
class Clock(Protocol):
    def monotonic_ns(self) -> int: ...

    def utc_timestamp(self) -> str: ...


@runtime_checkable
class Storage(Protocol):
    def read(self, relative: str) -> bytes: ...

    def write_atomic(self, relative: str, payload: bytes) -> None: ...

    def list(self, relative: str) -> tuple[str, ...]: ...

    def delete(self, relative: str) -> None: ...


@runtime_checkable
class AudioCapture(Protocol):
    def poll(self) -> "VoiceEvent | None": ...


@runtime_checkable
class AudioPlayback(Protocol):
    def speak(self, text: str) -> str: ...

    def cancel(self, playback_id: str) -> bool: ...


@runtime_checkable
class DisplayDevice(Protocol):
    def present(self, frame: "DisplayFrame") -> None: ...


@runtime_checkable
class ProcessSandbox(Protocol):
    def available(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class VoiceEvent:
    event_id: str
    transcript: str
    locale: str
    final: bool

    def __post_init__(self) -> None:
        if not self.event_id or not self.transcript.strip():
            raise PlatformError("evento de voz precisa de identidade e transcrição")
        if self.locale != "pt-BR":
            raise PlatformError("slice hosted inicial aceita apenas pt-BR")


@dataclass(frozen=True, slots=True)
class DisplayFrame:
    state: str
    semantic_color: str
    certainty: str
    summary: str
    sequence: int


class SystemClock:
    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def utc_timestamp(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LocalStorage:
    """Storage hosted confinado a uma raiz explicitamente fornecida."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise PlatformError("path traversal negado pelo Storage hosted") from error
        return candidate

    def read(self, relative: str) -> bytes:
        return self._resolve(relative).read_bytes()

    def write_atomic(self, relative: str, payload: bytes) -> None:
        destination = self._resolve(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, destination)

    def list(self, relative: str) -> tuple[str, ...]:
        directory = self._resolve(relative)
        if not directory.exists():
            return ()
        if not directory.is_dir():
            raise PlatformError("list exige diretório no Storage hosted")
        return tuple(
            sorted(
                path.relative_to(self.root).as_posix()
                for path in directory.iterdir()
                if path.is_file()
            )
        )

    def delete(self, relative: str) -> None:
        target = self._resolve(relative)
        if target.is_dir():
            if any(target.iterdir()):
                raise PlatformError("delete de diretório não vazio é negado")
            target.rmdir()
        elif target.exists():
            target.unlink()


class SyntheticAudioCapture:
    """Fila determinística do Sprint 2; não é apresentada como ASR."""

    def __init__(self) -> None:
        self._events: list[VoiceEvent] = []

    def emit(self, event: VoiceEvent) -> None:
        self._events.append(event)

    def poll(self) -> VoiceEvent | None:
        return self._events.pop(0) if self._events else None


class BufferedAudioPlayback:
    def __init__(self) -> None:
        self.active: dict[str, str] = {}
        self._sequence = 0

    def speak(self, text: str) -> str:
        self._sequence += 1
        playback_id = f"playback:{self._sequence}"
        self.active[playback_id] = text
        return playback_id

    def cancel(self, playback_id: str) -> bool:
        return self.active.pop(playback_id, None) is not None


class ConsoleDisplay:
    def __init__(self, *, emit_ansi: bool = True) -> None:
        self.frames: list[DisplayFrame] = []
        self.emit_ansi = emit_ansi

    def present(self, frame: DisplayFrame) -> None:
        self.frames.append(frame)
        if not self.emit_ansi:
            return
        color = "\x1b[38;5;214m" if frame.semantic_color == "amber" else "\x1b[38;5;110m"
        print(f"\x1b[40m{color}CASULO · {frame.state}\x1b[0m  {frame.summary}")


class DisabledProcessSandbox:
    """Fail-closed até o sandbox real do materializador existir."""

    def available(self) -> bool:
        return False
