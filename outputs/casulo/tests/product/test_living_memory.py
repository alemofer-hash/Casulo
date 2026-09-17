from __future__ import annotations

import json
import sys

import pytest

from casulo.product.living_memory import (
    DpapiSecretBox,
    LivingMemory,
    MemoryIntegrityError,
    TestSecretBox,
)
from casulo.product.math_boundary import SparseSignedCosine
from casulo.product.platform_contracts import LocalStorage
from casulo.product.hosted_shell import HostedShell
from casulo.product.platform_contracts import (
    BufferedAudioPlayback,
    ConsoleDisplay,
    SyntheticAudioCapture,
    VoiceEvent,
)


class FixedClock:
    def __init__(self) -> None:
        self.sequence = 0

    def monotonic_ns(self) -> int:
        return self.sequence

    def utc_timestamp(self) -> str:
        self.sequence += 1
        return f"2026-08-11T12:00:{self.sequence:02d}Z"


def memory_at(tmp_path):
    storage = LocalStorage(tmp_path / "profile")
    return (
        LivingMemory(
            storage=storage,
            clock=FixedClock(),
            secret_box=TestSecretBox(),
            allow_test_encryption=True,
        ),
        storage,
    )


def append_creation(memory: LivingMemory, event_id: str, subject: str, text: str) -> None:
    memory.append(
        event_id=event_id,
        kind="CREATION",
        subject_id=subject,
        text=text,
        payload={"name": text, "pending": "confirmar voz"},
        source_ids=(f"voice:{event_id}",),
    )


def test_close_reopen_rebuilds_projections_and_provenance(tmp_path) -> None:
    memory, storage = memory_at(tmp_path)
    append_creation(memory, "event:1", "creation:guide", "Guia de enchentes")
    memory.append(
        event_id="event:2",
        kind="COLLABORATION",
        subject_id="profile:guilherme",
        text="prefere correção direta",
        payload={"correction_directness": 9},
        source_ids=("voice:2",),
    )
    reopened = LivingMemory(
        storage=storage,
        clock=FixedClock(),
        secret_box=TestSecretBox(),
        allow_test_encryption=True,
    )
    assert len(reopened.events) == 2
    assert reopened.events[1].previous_hash == reopened.events[0].event_hash
    assert reopened.projection("creation")["creation:guide"]["provenance_event_ids"] == ["event:1"]
    assert reopened.projection("collaboration")["provenance_event_ids"] == ["event:2"]
    assert reopened.search("enchentes")[0].subject_id == "creation:guide"


def test_recall_found_and_ambiguous_are_honest(tmp_path) -> None:
    memory, _ = memory_at(tmp_path)
    append_creation(memory, "event:1", "creation:flood", "Guia de enchentes")
    found = memory.recall("lembra daquilo sobre enchentes?")
    assert found.status == "FOUND"
    assert found.provenance_event_ids == ("event:1",)
    append_creation(memory, "event:2", "creation:traffic", "Otimizador de trânsito")
    ambiguous = memory.recall("lembra daquilo?")
    assert ambiguous.status == "AMBIGUOUS"
    assert len(ambiguous.candidates) == 2


def test_sparse_similarity_preserves_memory_ranking_and_provenance(tmp_path) -> None:
    baseline, _ = memory_at(tmp_path / "dense")
    sparse = LivingMemory(
        storage=LocalStorage(tmp_path / "sparse"),
        clock=FixedClock(),
        secret_box=TestSecretBox(),
        allow_test_encryption=True,
        similarity_kernel=SparseSignedCosine(),
    )
    for memory in (baseline, sparse):
        append_creation(memory, "event:1", "creation:flood", "Guia de enchentes e rios")
        append_creation(memory, "event:2", "creation:traffic", "Otimizador de trânsito urbano")
    dense_hits = baseline.search("enchentes rios")
    sparse_hits = sparse.search("enchentes rios")
    assert [item.subject_id for item in sparse_hits] == [item.subject_id for item in dense_hits]
    assert [item.score for item in sparse_hits] == [item.score for item in dense_hits]
    assert sparse_hits[0].event_ids == ("event:1",)


def test_tampered_event_is_rejected_on_reopen(tmp_path) -> None:
    memory, storage = memory_at(tmp_path)
    append_creation(memory, "event:1", "creation:guide", "Guia")
    relative = storage.list("memory/events")[0]
    box = TestSecretBox()
    document = json.loads(box.open(storage.read(relative)))
    document["text"] = "adulterado"
    storage.write_atomic(relative, box.seal(json.dumps(document).encode("utf-8")))
    with pytest.raises(MemoryIntegrityError, match="hash"):
        LivingMemory(
            storage=storage,
            clock=FixedClock(),
            secret_box=box,
            allow_test_encryption=True,
        )


def test_export_and_explicit_delete(tmp_path) -> None:
    memory, storage = memory_at(tmp_path)
    append_creation(memory, "event:1", "creation:guide", "Guia")
    exported = json.loads(memory.export())
    assert exported["schema"] == "casulo.memory-export/1.0"
    assert exported["head_hash"] == memory.events[-1].event_hash
    with pytest.raises(MemoryIntegrityError, match="confirmação"):
        memory.delete_all("sim")
    assert memory.delete_all("DELETE MY CASULO MEMORY") == 1
    assert storage.list("memory/events") == ()


def test_nonproduction_encryption_is_fail_closed(tmp_path) -> None:
    with pytest.raises(MemoryIntegrityError, match="não produtiva"):
        LivingMemory(
            storage=LocalStorage(tmp_path),
            clock=FixedClock(),
            secret_box=TestSecretBox(),
        )


def test_hosted_shell_reopens_and_answers_lembra_daquilo(tmp_path) -> None:
    memory, storage = memory_at(tmp_path)
    capture = SyntheticAudioCapture()
    first = HostedShell(
        clock=FixedClock(),
        capture=capture,
        playback=BufferedAudioPlayback(),
        display=ConsoleDisplay(emit_ansi=False),
        memory=memory,
    )
    capture.emit(VoiceEvent("voice:1", "Quero um guia de enchentes", "pt-BR", True))
    first.poll_voice()
    first.run_one()

    reopened = LivingMemory(
        storage=storage,
        clock=FixedClock(),
        secret_box=TestSecretBox(),
        allow_test_encryption=True,
    )
    second_capture = SyntheticAudioCapture()
    second_display = ConsoleDisplay(emit_ansi=False)
    second = HostedShell(
        clock=FixedClock(),
        capture=second_capture,
        playback=BufferedAudioPlayback(),
        display=second_display,
        memory=reopened,
    )
    second_capture.emit(VoiceEvent("voice:2", "lembra daquilo?", "pt-BR", True))
    second.poll_voice()
    second.run_one()
    assert "guia de enchentes" in second_display.frames[-1].summary.casefold()
    assert second.creation.current.state.value == "SILENCE"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows hosted")
def test_dpapi_round_trip_binds_ciphertext_to_windows_user() -> None:
    box = DpapiSecretBox()
    plaintext = "memória Casulo".encode("utf-8")
    ciphertext = box.seal(plaintext)
    assert plaintext not in ciphertext
    assert box.open(ciphertext) == plaintext
