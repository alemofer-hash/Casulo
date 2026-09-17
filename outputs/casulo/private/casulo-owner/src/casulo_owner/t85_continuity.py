from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from casulo.product.guide_continuity import (
    ConstraintStrength,
    DialogueDirective,
    GuideContinuityKernel,
    QuestionCandidate,
    RecordKind,
)
from casulo.product.living_memory import LivingMemory, RecallAnswer, SecretBox
from casulo.product.math_boundary import SimilarityKernel
from casulo.product.platform_contracts import Clock, LocalStorage
from casulo.t.productive import ProductiveTCall, ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder


class ContinuityServiceError(RuntimeError):
    pass


T = TypeVar("T")


class SingleWriterLease:
    """Process-wide non-blocking lease over one byte; no hidden retry."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._stream = path.open("a+b")
        if self._stream.tell() == 0:
            self._stream.write(b"0")
            self._stream.flush()
        self._stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            self._stream.close()
            raise ContinuityServiceError("LivingMemory já possui um writer ativo") from error
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream.close()
            self._closed = True

    def __enter__(self) -> "SingleWriterLease":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class TContextSelection:
    directive: DialogueDirective
    decision: str
    t_call: ProductiveTCall


class T85ContinuityService:
    """Owner continuity: encrypted journal, deterministic state and T policy."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Clock,
        secret_box: SecretBox,
        t_runtime: Path,
        tcap: Path,
        allow_test_encryption: bool = False,
        similarity_kernel: SimilarityKernel | None = None,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lease = SingleWriterLease(self.root / "continuity.writer.lock")
        try:
            self.memory = LivingMemory(
                storage=LocalStorage(self.root / "living-memory"),
                clock=clock,
                secret_box=secret_box,
                allow_test_encryption=allow_test_encryption,
                similarity_kernel=similarity_kernel,
            )
            events = [
                dict(item.payload["continuity_event"])
                for item in self.memory.events
                if item.kind == "CONTINUITY_JOURNAL" and isinstance(item.payload.get("continuity_event"), Mapping)
            ]
            self.kernel = GuideContinuityKernel.from_event_log(events) if events else GuideContinuityKernel()
            self.executor = ProductiveTExecutor(t_runtime, tcap, self.root / "t-context-receipts")
            existing = [
                int(path.name.removeprefix("context.").removesuffix(".json"))
                for path in (self.root / "t-context-receipts").glob("context.*.json")
                if path.name.removeprefix("context.").removesuffix(".json").isdigit()
            ]
            self._selection_sequence = max(existing, default=0)
            receipt_paths = sorted((self.root / "t-context-receipts").glob("context.*.receipt.json"))
            if receipt_paths:
                latest = json.loads(receipt_paths[-1].read_text(encoding="utf-8"))
                self._previous_receipt_hash = str(latest["receipt"]["receipt_hash"])
            else:
                self._previous_receipt_hash = "0" * 64
        except BaseException:
            self._lease.close()
            raise

    @staticmethod
    def build_policy(source: Path, output: Path) -> Path:
        if output.exists():
            return output
        return TcapV2Builder().build(
            (source,), output,
            entry_module="owner.guide.context_policy", entry_function="decide",
            tests={"properties": ["project_isolation", "hard_constraints_preserved", "ambiguity_explicit", "cancel_fail_closed"]},
        ).directory

    def close(self) -> None:
        self._lease.close()

    def __enter__(self) -> "T85ContinuityService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _mutate(self, operation: Callable[[], T]) -> T:
        before = len(self.kernel.event_log)
        try:
            result = operation()
            for event in self.kernel.event_log[before:]:
                self._persist_event(event)
            return result
        except BaseException:
            persisted = [
                dict(item.payload["continuity_event"])
                for item in self.memory.events
                if item.kind == "CONTINUITY_JOURNAL" and isinstance(item.payload.get("continuity_event"), Mapping)
            ]
            self.kernel = GuideContinuityKernel.from_event_log(persisted) if persisted else GuideContinuityKernel()
            raise

    def _persist_event(self, event: Mapping[str, Any]) -> None:
        payload = dict(event["payload"])
        project_id = str(payload.get("project_id", "global"))
        if event["kind"] == "RECORD_ADDED":
            subject_id = str(payload["record_id"])
            text = str(payload["text"])
        else:
            subject_id = f"continuity:{project_id}"
            text = str(payload.get("statement", payload.get("summary", event["kind"])))
        source = payload.get("source_event_ids") or (payload.get("source_event_id") if payload.get("source_event_id") else event["event_hash"])
        source_ids = tuple(str(item) for item in source) if isinstance(source, (list, tuple)) else (str(source),)
        self.memory.append(
            event_id=f"continuity:{event['event_hash']}",
            kind="CONTINUITY_JOURNAL",
            subject_id=subject_id,
            text=text,
            payload={"project_id": project_id, "continuity_event": dict(event), "trainable": False},
            source_ids=source_ids,
        )

    def open_project(self, project_id: str, *, source_event_id: str) -> None:
        self._mutate(lambda: self.kernel.open_project(project_id, source_event_id=source_event_id))

    def record(
        self,
        *,
        record_id: str,
        project_id: str,
        kind: RecordKind,
        text: str,
        source_event_ids: tuple[str, ...],
        criticality: int = 0,
        unresolved: bool = False,
    ):
        return self._mutate(lambda: self.kernel.record(
            record_id=record_id, project_id=project_id, kind=kind, text=text,
            source_event_ids=source_event_ids, criticality=criticality,
            unresolved=unresolved,
        ))

    def add_constraint(self, *, constraint_id: str, project_id: str, key: str, statement: str, strength: ConstraintStrength, source_event_ids: tuple[str, ...]):
        return self._mutate(lambda: self.kernel.add_constraint(
            constraint_id=constraint_id, project_id=project_id, key=key,
            statement=statement, strength=strength, source_event_ids=source_event_ids,
        ))

    def resolve_constraint(self, *, winning_constraint_id: str, human_event_id: str, explicit_human_approval: bool):
        return self._mutate(lambda: self.kernel.resolve_constraint(
            winning_constraint_id=winning_constraint_id,
            human_event_id=human_event_id,
            explicit_human_approval=explicit_human_approval,
        ))

    def supersede(self, *, project_id: str, previous_record_id: str, new_record_id: str, text: str, human_event_id: str):
        previous = next((item for item in self.kernel.snapshot()["records"] if item["record_id"] == previous_record_id and item["project_id"] == project_id), None)
        if previous is None:
            raise ContinuityServiceError("registro anterior de supersession não encontrado")
        record = self.record(
            record_id=new_record_id, project_id=project_id, kind=RecordKind.DECISION,
            text=text, source_event_ids=(human_event_id, previous_record_id), criticality=max(8, int(previous["criticality"])),
        )
        self.memory.append(
            event_id=f"supersession:{new_record_id}", kind="SUPERSESSION",
            subject_id=new_record_id, text=text,
            payload={"project_id": project_id, "supersedes": previous_record_id, "replacement": new_record_id, "trainable": False},
            source_ids=(human_event_id, previous_record_id),
        )
        return record

    def select_context(
        self,
        *,
        project_id: str,
        query: str,
        budget_chars: int,
        questions: tuple[QuestionCandidate, ...] = (),
        human_resolution_present: bool = False,
        cancelled: bool = False,
    ) -> TContextSelection:
        directive = self.kernel.directive(project_id=project_id, query=query, budget_chars=budget_chars, questions=questions)
        review = self.kernel.constraints.review(project_id)
        hard = {item.statement for item in review.active if item.strength is ConstraintStrength.HARD}
        project_match = all(item.source == f"guide-continuity:{project_id}" for item in directive.context_items)
        mandatory_preserved = hard == set(directive.mandatory_constraints)
        self._selection_sequence += 1
        call = self.executor.execute(
            "owner.guide.context_policy", "decide",
            {
                "project_match": project_match,
                "budget_valid": 0 < budget_chars <= 96_000,
                "mandatory_preserved": mandatory_preserved,
                "ambiguity_present": bool(directive.conflicts or directive.selected_question),
                "human_resolution_present": human_resolution_present,
                "cancelled": cancelled,
            },
            call_id=f"context.{self._selection_sequence:08d}",
            surface_id="memory_governance", scope_id=f"project:{project_id}",
            previous_receipt_hash=self._previous_receipt_hash,
        )
        result = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") not in {"SELECT", "ASK_HUMAN"}:
            raise ContinuityServiceError(f"T context policy denied selection: {json.dumps(result, sort_keys=True)}")
        receipt_path = self.root / "t-context-receipts" / f"context.{self._selection_sequence:08d}.receipt.json"
        if receipt_path.exists():
            raise ContinuityServiceError("receipt T de contexto duplicado")
        envelope = {"observable": dict(call.observable), "receipt": dict(call.receipt)}
        encoded = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        temporary = receipt_path.with_name(f".{receipt_path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, receipt_path)
        self._previous_receipt_hash = str(call.receipt["receipt_hash"])
        return TContextSelection(directive, str(result["value"]), call)

    def record_turn(self, *, project_id: str, turn_id: str, user_text: str, assistant_text: str) -> None:
        self.record(
            record_id=f"{project_id}:{turn_id}:user", project_id=project_id,
            kind=RecordKind.THREAD, text=user_text,
            source_event_ids=(f"human:{turn_id}",), criticality=1,
        )
        self.record(
            record_id=f"{project_id}:{turn_id}:assistant", project_id=project_id,
            kind=RecordKind.THREAD, text=assistant_text,
            source_event_ids=(f"{project_id}:{turn_id}:user",), criticality=1,
        )

    def recall(self, query: str, *, project_id: str) -> RecallAnswer:
        return self.memory.recall(query, project_id=project_id)

    def compact(self, receipt_id: str) -> Mapping[str, Any]:
        return self.memory.compact_non_destructive(receipt_id=receipt_id)
