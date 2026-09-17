from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools" / "verify_frozen_evidence.py"


class FrozenEvidenceTests(unittest.TestCase):
    def test_frozen_evidence_chain(self) -> None:
        spec = importlib.util.spec_from_file_location("verify_frozen_evidence", VERIFIER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        checks = module.verify()

        self.assertGreaterEqual(len(checks), 5)


if __name__ == "__main__":
    unittest.main()
