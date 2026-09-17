from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import math
import re
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .domain import canonical_json, canonical_sha256
from .platform_contracts import Clock, Storage


MEMORY_EVENT_SCHEMA = "casulo.memory-event/1.0"
MEMORY_EXPORT_SCHEMA = "casulo.memory-export/1.0"
EVENT_FILE_RE = re.compile(r"^\d{20}-[0-9a-f]{64}\.json\.dpapi$")
TOKEN_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


class MemoryIntegrityError(RuntimeError):
    pass


class SecretBox(Protocol):
    production_safe: bool

    def seal(self, plaintext: bytes) -> bytes: ...

    def open(self, ciphertext: bytes) -> bytes: ...


class TestSecretBox:
    """Envelope explícito de teste; nunca elegível para dados reais."""

    production_safe = False

    def seal(self, plaintext: bytes) -> bytes:
        return b"TEST-ONLY\0" + base64.b64encode(plaintext)

    def open(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"TEST-ONLY\0"):
            raise MemoryIntegrityError("envelope de teste inválido")
        return base64.b64decode(ciphertext.split(b"\0", 1)[1], validate=True)


class DpapiSecretBox:
    """Criptografia hosted ligada ao usuário Windows via DPAPI."""

    production_safe = sys.platform == "win32"
    _FLAG_UI_FORBIDDEN = 0x1

    class _Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("DPAPI está disponível somente no Hosted Windows")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def seal(self, plaintext: bytes) -> bytes:
        source, source_buffer = self._source(plaintext)
        destination = self._Blob()
        ok = self._crypt32.CryptProtectData(
            ctypes.byref(source),
            "Casulo Living Memory",
            None,
            None,
            None,
            self._FLAG_UI_FORBIDDEN,
            ctypes.byref(destination),
        )
        del source_buffer
        return self._finish(ok, destination, "CryptProtectData")

    def open(self, ciphertext: bytes) -> bytes:
        source, source_buffer = self._source(ciphertext)
        destination = self._Blob()
        description = ctypes.c_wchar_p()
        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(source),
            ctypes.byref(description),
            None,
            None,
            None,
            self._FLAG_UI_FORBIDDEN,
            ctypes.byref(destination),
        )
        del source_buffer
        try:
            return self._finish(ok, destination, "CryptUnprotectData")
        finally:
            if description:
                self._kernel32.LocalFree(description)

    def _source(self, payload: bytes) -> tuple["DpapiSecretBox._Blob", Any]:
        buffer = ctypes.create_string_buffer(payload)
        return (
            self._Blob(
                len(payload),
                ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
            ),
            buffer,
        )

    def _finish(self, ok: int, destination: "DpapiSecretBox._Blob", name: str) -> bytes:
        if not ok:
            raise OSError(ctypes.get_last_error(), f"{name} falhou")
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            self._kernel32.LocalFree(destination.pbData)


@dataclass(frozen=True, slots=True)
class MemoryEvent:
    event_id: str
    sequence: int
    timestamp: str
    kind: str
    subject_id: str
    text: str
    payload: Mapping[str, Any]
    source_ids: tuple[str, ...]
    previous_hash: str | None
    event_hash: str
    schema: str = MEMORY_EVENT_SCHEMA

    def unsigned(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "text": self.text,
            "payload": dict(self.payload),
            "source_ids": list(self.source_ids),
            "previous_hash": self.previous_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned(), "event_hash": self.event_hash}

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        sequence: int,
        timestamp: str,
        kind: str,
        subject_id: str,
        text: str,
        payload: Mapping[str, Any],
        source_ids: tuple[str, ...],
        previous_hash: str | None,
    ) -> "MemoryEvent":
        unsigned = {
            "schema": MEMORY_EVENT_SCHEMA,
            "event_id": event_id,
            "sequence": sequence,
            "timestamp": timestamp,
            "kind": kind,
            "subject_id": subject_id,
            "text": text,
            "payload": dict(payload),
            "source_ids": list(source_ids),
            "previous_hash": previous_hash,
        }
        return cls(
            event_id=event_id,
            sequence=sequence,
            timestamp=timestamp,
            kind=kind,
            subject_id=subject_id,
            text=text,
            payload=dict(payload),
            source_ids=source_ids,
            previous_hash=previous_hash,
            event_hash=canonical_sha256(unsigned),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MemoryEvent":
        event = cls(
            event_id=str(value["event_id"]),
            sequence=int(value["sequence"]),
            timestamp=str(value["timestamp"]),
            kind=str(value["kind"]),
            subject_id=str(value["subject_id"]),
            text=str(value["text"]),
            payload=dict(value.get("payload", {})),
            source_ids=tuple(value.get("source_ids", [])),
            previous_hash=value.get("previous_hash"),
            event_hash=str(value["event_hash"]),
            schema=str(value.get("schema")),
        )
        if event.schema != MEMORY_EVENT_SCHEMA or canonical_sha256(event.unsigned()) != event.event_hash:
            raise MemoryIntegrityError("hash ou schema de evento inválido")
        return event


@dataclass(frozen=True, slots=True)
class MemoryHit:
    subject_id: str
    score: float
    summary: str
    event_ids: tuple[str, ...]
    latest_timestamp: str


@dataclass(frozen=True, slots=True)
class RecallAnswer:
    status: str
    answer: str
    candidates: tuple[MemoryHit, ...]
    provenance_event_ids: tuple[str, ...]


class LivingMemory:
    def __init__(
        self,
        *,
        storage: Storage,
        clock: Clock,
        secret_box: SecretBox,
        allow_test_encryption: bool = False,
    ) -> None:
        if not secret_box.production_safe and not allow_test_encryption:
            raise MemoryIntegrityError("criptografia não produtiva foi recusada")
        self.storage = storage
        self.clock = clock
        self.secret_box = secret_box
        self._lock = threading.RLock()
        self._events = self._load()
        self._rebuild()

    @property
    def events(self) -> tuple[MemoryEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        *,
        event_id: str,
        kind: str,
        subject_id: str,
        text: str,
        payload: Mapping[str, Any],
        source_ids: tuple[str, ...],
    ) -> MemoryEvent:
        with self._lock:
            if not event_id or any(item.event_id == event_id for item in self._events):
                raise MemoryIntegrityError("event_id vazio ou duplicado")
            if not subject_id or not source_ids:
                raise MemoryIntegrityError("memória exige subject e proveniência")
            sequence = len(self._events) + 1
            event = MemoryEvent.create(
                event_id=event_id,
                sequence=sequence,
                timestamp=self.clock.utc_timestamp(),
                kind=kind,
                subject_id=subject_id,
                text=text.strip(),
                payload=payload,
                source_ids=source_ids,
                previous_hash=self._events[-1].event_hash if self._events else None,
            )
            relative = f"memory/events/{sequence:020d}-{event.event_hash}.json.dpapi"
            self.storage.write_atomic(relative, self.secret_box.seal(canonical_json(event.to_dict())))
            self._events.append(event)
            self._rebuild()
            return event

    def search(self, query: str, *, limit: int = 5, project_id: str | None = None) -> tuple[MemoryHit, ...]:
        query_tokens = _tokens(query)
        query_vector = _vector(query_tokens)
        hits: list[MemoryHit] = []
        for subject_id, events in self._by_subject.items():
            scoped = [event for event in events if project_id is None or event.payload.get("project_id") == project_id]
            if not scoped:
                continue
            tokens = _tokens(" ".join(event.text for event in scoped))
            lexical = len(query_tokens & tokens) / max(1, len(query_tokens | tokens))
            vector = _cosine(query_vector, _vector(tokens))
            score = lexical * 0.65 + vector * 0.35
            if query_tokens and score <= 0:
                continue
            latest = scoped[-1]
            hits.append(
                MemoryHit(
                    subject_id=subject_id,
                    score=score,
                    summary=latest.text or str(latest.payload.get("name", subject_id)),
                    event_ids=tuple(event.event_id for event in scoped),
                    latest_timestamp=latest.timestamp,
                )
            )
        return tuple(sorted(hits, key=lambda item: (-item.score, item.subject_id))[:limit])

    def recall(self, query: str, *, project_id: str | None = None) -> RecallAnswer:
        cleaned = query.casefold().replace("lembra daquilo", "").strip(" ?!.,")
        hits = self.search(cleaned, limit=3, project_id=project_id) if cleaned else self._recent_hits(3, project_id=project_id)
        if not hits:
            return RecallAnswer("NOT_FOUND", "Não encontrei memória com essa proveniência.", (), ())
        if len(hits) > 1 and (not cleaned or abs(hits[0].score - hits[1].score) < 0.05):
            return RecallAnswer(
                "AMBIGUOUS",
                "Encontrei mais de uma criação. Qual delas você quer retomar?",
                hits,
                tuple(event_id for hit in hits for event_id in hit.event_ids),
            )
        hit = hits[0]
        return RecallAnswer(
            "FOUND",
            f"Sim. A última forma registrada foi: {hit.summary}",
            (hit,),
            hit.event_ids,
        )

    def projection(self, name: str) -> Mapping[str, Any]:
        projections = {
            "episodic": self._episodic,
            "semantic": self._semantic,
            "creation": self._creation,
            "collaboration": self._collaboration,
        }
        if name not in projections:
            raise KeyError(name)
        return projections[name]

    def export(self) -> bytes:
        return canonical_json(
            {
                "schema": MEMORY_EXPORT_SCHEMA,
                "events": [event.to_dict() for event in self._events],
                "head_hash": self._events[-1].event_hash if self._events else None,
            }
        )

    def compact_non_destructive(self, *, receipt_id: str) -> Mapping[str, Any]:
        """Seal a recoverable snapshot without deleting the canonical journal."""
        if not receipt_id or any(character in receipt_id for character in "/\\\0"):
            raise MemoryIntegrityError("receipt de compactação inválido")
        with self._lock:
            payload = self.export()
            relative = f"memory/compactions/{receipt_id}.json.dpapi"
            self.storage.write_atomic(relative, self.secret_box.seal(payload))
            return {
                "schema": "casulo.memory-compaction-receipt/1.0",
                "receipt_id": receipt_id,
                "events_preserved": len(self._events),
                "journal_head_hash": self._events[-1].event_hash if self._events else None,
                "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
                "canonical_events_deleted": 0,
                "path": relative,
            }

    def delete_all(self, confirmation: str) -> int:
        if confirmation != "DELETE MY CASULO MEMORY":
            raise MemoryIntegrityError("confirmação explícita de delete ausente")
        paths = self.storage.list("memory/events")
        for path in paths:
            self.storage.delete(path)
        count = len(self._events)
        self._events.clear()
        self._rebuild()
        return count

    def _load(self) -> list[MemoryEvent]:
        events: list[MemoryEvent] = []
        previous: str | None = None
        for relative in self.storage.list("memory/events"):
            if not EVENT_FILE_RE.fullmatch(relative.rsplit("/", 1)[-1]):
                # Atomic-write debris is retained for diagnosis but is not a
                # committed event and cannot enter the canonical chain.
                continue
            document = json.loads(self.secret_box.open(self.storage.read(relative)))
            event = MemoryEvent.from_dict(document)
            if event.sequence != len(events) + 1 or event.previous_hash != previous:
                raise MemoryIntegrityError("cadeia append-only quebrada")
            events.append(event)
            previous = event.event_hash
        return events

    def _rebuild(self) -> None:
        self._by_subject: dict[str, list[MemoryEvent]] = {}
        for event in self._events:
            self._by_subject.setdefault(event.subject_id, []).append(event)
        self._episodic = {
            event.event_id: {
                "timestamp": event.timestamp,
                "subject_id": event.subject_id,
                "kind": event.kind,
                "source_ids": list(event.source_ids),
            }
            for event in self._events
        }
        self._semantic = {
            token: sorted(
                {event.event_id for event in self._events if token in _tokens(event.text)}
            )
            for token in sorted({token for event in self._events for token in _tokens(event.text)})
        }
        self._creation = {
            subject: {
                "latest_event_id": events[-1].event_id,
                "latest_payload": dict(events[-1].payload),
                "provenance_event_ids": [event.event_id for event in events],
            }
            for subject, events in self._by_subject.items()
        }
        collaboration = [event for event in self._events if event.kind == "COLLABORATION"]
        self._collaboration = (
            {
                "preferences": dict(collaboration[-1].payload),
                "provenance_event_ids": [event.event_id for event in collaboration],
            }
            if collaboration
            else {"preferences": {}, "provenance_event_ids": []}
        )

    def _recent_hits(self, limit: int, *, project_id: str | None = None) -> tuple[MemoryHit, ...]:
        values = [
            MemoryHit(
                subject_id=subject,
                score=1.0,
                summary=scoped[-1].text or subject,
                event_ids=tuple(event.event_id for event in scoped),
                latest_timestamp=scoped[-1].timestamp,
            )
            for subject, events in self._by_subject.items()
            if (scoped := [event for event in events if project_id is None or event.payload.get("project_id") == project_id])
        ]
        return tuple(sorted(values, key=lambda item: item.latest_timestamp, reverse=True)[:limit])


def _tokens(text: str) -> set[str]:
    return {item.casefold() for item in TOKEN_RE.findall(text) if len(item) > 1}


def _vector(tokens: set[str], dimensions: int = 64) -> tuple[float, ...]:
    vector = [0.0] * dimensions
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        vector[index] += 1.0 if digest[2] & 1 else -1.0
    return tuple(vector)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, numerator / (left_norm * right_norm))
