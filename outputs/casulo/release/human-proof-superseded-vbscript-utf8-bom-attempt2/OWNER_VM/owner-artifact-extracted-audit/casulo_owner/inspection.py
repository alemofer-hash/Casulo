from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
_CATEGORIES = frozenset({"VOICE", "CHEMISTRY", "INTELLIGENCE", "CREATION", "VISUAL", "LATENCY", "BUG", "DESIRED_CHANGE"})


class InspectionError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class OwnerInspectionNote:
    note_id: str
    created_utc: str
    channel: str
    category: str
    text: str
    creation_id: str
    creation_version: int
    creation_state: str
    source_event_ids: tuple[str, ...]
    previous_hash: str
    note_hash: str
    raw_audio_persisted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.owner-inspection-note/1.0",
            "note_id": self.note_id,
            "created_utc": self.created_utc,
            "channel": self.channel,
            "category": self.category,
            "text": self.text,
            "creation_id": self.creation_id,
            "creation_version": self.creation_version,
            "creation_state": self.creation_state,
            "source_event_ids": list(self.source_event_ids),
            "previous_hash": self.previous_hash,
            "note_hash": self.note_hash,
            "raw_audio_persisted": self.raw_audio_persisted,
        }


class OwnerInspectionRecorder:
    def __init__(self, root: str | Path, *, session_id: str) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        if self.root.exists() and self.root.is_symlink():
            raise InspectionError("inspection root nao pode ser symlink")
        if not _ID.fullmatch(session_id):
            raise InspectionError("session_id invalido")
        self.session_id = session_id
        self.notes_path = self.root / "notes.jsonl"
        self.session_path = self.root / "session.json"
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.session_path.exists():
            self.session_path.write_text(
                json.dumps(
                    {
                        "schema": "casulo.owner-inspection-session/1.0",
                        "session_id": session_id,
                        "created_utc": datetime.now(UTC).isoformat(),
                        "technical_mode": False,
                        "raw_audio_persisted": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
                newline="\n",
            )

    def set_technical_mode(self, enabled: bool, *, human_event_id: str) -> None:
        if not _ID.fullmatch(human_event_id):
            raise InspectionError("evento humano invalido")
        payload = json.loads(self.session_path.read_text(encoding="utf-8"))
        payload["technical_mode"] = bool(enabled)
        payload["technical_mode_human_event_id"] = human_event_id
        self.session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    @property
    def note_count(self) -> int:
        return len(self._notes())

    def record(
        self,
        *,
        note_id: str,
        channel: str,
        category: str,
        text: str,
        creation_id: str,
        creation_version: int,
        creation_state: str,
        source_event_ids: tuple[str, ...],
        raw_audio: bytes | None = None,
    ) -> OwnerInspectionNote:
        if raw_audio is not None:
            raise InspectionError("audio bruto nao pode ser persistido por default")
        if not _ID.fullmatch(note_id) or channel not in {"voice", "text"} or category not in _CATEGORIES:
            raise InspectionError("metadados da nota invalidos")
        clean = " ".join(text.replace("\x00", "").split())
        if not clean or len(clean) > 4000 or creation_version < 0 or not source_event_ids:
            raise InspectionError("conteudo ou contexto da nota invalido")
        existing = self._notes()
        if any(note["note_id"] == note_id for note in existing):
            raise InspectionError("note_id duplicado")
        previous = existing[-1]["note_hash"] if existing else "0" * 64
        body = {
            "note_id": note_id,
            "created_utc": datetime.now(UTC).isoformat(),
            "channel": channel,
            "category": category,
            "text": clean,
            "creation_id": creation_id,
            "creation_version": creation_version,
            "creation_state": creation_state,
            "source_event_ids": list(source_event_ids),
            "previous_hash": previous,
            "raw_audio_persisted": False,
        }
        note_hash = hashlib.sha256(bytes.fromhex(previous) + _canonical(body)).hexdigest()
        note = OwnerInspectionNote(
            note_id,
            body["created_utc"],
            channel,
            category,
            clean,
            creation_id,
            creation_version,
            creation_state,
            source_event_ids,
            previous,
            note_hash,
        )
        with self.notes_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(note.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        return note

    def export(self, destination: str | Path, *, environment: dict[str, Any]) -> dict[str, Any]:
        target = Path(destination).expanduser().resolve(strict=False)
        if target.exists() or target.is_symlink():
            raise InspectionError("export existente; overwrite negado")
        target.mkdir(parents=True)
        notes = self._notes()
        (target / "session.json").write_bytes(self.session_path.read_bytes())
        (target / "notes.jsonl").write_bytes(self.notes_path.read_bytes() if self.notes_path.exists() else b"")
        refs = sorted({(note["creation_id"], int(note["creation_version"])) for note in notes})
        (target / "creation_refs.json").write_text(json.dumps([{"creation_id": item[0], "version": item[1]} for item in refs], ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        (target / "state_markers.json").write_text(json.dumps([{"note_id": note["note_id"], "state": note["creation_state"], "source_event_ids": note["source_event_ids"]} for note in notes], ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        desired = [note for note in notes if note["category"] == "DESIRED_CHANGE"]
        (target / "desired_changes.md").write_text("# Mudancas desejadas\n\n" + "\n".join(f"- {note['text']}" for note in desired) + "\n", encoding="utf-8", newline="\n")
        safe_environment = {**environment, "raw_audio_persisted": False, "secrets_included": False}
        (target / "environment_manifest.json").write_text(json.dumps(safe_environment, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        files = sorted(path for path in target.iterdir() if path.is_file())
        sums = "".join(f"{_sha(path)}  {path.name}\n" for path in files)
        (target / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")
        return {
            "schema": "casulo.owner-inspection-export/1.0",
            "session_id": self.session_id,
            "destination": str(target),
            "notes": len(notes),
            "raw_audio_persisted": False,
            "sha256sums_sha256": _sha(target / "SHA256SUMS"),
        }

    def _notes(self) -> list[dict[str, Any]]:
        if not self.notes_path.exists():
            return []
        return [json.loads(line) for line in self.notes_path.read_text(encoding="utf-8").splitlines() if line]
