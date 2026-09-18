from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


CONTRACT_VERSION = "casulo.family/1.0"
MAX_MESSAGE_CHARS = 8_192
IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class FamilyContractError(ValueError):
    pass


class FamilyAuthorizationError(PermissionError):
    pass


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class EventKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    STARTED = "STARTED"
    DELTA = "DELTA"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


TERMINAL_KINDS = frozenset(
    {EventKind.COMPLETED, EventKind.CANCELLED, EventKind.FAILED}
)


def _validate_identifier(value: str, label: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise FamilyContractError(f"{label} inválido")
    return value


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: str
    device_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.user_id, "user_id")
        _validate_identifier(self.device_id, "device_id")


@dataclass(frozen=True, slots=True)
class ChatRequest:
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.message, str):
            raise FamilyContractError("message deve ser texto")
        if not self.message.strip():
            raise FamilyContractError("message vazio")
        if len(self.message) > MAX_MESSAGE_CHARS:
            raise FamilyContractError("message excede o limite")
        if "\x00" in self.message:
            raise FamilyContractError("message contém NUL")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ChatRequest:
        if set(value) != {"message"}:
            raise FamilyContractError("payload deve conter somente message")
        return cls(message=value["message"])


@dataclass(frozen=True, slots=True)
class JobEvent:
    job_id: str
    correlation_id: str
    sequence: int
    kind: EventKind
    timestamp_utc: str
    payload: Mapping[str, Any]

    @property
    def terminal(self) -> bool:
        return self.kind in TERMINAL_KINDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_VERSION,
            "job_id": self.job_id,
            "correlation_id": self.correlation_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "timestamp_utc": self.timestamp_utc,
            "payload": dict(self.payload),
        }
