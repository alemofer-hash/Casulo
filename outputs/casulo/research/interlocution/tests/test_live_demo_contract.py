from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_live_demo_has_real_fail_closed_steps() -> None:
    source = (ROOT / "research/interlocution/tools/run_live_demo.py").read_text(encoding="utf-8")
    assert "TAMPERED_DATASET_REJECTED_BY_T" in source
    assert "INCOMPLETE_EXECUTION_REJECTED" in source
    assert "run_governed_worker" in source
    assert '"fixture": False' in source
    assert '"external_api": False' in source
    assert "dataset_hash_mismatch" in source
    assert "tamper-runtime-inputs" in source
