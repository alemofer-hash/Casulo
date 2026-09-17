from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Any, Callable, Protocol

from .platform_contracts import PlatformError
from .voice_duplex import TtsSession


class PcmOutputSession(Protocol):
    def write(self, pcm_s16le: bytes) -> None: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


class PcmOutput(Protocol):
    def open(self, *, sample_rate: int, channels: int) -> PcmOutputSession: ...


class _SoundDeviceOutputSession:
    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._closed = False
        self._lock = threading.Lock()
        self._stream.start()

    def write(self, pcm_s16le: bytes) -> None:
        with self._lock:
            if not self._closed:
                self._stream.write(pcm_s16le)

    def cancel(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._stream.abort()
            self._stream.close()
            self._closed = True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._stream.stop()
            self._stream.close()
            self._closed = True


class SoundDevicePcmOutput:
    """Lazy hosted adapter; no package import or device access at module load."""

    def open(self, *, sample_rate: int, channels: int) -> PcmOutputSession:
        import sounddevice  # type: ignore[import-not-found]

        if sample_rate <= 0 or channels != 1:
            raise PlatformError("output hosted inicial exige PCM16 mono")
        stream = sounddevice.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
        )
        return _SoundDeviceOutputSession(stream)


class _WindowsPcmSpeechSession:
    def __init__(self, process: Any, output: PcmOutputSession) -> None:
        if process.stdout is None:
            raise PlatformError("TTS não abriu stream PCM")
        self._process = process
        self._stdout = process.stdout
        self._stderr = process.stderr
        self._output = output
        self._done = threading.Event()
        self._cancelled = threading.Event()
        self._error: str | None = None
        self._stderr_bytes = bytearray()
        self._stderr_pump = threading.Thread(target=self._pump_stderr, daemon=True)
        self._pump = threading.Thread(target=self._pump_pcm, daemon=True)
        self._stderr_pump.start()
        self._pump.start()

    @property
    def active(self) -> bool:
        return not self._done.is_set()

    @property
    def error(self) -> str | None:
        return self._error

    def cancel(self) -> None:
        if self._done.is_set():
            return
        self._cancelled.set()
        # Stop acoustic output first; process termination can take longer.
        self._output.cancel()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1.0)
        self._done.set()
        self._pump.join(timeout=1.0)
        self._stderr_pump.join(timeout=1.0)

    def _pump_pcm(self) -> None:
        try:
            while not self._cancelled.is_set():
                chunk = self._stdout.read(4096)
                if not chunk:
                    break
                if self._cancelled.is_set():
                    break
                if len(chunk) % 2:
                    raise PlatformError("TTS produziu frame PCM16 truncado")
                self._output.write(chunk)
        finally:
            returncode = self._process.wait()
            self._stderr_pump.join(timeout=1.0)
            if returncode != 0 and not self._cancelled.is_set():
                self._error = self._stderr_bytes.decode("utf-8", "replace").strip() or (
                    f"TTS encerrou com código {returncode}"
                )
            if not self._cancelled.is_set():
                self._output.close()
            self._done.set()

    def _pump_stderr(self) -> None:
        if self._stderr is None:
            return
        while len(self._stderr_bytes) < 16 * 1024:
            chunk = self._stderr.read(min(4096, 16 * 1024 - len(self._stderr_bytes)))
            if not chunk:
                return
            self._stderr_bytes.extend(chunk)


class WindowsBufferedPcmTts:
    """System.Speech -> buffered PCM16. Hosted fallback, not redistributed."""

    locale = "pt-BR"
    streaming_pcm = False
    sample_rate = 16_000

    def __init__(
        self,
        *,
        output: PcmOutput | None = None,
        voice: str = "Microsoft Maria Desktop",
        process_factory: Callable[..., Any] | None = None,
    ) -> None:
        if sys.platform != "win32" and process_factory is None:
            raise PlatformError("System.Speech exige Windows")
        self.output = output or SoundDevicePcmOutput()
        self.voice = voice
        self._process_factory = process_factory or subprocess.Popen

    def speak(self, text: str) -> TtsSession:
        normalized = text.strip()
        if not normalized or len(normalized.encode("utf-8")) > 32 * 1024:
            raise PlatformError("texto TTS vazio ou acima do limite")
        environment = os.environ.copy()
        environment["CASULO_TTS_TEXT"] = normalized
        environment["CASULO_TTS_VOICE"] = self.voice
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=[System.Speech.Synthesis.SpeechSynthesizer]::new();"
            "$s.SelectVoice($env:CASULO_TTS_VOICE);"
            "$f=[System.Speech.AudioFormat.SpeechAudioFormatInfo]::new("
            "16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
            "[System.Speech.AudioFormat.AudioChannel]::Mono);"
            "$m=[System.IO.MemoryStream]::new();$s.SetOutputToAudioStream($m,$f);"
            "$s.Speak($env:CASULO_TTS_TEXT);$b=$m.ToArray();"
            "[Console]::OpenStandardOutput().Write($b,0,$b.Length);"
            "$s.SetOutputToNull();$m.Dispose();$s.Dispose()"
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = self._process_factory(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        try:
            output = self.output.open(sample_rate=self.sample_rate, channels=1)
            return _WindowsPcmSpeechSession(process, output)
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
            raise


class _WindowsDirectSpeechSession:
    def __init__(self, process: Any) -> None:
        self._process = process
        self._cancelled = False

    @property
    def active(self) -> bool:
        return self._process.poll() is None

    @property
    def error(self) -> str | None:
        returncode = self._process.poll()
        if returncode in {None, 0} or self._cancelled:
            return None
        if self._process.stderr is None:
            return f"TTS direto encerrou com código {returncode}"
        detail = self._process.stderr.read(16 * 1024).decode("utf-8", "replace").strip()
        return detail or f"TTS direto encerrou com código {returncode}"

    def cancel(self) -> None:
        if self._process.poll() is not None:
            return
        self._cancelled = True
        self._process.terminate()
        try:
            self._process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=0.5)


class WindowsDirectStreamingTts:
    """Hosted SAPI playback that starts before synthesis ends and is kill-cancelable."""

    locale = "pt-BR"
    streaming_pcm = False
    streaming_playback = True
    redistributed = False

    def __init__(
        self,
        *,
        voice: str = "Microsoft Maria Desktop",
        process_factory: Callable[..., Any] | None = None,
    ) -> None:
        if sys.platform != "win32" and process_factory is None:
            raise PlatformError("System.Speech exige Windows")
        self.voice = voice
        self._process_factory = process_factory or subprocess.Popen

    def speak(self, text: str) -> TtsSession:
        normalized = text.strip()
        if not normalized or len(normalized.encode("utf-8")) > 32 * 1024:
            raise PlatformError("texto TTS vazio ou acima do limite")
        environment = os.environ.copy()
        environment["CASULO_TTS_TEXT"] = normalized
        environment["CASULO_TTS_VOICE"] = self.voice
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=[System.Speech.Synthesis.SpeechSynthesizer]::new();"
            "$s.SelectVoice($env:CASULO_TTS_VOICE);"
            "$s.SetOutputToDefaultAudioDevice();"
            "$s.Speak($env:CASULO_TTS_TEXT);$s.Dispose()"
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = self._process_factory(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        return _WindowsDirectSpeechSession(process)
