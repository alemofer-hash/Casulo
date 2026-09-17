from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from casulo.t.scientific import (
    PYTORCH_COMPILE_BASELINE,
    PYTORCH_EAGER_BASELINE,
    PreregistrationError,
    create_training_preregistration,
    judge_training_evidence,
    verify_preregistration,
    verify_scientific_chain,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "t" / "flood_surrogate_training.t"
OFFICIAL_EVIDENCE = ROOT / "evidence" / "2026-07-30-prova-irrefutavel"
OFFICIAL_REPORT = (
    ROOT
    / "benchmarks"
    / "results"
    / "2026-07-30-scientific-covenant-eager"
    / "training-report.json"
)
OFFICIAL_COMPILE_EVIDENCE = (
    ROOT / "evidence" / "2026-07-30-pytorch-compile"
)
OFFICIAL_COMPILE_REPORT = (
    ROOT
    / "benchmarks"
    / "results"
    / "2026-07-30-scientific-covenant-compile"
    / "training-report.json"
)


class ScientificPreregistrationTests(unittest.TestCase):
    def test_preregistration_is_sealed_and_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "preregistration.json"
            created = create_training_preregistration(
                EXAMPLE,
                output,
                samples=5,
                warmups=1,
                bootstrap_resamples=200,
            )
            verified = verify_preregistration(output)

            self.assertEqual(created.experiment_id, verified.experiment_id)
            self.assertFalse(
                verified.document["observed_results_at_registration"]
            )
            self.assertEqual(
                verified.document["design"]["required_baselines"],
                [PYTORCH_EAGER_BASELINE, PYTORCH_COMPILE_BASELINE],
            )
            self.assertEqual(
                verified.document["design"]["implementation"]["binding"],
                "sha256-source-files",
            )
            with self.assertRaisesRegex(PreregistrationError, "imutável"):
                create_training_preregistration(EXAMPLE, output)

    def test_tampered_preregistration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "preregistration.json"
            create_training_preregistration(
                EXAMPLE,
                output,
                samples=5,
                warmups=1,
                bootstrap_resamples=200,
            )
            document = json.loads(output.read_text(encoding="utf-8"))
            document["hypothesis"]["commercial_threshold"] = 0.5
            output.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(PreregistrationError, "adulterado"):
                verify_preregistration(output)


class ScientificJudgeTests(unittest.TestCase):
    def test_missing_compiled_baseline_makes_positive_eager_result_inconclusive(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration_path = root / "preregistration.json"
            preregistration = create_training_preregistration(
                EXAMPLE,
                preregistration_path,
                samples=5,
                warmups=1,
                bootstrap_resamples=200,
            )
            report_path = root / "training-report.json"
            report_path.write_text(
                json.dumps(
                    _report_for(preregistration.document, speedup=8.0)
                ),
                encoding="utf-8",
            )

            verdict = judge_training_evidence(
                preregistration_path,
                report_path,
                root / "verdict.json",
            )

            self.assertEqual(verdict.classification, "INCONCLUSIVE")
            self.assertEqual(
                verdict.document["evidence"]["missing_required_baselines"],
                [PYTORCH_COMPILE_BASELINE],
            )
            self.assertFalse(
                verdict.document["recomputed_metrics"]["commercial_gate"]
            )

    def test_eager_only_preregistered_result_can_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration_path = root / "preregistration.json"
            preregistration = create_training_preregistration(
                EXAMPLE,
                preregistration_path,
                samples=5,
                warmups=1,
                bootstrap_resamples=200,
                required_baselines=[PYTORCH_EAGER_BASELINE],
            )
            report_path = root / "training-report.json"
            report_path.write_text(
                json.dumps(
                    _report_for(preregistration.document, speedup=8.0)
                ),
                encoding="utf-8",
            )

            verdict = judge_training_evidence(
                preregistration_path,
                report_path,
                root / "verdict.json",
            )

            self.assertEqual(verdict.classification, "POSITIVE")
            self.assertTrue(
                verdict.document["recomputed_metrics"]["commercial_gate"]
            )

    def test_reported_median_cannot_disagree_with_raw_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration_path = root / "preregistration.json"
            preregistration = create_training_preregistration(
                EXAMPLE,
                preregistration_path,
                samples=5,
                warmups=1,
                bootstrap_resamples=200,
                required_baselines=[PYTORCH_EAGER_BASELINE],
            )
            report = _report_for(preregistration.document, speedup=8.0)
            report["comparison"]["paired_speedup_median"] = 80.0
            report_path = root / "training-report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            verdict = judge_training_evidence(
                preregistration_path,
                report_path,
                root / "verdict.json",
            )

            self.assertEqual(verdict.classification, "INVALID")
            self.assertIn(
                "REPORTED_MEDIAN_DIVERGES_FROM_RAW_SAMPLES",
                verdict.document["evidence"]["integrity_failures"],
            )


@unittest.skipUnless(
    OFFICIAL_EVIDENCE.is_dir() and OFFICIAL_REPORT.is_file(),
    "cadeia científica oficial não incluída",
)
class OfficialScientificChainTests(unittest.TestCase):
    def test_inconclusive_chain_is_reproducible_and_preserves_missing_baseline(
        self,
    ) -> None:
        checks = verify_scientific_chain(
            OFFICIAL_EVIDENCE / "preregistration.json",
            OFFICIAL_REPORT,
            OFFICIAL_EVIDENCE / "pytorch-compile-probe.json",
            OFFICIAL_EVIDENCE / "verdict-v2.json",
        )

        self.assertEqual(len(checks), 7)


@unittest.skipUnless(
    OFFICIAL_COMPILE_EVIDENCE.is_dir()
    and OFFICIAL_COMPILE_REPORT.is_file(),
    "cadeia científica compilada oficial não incluída",
)
class OfficialCompiledScientificChainTests(unittest.TestCase):
    def test_positive_compiled_chain_is_independently_reproducible(self) -> None:
        checks = verify_scientific_chain(
            OFFICIAL_COMPILE_EVIDENCE / "preregistration.json",
            OFFICIAL_COMPILE_REPORT,
            OFFICIAL_COMPILE_EVIDENCE / "capability-probe.json",
            OFFICIAL_COMPILE_EVIDENCE / "verdict.json",
        )
        verdict = json.loads(
            (OFFICIAL_COMPILE_EVIDENCE / "verdict.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(len(checks), 7)
        self.assertEqual(verdict["classification"], "POSITIVE")
        self.assertTrue(verdict["recomputed_metrics"]["commercial_gate"])


def _report_for(preregistration: dict, *, speedup: float) -> dict:
    design = preregistration["design"]
    candidate = [100, 102, 98, 101, 99]
    reference = [round(value * speedup) for value in candidate]
    paired = [
        baseline / casulo
        for baseline, casulo in zip(reference, candidate, strict=True)
    ]
    quality = {
        "equivalent_training": True,
        "quality_target_reached": True,
        "same_dataset": True,
        "same_architecture": True,
        "same_initial_parameters": True,
        "same_optimizer": True,
        "same_learning_rate": True,
        "same_epochs": True,
        "pytorch_deterministic": True,
        "casulo_t_deterministic": True,
    }
    return {
        "protocol": "casulo-training-benchmark/0.1",
        "scientific": {
            "status": "PREREGISTERED",
            "claims_allowed": True,
            "experiment_id": preregistration["experiment_id"],
            "bound_design": {
                "source_sha256": design["source"]["sha256"],
                "model": design["model"],
                "records": design["records"],
                "samples": design["samples"],
                "warmups": design["warmups"],
                "workers": design["workers"],
                "seed": design["seed"],
                "bootstrap_resamples": design["bootstrap_resamples"],
                **(
                    {"implementation": design["implementation"]}
                    if "implementation" in design
                    else {}
                ),
            },
        },
        "quality": quality,
        "pytorch": {"wall_ns_samples": reference},
        "casulo_t": {"wall_ns_samples": candidate},
        "comparison": {"paired_speedup_median": sorted(paired)[2]},
        "outcomes": {"pytorch": {"backend": PYTORCH_EAGER_BASELINE}},
        "energy": {
            "electrical_energy_measured": False,
            "joules": None,
        },
    }


if __name__ == "__main__":
    unittest.main()
