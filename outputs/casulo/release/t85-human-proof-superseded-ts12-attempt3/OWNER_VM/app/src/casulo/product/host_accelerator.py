from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Callable


class AcceleratorProtocolError(ValueError):
    pass


ALLOWED_FRAME_TYPES = frozenset({"guide.turn", "job.cancel", "presence.ping"})


@dataclass(frozen=True, slots=True)
class AcceleratorHandshake:
    protocol_version: str
    session_nonce: str
    guest_build_hash: str
    service_build_hash: str
    model_hash: str
    adapter_hash: str
    max_frame_bytes: int = 4096
    max_queue: int = 4

    def __post_init__(self) -> None:
        hashes = (self.guest_build_hash, self.service_build_hash, self.model_hash, self.adapter_hash)
        if self.protocol_version != "casulo-host-accelerator/1.0":
            raise AcceleratorProtocolError("protocol version incompatível")
        if len(self.session_nonce) < 16 or any(len(value) != 64 for value in hashes):
            raise AcceleratorProtocolError("handshake incompleto")
        if not 1 <= self.max_frame_bytes <= 65536 or not 1 <= self.max_queue <= 16:
            raise AcceleratorProtocolError("limites de sessão inválidos")


@dataclass(frozen=True, slots=True)
class AcceleratorFrame:
    frame_type: str
    request_id: str
    generation: int
    payload: bytes
    payload_sha256: str
    deadline_monotonic_ns: int

    @classmethod
    def create(cls, frame_type: str, request_id: str, generation: int, payload: bytes, deadline_monotonic_ns: int) -> "AcceleratorFrame":
        return cls(frame_type, request_id, generation, bytes(payload), hashlib.sha256(payload).hexdigest(), deadline_monotonic_ns)


@dataclass(frozen=True, slots=True)
class AcceleratorReceipt:
    request_id: str
    generation: int
    input_sha256: str
    output_sha256: str
    status: str


class HostAcceleratorService:
    """Bounded first-party host bridge: no shell, paths, files or generic RPC."""

    def __init__(self, handshake: AcceleratorHandshake, handler: Callable[[str, bytes], bytes]) -> None:
        self.handshake = handshake
        self.handler = handler
        self._seen: set[str] = set()
        self._cancelled_generation = -1

    def cancel_through(self, generation: int) -> None:
        self._cancelled_generation = max(self._cancelled_generation, generation)

    def handle(self, frame: AcceleratorFrame, *, now_monotonic_ns: int | None = None) -> tuple[bytes, AcceleratorReceipt]:
        now = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        if frame.frame_type not in ALLOWED_FRAME_TYPES:
            raise AcceleratorProtocolError("frame type fora da allowlist")
        if not frame.request_id or frame.request_id in self._seen:
            raise AcceleratorProtocolError("request replay ou identidade vazia")
        if frame.generation < 0 or frame.generation <= self._cancelled_generation:
            raise AcceleratorProtocolError("resultado stale/cancelado")
        if now > frame.deadline_monotonic_ns:
            raise AcceleratorProtocolError("deadline expirado")
        if not frame.payload or len(frame.payload) > self.handshake.max_frame_bytes:
            raise AcceleratorProtocolError("payload fora dos limites")
        actual = hashlib.sha256(frame.payload).hexdigest()
        if not hmac.compare_digest(actual, frame.payload_sha256):
            raise AcceleratorProtocolError("payload hash inválido")
        # Reject path/shell-shaped keys at the protocol boundary even though
        # handlers only receive bytes and never a command line.
        try:
            envelope = json.loads(frame.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AcceleratorProtocolError("payload JSON inválido") from error
        if not isinstance(envelope, dict) or any(key in envelope for key in ("command", "shell", "host_path", "device")):
            raise AcceleratorProtocolError("payload contém campo proibido")
        self._seen.add(frame.request_id)
        output = bytes(self.handler(frame.frame_type, frame.payload))
        if len(output) > self.handshake.max_frame_bytes:
            raise AcceleratorProtocolError("resposta fora dos limites")
        return output, AcceleratorReceipt(frame.request_id, frame.generation, actual, hashlib.sha256(output).hexdigest(), "PASS")
