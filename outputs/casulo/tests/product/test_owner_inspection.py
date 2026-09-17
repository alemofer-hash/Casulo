from pathlib import Path

import pytest

from casulo_owner.inspection import InspectionError, OwnerInspectionRecorder


def test_note_is_contextual_append_only_and_rejects_raw_audio(tmp_path: Path) -> None:
    recorder = OwnerInspectionRecorder(tmp_path / "session", session_id="inspection:test")
    first = recorder.record(
        note_id="note:1", channel="voice", category="VOICE", text="a voz está lenta aqui",
        creation_id="creation:1", creation_version=7, creation_state="SIMULATION",
        source_event_ids=("voice:note:1",),
    )
    second = recorder.record(
        note_id="note:2", channel="text", category="DESIRED_CHANGE", text="diminuir a latência sem esconder o estado",
        creation_id="creation:1", creation_version=7, creation_state="SIMULATION",
        source_event_ids=("text:note:2",),
    )
    assert second.previous_hash == first.note_hash
    with pytest.raises(InspectionError, match="audio bruto"):
        recorder.record(
            note_id="note:3", channel="voice", category="VOICE", text="x",
            creation_id="creation:1", creation_version=7, creation_state="SIMULATION",
            source_event_ids=("voice:note:3",), raw_audio=b"pcm",
        )


def test_export_is_sanitized_and_does_not_overwrite(tmp_path: Path) -> None:
    recorder = OwnerInspectionRecorder(tmp_path / "session", session_id="inspection:export")
    recorder.set_technical_mode(True, human_event_id="human:technical:on")
    recorder.record(
        note_id="note:1", channel="text", category="DESIRED_CHANGE", text="mais silêncio visual",
        creation_id="creation:1", creation_version=2, creation_state="FIRST_FORM",
        source_event_ids=("text:1",),
    )
    exported = recorder.export(tmp_path / "export", environment={"cloud": "RELEASE_LOCKED"})
    assert exported["raw_audio_persisted"] is False
    assert not list((tmp_path / "export").glob("*.wav"))
    assert "mais silêncio visual" in (tmp_path / "export" / "desired_changes.md").read_text(encoding="utf-8")
    with pytest.raises(InspectionError, match="overwrite"):
        recorder.export(tmp_path / "export", environment={})
