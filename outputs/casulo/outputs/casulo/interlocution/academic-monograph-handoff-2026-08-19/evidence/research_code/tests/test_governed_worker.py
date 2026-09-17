from __future__ import annotations

import json
from pathlib import Path

import pytest

from interlocution.worker import (
    WorkerDenied,
    build_primitive_manifest,
    run_governed_worker,
)
from interlocution.contracts import canonical_sha256


ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"


def manifest(tmp_path: Path) -> Path:
    value = build_primitive_manifest(
        executable=FULL / "worker/tcap_full_worker.exe",
        source=FULL / "worker/tcap_full_worker.rs",
        tcap=FULL / "artifact/FloodSurrogate.full.tcap",
    )
    path = tmp_path / "primitive.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_complete_worker_emits_one_internal_receipt_with_exact_counters(tmp_path: Path) -> None:
    result = run_governed_worker(
        grant_file=CAMPAIGN / "authority-grant.json",
        authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
        primitive_manifest_file=manifest(tmp_path),
        executable=FULL / "worker/tcap_full_worker.exe",
        dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
        initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
        output_directory=tmp_path / "work",
        count=1,
    )
    assert result.summary["K_completed"] == 1
    receipt = result.receipts[0]
    assert receipt["epochs_completed"] == 400
    assert receipt["forward_epochs"] == 400
    assert receipt["backward_epochs"] == 400
    assert receipt["optimizer_steps"] == 400
    assert receipt["records_visited"] == 409600
    assert receipt["parameter_writes"] == 32400


def test_tampered_authority_grant_fails_before_worker(tmp_path: Path) -> None:
    grant = json.loads((CAMPAIGN / "authority-grant.json").read_text(encoding="utf-8"))
    grant["config_from_t"]["epochs"] = "8"
    tampered = tmp_path / "grant.json"
    tampered.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(WorkerDenied, match="grant seal mismatch"):
        run_governed_worker(
            grant_file=tampered,
            authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
            primitive_manifest_file=manifest(tmp_path),
            executable=FULL / "worker/tcap_full_worker.exe",
            dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
            initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
            output_directory=tmp_path / "work",
        )


def test_canary_or_other_dataset_is_rejected_after_t_authorization(tmp_path: Path) -> None:
    wrong = tmp_path / "eight-record-canary.bin"
    wrong.write_bytes(b"FWDATA1\0" + b"\0" * 128)
    with pytest.raises(WorkerDenied, match="dataset changed after T authorization"):
        run_governed_worker(
            grant_file=CAMPAIGN / "authority-grant.json",
            authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
            primitive_manifest_file=manifest(tmp_path),
            executable=FULL / "worker/tcap_full_worker.exe",
            dataset=wrong,
            initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
            output_directory=tmp_path / "work",
        )


def test_reordered_or_duplicated_t_receipts_are_rejected(tmp_path: Path) -> None:
    lines = (CAMPAIGN / "receipts/policy-authority.jsonl").read_text(encoding="utf-8").splitlines()
    broken = tmp_path / "receipts.jsonl"
    broken.write_text("\n".join([lines[1], lines[0], *lines[2:]]) + "\n", encoding="utf-8")
    with pytest.raises(WorkerDenied, match="surfaces are incomplete or reordered"):
        run_governed_worker(
            grant_file=CAMPAIGN / "authority-grant.json",
            authority_receipt_file=broken,
            primitive_manifest_file=manifest(tmp_path),
            executable=FULL / "worker/tcap_full_worker.exe",
            dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
            initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
            output_directory=tmp_path / "work",
        )


def test_initialization_changed_after_authorization_is_rejected(tmp_path: Path) -> None:
    wrong = tmp_path / "initializations.bin"
    raw = bytearray((FULL / "artifact/FloodSurrogate.initializations.bin").read_bytes())
    raw[-1] ^= 1
    wrong.write_bytes(raw)
    with pytest.raises(WorkerDenied, match="initialization changed after T authorization"):
        run_governed_worker(
            grant_file=CAMPAIGN / "authority-grant.json",
            authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
            primitive_manifest_file=manifest(tmp_path),
            executable=FULL / "worker/tcap_full_worker.exe",
            dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
            initializations=wrong,
            output_directory=tmp_path / "work",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("epochs", "399"),
        ("dtype", "float32"),
        ("optimizer_state_policy", "preserve_across_cases"),
    ],
)
def test_python_cannot_override_and_reseal_a_t_decision(
    tmp_path: Path, field: str, value: str
) -> None:
    grant = json.loads((CAMPAIGN / "authority-grant.json").read_text(encoding="utf-8"))
    grant["config_from_t"][field] = value
    grant_seed = {key: item for key, item in grant.items() if key != "grant_sha256"}
    grant["grant_sha256"] = canonical_sha256(grant_seed)
    changed = tmp_path / "grant.json"
    changed.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(WorkerDenied, match="policy is not supported"):
        run_governed_worker(
            grant_file=changed,
            authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
            primitive_manifest_file=manifest(tmp_path),
            executable=FULL / "worker/tcap_full_worker.exe",
            dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
            initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
            output_directory=tmp_path / "work",
        )


def test_primitive_cannot_claim_decision_authority_even_with_recomputed_seal(tmp_path: Path) -> None:
    value = json.loads(manifest(tmp_path).read_text(encoding="utf-8"))
    value["decision_authority"] = True
    seed = {key: item for key, item in value.items() if key != "manifest_sha256"}
    value["manifest_sha256"] = canonical_sha256(seed)
    changed = tmp_path / "authority-claiming-primitive.json"
    changed.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(WorkerDenied, match="forbidden decision authority"):
        run_governed_worker(
            grant_file=CAMPAIGN / "authority-grant.json",
            authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
            primitive_manifest_file=changed,
            executable=FULL / "worker/tcap_full_worker.exe",
            dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
            initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
            output_directory=tmp_path / "work",
        )


def test_existing_output_cannot_be_silently_reused_as_new_work(tmp_path: Path) -> None:
    output = tmp_path / "work"
    output.mkdir()
    (output / "worker-summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(WorkerDenied, match="output already exists"):
        run_governed_worker(
            grant_file=CAMPAIGN / "authority-grant.json",
            authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
            primitive_manifest_file=manifest(tmp_path),
            executable=FULL / "worker/tcap_full_worker.exe",
            dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
            initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
            output_directory=output,
        )
