from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
VERIFY_PATH = ROOT / "research/interlocution/independent_verifier.py"
SPEC = importlib.util.spec_from_file_location("interlocution_independent_verifier", VERIFY_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)

CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
WORK = CAMPAIGN / "receipts/full-worker-smoke"


def arguments(**changes):
    values = {
        "grant_file": CAMPAIGN / "authority-grant.json",
        "authority_receipt_file": CAMPAIGN / "receipts/policy-authority.jsonl",
        "primitive_manifest_file": CAMPAIGN / "primitive-manifest.json",
        "work_receipt_file": WORK / "work-receipts.jsonl",
        "result_file": WORK / "worker-result.bin",
        "summary_file": WORK / "worker-summary.json",
        "dataset_file": FULL / "artifact/FloodSurrogate.dataset.bin",
        "initialization_file": FULL / "artifact/FloodSurrogate.initializations.bin",
    }
    values.update(changes)
    return values


def test_valid_smoke_is_recomputed_without_trainer_import() -> None:
    result = verifier.verify_bundle(**arguments())
    assert result["status"] == "PASS"
    assert result["work_units"] == 1
    assert result["trainer_imported"] is False
    source = VERIFY_PATH.read_text(encoding="utf-8")
    assert "casulo.livelab" not in source
    assert "interlocution.worker" not in source


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("epochs_completed", 399, "invalid seal: receipt_hash"),
        ("optimizer_steps", 399, "invalid seal: receipt_hash"),
        ("records_visited", 8 * 400, "invalid seal: receipt_hash"),
    ],
)
def test_plausible_but_incomplete_work_is_rejected(tmp_path: Path, field: str, value: int, message: str) -> None:
    receipt = json.loads((WORK / "work-receipts.jsonl").read_text(encoding="utf-8"))
    receipt[field] = value
    receipt_seed = {
        key: item for key, item in receipt.items()
        if key not in {"receipt_hash", "chain_hash"}
    }
    receipt["receipt_hash"] = verifier.canonical_sha256(receipt_seed)
    receipt["chain_hash"] = __import__("hashlib").sha256(
        bytes.fromhex("0" * 64) + bytes.fromhex(receipt["receipt_hash"])
    ).hexdigest()
    path = tmp_path / "receipt.jsonl"
    path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    summary = json.loads((WORK / "worker-summary.json").read_text(encoding="utf-8"))
    summary["receipt_file_sha256"] = verifier.sha256_file(path)
    summary["work_chain_tip"] = receipt["chain_hash"]
    summary[field] = value
    summary_seed = {key: item for key, item in summary.items() if key != "summary_sha256"}
    summary["summary_sha256"] = verifier.canonical_sha256(summary_seed)
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(verifier.VerificationFailure, match=f"work receipt field mismatch: {field}"):
        verifier.verify_bundle(**arguments(work_receipt_file=path, summary_file=summary_path))


def test_result_cache_or_replay_tamper_is_rejected(tmp_path: Path) -> None:
    raw = bytearray((WORK / "worker-result.bin").read_bytes())
    raw[-1] ^= 1
    path = tmp_path / "result.bin"
    path.write_bytes(raw)
    with pytest.raises(verifier.VerificationFailure, match="result file hash mismatch"):
        verifier.verify_bundle(**arguments(result_file=path))


def test_duplicate_receipt_cannot_turn_one_execution_into_k_two(tmp_path: Path) -> None:
    line = (WORK / "work-receipts.jsonl").read_text(encoding="utf-8").strip()
    path = tmp_path / "receipts.jsonl"
    path.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(verifier.VerificationFailure, match="receipt/result count mismatch"):
        verifier.verify_bundle(**arguments(work_receipt_file=path))


def test_rehashed_invented_case_is_compared_to_result_binary(tmp_path: Path) -> None:
    receipt = json.loads((WORK / "work-receipts.jsonl").read_text(encoding="utf-8"))
    receipt["case_id"] = "case-9999"
    seed = {key: item for key, item in receipt.items() if key not in {"receipt_hash", "chain_hash"}}
    receipt["receipt_hash"] = verifier.canonical_sha256(seed)
    receipt["chain_hash"] = __import__("hashlib").sha256(
        bytes.fromhex("0" * 64) + bytes.fromhex(receipt["receipt_hash"])
    ).hexdigest()
    path = tmp_path / "receipt.jsonl"
    path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    summary = json.loads((WORK / "worker-summary.json").read_text(encoding="utf-8"))
    summary["receipt_file_sha256"] = verifier.sha256_file(path)
    summary["work_chain_tip"] = receipt["chain_hash"]
    summary_seed = {key: item for key, item in summary.items() if key != "summary_sha256"}
    summary["summary_sha256"] = verifier.canonical_sha256(summary_seed)
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(verifier.VerificationFailure, match="work receipt field mismatch: case_id"):
        verifier.verify_bundle(**arguments(work_receipt_file=path, summary_file=summary_path))


def test_reordered_t_receipt_stream_is_rejected_independently(tmp_path: Path) -> None:
    lines = (CAMPAIGN / "receipts/policy-authority.jsonl").read_text(encoding="utf-8").splitlines()
    path = tmp_path / "authority.jsonl"
    path.write_text("\n".join([lines[1], lines[0], *lines[2:]]) + "\n", encoding="utf-8")
    with pytest.raises(verifier.VerificationFailure, match="surfaces are reordered or missing"):
        verifier.verify_bundle(**arguments(authority_receipt_file=path))
