from __future__ import annotations

import io
import json
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
from casulo.t.borboleta import (
    BORBOLETA_PROTOCOL,
    BorboletaConfig,
    BorboletaLaboratorio,
    generate_hydrological_dataset,
)
from casulo.t.cli import main as t_main


CANONICAL_SOURCE = ROOT / "examples" / "t" / "balanco_hidrico.t"


class BorboletaDatasetTests(unittest.TestCase):
    def test_generation_is_deterministic_and_versioned(self) -> None:
        config = BorboletaConfig(records=30, seed=77, bootstrap_resamples=10)
        first = generate_hydrological_dataset(config)
        second = generate_hydrological_dataset(config)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.payloads, second.payloads)
        self.assertEqual(len(first.sha256), 64)
        self.assertTrue(first.protocol.startswith("casulo-dataset/"))

    def test_generated_payloads_obey_input_guard(self) -> None:
        dataset = generate_hydrological_dataset(
            BorboletaConfig(records=50, bootstrap_resamples=10)
        )
        self.assertTrue(
            all(item["precipitation"] >= 0 for item in dataset.payloads)
        )


class BorboletaLaboratorioTests(unittest.TestCase):
    def test_report_proves_equivalence_and_labels_energy(self) -> None:
        config = BorboletaConfig(
            records=20,
            duplicate_rate=0.0,
            samples=3,
            iterations=1,
            warmups=0,
            bootstrap_resamples=50,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                root / "artifact",
            ).output_dir
            report = BorboletaLaboratorio().run(
                artifact,
                config=config,
            )
            json_path, html_path = report.write(root / "report")
            saved = json.loads(json_path.read_text(encoding="utf-8"))
            rendered = html_path.read_text(encoding="utf-8")
        self.assertEqual(report.protocol, BORBOLETA_PROTOCOL)
        self.assertTrue(report.comparison["semantically_equivalent"])
        self.assertEqual(len(report.equivalence_sha256), 64)
        self.assertGreater(report.scalar.median_wall_ns, 0)
        self.assertGreater(report.optimized.median_wall_ns, 0)
        self.assertGreater(report.adaptive.median_wall_ns, 0)
        self.assertIn("electrical_energy_measured", report.energy)
        self.assertIn("decision", report.adaptation)
        self.assertEqual(
            report.adaptation["decision"]["strategy"],
            "FUSE_TYPED_BATCH",
        )
        self.assertIn(
            report.adaptation["assessment"],
            {"CORRECT", "INCONCLUSIVE_SAFE"},
        )
        self.assertEqual(saved["artifact_id"], report.artifact_id)
        self.assertTrue(
            report.comparison["representation"]["available"]
        )
        self.assertGreater(
            report.comparison["representation"][
                "peak_traced_bytes_reduction"
            ],
            0.0,
        )
        self.assertIn("Casulo", rendered)
        self.assertIn("Borboleta", rendered)

    def test_experiment_cli_materializes_complete_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "experiment"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = t_main(
                    [
                        "experiment",
                        str(CANONICAL_SOURCE),
                        "--output",
                        str(output),
                        "--records",
                        "20",
                        "--samples",
                        "2",
                        "--iterations",
                        "1",
                        "--warmups",
                        "0",
                        "--bootstrap-resamples",
                        "20",
                        "--build-dir",
                        str(Path(temporary) / "implicit-build"),
                    ]
                )
            summary = json.loads(stdout.getvalue())
            materialized = [
                (output / name).is_file()
                for name in (
                    "dataset.json",
                    "dataset-manifest.json",
                    "borboleta-report.json",
                    "borboleta-report.html",
                )
            ]
        self.assertEqual(status, 0)
        self.assertTrue(summary["ok"])
        self.assertTrue(all(materialized))


if __name__ == "__main__":
    unittest.main()
