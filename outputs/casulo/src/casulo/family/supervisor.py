from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from .contracts import ChatRequest


class FamilyEngine(Protocol):
    mock_only: bool

    def generate(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]: ...


@dataclass(slots=True)
class DeterministicMockEngine:
    delay_seconds: float = 0.0
    mock_only: bool = True

    def generate(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]:
        chunks = ("[MOCK LOCAL] ", f"Resposta para: {request.message}")
        for chunk in chunks:
            if cancelled():
                return
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            if cancelled():
                return
            yield chunk


class FamilySupervisor:
    def __init__(self, engine: FamilyEngine) -> None:
        if not engine.mock_only:
            raise ValueError("Day 1 aceita somente engine mock")
        self.engine = engine

    def respond(
        self, request: ChatRequest, cancelled: Callable[[], bool]
    ) -> Iterable[str]:
        yield from self.engine.generate(request, cancelled)
