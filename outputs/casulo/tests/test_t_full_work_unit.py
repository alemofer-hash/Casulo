from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from casulo.livelab.energy_v1.full_workers import (
    create_receipts,
    parse_initializations,
    parse_result_file,
    validate_full_tcap,
    validate_receipts,
)
from casulo.t.full_work_unit import (
    EPOCHS,
    RECORDS,
    SCIENTIFIC_WORK_UNIT,
    WorkUnitContract,
    build_full_work_unit_tcap,
)
from tools.run_full_worker_validation import _fit


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "t" / "flood_surrogate_training.t"


def _contract() -> WorkUnitContract:
    digest = "0" * 64
    return WorkUnitContract(
        workload_class=SCIENTIFIC_WORK_UNIT,
        work_unit_schema="casulo-flood-work-unit/1.0",
        records_per_epoch=RECORDS,
        epochs=EPOCHS,
        batch_size=RECORDS,
        input_features=8,
        hidden_features=8,
        output_features=1,
        precision="float64",
        optimizer="sgd",
        learning_rate=0.018,
        dataset_hash=digest,
        initialization_bundle_hash=digest,
        expected_record_visits=RECORDS * EPOCHS,
        expected_optimizer_steps=EPOCHS,
        expected_parameter_writes=81 * EPOCHS,
        scientific_eligible=True,
        general_ir_sha256=digest,
        graph_sha256=digest,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workload_class", "CORRECTNESS_CANARY"),
        ("records_per_epoch", 8),
        ("epochs", 399),
        ("dataset_hash", "f" * 63),
        ("scientific_eligible", False),
    ],
)
def test_scientific_contract_rejects_canary_or_mismatch(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="scientific work-unit"):
        dataclasses.replace(_contract(), **{field: value}).validate()


def test_incomplete_receipt_cannot_be_promoted_to_completed_work() -> None:
    with pytest.raises(ValueError, match="counter mismatch"):
        validate_receipts([{"receipt_hash": "x", "chain_hash": "y"}], 1)


def test_k_linearity_uses_every_preregistered_direction_as_a_replicate() -> None:
    rows = []
    for k in (1, 2, 5, 10, 20, 50, 100):
        for noise in (-0.02, 0.02):
            rows.append(
                {"K": k, "timing": {"worker_monotonic_ns": int((0.01 + 0.03 * k + noise) * 1e9)}}
            )
    fit = _fit(rows)
    assert fit["replicates_per_K"] == {str(k): 2 for k in (1, 2, 5, 10, 20, 50, 100)}
    assert fit["R2"] == pytest.approx(1.0)
    assert fit["gate"] == "PASS"


def _toolchain_available() -> bool:
    rustup = shutil.which("rustup")
    if rustup is None:
        return False
    result = subprocess.run(
        [rustup, "which", "--toolchain", "nightly-2026-02-01", "rustc"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.skipif(not _toolchain_available(), reason="pinned Rust toolchain unavailable")
def test_full_tcap_binds_dataset_ir_graph_and_initializations(tmp_path: Path) -> None:
    artifact = build_full_work_unit_tcap(SOURCE, tmp_path, case_count=2)
    contract, segments, cases = validate_full_tcap(artifact.tcap_file)

    assert contract.records_per_epoch == 1024
    assert contract.epochs == 400
    assert contract.expected_record_visits == 409600
    assert contract.expected_optimizer_steps == 400
    assert contract.expected_parameter_writes == 32400
    assert contract.scientific_eligible
    assert len(cases) == 2
    assert cases[0].nonce != cases[1].nonce
    assert len(segments["scientific_dataset"]) == 73752

    raw = bytearray(artifact.tcap_file.read_bytes())
    raw[-1] ^= 1
    corrupted = tmp_path / "corrupted.tcap"
    corrupted.write_bytes(raw)
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_full_tcap(corrupted)
