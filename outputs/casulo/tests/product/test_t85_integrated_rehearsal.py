from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("run_t85_integrated_rehearsal", ROOT / "tools/run_t85_integrated_rehearsal.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
StepLedger = MODULE.StepLedger
_request_absent = MODULE._request_absent
_verify_release = MODULE._verify_release


def test_release_manifest_is_verified_without_checkout_execution() -> None:
    result = _verify_release(ROOT / "release/t85-human-proof")
    assert result["valid"] is True
    assert result["mismatches"] == []
    assert result["checkout_dependency"] is False


def test_novelty_scan_finds_literal_and_accepts_unseen_requirement(tmp_path: Path) -> None:
    (tmp_path / "known.py").write_text("KNOWN_LITERAL", encoding="utf-8")
    result = _request_absent(tmp_path, "KNOWN_LITERAL", ("UNSEEN_A", "UNSEEN_B", "UNSEEN_C"))
    assert result["absent"] is False
    assert result["hits"]["KNOWN_LITERAL"] == ["known.py"]
    assert all(not result["hits"][item] for item in ("UNSEEN_A", "UNSEEN_B", "UNSEEN_C"))


def test_step_ledger_is_append_only_hash_chain(tmp_path: Path) -> None:
    ledger = StepLedger(tmp_path)
    first = ledger.add("FIRST", {"real": True})
    second = ledger.add("SECOND", {"receipt": first["receipt_hash"]})
    rows = [json.loads(line) for line in (tmp_path / "step-receipts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows == [first, second]
    assert second["previous_receipt_hash"] == first["receipt_hash"]
    unsigned = {key: value for key, value in second.items() if key != "receipt_hash"}
    canonical = (json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == second["receipt_hash"]


def test_harness_requires_holdout_text_via_cli() -> None:
    source = (ROOT / "tools/run_t85_integrated_rehearsal.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--idea", required=True)' in source
    assert 'parser.add_argument("--requirement", action="append", required=True)' in source
    assert "agente local que reconcilia cadernos" not in source
