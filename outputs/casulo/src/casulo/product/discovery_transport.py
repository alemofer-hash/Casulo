from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


DIALOGUE_TRANSPORTS = ("vm-bridge", "host-direct")
TOKEN_LIMIT_NOTICE = "Casulo status · RESPONSE_LIMIT_REACHED · resposta preservada; peça para continuar"


class DialogueBridge(Protocol):
    def bridge_boot(
        self,
        response: Callable[[], str],
        *,
        timeout: float,
        acceleration: str,
    ) -> dict[str, Any]: ...


def deliver_dialogue(
    *,
    transport: str,
    controller: DialogueBridge,
    provider: Callable[[], str],
) -> dict[str, object]:
    """Deliver one dialogue turn under an explicitly named UX profile.

    The default ``vm-bridge`` path retains the release-proof behaviour.
    ``host-direct`` is intentionally limited to discovery: it removes a TCG
    guest boot from ordinary conversation while creation still uses its own VM
    acceptance gate in the owner launcher.
    """
    if transport == "host-direct":
        answer = provider()
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("resposta host-direct vazia ou inválida")
        return {
            "schema": "casulo.discovery-dialogue-delivery/1.0",
            "transport": "HOST_DIRECT",
            "answer_chars": len(answer),
            "vm_creation_gate_preserved": True,
            "scientific_or_release_proof": False,
        }
    if transport == "vm-bridge":
        return controller.bridge_boot(provider, acceleration="tcg", timeout=900)
    raise ValueError("transporte de diálogo fora da allowlist")


class IncrementalLineFramer:
    """Frames diagnostics without delaying raw fragments shown by the GUI."""

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, fragment: str) -> tuple[str, ...]:
        if not isinstance(fragment, str):
            raise TypeError("fragmento precisa ser texto")
        self._pending += fragment
        complete: list[str] = []
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            complete.append(line + "\n")
        return tuple(complete)

    def finish(self) -> tuple[str, ...]:
        if not self._pending:
            return ()
        pending, self._pending = self._pending, ""
        return (pending,)


def completion_notice(finish_reason: str | None) -> str | None:
    """Expose a real model limit without guessing from punctuation or prose."""
    return TOKEN_LIMIT_NOTICE if finish_reason == "length" else None
