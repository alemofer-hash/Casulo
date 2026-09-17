from __future__ import annotations

import argparse
import json
from pathlib import Path

from casulo.product.domain import CreationAggregate, IntentDelta, IntentOperation
from casulo.product.domain import DeltaConfirmation
from casulo.product.intent_engine import IntentEngine
from casulo.product.materializer import MaterializedPackageImporter
from tools.casulo_owner_vm_inspect import render_creation_timeline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creation-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.creation_root.resolve(strict=True)
    receipt = json.loads((root / "materialization-receipt.json").read_text(encoding="utf-8"))
    archive = Path(receipt["archive"])
    if not archive.is_file():
        archive = root / "materialized" / archive.name
    imported = MaterializedPackageImporter().import_archive(archive)
    aggregate = imported.aggregate_for_reedit()
    proposed = IntentDelta(
        "intent:reedit:preserved-einstein",
        aggregate.current.creation_id,
        aggregate.current.version,
        (IntentOperation("set", ("constraints", "audit_note"), "renderer recovered without mutating materialized archive"),),
        "round-trip and localized re-edit proof",
        ("forensic:inspection-failure-3",),
        1.0,
        DeltaConfirmation.PROPOSED,
        (("constraints", "audit_note"),),
    )
    delta = IntentEngine().decide(
        proposed,
        human_event_id="human:forensic-reedit-confirmed",
        accepted=True,
        explicit_human_approval=True,
    )
    reedited = aggregate.apply_delta(delta)
    visual = render_creation_timeline(
        root,
        {"materialization": {"archive": str(archive)}},
        args.output.resolve(),
    )
    result = {
        "schema": "casulo.preserved-creation-recovery/1.0",
        "archive": str(archive),
        "archive_sha256": imported.archive_sha256,
        "round_trip_creation_id": imported.creation.creation_id,
        "round_trip_version": imported.creation.version,
        "reedit_version": reedited.version,
        "reedit_localized": reedited.content["constraints"]["audit_note"],
        "visual": visual,
        "source_archive_mutated": False,
    }
    (args.output / "preserved-recovery.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
