from __future__ import annotations

import io
import json
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo.t import ArtifactBuilder
from casulo.t.adaptativo import (
    EstrategiaMetamorfose,
    MetamorfoseAdaptativa,
    ModeloCrisalida,
    PerfilLarva,
)
from casulo.t.cli import main as t_main


CANONICAL_SOURCE = ROOT / "examples" / "t" / "balanco_hidrico.t"


def payload(index: int) -> dict[str, float]:
    return {
        "precipitation": 100.0 + index,
        "evapotranspiration": 10.0,
        "surface_flow": 20.0,
        "base_flow": 5.0,
    }


class PerfilLarvaTests(unittest.TestCase):
    def test_profile_counts_exact_repetition_and_bytes(self) -> None:
        values = [payload(index % 10) for index in range(100)]
        profile = PerfilLarva.from_payloads(values)
        self.assertEqual(profile.records, 100)
        self.assertEqual(profile.unique_records, 10)
        self.assertEqual(profile.repeated_records, 90)
        self.assertAlmostEqual(profile.repetition_rate, 0.9)
        self.assertGreater(profile.total_payload_bytes, 0)


class ModeloCrisalidaTests(unittest.TestCase):
    def test_cheap_operation_recalculates_at_twenty_five_percent(self) -> None:
        values = [payload(index % 1_500) for index in range(2_000)]
        random.Random(8).shuffle(values)
        profile = PerfilLarva.from_payloads(values)
        decision = ModeloCrisalida().decide(
            operation="WaterBalance",
            operation_cost=8,
            cacheable=True,
            profile=profile,
        )
        self.assertEqual(
            decision.strategy,
            EstrategiaMetamorfose.RECALCULATE,
        )
        self.assertFalse(decision.use_cache)

    def test_cheap_operation_deduplicates_at_fifty_percent(self) -> None:
        values = [payload(index % 1_000) for index in range(2_000)]
        random.Random(8).shuffle(values)
        profile = PerfilLarva.from_payloads(values)
        decision = ModeloCrisalida().decide(
            operation="WaterBalance",
            operation_cost=8,
            cacheable=True,
            profile=profile,
        )
        self.assertEqual(
            decision.strategy,
            EstrategiaMetamorfose.DEDUPLICATE_BATCH,
        )
        self.assertTrue(decision.use_cache)

    def test_expensive_operation_accepts_lower_repetition(self) -> None:
        values = [payload(index % 400) for index in range(1_000)]
        random.Random(8).shuffle(values)
        profile = PerfilLarva.from_payloads(values)
        decision = ModeloCrisalida().decide(
            operation="Expensive",
            operation_cost=512,
            cacheable=True,
            profile=profile,
        )
        self.assertEqual(
            decision.strategy,
            EstrategiaMetamorfose.DEDUPLICATE_BATCH,
        )

    def test_memory_budget_blocks_cache(self) -> None:
        values = [
            {"id": index, "content": "x" * 2_000}
            for index in range(100)
        ]
        profile = PerfilLarva.from_payloads(values * 20)
        decision = ModeloCrisalida(memory_budget_bytes=1_000).decide(
            operation="Large",
            operation_cost=4_096,
            cacheable=True,
            profile=profile,
        )
        self.assertEqual(
            decision.strategy,
            EstrategiaMetamorfose.RECALCULATE,
        )
        self.assertTrue(
            any("orçamento" in reason for reason in decision.reasons)
        )


class MetamorfoseAdaptativaTests(unittest.TestCase):
    def test_manifest_exposes_optimization_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            optimization = built.manifest["operations"][0]["optimization"]
        self.assertEqual(optimization["estimated_cost"], 8)
        self.assertTrue(optimization["cacheable"])
        self.assertTrue(optimization["deterministic"])
        self.assertEqual(
            optimization["key_protocol"],
            "casulo-structural-key/0.1",
        )
        self.assertEqual(optimization["cache_scope"], "batch-local")
        self.assertEqual(
            optimization["buffer_protocol"],
            "casulo-typed-buffer/0.1",
        )
        self.assertEqual(optimization["manifestation"], "boundary")

    def test_runtime_fuses_unique_typed_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            executed = MetamorfoseAdaptativa().run(
                artifact,
                [payload(index) for index in range(100)],
            )
        self.assertEqual(
            executed.decision.strategy,
            EstrategiaMetamorfose.FUSE_TYPED_BATCH,
        )
        self.assertTrue(executed.payload["cache"]["enabled"])
        self.assertEqual(
            executed.payload["cache"]["buffer_protocol"],
            "casulo-typed-buffer/0.1",
        )
        self.assertEqual(executed.payload["count"], 100)

    def test_runtime_deduplicates_high_repetition_batch(self) -> None:
        values = [payload(index % 5) for index in range(100)]
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            executed = MetamorfoseAdaptativa().run(artifact, values)
        self.assertEqual(
            executed.decision.strategy,
            EstrategiaMetamorfose.DEDUPLICATE_BATCH,
        )
        self.assertTrue(executed.payload["cache"]["enabled"])
        self.assertEqual(executed.payload["cache"]["hits"], 95)
        self.assertEqual(
            [item["input"] for item in executed.payload["items"]],
            values,
        )

    def test_cli_manifests_adaptive_decision(self) -> None:
        values = [payload(index) for index in range(100)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                root / "artifact",
            ).output_dir
            input_file = root / "input.json"
            input_file.write_text(json.dumps(values), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = t_main(
                    [
                        "run",
                        str(artifact),
                        "--input",
                        str(input_file),
                        "--adaptive",
                        "--build-dir",
                        str(root / "implicit-build"),
                    ]
                )
            result = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(
            result["adaptation"]["decision"]["strategy"],
            "FUSE_TYPED_BATCH",
        )
        self.assertTrue(result["cache"]["enabled"])


if __name__ == "__main__":
    unittest.main()
