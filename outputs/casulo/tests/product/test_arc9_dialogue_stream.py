from __future__ import annotations

import hashlib
import time

from casulo_owner.generative_engine import AppendOnlyTraceStore
from casulo_owner.local_model_runtime import ModelStreamEvent, ModelStreamKind, StochasticTrace
from tools.casulo_owner_vm_inspect import dialogue_turn


class StreamingRuntimeDouble:
    def stream_chat(self, request, cancellation):
        fragments = ("Vamos ", "pensar juntos.")
        yield ModelStreamEvent(request.operation_id, 1, ModelStreamKind.STARTED)
        for sequence, fragment in enumerate(fragments, start=2):
            yield ModelStreamEvent(request.operation_id, sequence, ModelStreamKind.TOKEN, fragment)
        now = time.monotonic_ns()
        text = "".join(fragments)
        yield ModelStreamEvent(
            request.operation_id,
            4,
            ModelStreamKind.COMPLETED,
            trace=StochasticTrace(
                request.operation_id,
                "runtime-double",
                "a" * 64,
                request.policy.policy_id,
                request.policy.seed,
                request.context_digest,
                hashlib.sha256(text.encode("utf-8")).hexdigest(),
                2,
                "stop",
                now - 1,
                now,
            ),
        )


def test_dialogue_emits_structured_tokens_instead_of_block_output(tmp_path, capsys) -> None:
    events = []
    conversation = []
    answer = dialogue_turn(
        StreamingRuntimeDouble(),
        AppendOnlyTraceStore(tmp_path / "traces.jsonl"),
        conversation,
        "Quero desenvolver uma ideia com cuidado.",
        turn_id="turn:arc9",
        stream_sink=lambda kind, payload: events.append((kind, dict(payload))),
    )
    assert answer == "Vamos pensar juntos."
    assert [kind for kind, _ in events] == [
        "ASSISTANT_START",
        "ASSISTANT_TOKEN",
        "ASSISTANT_TOKEN",
        "ASSISTANT_END",
    ]
    assert [payload["text"] for kind, payload in events if kind == "ASSISTANT_TOKEN"] == ["Vamos ", "pensar juntos."]
    assert events[-1][1]["finish_reason"] == "stop"
    assert capsys.readouterr().out == ""
    assert len(conversation) == 2
