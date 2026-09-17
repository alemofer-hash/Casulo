from __future__ import annotations

import argparse
import json
from pathlib import Path

from .living_memory import DpapiSecretBox, LivingMemory
from .platform_contracts import LocalStorage, SystemClock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo local da Living Memory")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--text", default="Quero um guia de enchentes")
    args = parser.parse_args(argv)
    storage = LocalStorage(args.root)
    memory = LivingMemory(
        storage=storage,
        clock=SystemClock(),
        secret_box=DpapiSecretBox(),
    )
    if not memory.events:
        memory.append(
            event_id="demo:voice:1",
            kind="CREATION",
            subject_id="creation:demo",
            text=args.text,
            payload={"pending": "confirmar forma"},
            source_ids=("voice:demo:1",),
        )
    reopened = LivingMemory(
        storage=storage,
        clock=SystemClock(),
        secret_box=DpapiSecretBox(),
    )
    answer = reopened.recall("lembra daquilo?")
    print(
        json.dumps(
            {
                "events": len(reopened.events),
                "head_hash": reopened.events[-1].event_hash,
                "recall_status": answer.status,
                "answer": answer.answer,
                "provenance": list(answer.provenance_event_ids),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
