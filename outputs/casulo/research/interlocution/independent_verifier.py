"""Read-only verifier with no import of trainer, worker or Casulo runtime code."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any, Mapping


POLICY_SURFACES = (
    "dataset_identity_integrity",
    "initialization_bundle",
    "numerical_precision",
    "loss_function",
    "update_rule",
    "optimizer_state",
    "working_set",
    "stopping",
    "equivalence_acceptance",
)
WORK_SCHEMA = "casulo.interlocution-work-receipt/1.0"
RESULT_HEADER = struct.Struct("<8sII")
RESULT_CASE = struct.Struct("<IIQ32s6Qdd")
PARAMETERS = 81
RECORDS = 1024
EPOCHS = 400


class VerificationFailure(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VerificationFailure(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise VerificationFailure(f"JSON object required: {path}")
    return value


def load_jsonl(path: str | Path) -> tuple[dict[str, Any], ...]:
    try:
        result = tuple(
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VerificationFailure(f"invalid JSONL: {path}") from error
    if not all(isinstance(item, dict) for item in result):
        raise VerificationFailure("JSONL object records required")
    return result


def verify_seal(value: Mapping[str, Any], field: str) -> None:
    observed = value.get(field)
    if not isinstance(observed, str) or len(observed) != 64:
        raise VerificationFailure(f"missing seal: {field}")
    if canonical_sha256({key: item for key, item in value.items() if key != field}) != observed:
        raise VerificationFailure(f"invalid seal: {field}")


def verify_authority(
    grant: Mapping[str, Any], receipts: tuple[Mapping[str, Any], ...]
) -> str:
    verify_seal(grant, "grant_sha256")
    if len(receipts) != 9:
        raise VerificationFailure("authority receipt count differs from nine")
    if tuple(item.get("surface_id") for item in receipts) != POLICY_SURFACES:
        raise VerificationFailure("authority receipt surfaces are reordered or missing")
    if grant.get("receipt_chain") != [item.get("receipt_hash") for item in receipts]:
        raise VerificationFailure("grant receipt chain differs from raw receipts")
    previous = "0" * 64
    for receipt in receipts:
        if receipt.get("schema") != "casulo.t-decision-receipt/2.0":
            raise VerificationFailure("authority receipt schema mismatch")
        if receipt.get("result") != "ok":
            raise VerificationFailure("authority receipt is not ok")
        if receipt.get("previous_receipt_hash") != previous:
            raise VerificationFailure("authority receipt previous hash mismatch")
        receipt_hash = receipt.get("receipt_hash")
        if not isinstance(receipt_hash, str) or len(receipt_hash) != 64:
            raise VerificationFailure("missing seal: receipt_hash")
        receipt_seed = {
            key: item
            for key, item in receipt.items()
            if key not in {"receipt_hash", "chain_hash"}
        }
        if canonical_sha256(receipt_seed) != receipt_hash:
            raise VerificationFailure("invalid seal: receipt_hash")
        if receipt.get("tcap_hash") != grant.get("tcap_hash"):
            raise VerificationFailure("authority receipt TCAP mismatch")
        previous = str(receipt["receipt_hash"])
    return previous


def parse_result(path: str | Path) -> tuple[dict[str, Any], ...]:
    raw = Path(path).read_bytes()
    if len(raw) < RESULT_HEADER.size:
        raise VerificationFailure("result file is truncated")
    magic, count, records = RESULT_HEADER.unpack_from(raw)
    if magic != b"FWRES1\0\0" or records != RECORDS or count < 1:
        raise VerificationFailure("result header is invalid")
    offset = RESULT_HEADER.size
    results = []
    for _ in range(count):
        if offset + RESULT_CASE.size > len(raw):
            raise VerificationFailure("result case header is truncated")
        fields = RESULT_CASE.unpack_from(raw, offset)
        offset += RESULT_CASE.size
        scalar_count = PARAMETERS + RECORDS
        byte_count = scalar_count * 8
        if offset + byte_count > len(raw):
            raise VerificationFailure("result numeric payload is truncated")
        parameter_raw = raw[offset : offset + PARAMETERS * 8]
        prediction_raw = raw[
            offset + PARAMETERS * 8 : offset + byte_count
        ]
        offset += byte_count
        results.append(
            {
                "index": fields[0],
                "case_id": fields[1],
                "seed": fields[2],
                "nonce": fields[3].hex(),
                "epochs_completed": fields[4],
                "forward_epochs": fields[5],
                "backward_epochs": fields[6],
                "optimizer_steps": fields[7],
                "records_visited": fields[8],
                "parameter_writes": fields[9],
                "initial_loss": fields[10],
                "final_loss": fields[11],
                "final_parameters_hash": hashlib.sha256(parameter_raw).hexdigest(),
                "predictions_hash": hashlib.sha256(prediction_raw).hexdigest(),
            }
        )
    if offset != len(raw):
        raise VerificationFailure("result file has trailing bytes")
    return tuple(results)


def verify_work(
    *,
    receipts: tuple[Mapping[str, Any], ...],
    results: tuple[Mapping[str, Any], ...],
    summary: Mapping[str, Any],
    authority_tip: str,
    primitive: Mapping[str, Any],
    dataset_hash: str,
    initialization_hash: str,
    result_file_hash: str,
    receipt_file_hash: str,
) -> str:
    verify_seal(primitive, "manifest_sha256")
    verify_seal(summary, "summary_sha256")
    if primitive.get("decision_authority") is not False:
        raise VerificationFailure("foreign primitive claims decision authority")
    if len(receipts) != len(results) or not receipts:
        raise VerificationFailure("receipt/result count mismatch")
    if summary.get("K_completed") != len(receipts):
        raise VerificationFailure("summary K_completed mismatch")
    if summary.get("K_requested") != len(receipts) or summary.get("K_started") != len(receipts):
        raise VerificationFailure("requested, started and completed K differ")
    if summary.get("authority_chain_tip") != authority_tip:
        raise VerificationFailure("summary authority tip mismatch")
    if summary.get("receipt_file_sha256") != receipt_file_hash:
        raise VerificationFailure("summary receipt file hash mismatch")
    if summary.get("result_file_sha256") != result_file_hash:
        raise VerificationFailure("summary result file hash mismatch")
    case_ids: set[str] = set()
    nonces: set[str] = set()
    previous = "0" * 64
    for receipt, result in zip(receipts, results, strict=True):
        if receipt.get("schema") != WORK_SCHEMA:
            raise VerificationFailure("work receipt schema mismatch")
        if receipt.get("previous_work_chain_hash") != previous:
            raise VerificationFailure("work receipt chain order mismatch")
        receipt_hash = receipt.get("receipt_hash")
        if not isinstance(receipt_hash, str) or len(receipt_hash) != 64:
            raise VerificationFailure("missing seal: receipt_hash")
        receipt_seed = {
            key: item
            for key, item in receipt.items()
            if key not in {"receipt_hash", "chain_hash"}
        }
        if canonical_sha256(receipt_seed) != receipt_hash:
            raise VerificationFailure("invalid seal: receipt_hash")
        computed_chain = hashlib.sha256(
            bytes.fromhex(previous) + bytes.fromhex(receipt_hash)
        ).hexdigest()
        if receipt.get("chain_hash") != computed_chain:
            raise VerificationFailure("work receipt chain hash mismatch")
        expected = {
            "case_id": f"case-{int(result['case_id']):04d}",
            "case_index": result["index"],
            "nonce": result["nonce"],
            "seed": result["seed"],
            "epochs_completed": EPOCHS,
            "forward_epochs": EPOCHS,
            "backward_epochs": EPOCHS,
            "optimizer_steps": EPOCHS,
            "records_visited": RECORDS * EPOCHS,
            "parameter_writes": PARAMETERS * EPOCHS,
            "final_parameters_hash": result["final_parameters_hash"],
            "predictions_hash": result["predictions_hash"],
            "dataset_hash": dataset_hash,
            "initialization_bundle_hash": initialization_hash,
            "authority_receipt_hash": authority_tip,
            "primitive_manifest_sha256": primitive["manifest_sha256"],
            "result_file_sha256": result_file_hash,
        }
        for field, value in expected.items():
            if receipt.get(field) != value:
                raise VerificationFailure(f"work receipt field mismatch: {field}")
        counter_hash = canonical_sha256(
            {
                "epochs_completed": EPOCHS,
                "forward_epochs": EPOCHS,
                "backward_epochs": EPOCHS,
                "optimizer_steps": EPOCHS,
                "records_visited": RECORDS * EPOCHS,
                "parameter_writes": PARAMETERS * EPOCHS,
            }
        )
        if receipt.get("runtime_counter_hash") != counter_hash:
            raise VerificationFailure("runtime counter hash mismatch")
        if not math.isfinite(float(receipt.get("final_loss", math.nan))):
            raise VerificationFailure("work receipt final loss is not finite")
        if receipt["case_id"] in case_ids or receipt["nonce"] in nonces:
            raise VerificationFailure("work receipts duplicate case or nonce")
        case_ids.add(str(receipt["case_id"]))
        nonces.add(str(receipt["nonce"]))
        previous = computed_chain
    if summary.get("work_chain_tip") != previous:
        raise VerificationFailure("summary work chain tip mismatch")
    totals = {
        "epochs_completed": EPOCHS * len(receipts),
        "optimizer_steps": EPOCHS * len(receipts),
        "records_visited": RECORDS * EPOCHS * len(receipts),
        "parameter_writes": PARAMETERS * EPOCHS * len(receipts),
    }
    for field, value in totals.items():
        if summary.get(field) != value:
            raise VerificationFailure(f"summary total mismatch: {field}")
    return previous


def verify_bundle(
    *,
    grant_file: str | Path,
    authority_receipt_file: str | Path,
    primitive_manifest_file: str | Path,
    work_receipt_file: str | Path,
    result_file: str | Path,
    summary_file: str | Path,
    dataset_file: str | Path,
    initialization_file: str | Path,
) -> dict[str, Any]:
    grant = load_object(grant_file)
    authority_receipts = load_jsonl(authority_receipt_file)
    primitive = load_object(primitive_manifest_file)
    receipts = load_jsonl(work_receipt_file)
    summary = load_object(summary_file)
    authority_tip = verify_authority(grant, authority_receipts)
    dataset_hash = sha256_file(dataset_file)
    initialization_hash = sha256_file(initialization_file)
    if grant.get("config_from_t", {}).get("dataset_sha256") != dataset_hash:
        raise VerificationFailure("dataset identity differs from T authority")
    if grant.get("config_from_t", {}).get("bundle_sha256") != initialization_hash:
        raise VerificationFailure("initialization identity differs from T authority")
    results = parse_result(result_file)
    work_tip = verify_work(
        receipts=receipts,
        results=results,
        summary=summary,
        authority_tip=authority_tip,
        primitive=primitive,
        dataset_hash=dataset_hash,
        initialization_hash=initialization_hash,
        result_file_hash=sha256_file(result_file),
        receipt_file_hash=sha256_file(work_receipt_file),
    )
    seed = {
        "schema": "casulo.interlocution-independent-verification/1.0",
        "status": "PASS",
        "authority_surfaces": 9,
        "work_units": len(receipts),
        "authority_chain_tip": authority_tip,
        "work_chain_tip": work_tip,
        "dataset_sha256": dataset_hash,
        "initialization_sha256": initialization_hash,
        "result_sha256": sha256_file(result_file),
        "trainer_imported": False,
        "analysis_json_trusted": False,
    }
    return {**seed, "verification_sha256": canonical_sha256(seed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in (
        "grant_file",
        "authority_receipt_file",
        "primitive_manifest_file",
        "work_receipt_file",
        "result_file",
        "summary_file",
        "dataset_file",
        "initialization_file",
    ):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_bundle(**vars(args))
    except VerificationFailure as error:
        print(json.dumps({"status":"FAIL","reason":str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
