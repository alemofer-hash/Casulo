from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("run_t85_final_authority_audit", ROOT / "tools/run_t85_final_authority_audit.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_final_authority_score_is_evidence_bound_and_above_target() -> None:
    audit, seals = MODULE.build_audit(ROOT / "docs/product/TS_SOVEREIGNTY_MATRIX.json")
    assert audit.authority_score == 56 / 65
    assert audit.execution_score == 56 / 65
    assert audit.critical_coverage == 1.0
    assert seals and all(item["valid"] for item in seals.values())


def test_unmigrated_surfaces_receive_no_credit() -> None:
    audit, _ = MODULE.build_audit(ROOT / "docs/product/TS_SOVEREIGNTY_MATRIX.json")
    by_id = {item["id"]: item for item in audit.to_dict()["surfaces"]}
    assert set(MODULE.NOT_MIGRATED) == {"tools_composition", "interface_state", "recovery_update"}
    assert all(by_id[item]["degree"] == 0.0 and by_id[item]["execution_credit"] == 0.0 for item in MODULE.NOT_MIGRATED)
