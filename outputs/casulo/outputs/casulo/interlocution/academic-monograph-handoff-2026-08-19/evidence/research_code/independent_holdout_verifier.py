"""Independent holdout verifier; deliberately imports no trainer or T runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SURFACES = (
    "dataset_identity_integrity", "initialization_bundle", "numerical_precision",
    "loss_function", "update_rule", "optimizer_state", "working_set",
    "stopping", "equivalence_acceptance",
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object required: {path}")
    return value


def seal(value: dict, field: str) -> None:
    observed = value.get(field)
    seed = {key: item for key, item in value.items() if key != field}
    if not isinstance(observed, str) or digest(seed) != observed:
        raise ValueError(f"invalid seal {field}")


def verify(root: Path) -> dict:
    spec = load(root / "spec.json")
    grant = load(root / "authority-grant.json")
    candidate = load(root / "candidate.json")
    reference = load(root / "reference.json")
    acceptance = load(root / "accepted.json")
    seal(spec, "spec_sha256")
    seal(grant, "grant_sha256")
    seal(candidate, "result_sha256")
    seal(reference, "result_sha256")
    seal(acceptance, "acceptance_sha256")
    if file_digest(root / "dataset.npz") != spec["dataset_sha256"]:
        raise ValueError("dataset hash mismatch")
    if file_digest(root / "initializations.npz") != spec["initialization_sha256"]:
        raise ValueError("initialization hash mismatch")
    policy = [json.loads(line) for line in (root / "policy-receipts.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if tuple(item.get("surface_id") for item in policy) != SURFACES:
        raise ValueError("nine T surfaces missing or reordered")
    previous = "0" * 64
    for item in policy:
        if item.get("previous_receipt_hash") != previous or item.get("result") != "ok":
            raise ValueError("T policy receipt chain invalid")
        seed = {key: value for key, value in item.items() if key != "receipt_hash"}
        if digest(seed) != item.get("receipt_hash"):
            raise ValueError("T policy receipt seal invalid")
        previous = item["receipt_hash"]
    receipts = [json.loads(line) for line in (root / "work-receipts.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if len(receipts) != spec["cases"]:
        raise ValueError("work receipt count mismatch")
    work_previous = "0" * 64
    case_ids: set[str] = set()
    nonces: set[str] = set()
    for item in receipts:
        if item.get("previous_work_chain_hash") != work_previous:
            raise ValueError("work receipt order mismatch")
        item_seed = {key: value for key, value in item.items() if key not in {"receipt_hash", "chain_hash"}}
        if digest(item_seed) != item.get("receipt_hash"):
            raise ValueError("work receipt seal invalid")
        chain = hashlib.sha256(bytes.fromhex(work_previous) + bytes.fromhex(item["receipt_hash"])).hexdigest()
        if item.get("chain_hash") != chain:
            raise ValueError("work receipt chain invalid")
        expected = {
            "epochs_completed": spec["epochs"],
            "forward_epochs": spec["epochs"],
            "backward_epochs": spec["epochs"],
            "optimizer_steps": spec["epochs"],
            "records_visited": spec["working_set_count"] * spec["epochs"],
            "parameter_writes": (spec["input_features"] + 1) * spec["epochs"],
            "dataset_sha256": spec["dataset_sha256"],
            "initialization_sha256": spec["initialization_sha256"],
            "authority_tip": previous,
        }
        for field, value in expected.items():
            if item.get(field) != value:
                raise ValueError(f"work receipt mismatch: {field}")
        if item["case_id"] in case_ids or item["nonce"] in nonces:
            raise ValueError("duplicate holdout case or nonce")
        case_ids.add(item["case_id"])
        nonces.add(item["nonce"])
        work_previous = chain
    if candidate["work_chain_tip"] != work_previous:
        raise ValueError("candidate does not bind work chain")
    tolerance = float(spec["absolute_tolerance"])
    maximum = 0.0
    for left, right in zip(candidate["cases"], reference["cases"], strict=True):
        if left["case_id"] != right["case_id"]:
            raise ValueError("case identity mismatch")
        values = [abs(float(left["final_loss"]) - float(right["final_loss"]))]
        values += [abs(float(a) - float(b)) for a, b in zip(left["parameters"], right["parameters"], strict=True)]
        values += [abs(float(a) - float(b)) for a, b in zip(left["predictions"], right["predictions"], strict=True)]
        if any(not math.isfinite(item) for item in values):
            raise ValueError("non-finite equivalence evidence")
        maximum = max(maximum, max(values))
    if maximum > tolerance:
        raise ValueError(f"equivalence tolerance exceeded: {maximum}")
    judge = load(root / "judge-receipt.json")
    if judge["runtime_receipt"].get("result") != "ok" or judge["observable"]["result"]["value"].get("decision") != "PUBLISH":
        raise ValueError("T judge did not authorize publication")
    if acceptance.get("judge_receipt_hash") != judge["runtime_receipt"].get("receipt_hash"):
        raise ValueError("acceptance does not consume T judgment")
    result = {
        "schema": "casulo.interlocution-independent-holdout-verification/1.0",
        "status": "PASS",
        "holdout_id": spec["id"],
        "authority_surfaces": 9,
        "work_units": len(receipts),
        "maximum_abs_difference": maximum,
        "trainer_imported": False,
        "analysis_json_trusted": False,
    }
    return {**result, "verification_sha256": digest(result)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.root.resolve())
    except Exception as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
