"""Half-duplex voice turns. Authentication is rechecked at every boundary."""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from dataclasses import replace

from .contracts import (ChatRequest, EventKind, FamilyAuthorizationError,
                        FamilyBackpressureError, FamilyUnavailableError)
from .voice_service import VoiceCancelled, wav_to_pcm


@dataclass
class VoiceTurn:
    auth: object
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "IDLE"
    cancellation: threading.Event = field(default_factory=threading.Event)
    audio: bytes = b""
    states: list = field(default_factory=list)
    job_id: str | None = None
    policy_request: object = None
    deadline: float = field(default_factory=lambda: time.monotonic() + 180)
    result: str | None = None
    metadata: dict = field(default_factory=dict)


class VoiceCoordinator:
    def __init__(self, runtime, service):
        if runtime.persona_resolver is None:
            raise ValueError("voice requires principal/persona resolver")
        self.runtime, self.service = runtime, service
        self.resolver = runtime.persona_resolver
        self._lock = threading.RLock()
        self._turns = {}
        self._active = None
        self._worker = None
        self._closed = threading.Event()
        self._janitor = threading.Thread(target=self._maintenance,
                                         name="cleo-voice-expiry", daemon=True)
        self._janitor.start()

    def _state(self, turn, state):
        with self._lock:
            turn.state = state
            turn.states.append({"state": state, "at": time.monotonic()})

    def submit(self, auth, audio):
        self.resolver.authorize(auth)
        wav_to_pcm(audio)
        with self._lock:
            if self._closed.is_set():
                raise FamilyUnavailableError("VOICE_STOPPED")
            if self._active is not None or (self._worker and self._worker.is_alive()):
                raise FamilyBackpressureError("VOICE_HALF_DUPLEX_BUSY")
            if len(self._turns) >= 16:
                raise FamilyBackpressureError("VOICE_RECEIPT_CAPACITY")
            self.runtime.supervisor.admission_sample()
            turn = VoiceTurn(auth)
            self._turns[turn.turn_id] = turn
            self._active = turn.turn_id
            self._worker = threading.Thread(target=self._run, args=(turn, audio),
                                            name="cleo-voice-turn", daemon=True)
            self._worker.start()
            return turn.turn_id

    def _invalid(self, turn):
        if turn.cancellation.is_set() or self._closed.is_set():
            return True
        try:
            self.resolver.authorize(turn.auth)
            return bool(turn.policy_request and not self.resolver.valid_request(
                turn.auth, turn.policy_request))
        except FamilyAuthorizationError:
            return True

    def _check(self, turn):
        if self._invalid(turn):
            raise VoiceCancelled("VOICE_CANCELLED")

    def _run(self, turn, audio):
        started = time.monotonic()
        text = answer = ""
        try:
            self._check(turn)
            self._state(turn, "TRANSCRIBING")
            transcript = self.service.call("asr", audio, lambda: self._invalid(turn))
            audio = b""
            text = transcript.decode("utf-8").strip()
            transcript = b""
            self._state(turn, "RESOLVING_PRINCIPAL")
            self._check(turn)
            self._state(turn, "RESOLVING_PERSONA")
            _, metadata = self.resolver.resolve(turn.auth, text)
            turn.metadata.update(metadata)
            self._state(turn, "THINKING")
            job = self.runtime.submit(turn.auth, ChatRequest(text))
            turn.job_id, turn.policy_request = job.job_id, job.request
            text = ""
            completed = False
            for event in self.runtime.stream_events(turn.auth, job.job_id, timeout=300):
                self._check(turn)
                if event.kind == EventKind.DELTA:
                    answer += event.payload["text"]
                    if len(answer) > 2048:
                        raise FamilyUnavailableError("FINAL_RESPONSE_BOUND")
                if event.kind == EventKind.COMPLETED:
                    completed = True
                    turn.metadata["model_metrics"] = dict(event.payload)
                elif event.kind == EventKind.CANCELLED:
                    raise VoiceCancelled("MODEL_NOT_COMPLETED")
                elif event.kind == EventKind.FAILED:
                    raise FamilyUnavailableError("MODEL_FAILED")
            self._check(turn)
            if not completed or not answer.strip():
                raise FamilyUnavailableError("NO_AUTHORIZED_FINAL_RESPONSE")
            # Do not speak raw markup, hidden reasoning, injected role delimiters,
            # or unbounded output. This is a fail-closed output contract, not a
            # claim that a small model semantically filters every hostile phrase.
            if any(marker in answer.lower() for marker in
                   ("<think", "</think", "<|", "system_prompt", "explicit_sensuality")):
                raise FamilyUnavailableError("FINAL_RESPONSE_POLICY_DENIED")
            self._state(turn, "SYNTHESIZING")
            output = self.service.call("tts", answer.encode("utf-8"),
                                       lambda: self._invalid(turn))
            self._check(turn)
            with self._lock:
                turn.audio = output
                turn.deadline = time.monotonic() + 30
                turn.metadata.update({"audio_bytes": len(output),
                                      "audio_sha256": hashlib.sha256(output).hexdigest()})
            self._state(turn, "PLAYING")
            turn.result = "READY_FOR_PLAYBACK"
        except Exception as error:
            turn.result = "CANCELLED" if self._invalid(turn) or isinstance(
                error, VoiceCancelled) else "FAILED"
            turn.metadata["reason_code"] = type(error).__name__
            turn.audio = b""
            self._state(turn, "IDLE")
        finally:
            audio, text, answer = b"", "", ""
            if turn.job_id:
                self.runtime.store.cancel(turn.job_id, turn.auth, requested_by="voice_cleanup")
                # Wait for the owning model worker to leave its finally block.
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    with self.runtime._active_lock:
                        active = self.runtime._active_job
                    if active is None or active.job_id != turn.job_id:
                        break
                    time.sleep(0.025)
                else:
                    turn.result = "FAILED"
                    turn.metadata["reason_code"] = "MODEL_CLEANUP_TIMEOUT"
                    turn.audio = b""
                self.runtime.store.forget(turn.job_id)
            if turn.policy_request is not None:
                turn.policy_request = replace(turn.policy_request,
                                              message="[EPHEMERAL_DISCARDED]", system_prompt="")
            turn.metadata["duration_ms"] = round((time.monotonic()-started)*1000, 3)
            with self._lock:
                if turn.result != "READY_FOR_PLAYBACK":
                    self._active = None
                    turn.deadline = time.monotonic() + 30

    def _owned(self, auth, turn_id, *, authorize=True):
        if authorize:
            self.resolver.authorize(auth)
        turn = self._turns.get(turn_id)
        if turn is None:
            raise KeyError(turn_id)
        if turn.auth != auth:
            raise FamilyAuthorizationError("VOICE_TURN_DENIED")
        return turn

    def snapshot(self, auth, turn_id):
        with self._lock:
            turn = self._owned(auth, turn_id)
            return {"turn_id": turn.turn_id, "state": turn.state, "result": turn.result,
                    "states": list(turn.states), **turn.metadata}

    def take_audio(self, auth, turn_id):
        with self._lock:
            turn = self._owned(auth, turn_id)
            if self._invalid(turn) or turn.result != "READY_FOR_PLAYBACK" or not turn.audio:
                raise FamilyUnavailableError("AUDIO_NOT_READY")
            audio, turn.audio = turn.audio, b""
            return audio

    def cancel(self, auth, turn_id):
        with self._lock:
            # Authenticated ownership suffices to cancel after route downgrade.
            turn = self._owned(auth, turn_id, authorize=False)
            turn.cancellation.set()
            turn.audio = b""
            if turn.job_id:
                try:
                    self.runtime.store.cancel(turn.job_id, auth, requested_by="voice_cancel")
                except KeyError:
                    pass
            if turn.result == "READY_FOR_PLAYBACK":
                turn.result = "CANCELLED"
                self._state(turn, "IDLE")
                self._active = None

    def playback_finished(self, auth, turn_id):
        with self._lock:
            turn = self._owned(auth, turn_id)
            if turn.result != "READY_FOR_PLAYBACK":
                raise FamilyUnavailableError("PLAYBACK_NOT_READY")
            turn.audio = b""
            turn.result = "COMPLETED"
            self._state(turn, "IDLE")
            self._active = None

    def _maintenance(self):
        while not self._closed.wait(0.1):
            with self._lock:
                for key, turn in list(self._turns.items()):
                    if self._invalid(turn):
                        self.cancel(turn.auth, key)
                    if time.monotonic() >= turn.deadline:
                        self.cancel(turn.auth, key)
                        if self._active != key and not (self._worker and self._worker.is_alive()):
                            self._turns.pop(key, None)
                self.runtime.store.expire()

    def close(self):
        self._closed.set()
        with self._lock:
            for turn in self._turns.values():
                turn.cancellation.set()
                turn.audio = b""
        self.service.cancel()
        if self._worker:
            self._worker.join(20)
            if self._worker.is_alive():
                raise FamilyUnavailableError("VOICE_TURN_LEAK")
        self._janitor.join(3)
        self._turns.clear()
        self._active = None
