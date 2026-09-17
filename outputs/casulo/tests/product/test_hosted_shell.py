from __future__ import annotations

import pytest

from casulo.product.domain import CreationState
from casulo.product.hosted_shell import HostedShell, QueueClass
from casulo.product.platform_contracts import (
    BufferedAudioPlayback,
    ConsoleDisplay,
    LocalStorage,
    PlatformError,
    SyntheticAudioCapture,
    SystemClock,
    VoiceEvent,
)


def make_shell():
    capture = SyntheticAudioCapture()
    playback = BufferedAudioPlayback()
    display = ConsoleDisplay(emit_ansi=False)
    shell = HostedShell(
        clock=SystemClock(),
        capture=capture,
        playback=playback,
        display=display,
    )
    return shell, capture, playback, display


def test_shell_boots_in_silence_and_reacts_to_synthetic_voice() -> None:
    shell, capture, playback, display = make_shell()
    shell.boot()
    assert display.frames[-1].state == "SILENCE"
    capture.emit(VoiceEvent("voice:1", "Quero criar um guia", "pt-BR", True))
    assert shell.poll_voice()
    assert shell.run_one() == "VOICE"
    assert shell.creation.current.state is CreationState.FIRST_INTENT
    assert display.frames[-1].semantic_color == "amber"
    assert playback.active


def test_presence_preempts_background_without_fake_progress() -> None:
    shell, capture, _, display = make_shell()
    shell.enqueue(QueueClass.BACKGROUND, "BACKGROUND_STATUS", "Marco real: índice aberto")
    capture.emit(VoiceEvent("voice:1", "Interrompe", "pt-BR", True))
    shell.poll_voice()
    assert shell.run_one() == "VOICE"
    assert shell.run_one() == "BACKGROUND_STATUS"
    assert display.frames[-1].summary == "Marco real: índice aberto"


def test_partial_transcript_never_consolidates_intent() -> None:
    shell, capture, _, display = make_shell()
    capture.emit(VoiceEvent("voice:partial", "Talvez eu", "pt-BR", False))
    shell.poll_voice()
    shell.run_one()
    assert shell.creation.current.state is CreationState.SILENCE
    assert display.frames[-1].certainty == "provisional"


def test_buffered_playback_can_be_interrupted() -> None:
    shell, capture, playback, _ = make_shell()
    capture.emit(VoiceEvent("voice:1", "Começar", "pt-BR", True))
    shell.poll_voice()
    shell.run_one()
    assert playback.active
    assert shell.interrupt_guide()
    assert not playback.active


def test_hosted_storage_denies_path_traversal_and_writes_atomically(tmp_path) -> None:
    storage = LocalStorage(tmp_path / "memory")
    storage.write_atomic("events/1.json", b"{}\n")
    assert storage.read("events/1.json") == b"{}\n"
    with pytest.raises(PlatformError, match="path traversal"):
        storage.write_atomic("../secret", b"no")


def test_voice_locale_is_explicit() -> None:
    with pytest.raises(PlatformError, match="pt-BR"):
        VoiceEvent("voice:1", "hello", "en-US", True)
