from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from casulo.t.training import (
    TrainingError,
    TrainingSpecError,
    build_training_artifact,
    generate_training_dataset,
    parse_training_file,
    parse_training_spec,
    run_training_experiment,
    select_training_workers,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "t" / "flood_surrogate_training.t"
OFFICIAL_PROOF = (
    ROOT
    / "benchmarks"
    / "results"
    / "2026-07-30-sprint012-training-proof"
)
HAS_ML_RUNTIME = (
    importlib.util.find_spec("numpy") is not None
    and importlib.util.find_spec("torch") is not None
    and (
        shutil.which("gcc")
        or shutil.which("gcc.exe")
        or shutil.which("clang")
        or shutil.which("clang.exe")
    )
)


class TrainingSpecTests(unittest.TestCase):
    def test_example_declares_a_reproducible_full_batch_mlp(self) -> None:
        spec = parse_training_file(EXAMPLE)

        self.assertEqual(spec.name, "FloodSurrogate")
        self.assertEqual(spec.input_features, 8)
        self.assertEqual(spec.output_features, 1)
        self.assertEqual(spec.precision, "float64")
        self.assertEqual(spec.batch, "full")

    def test_unknown_or_missing_properties_are_rejected(self) -> None:
        with self.assertRaisesRegex(TrainingSpecError, "desconhecidas"):
            parse_training_spec(
                EXAMPLE.read_text(encoding="utf-8") + "\n  magic yes\n"
            )
        with self.assertRaisesRegex(TrainingSpecError, "ausentes"):
            parse_training_spec(
                EXAMPLE.read_text(encoding="utf-8").replace(
                    "  optimizer sgd\n",
                    "",
                )
            )

    @unittest.skipUnless(
        importlib.util.find_spec("numpy") is not None,
        "NumPy não instalado",
    )
    def test_dataset_has_frozen_training_and_validation_partitions(self) -> None:
        spec = parse_training_file(EXAMPLE)
        first = generate_training_dataset(spec, records=64, seed=123)
        second = generate_training_dataset(spec, records=64, seed=123)

        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.inputs.shape, (64, 8))
        self.assertEqual(first.validation_inputs.shape, (128, 8))
        self.assertEqual(first.inputs.tobytes(), second.inputs.tobytes())
        self.assertEqual(
            first.validation_targets.tobytes(),
            second.validation_targets.tobytes(),
        )

    def test_artifact_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifact"
            first = build_training_artifact(EXAMPLE, output)
            second = build_training_artifact(EXAMPLE, output)

            self.assertEqual(first.artifact_id, second.artifact_id)
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["artifact_id"], first.artifact_id)
            self.assertEqual(
                manifest["semantics"]["reduction"],
                "contiguous-partitions-worker-order",
            )

    def test_artifact_reuse_rejects_tampered_native_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifact"
            build_training_artifact(EXAMPLE, output)
            native_source = output / "casulo_training.c"
            native_source.write_text(
                native_source.read_text(encoding="utf-8") + "\n/* tampered */\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(TrainingError, "adulterado"):
                build_training_artifact(EXAMPLE, output)

    def test_scheduler_refuses_harmful_parallelism_for_compact_model(self) -> None:
        spec = parse_training_file(EXAMPLE)

        decision = select_training_workers(spec, 1_024, "auto")

        self.assertEqual(decision["selected_workers"], 1)
        self.assertIn("sincronização", decision["reason"])


@unittest.skipUnless(HAS_ML_RUNTIME, "runtime ML/C99 opcional indisponível")
class TrainingExperimentTests(unittest.TestCase):
    def test_smoke_proves_equivalence_without_forcing_6x_claim(self) -> None:
        source = (
            EXAMPLE.read_text(encoding="utf-8")
            .replace("  epochs 400", "  epochs 2")
            .replace("  target_loss 0.08", "  target_loss 10.0")
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "smoke.t"
            source_path.write_text(source, encoding="utf-8")
            report = run_training_experiment(
                source_path,
                root / "result",
                records=32,
                samples=5,
                warmups=1,
                workers=1,
                seed=456,
                bootstrap_resamples=200,
            )

            self.assertTrue(report.quality["equivalent_training"])
            self.assertTrue(report.quality["quality_target_reached"])
            self.assertEqual(report.comparison["workers"], 1)
            self.assertFalse(report.energy["electrical_energy_measured"])
            self.assertEqual(
                report.scientific["status"],
                "EXPLORATORY_UNREGISTERED",
            )
            self.assertFalse(report.comparison["claim_gate_6x"])
            self.assertTrue((root / "result" / "training-report.json").is_file())
            self.assertTrue((root / "result" / "training-report.html").is_file())


@unittest.skipUnless(OFFICIAL_PROOF.is_dir(), "prova oficial não incluída")
class TrainingEvidenceTests(unittest.TestCase):
    def test_official_proof_passes_the_independent_verifier(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "verify_training_evidence.py"),
                "--directory",
                str(OFFICIAL_PROOF),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("TRAINING EVIDENCE IS VALID", completed.stdout)


if __name__ == "__main__":
    unittest.main()
