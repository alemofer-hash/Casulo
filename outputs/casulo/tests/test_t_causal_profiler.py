from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from casulo.t.causal_profiler import (
    CAUSAL_PROFILE_PROTOCOL,
    CausalProfilerError,
    create_causal_profile,
)


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "examples" / "tensor" / "mlp-mse-medium.tensor.json"


class CausalProfilerTests(unittest.TestCase):
    def test_profile_accounts_without_timing_or_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = create_causal_profile(
                GRAPH,
                Path(temporary) / "profile",
                wrt=("weight1", "weight2"),
                workers=4,
                gemm_workers=1,
                provider="openblas",
            )
            document = json.loads(
                profile.json_path.read_text(encoding="utf-8")
            )

            self.assertEqual(
                document["protocol"],
                CAUSAL_PROFILE_PROTOCOL,
            )
            self.assertFalse(document["scientific"]["runtime_measured"])
            self.assertIsNone(document["scientific"]["claim"])
            self.assertGreater(
                document["summary"]["known_scalar_flops"],
                0,
            )
            self.assertGreater(
                document["summary"]["logical_traffic_bytes"],
                0,
            )
            self.assertGreater(
                document["summary"]["category_counts"]["GEMM"],
                0,
            )
            self.assertTrue(profile.html_path.is_file())
            self.assertTrue(
                all(
                    item["claim"] is None
                    for item in document["instructions"]
                )
            )

    def test_ablation_matrix_is_declared_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = create_causal_profile(
                GRAPH,
                Path(temporary) / "profile",
                wrt=("weight1", "weight2"),
            )
            ablation = profile.document["ablation_plan"]

            self.assertEqual(len(ablation["variants"]), 6)
            self.assertIn(
                "no variant may be selected",
                ablation["selection_metric"],
            )
            self.assertIsNone(ablation["claim"])

    def test_profile_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "profile"
            create_causal_profile(
                GRAPH,
                output,
                wrt=("weight1", "weight2"),
            )

            with self.assertRaisesRegex(CausalProfilerError, "imutável"):
                create_causal_profile(
                    GRAPH,
                    output,
                    wrt=("weight1", "weight2"),
                )


if __name__ == "__main__":
    unittest.main()
