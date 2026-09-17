from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


AUTOMATED_SCHEMA = "casulo.monday-discovery-automated-event/1.0"
HUMAN_SCHEMA = "casulo.monday-discovery-human-note/1.0"
SESSION_SCHEMA = "casulo.monday-discovery-session/1.0"
SUMMARY_SCHEMA = "casulo.monday-discovery-summary/1.0"

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,159}$")
_HUMAN_CATEGORIES = frozenset(
    {
        "GENERAL",
        "VOICE",
        "CHEMISTRY",
        "MEMORY",
        "PROJECT_BLEED",
        "INTENT_ARTIFACT_DIVERGENCE",
        "CREATION",
        "VISUAL",
        "LATENCY",
        "BUG",
        "DESIRED_CHANGE",
        "SESSION_VERDICT",
    }
)
_SEVERITIES = frozenset({"UNASSESSED", "P0", "P1", "P2", "P3"})
_SENSITIVE_KEYS = frozenset(
    {"text", "content", "transcript", "prompt", "response", "secret", "token", "credential", "pcm", "raw_audio"}
)


class DiscoverySessionError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_payload(value: Any, *, key: str = "payload") -> Any:
    normalized_key = key.casefold()
    if normalized_key in _SENSITIVE_KEYS:
        raise DiscoverySessionError(f"campo sensivel negado em evento automatico: {key}")
    if isinstance(value, Mapping):
        return {str(item_key): _safe_payload(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise DiscoverySessionError("lista automatica excede limite")
        return [_safe_payload(item, key=key) for item in value]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise DiscoverySessionError("numero automatico nao finito")
        return value
    if isinstance(value, str):
        if len(value) > 1200 or "\x00" in value:
            raise DiscoverySessionError("string automatica invalida")
        return value
    raise DiscoverySessionError(f"tipo automatico nao suportado: {type(value).__name__}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def verify_chain(path: Path, *, hash_field: str, previous_field: str) -> dict[str, Any]:
    previous = "0" * 64
    records = _read_jsonl(path)
    for index, record in enumerate(records, start=1):
        if record.get(previous_field) != previous:
            return {"valid": False, "records": len(records), "failed_at": index, "reason": "previous_hash"}
        expected = str(record.get(hash_field, ""))
        unsigned = {key: value for key, value in record.items() if key != hash_field}
        actual = sha256_bytes(bytes.fromhex(previous) + canonical_json(unsigned))
        if expected != actual:
            return {"valid": False, "records": len(records), "failed_at": index, "reason": "record_hash"}
        previous = expected
    return {"valid": True, "records": len(records), "head": previous}


class DiscoverySessionRecorder:
    """Privacy-minimised, append-only observer for a Guilherme-owned session."""

    def __init__(self, root: str | Path, *, session_id: str, release_manifest_sha256: str) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        if not _ID.fullmatch(session_id):
            raise DiscoverySessionError("session_id invalido")
        if self.root.exists():
            raise DiscoverySessionError("session root ja existe; overwrite negado")
        if self.root.parent.exists() and self.root.parent.is_symlink():
            raise DiscoverySessionError("parent symlink negado")
        self.root.mkdir(parents=True)
        if self.root.is_symlink():
            raise DiscoverySessionError("session root symlink negado")
        self.session_id = session_id
        self.release_manifest_sha256 = release_manifest_sha256
        self.automated_path = self.root / "automated-events.jsonl"
        self.human_path = self.root / "human-notes.jsonl"
        self.session_path = self.root / "session.json"
        self.summary_path = self.root / "session-summary.json"
        self._started_ns = time.perf_counter_ns()
        self._event_lock = threading.Lock()
        self._human_lock = threading.Lock()
        self._automated_previous = "0" * 64
        self._human_previous = "0" * 64
        self._automated_count = 0
        self._human_count = 0
        metadata = {
            "schema": SESSION_SCHEMA,
            "session_id": session_id,
            "created_utc": datetime.now(UTC).isoformat(),
            "release_manifest_sha256": release_manifest_sha256,
            "source_separation": {"automated": "automated-events.jsonl", "human_opinion": "human-notes.jsonl"},
            "raw_audio_persisted": False,
            "transcripts_persisted_by_observer": False,
            "user_content_persisted_by_observer": False,
            "secrets_included": False,
            "physical_voice_authorized": False,
        }
        self.session_path.write_bytes(canonical_json(metadata) + b"\n")

    def record_automated(self, kind: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not _ID.fullmatch(kind):
            raise DiscoverySessionError("kind automatico invalido")
        safe = _safe_payload(dict(payload or {}))
        with self._event_lock:
            self._automated_count += 1
            unsigned = {
                "schema": AUTOMATED_SCHEMA,
                "session_id": self.session_id,
                "event_id": f"auto:{self._automated_count:06d}",
                "kind": kind,
                "created_utc": datetime.now(UTC).isoformat(),
                "monotonic_offset_ms": round((time.perf_counter_ns() - self._started_ns) / 1_000_000, 3),
                "provenance": "AUTOMATED_OBSERVER",
                "payload": safe,
                "previous_hash": self._automated_previous,
            }
            event_hash = sha256_bytes(bytes.fromhex(self._automated_previous) + canonical_json(unsigned))
            record = {**unsigned, "event_hash": event_hash}
            self._append(self.automated_path, record)
            self._automated_previous = event_hash
            return record

    def record_human_note(
        self,
        text: str,
        *,
        category: str,
        severity: str = "UNASSESSED",
        source_event_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        clean = " ".join(text.replace("\x00", "").split())
        category = category.strip().upper()
        severity = severity.strip().upper()
        if not clean or len(clean) > 4000:
            raise DiscoverySessionError("nota humana deve conter de 1 a 4000 caracteres")
        if category not in _HUMAN_CATEGORIES or severity not in _SEVERITIES:
            raise DiscoverySessionError("categoria ou severidade humana invalida")
        if any(not _ID.fullmatch(item) for item in source_event_ids):
            raise DiscoverySessionError("source event humano invalido")
        with self._human_lock:
            self._human_count += 1
            unsigned = {
                "schema": HUMAN_SCHEMA,
                "session_id": self.session_id,
                "note_id": f"human:{self._human_count:06d}",
                "created_utc": datetime.now(UTC).isoformat(),
                "provenance": "HUMAN_OPINION_GUILHERME",
                "consent": "EXPLICIT_NOTE_SUBMISSION",
                "category": category,
                "severity": severity,
                "text": clean,
                "source_event_ids": list(source_event_ids),
                "raw_audio_persisted": False,
                "previous_hash": self._human_previous,
            }
            note_hash = sha256_bytes(bytes.fromhex(self._human_previous) + canonical_json(unsigned))
            record = {**unsigned, "note_hash": note_hash}
            self._append(self.human_path, record)
            self._human_previous = note_hash
            return record

    def authorize_physical_voice(self, *, consent_sha256: str) -> None:
        metadata = json.loads(self.session_path.read_text(encoding="utf-8"))
        metadata["physical_voice_authorized"] = True
        metadata["physical_voice_consent_utc"] = datetime.now(UTC).isoformat()
        metadata["physical_voice_consent_sha256"] = consent_sha256
        temporary = self.session_path.with_suffix(".tmp")
        temporary.write_bytes(canonical_json(metadata) + b"\n")
        os.replace(temporary, self.session_path)
        self.record_automated("PHYSICAL_VOICE_CONSENT_GRANTED", {"consent_sha256": consent_sha256})

    def finalize(self, *, outcome: str, process_exit_code: int | None) -> dict[str, Any]:
        if self.summary_path.exists():
            return json.loads(self.summary_path.read_text(encoding="utf-8"))
        events = _read_jsonl(self.automated_path)
        human = _read_jsonl(self.human_path)

        def first_offset(kind: str) -> float | None:
            return next((float(item["monotonic_offset_ms"]) for item in events if item["kind"] == kind), None)

        states = sorted(
            {
                str(item["payload"]["visual_state"])
                for item in events
                if isinstance(item.get("payload"), dict) and item["payload"].get("visual_state")
            }
        )
        failures = [item["event_id"] for item in events if item["kind"] in {"RECOVERABLE_FAILURE", "INFRASTRUCTURE_EXPOSED", "TRACEBACK_EXPOSED", "COMPONENT_FAILURE"}]
        summary = {
            "schema": SUMMARY_SCHEMA,
            "session_id": self.session_id,
            "finalized_utc": datetime.now(UTC).isoformat(),
            "outcome": outcome,
            "process_exit_code": process_exit_code,
            "metrics": {
                "time_to_presence_ms": first_offset("PRESENCE_READY"),
                "time_to_substantive_content_ms": first_offset("SUBSTANTIVE_RESPONSE"),
                "user_turns": sum(item["kind"] == "USER_TURN" for item in events),
                "substantive_responses": sum(item["kind"] == "SUBSTANTIVE_RESPONSE" for item in events),
                "interruptions": sum(item["kind"] == "BARGE_IN" for item in events),
                "silence_threshold_events": sum(item["kind"] == "SILENCE_THRESHOLD" for item in events),
                "human_notes": len(human),
                "visual_states_visited": states,
                "infrastructure_or_traceback_events": failures,
            },
            "chains": {
                "automated": verify_chain(self.automated_path, hash_field="event_hash", previous_field="previous_hash"),
                "human": verify_chain(self.human_path, hash_field="note_hash", previous_field="previous_hash"),
            },
            "privacy": {
                "raw_audio_persisted": False,
                "transcripts_persisted_by_observer": False,
                "user_content_persisted_by_observer": False,
                "secrets_included": False,
            },
        }
        self.summary_path.write_bytes(canonical_json(summary) + b"\n")
        return summary

    @property
    def last_automated_event_id(self) -> str | None:
        return f"auto:{self._automated_count:06d}" if self._automated_count else None

    @staticmethod
    def _append(path: Path, record: Mapping[str, Any]) -> None:
        with path.open("ab", buffering=0) as stream:
            stream.write(canonical_json(record) + b"\n")
            os.fsync(stream.fileno())


__all__ = [
    "DiscoverySessionError",
    "DiscoverySessionRecorder",
    "verify_chain",
]
