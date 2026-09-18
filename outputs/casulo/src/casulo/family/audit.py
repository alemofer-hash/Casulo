from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping


AUDIT_SCHEMA = "casulo.family.audit/1.0"
_FORBIDDEN_KEYS = {
    "content",
    "credential",
    "message",
    "password",
    "prompt",
    "response",
    "secret",
    "token",
}
_ALLOWED_MESSAGE_METADATA = {"message_chars", "message_sha256"}


class AuditIntegrityError(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _validate_fields(fields: Mapping[str, Any]) -> None:
    for key in fields:
        normalized = key.casefold()
        if normalized in _ALLOWED_MESSAGE_METADATA:
            continue
        if normalized in _FORBIDDEN_KEYS or normalized.endswith("_text"):
            raise AuditIntegrityError(f"campo sensível recusado: {key}")
        if any(item in normalized for item in ("password", "credential", "secret")):
            raise AuditIntegrityError(f"campo sensível recusado: {key}")


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._head = self._verify_existing()

    def append(
        self,
        *,
        timestamp_utc: str,
        event_type: str,
        correlation_id: str,
        user_id: str,
        device_id: str,
        fields: Mapping[str, Any],
    ) -> str:
        _validate_fields(fields)
        with self._lock:
            record: dict[str, Any] = {
                "schema": AUDIT_SCHEMA,
                "timestamp_utc": timestamp_utc,
                "event_type": event_type,
                "correlation_id": correlation_id,
                "user_id": user_id,
                "device_id": device_id,
                "fields": dict(fields),
                "previous_hash": self._head,
            }
            record_hash = hashlib.sha256(_canonical(record)).hexdigest()
            record["record_hash"] = record_hash
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_canonical(record).decode("utf-8") + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._head = record_hash
            return record_hash

    def _verify_existing(self) -> str | None:
        if not self.path.exists():
            return None
        previous: str | None = None
        for number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                record = json.loads(line)
                observed = record.pop("record_hash")
            except (json.JSONDecodeError, KeyError) as error:
                raise AuditIntegrityError(f"registro inválido na linha {number}") from error
            if record.get("previous_hash") != previous:
                raise AuditIntegrityError(f"cadeia quebrada na linha {number}")
            expected = hashlib.sha256(_canonical(record)).hexdigest()
            if observed != expected:
                raise AuditIntegrityError(f"hash inválido na linha {number}")
            previous = observed
        return previous
