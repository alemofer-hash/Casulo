from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from casulo.t.scheduler_ablation import (
    VARIANT_ADAPTIVE,
    VARIANT_FIXED,
    classify_statistics,
    create_preregistration,
)
from casulo.t.window_calibration import verify_evidence


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "examples" / "tensor-suite" / "heldout-wide.tensor.json"


class SchedulerAblationTests(unittest.TestCase):
    def test_preregistration_seals_three_balanced_blocks(self) -> None:
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
            self.assertEqual(document["design"]["blocks"], 3)
            self.assertEqual(document["design"]["pairs_per_block"], 8)
            self.assertFalse(
                document["design"][
                    "uses_speedup_to_select_measurement_parameters"
                ]
            )
            self.assertEqual(
                document["design"]["power_contract"][
                    "minimum_start_battery_percent_if_unplugged"
                ],
                60.0,
            )
            for scheduled in document["design"]["schedule"]:
                first_positions = [order[0] for order in scheduled["orders"]]
                self.assertEqual(first_positions.count(VARIANT_FIXED), 4)
                self.assertEqual(first_positions.count(VARIANT_ADAPTIVE), 4)

    def test_decision_prefers_only_effect_with_directional_interval(self) -> None:
        common = {
            "fixed_cv": 0.05,
            "adaptive_cv": 0.05,
            "max_cv": 0.15,
            "practical_effect": 0.02,
            "equivalence_margin": 0.02,
        }
        self.assertEqual(
            classify_statistics(
                median_ratio=1.08,
                ci95_low=1.04,
                ci95_high=1.12,
                **common,
            ),
            "ADAPTIVE",
        )
        self.assertEqual(
            classify_statistics(
                median_ratio=0.92,
                ci95_low=0.89,
                ci95_high=0.96,
                **common,
            ),
            "FIXED",
        )
        self.assertEqual(
            classify_statistics(
                median_ratio=1.00,
                ci95_low=0.99,
                ci95_high=1.01,
                **common,
            ),
            "EQUIVALENT",
        )
        self.assertEqual(
            classify_statistics(
                median_ratio=1.03,
                ci95_low=0.97,
                ci95_high=1.08,
                **common,
            ),
            "INCONCLUSIVE",
        )

    def test_instability_precedes_effect(self) -> None:
        classification = classify_statistics(
            median_ratio=2.0,
            ci95_low=1.8,
            ci95_high=2.2,
            fixed_cv=0.20,
            adaptive_cv=0.05,
            max_cv=0.15,
            practical_effect=0.02,
            equivalence_margin=0.02,
        )

        self.assertEqual(classification, "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
