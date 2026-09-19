"""Authenticated loopback ASR/TTS, bounded one-shot children, no audio files."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import io
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .contracts import FamilyBackpressureError, FamilyResourceError, FamilyUnavailableError
from .model_gate import _available_physical_memory, _process_memory
from .bounded_http import BoundedThreadingHTTPServer, discard_unread_body


class VoiceCancelled(FamilyUnavailableError):
    pass


def wav_to_pcm(raw: bytes) -> bytes:
    if len(raw) > 640128:
        raise ValueError("audio exceeds 20 seconds")
    with wave.open(io.BytesIO(raw), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError("PCM16 mono 16kHz required")
        if not 1600 <= audio.getnframes() <= 320000 or audio.getcomptype() != "NONE":
            raise ValueError("audio duration invalid")
        pcm = audio.readframes(320001)
        if len(pcm) != audio.getnframes() * 2:
            raise ValueError("truncated audio")
        return pcm


def pcm_to_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)
    return output.getvalue()


class LocalVoiceService:
    def __init__(self, library: Path, model: Path, *, resource_probe=None):
        self.library, self.model = library.resolve(), model.resolve()
        self.resource_probe = resource_probe or self._resources
        self._key = secrets.token_urlsafe(32)
        self._slot = threading.Lock()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._child = None
        self.state = "STOPPED"
        self.receipts = []
        self.samples = []
        self._operation_id = None
        self._closed = False
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):  # noqa: N802
                if not hmac.compare_digest(self.headers.get("Authorization", ""),
                                           "Bearer " + service._key):
                    discard_unread_body(self, 8192)
                    self.send_error(401)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                    maximum = 640128 if self.path == "/asr" else 8192
                    if self.path not in {"/asr", "/tts"} or not 0 < length <= maximum:
                        raise ValueError("voice payload invalid")
                    self.connection.settimeout(5)
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError("voice body truncated")
                    output = service._execute(self.path, raw,
                                              self.headers.get("X-Operation-ID", ""))
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(output)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(output)
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception as error:
                    self.send_error(429 if isinstance(error, FamilyBackpressureError) else 503,
                                    type(error).__name__)

        self._server = BoundedThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="cleo-voice-loopback", daemon=True)

    @property
    def address(self):
        return self._server.server_address

    def start(self):
        if self.state != "STOPPED" or self._closed:
            raise FamilyUnavailableError("voice second instance denied")
        self.state = "STARTING"
        self.resource_probe()
        for path in (self.library, self.model):
            if not path.is_file():
                raise FamilyUnavailableError("voice dependency absent")
        self._thread.start()
        self.state = "READY"

    def _resources(self):
        ram = _available_physical_memory()
        disk = shutil.disk_usage(self.model).free
        if ram is None or ram < 1024**3 or disk < 30 * 1024**3:
            raise FamilyResourceError("VOICE_RESOURCE_FLOOR")
        with self._lock:
            child = self._child
        memory = _process_memory(os.getpid())
        child_memory = {} if child is None else _process_memory(child.pid)
        sample = {"at": time.time(), "available_ram_bytes": ram,
                  "disk_free_bytes": disk, "runner_working_set_bytes": memory.get("working_set_bytes"),
                  "voice_working_set_bytes": child_memory.get("working_set_bytes", 0)}
        self.samples.append(sample)
        del self.samples[:-4096]
        return sample

    def call(self, stage, raw, cancelled=lambda: False):
        if stage not in {"asr", "tts"} or self._closed:
            raise FamilyUnavailableError("voice unavailable")
        operation = secrets.token_hex(16)
        done = threading.Event()
        connection = http.client.HTTPConnection(*self.address, timeout=125)

        def monitor():
            while not done.wait(0.025):
                if cancelled():
                    self.cancel(operation)

        watcher = threading.Thread(target=monitor, name="cleo-voice-cancel", daemon=True)
        watcher.start()
        try:
            if cancelled():
                raise VoiceCancelled("VOICE_CANCELLED")
            connection.request("POST", "/" + stage, raw,
                               {"Authorization": "Bearer " + self._key,
                                "X-Operation-ID": operation})
            response = connection.getresponse()
            output = response.read(1920129)
            if cancelled():
                raise VoiceCancelled("VOICE_CANCELLED")
            if response.status != 200 or len(output) > 1920128:
                raise FamilyUnavailableError("VOICE_STAGE_FAILED")
            return output
        finally:
            done.set()
            connection.close()
            watcher.join(2)
            if watcher.is_alive():
                raise FamilyUnavailableError("VOICE_MONITOR_LEAK")

    def cancel(self, operation=None):
        with self._lock:
            if operation is None or self._operation_id == operation:
                self._cancel.set()

    def _execute(self, stage, raw, operation):
        if not self._slot.acquire(blocking=False):
            raise FamilyBackpressureError("VOICE_BUSY")
        started = time.monotonic()
        result = "FAILED"
        child = None
        reader = writer = None
        overflow = threading.Event()
        output = bytearray()
        try:
            with self._lock:
                if self._closed:
                    raise FamilyUnavailableError("voice closed")
                self._operation_id = operation
                self._cancel.clear()
                self.state = "BUSY"
            self.resource_probe()
            if stage == "/asr":
                payload = wav_to_pcm(raw)
                command = [sys.executable, "-m", "casulo.family.voice_worker",
                           str(self.library), str(self.model)]
                cap = 8192
            else:
                text = raw.decode("utf-8")
                if not 1 <= len(text) <= 2048 or "\x00" in text:
                    raise ValueError("final answer exceeds TTS bounds")
                payload = raw
                command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                           str(Path(__file__).with_name("voice_tts.ps1"))]
                cap = 1920000
            child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with self._lock:
                self._child = child

            def read_output():
                while chunk := child.stdout.read(4096):
                    if len(output) + len(chunk) > cap:
                        overflow.set()
                        return
                    output.extend(chunk)

            def write_input():
                try:
                    child.stdin.write(payload)
                    child.stdin.flush()
                except (OSError, ValueError):
                    pass
                finally:
                    child.stdin.close()

            reader = threading.Thread(target=read_output, name="cleo-voice-output", daemon=True)
            writer = threading.Thread(target=write_input, name="cleo-voice-input", daemon=True)
            reader.start()
            writer.start()
            while child.poll() is None:
                self.resource_probe()
                if self._cancel.wait(0.1):
                    raise VoiceCancelled("VOICE_CANCELLED")
                if overflow.is_set() or time.monotonic() - started > 120:
                    raise FamilyUnavailableError("VOICE_BOUND_EXCEEDED")
            reader.join(2)
            writer.join(2)
            if child.returncode != 0 or overflow.is_set() or not output:
                raise FamilyUnavailableError("VOICE_CHILD_FAILED")
            if self._cancel.is_set():
                raise VoiceCancelled("VOICE_CANCELLED")
            result = "COMPLETED"
            return bytes(output) if stage == "/asr" else pcm_to_wav(bytes(output))
        except VoiceCancelled:
            result = "CANCELLED"
            raise
        finally:
            if child is not None:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(5)
                for thread in (writer, reader):
                    if thread:
                        thread.join(5)
                for pipe in (child.stdin, child.stdout):
                    if pipe:
                        pipe.close()
            self.receipts.append({"stage": stage, "result": result,
                                  "duration_ms": round((time.monotonic()-started)*1000, 3),
                                  "pid": None if child is None else child.pid,
                                  "exit_code": None if child is None else child.returncode,
                                  "input_bytes": len(raw), "output_bytes": len(output),
                                  "output_sha256": hashlib.sha256(output).hexdigest(),
                                  "audio_disk_files": 0})
            del self.receipts[:-128]
            output.clear()
            with self._lock:
                self._child = None
                self._operation_id = None
                self.state = "STOPPED" if self._closed else "READY"
            self._slot.release()

    def close(self):
        with self._lock:
            self._closed = True
            self._cancel.set()
            self.state = "DRAINING"
        if self._thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        self._thread.join(5) if self._thread.ident else None
        if not self._slot.acquire(timeout=10):
            raise FamilyUnavailableError("VOICE_PROCESS_LEAK")
        self._slot.release()
        self.state = "STOPPED"
