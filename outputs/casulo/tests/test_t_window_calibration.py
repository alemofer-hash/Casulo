from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from casulo.t.window_calibration import (
    WindowCalibrationError,
    create_preregistration,
    select_smallest_stable_window,
    verify_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "examples" / "tensor" / "mlp-mse-medium.tensor.json"


def _report(window_ms: float, cv: float, stable: bool) -> dict:
    return {
        "window_ms": window_ms,
        "statistics": {
            "coefficient_of_variation": cv,
            "stable": stable,
        },
    }


class WindowCalibrationTests(unittest.TestCase):
    def test_preregistration_is_immutable_and_hash_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "preregistration.json"
            document = create_preregistration(
                GRAPH,
                output,
                wrt=("weight1", "weight2"),
            )
            verified, digest = verify_evidence(output)

            self.assertEqual(verified, document)
            self.assertEqual(len(digest), 64)
            self.assertFalse(
                document["design"]["uses_speedup_or_winner_selection"]
            )
            self.assertFalse(document["scientific_scope"]["claim_eligible"])
            with self.assertRaises(WindowCalibrationError):
                create_preregistration(
                    GRAPH,
                    output,
                    wrt=("weight1", "weight2"),
                )

    def test_adaptive_gemm_policy_can_be_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "adaptive.json"
            document = create_preregistration(
                GRAPH,
                output,
                wrt=("weight1", "weight2"),
                workers=2,
                gemm_workers="adaptive",
                provider="openblas",
            )

            self.assertEqual(document["workload"]["workers"], 2)
            self.assertEqual(
                document["workload"]["gemm_workers"],
                "adaptive",
            )
            self.assertEqual(document["workload"]["provider"], "openblas")

    def test_first_stable_window_is_selected_in_registered_order(self) -> None:
        preregistration = {
            "design": {"windows_ms": [250.0, 500.0, 1000.0]}
        }
        decision = select_smallest_stable_window(
            preregistration,
            [_report(250, 0.20, False), _report(500, 0.08, True)],
        )

        self.assertEqual(decision["status"], "PASSED")
        self.assertEqual(decision["selected_window_ms"], 500.0)
        self.assertFalse(decision["uses_speedup_or_winner_selection"])

    def test_missing_next_window_is_explicit(self) -> None:
        preregistration = {"design": {"windows_ms": [250.0, 500.0]}}
        decision = select_smallest_stable_window(
            preregistration,
            [_report(250, 0.20, False)],
        )

        self.assertEqual(decision["status"], "INCONCLUSIVE")
        self.assertTrue(decision["needs_next_window"])
        self.assertEqual(decision["next_window_ms"], 500.0)

    def test_out_of_order_gap_cannot_skip_a_smaller_window(self) -> None:
        preregistration = {"design": {"windows_ms": [250.0, 500.0]}}
        decision = select_smallest_stable_window(
            preregistration,
            [_report(500, 0.01, True)],
        )

        self.assertEqual(decision["status"], "INCONCLUSIVE")
        self.assertEqual(decision["next_window_ms"], 250.0)


if __name__ == "__main__":
    unittest.main()
