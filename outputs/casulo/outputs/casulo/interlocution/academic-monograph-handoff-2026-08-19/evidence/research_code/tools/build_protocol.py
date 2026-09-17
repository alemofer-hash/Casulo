from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from casulo.t.v2_tcap import verify_tcap_v2
from interlocution.authority import TrainingAuthority
from interlocution.contracts import (
    build_confirmed_intent,
    build_requirement_graph,
    build_training_authority_plan,
    canonical_bytes,
    canonical_sha256,
)
from interlocution.policy import compile_training_authority_tcap, source_inventory


CAMPAIGN = "2026-08-18-interlocution-live-instance-attempt1"
FULL_WORKER = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
DATASET = FULL_WORKER / "artifact/FloodSurrogate.dataset.bin"
INITIALIZATIONS = FULL_WORKER / "artifact/FloodSurrogate.initializations.bin"
RUNTIME = ROOT / "t-runtime/target/release/casulo-t-runtime.exe"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_once(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise FileExistsError(f"append-only artifact is unreadable: {path}") from error
        if existing != value:
            raise FileExistsError(f"append-only artifact differs: {path}")
        return
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(raw, encoding="utf-8", newline="\n")


def capabilities() -> dict[str, bool]:
    return {
        "float64_supported": True,
        "mse_supported": True,
        "sgd_supported": True,
        "reset_supported": True,
        "no_cross_case_state": True,
        "selection_supported": True,
        "fixed_epoch_supported": True,
        "counter_supported": True,
        "independent_verifier_available": True,
        "publisher_requires_t": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs/casulo/interlocution" / CAMPAIGN,
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if not DATASET.is_file() or not INITIALIZATIONS.is_file() or not RUNTIME.is_file():
        raise RuntimeError("sealed full-worker dataset, initialization or T runtime is absent")

    dataset_hash = sha256_file(DATASET)
    initialization_hash = sha256_file(INITIALIZATIONS)
    if dataset_hash != "f393212f183a28a663adeb11995c5ab3ac769df7f06ded2dcfbc5e91cd31f802":
        raise RuntimeError("full-worker dataset hash diverged")
    if initialization_hash != "1b77bc6f3ee729282756b8244c4b198395e2fe6bcda6a8d4dd255aa370af13e3":
        raise RuntimeError("full-worker initialization hash diverged")

    confirmation_seed = {
        "schema": "casulo.interlocution-human-confirmation/1.0",
        "owner": "Guilherme Moura Fernandes",
        "kind": "EXPLICIT_USER_GOAL_SUBMISSION",
        "utterance": "Bora",
        "goal_title": "PROVA VIVA DO TEOREMA DA INTERLOCUCAO",
        "binding_requirements": [
            "nine critical decisions causally governed by T",
            "full 1024-record FloodSurrogate",
            "no eight-record canary",
            "no forced positive result",
            "independent verification and two frozen holdouts",
        ],
        "received_at_session_date": "2026-08-18",
    }
    confirmation = {
        **confirmation_seed,
        "event_sha256": canonical_sha256(confirmation_seed),
    }
    intent = build_confirmed_intent(
        campaign_id=CAMPAIGN,
        dataset_sha256=dataset_hash,
        initialization_sha256=initialization_hash,
        confirmation_event_sha256=confirmation["event_sha256"],
    )
    graph = build_requirement_graph(intent)
    plan = build_training_authority_plan(intent, graph)

    write_once(output / "human-confirmation-event.json", confirmation)
    write_once(output / "confirmed_intent.json", intent)
    write_once(output / "requirement_graph.json", graph)
    write_once(output / "training_authority_plan.json", plan)

    tcap_directory = output / "tcap/training-authority-plan.tcap"
    if tcap_directory.exists():
        root, manifest, typed = verify_tcap_v2(tcap_directory)
        tcap_hash = str(manifest["tcap_hash"])
    else:
        build = compile_training_authority_tcap(
            plan, output / "t_sources", tcap_directory
        )
        root, manifest, typed = verify_tcap_v2(build.directory)
        tcap_hash = build.tcap_hash
    binding = {
        "schema": "casulo.interlocution-tcap-binding/1.0",
        "campaign_id": CAMPAIGN,
        "plan_sha256": plan["plan_sha256"],
        "tcap_hash": tcap_hash,
        "manifest_sha256": sha256_file(root / "MANIFEST.json"),
        "module_count": len(typed["modules"]),
        "source_inventory": source_inventory(output / "t_sources"),
        "general_pipeline": [
            "T/2.0 source",
            "V2Parser AST",
            "V2Analyzer semantics",
            "typed IR",
            "module graph",
            "structured bytecode",
            "TCAP v2",
            "Rust T runtime",
        ],
        "foreign_boundaries": manifest["sections"]["foreign_boundaries"],
    }
    write_once(output / "tcap-binding.json", binding)

    initialization_manifest = json.loads(
        (FULL_WORKER / "artifact/initialization_bundle.json").read_text(encoding="utf-8")
    )
    if initialization_manifest.get("sha256") != initialization_hash:
        raise RuntimeError("initialization metadata does not match sealed payload")
    authority = TrainingAuthority(
        RUNTIME,
        root,
        output / "receipts/policy-inputs",
    )
    grant = authority.authorize(
        dataset_sha256=dataset_hash,
        records=1024,
        input_features=8,
        initialization_sha256=initialization_hash,
        cases_unique=bool(initialization_manifest["all_parameter_hashes_unique"]),
        nonces_unique=bool(initialization_manifest["all_nonces_unique"]),
        capabilities=capabilities(),
    )
    receipt_path = output / "receipts/policy-authority.jsonl"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        raise FileExistsError(f"append-only artifact already exists: {receipt_path}")
    receipt_path.write_text(
        "".join(
            json.dumps(item.receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
            for item in grant.calls
        ),
        encoding="utf-8",
        newline="\n",
    )
    grant_document = {
        "schema": "casulo.interlocution-authority-grant/1.0",
        "campaign_id": CAMPAIGN,
        "plan_sha256": plan["plan_sha256"],
        "tcap_hash": tcap_hash,
        "config_from_t": dict(grant.config),
        "receipt_chain": list(grant.receipt_chain),
        "surfaces": [item.receipt["surface_id"] for item in grant.calls],
        "foreign_affirmative_fallback": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    grant_document["grant_sha256"] = canonical_sha256(grant_document)
    write_once(output / "authority-grant.json", grant_document)
    print(
        json.dumps(
            {
                "campaign": CAMPAIGN,
                "intent_sha256": intent["intent_sha256"],
                "plan_sha256": plan["plan_sha256"],
                "tcap_hash": tcap_hash,
                "decisions": len(grant.calls),
                "grant_sha256": grant_document["grant_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
