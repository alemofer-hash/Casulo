from __future__ import annotations

import hashlib
import json
from pathlib import Path

from casulo.t.api import check_file


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "conformance/golden"
EXPECTED_TREE = "3078bc4433a824d9729eaf5d00d2ad2e64849b5989a54ea1d557fa97d9f9d183"


def test_t10_source_corpus_is_frozen() -> None:
    digest = hashlib.sha256()
    files = sorted(
        path for path in GOLDEN.rglob("*") if path.is_file() and path.name != "manifest.json"
    )
    assert len(files) == 42
    for path in files:
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(relative + b"\0" + path.read_bytes())
    assert digest.hexdigest() == EXPECTED_TREE


def test_t10_manifest_outcomes_and_diagnostics_remain_compatible() -> None:
    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "T 1.0"
    for case in manifest["cases"]:
        result = check_file(GOLDEN / case["path"])
        codes = [diagnostic.code for diagnostic in result.diagnostics]
        assert result.ok is case["ok"], case["path"]
        assert codes == case["codes"], case["path"]
