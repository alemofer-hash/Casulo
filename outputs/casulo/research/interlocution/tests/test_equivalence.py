from __future__ import annotations

import struct
from pathlib import Path

from interlocution.equivalence import compare_result_files


ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1/receipts/full-worker-smoke"


def test_identical_result_is_operationally_equivalent() -> None:
    result = compare_result_files(
        WORK / "worker-result.bin", WORK / "worker-result.bin", tolerance=1e-9
    )
    assert result["status"] == "PASS"
    assert result["maximum_parameter_abs_difference"] == 0
    assert result["maximum_prediction_abs_difference"] == 0


def test_counter_divergence_is_not_hidden_by_numerical_plausibility(tmp_path: Path) -> None:
    raw = bytearray((WORK / "worker-result.bin").read_bytes())
    # Header is 16 bytes. The first per-case epoch counter begins after
    # index, case_id, seed and nonce: 16 + 4 + 4 + 8 + 32.
    offset = 16 + 4 + 4 + 8 + 32
    struct.pack_into("<Q", raw, offset, 399)
    changed = tmp_path / "changed.bin"
    changed.write_bytes(raw)
    result = compare_result_files(changed, WORK / "worker-result.bin", tolerance=1e-9)
    assert result["status"] == "FAIL"
    assert result["cases"][0]["counters_equal"] is False

