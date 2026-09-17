from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

from .domain import CreationAggregate, CreationSpec, CreationState
from .creation_pipeline import CreationPipeline
from .guide_presence import GuidePresence, JobEvent
from .intent_engine import InterpretationStatus
from .living_memory import LivingMemory
from .platform_contracts import (
    AudioCapture,
    AudioPlayback,
    Clock,
    DisplayDevice,
    DisplayFrame,
    VoiceEvent,
)


class ProductFeature(StrEnum):
    MINIMAL = "casulo-minimal"
    VOICE = "casulo-voice"
    GUIDE = "casulo-guide"
    CREATOR = "casulo-creator"
    FULL = "casulo-full"


class QueueClass(IntEnum):
    PRESENCE = 0
    FLOW = 10
    SYSTEM = 20
    BACKGROUND = 30
    AUDIT = 40


@dataclass(order=True, slots=True)
class ShellTask:
    priority: int
    sequence: int
    kind: str = field(compare=False)
    payload: Any = field(compare=False)


class HostedShell:
    """Event loop hosted mínimo, sem dependências gráficas ou de IA."""

    def __init__(
        self,
        *,
        clock: Clock,
        capture: AudioCapture,
        playback: AudioPlayback,
        display: DisplayDevice,
        creation_id: str = "creation:hosted-shell",
        features: frozenset[ProductFeature] = frozenset({ProductFeature.MINIMAL}),
        memory: LivingMemory | None = None,
        guide: GuidePresence | None = None,
    ) -> None:
        self.clock = clock
        self.capture = capture
        self.playback = playback
        self.display = display
        self.features = features
        self.creation = CreationAggregate(CreationSpec(creation_id))
        self.creation_pipeline = (
            CreationPipeline(self.creation)
            if ProductFeature.CREATOR in features or ProductFeature.FULL in features
            else None
        )
        self.last_forge_receipt = (
            self.creation_pipeline.bootstrap() if self.creation_pipeline is not None else None
        )
        self.memory = memory
        self.guide = guide
        self._queue: list[ShellTask] = []
        self._sequence = 0
        self._frame_sequence = 0
        self._last_playback_id: str | None = None

    def boot(self) -> None:
        self._present("ivory", "confirmed", "Guia disponível; aguardando sua voz.")

    def enqueue(self, queue: QueueClass, kind: str, payload: Any) -> None:
        self._sequence += 1
        heapq.heappush(self._queue, ShellTask(int(queue), self._sequence, kind, payload))

    def poll_voice(self) -> bool:
        event = self.capture.poll()
        if event is None:
            return False
        self.enqueue(QueueClass.PRESENCE, "VOICE", event)
        return True

    def accept_duplex_event(self, event: Any) -> bool:
        """Ponte estreita: somente transcript do duplex entra no shell."""
        transcript = getattr(event, "transcript", None)
        if transcript is None:
            return False
        self.enqueue(
            QueueClass.PRESENCE,
            "VOICE",
            VoiceEvent(
                event_id=transcript.transcript_id,
                transcript=transcript.text,
                locale=transcript.locale,
                final=transcript.final,
            ),
        )
        return True

    def accept_job_event(self, event: JobEvent) -> None:
        if self.guide is None:
            raise ValueError("Guide Presence não configurada")
        self.enqueue(QueueClass.BACKGROUND, "GUIDE_JOB_EVENT", event)

    def run_one(self) -> str | None:
        if not self._queue:
            return None
        task = heapq.heappop(self._queue)
        if task.kind == "VOICE":
            self._on_voice(task.payload)
        elif task.kind == "BACKGROUND_STATUS":
            self._present("cobalt", "computing", str(task.payload))
        elif task.kind == "GUIDE_JOB_EVENT":
            turn = self.guide.accept_job_event(task.payload)
            self._present("cobalt", turn.certainty, turn.text)
        else:
            raise ValueError(f"task desconhecida: {task.kind}")
        return task.kind

    def interrupt_guide(self) -> bool:
        if self._last_playback_id is None:
            return False
        cancelled = self.playback.cancel(self._last_playback_id)
        if cancelled:
            self._last_playback_id = None
        return cancelled

    def _on_voice(self, event: VoiceEvent) -> None:
        if not event.final:
            self._present("cobalt", "provisional", f"Ouvindo: {event.transcript}")
            return
        if self.creation_pipeline is not None and self.creation_pipeline.pending is not None:
            normalized = event.transcript.casefold().strip(" .!?")
            if normalized in {"confirmo", "sim, confirmo", "pode aplicar"}:
                decision = self.creation_pipeline.decide(
                    human_event_id=event.event_id,
                    accepted=True,
                    explicit_human_approval=True,
                )
                self.last_forge_receipt = decision.forge_receipt
                if self.creation.current.state is CreationState.FIRST_INTENT:
                    self.creation.transition(CreationState.FIRST_FORM, event.event_id)
                rebuilt = ", ".join(decision.forge_receipt.rebuilt_units) if decision.forge_receipt else "nenhum"
                message = f"Mudança confirmada. Subgrafo recompilado: {rebuilt}."
                self._present("cobalt", "confirmed", message)
                self._last_playback_id = self.playback.speak(message)
                return
            if normalized in {"rejeito", "não confirmo", "nao confirmo", "cancele a mudança"}:
                self.creation_pipeline.decide(
                    human_event_id=event.event_id,
                    accepted=False,
                    explicit_human_approval=True,
                )
                message = "Mudança rejeitada; a forma anterior foi preservada."
                self._present("amber", "confirmed", message)
                self._last_playback_id = self.playback.speak(message)
                return
            message = "Há uma mudança proposta. Diga ‘confirmo’ ou ‘rejeito’ antes de formular outra."
            self._present("amber", "proposed", message)
            self._last_playback_id = self.playback.speak(message)
            return
        if self.memory is not None and "lembra daquilo" in event.transcript.casefold():
            recalled = self.memory.recall(event.transcript)
            color = "amber" if recalled.status == "AMBIGUOUS" else "cobalt"
            certainty = "proposed" if recalled.status == "AMBIGUOUS" else "confirmed"
            self._present(color, certainty, recalled.answer)
            self._last_playback_id = self.playback.speak(recalled.answer)
            return
        if self.creation.current.state is CreationState.SILENCE:
            self.creation.transition(CreationState.FIRST_INTENT, event.event_id)
        if self.memory is not None:
            self.memory.append(
                event_id=f"memory:{event.event_id}",
                kind="CREATION",
                subject_id=self.creation.current.creation_id,
                text=event.transcript,
                payload={
                    "state": self.creation.current.state.value,
                    "version": self.creation.current.version,
                },
                source_ids=(event.event_id,),
            )
        if self.creation_pipeline is not None:
            interpretation = self.creation_pipeline.propose(
                source_event_id=event.event_id,
                utterance=event.transcript,
            )
            if interpretation.status is InterpretationStatus.EXACT:
                assert interpretation.delta is not None
                operation = interpretation.delta.operations[0]
                path = ".".join(operation.path)
                message = f"Proponho {operation.action} em {path}. Diga ‘confirmo’ ou ‘rejeito’."
                self._present("amber", "proposed", message)
                self._last_playback_id = self.playback.speak(message)
                return
        if self.guide is not None:
            turn = self.guide.respond(
                event_id=event.event_id,
                text=event.transcript,
                final=True,
            )
            self._present("amber", turn.certainty, turn.text)
            self._last_playback_id = self.playback.speak(turn.text)
            return
        self._present("amber", "proposed", f"Primeira intenção: {event.transcript}")
        self._last_playback_id = self.playback.speak(
            "Entendi o começo. Vamos dar forma a isso juntos."
        )

    def _present(self, color: str, certainty: str, summary: str) -> None:
        self._frame_sequence += 1
        self.display.present(
            DisplayFrame(
                state=self.creation.current.state.value,
                semantic_color=color,
                certainty=certainty,
                summary=summary,
                sequence=self._frame_sequence,
            )
        )
