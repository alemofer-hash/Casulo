from __future__ import annotations

import argparse
import json
from pathlib import Path

from .creation_field import CreationFieldRenderer
from .creation_pipeline import CreationPipeline
from .domain import CreationAggregate, CreationSpec, CreationState


def main() -> int:
    parser = argparse.ArgumentParser(description="Creation Field hosted, sem canvas de blocos")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    renderer = CreationFieldRenderer()
    aggregate = CreationAggregate(CreationSpec("creation:field-demo"))
    pipeline = CreationPipeline(aggregate)
    pipeline.bootstrap()
    frames = [renderer.project(aggregate.current, provenance_event_ids=())]

    aggregate.transition(CreationState.FIRST_INTENT, "voice:first")
    pending = pipeline.propose(
        source_event_id="voice:proposal",
        utterance="defina behavior.tone como direto",
    ).delta
    decision = pipeline.decide(
        human_event_id="voice:confirm",
        accepted=True,
        explicit_human_approval=True,
    )
    for state in CreationState:
        if state is CreationState.SILENCE:
            continue
        intent_state = state in {
            CreationState.FIRST_INTENT,
            CreationState.LISTENING,
            CreationState.CLARIFICATION,
        }
        creation = CreationSpec(
            aggregate.current.creation_id,
            version=aggregate.current.version,
            state=state,
            content=aggregate.current.content,
        )
        frames.append(
            renderer.project(
                creation,
                provenance_event_ids=(f"demo:{state.value.casefold()}",),
                pending_delta=pending if intent_state else None,
                forge_receipt=None if intent_state else decision.forge_receipt,
            )
        )
    pages: list[dict[str, str]] = []
    for index, frame in enumerate(frames):
        filename = f"{index}-{frame.state.value.casefold()}.html"
        (output / filename).write_text(renderer.render_html(frame), encoding="utf-8")
        pages.append({"state": frame.state.value, "file": filename, "sha256": frame.content_sha256})
    links = "".join(
        f'<li><a href="{item["file"]}">{item["state"]}</a></li>' for item in pages
    )
    (output / "index.html").write_text(
        "<!doctype html><html lang=\"pt-BR\"><meta charset=\"utf-8\">"
        "<title>Casulo · Creation Field</title><body><h1>Creation Field</h1><ol>"
        + links
        + "</ol></body></html>",
        encoding="utf-8",
    )
    print(json.dumps({"schema": "casulo.creation-field-demo/1.0", "ok": True, "output": str(output), "pages": pages}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
