from __future__ import annotations

import io
import json
import statistics
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from casulo.t.cli import main as t_main
from casulo.t.tensor_lab import (
    TENSOR_LAB_BACKEND_CASULO,
    TENSOR_LAB_BACKEND_EAGER,
    TENSOR_LAB_BACKEND_INDUCTOR,
    TENSOR_LAB_PREREGISTRATION_PROTOCOL,
    TENSOR_LAB_REPORT_PROTOCOL,
    TensorLabPreregistrationError,
    create_tensor_lab_preregistration,
    judge_tensor_lab,
    verify_tensor_lab_chain,
    verify_tensor_lab_preregistration,
)


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "examples" / "tensor" / "mlp-mse-medium.tensor.json"
ORDERS = (
    (
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_EAGER,
        TENSOR_LAB_BACKEND_INDUCTOR,
    ),
    (
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_INDUCTOR,
        TENSOR_LAB_BACKEND_EAGER,
    ),
    (
        TENSOR_LAB_BACKEND_EAGER,
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_INDUCTOR,
    ),
    (
        TENSOR_LAB_BACKEND_EAGER,
        TENSOR_LAB_BACKEND_INDUCTOR,
        TENSOR_LAB_BACKEND_CASULO,
    ),
    (
        TENSOR_LAB_BACKEND_INDUCTOR,
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_EAGER,
    ),
    (
        TENSOR_LAB_BACKEND_INDUCTOR,
        TENSOR_LAB_BACKEND_EAGER,
        TENSOR_LAB_BACKEND_CASULO,
    ),
)


def _create_preregistration(root: Path):
    return create_tensor_lab_preregistration(
        GRAPH,
        root / "preregistration.json",
        wrt=("weight1", "weight2"),
        samples=7,
        warmups=1,
        inner_iterations=10,
        workers=1,
        bootstrap_resamples=200,
    )


def _synthetic_report(
    preregistration: dict,
    *,
    eager_speedup: float = 3.0,
    inductor_speedup: float = 1.2,
    missing_inductor: bool = False,
) -> dict:
    design = preregistration["design"]
    available = {
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_EAGER,
    }
    if not missing_inductor:
        available.add(TENSOR_LAB_BACKEND_INDUCTOR)
    samples = []
    candidate_values = [100, 102, 98, 101, 99, 103, 97]
    for index, candidate in enumerate(candidate_values):
        order = [
            backend
            for backend in ORDERS[index % len(ORDERS)]
            if backend in available
        ]
        measurements = {
            TENSOR_LAB_BACKEND_CASULO: {
                "wall_ns": candidate,
                "cpu_ns": candidate,
                "inner_iterations": design["inner_iterations"],
            },
            TENSOR_LAB_BACKEND_EAGER: {
                "wall_ns": round(candidate * eager_speedup),
                "cpu_ns": round(candidate * eager_speedup),
                "inner_iterations": design["inner_iterations"],
            },
        }
        if not missing_inductor:
            measurements[TENSOR_LAB_BACKEND_INDUCTOR] = {
                "wall_ns": round(candidate * inductor_speedup),
                "cpu_ns": round(candidate * inductor_speedup),
                "inner_iterations": design["inner_iterations"],
            }
        samples.append(
            {
                "index": index,
                "order": order,
                "measurements": measurements,
            }
        )
    comparisons = {
        TENSOR_LAB_BACKEND_EAGER: {
            "wall_speedup_median": sorted(
                sample["measurements"][TENSOR_LAB_BACKEND_EAGER][
                    "wall_ns"
                ]
                / sample["measurements"][TENSOR_LAB_BACKEND_CASULO][
                    "wall_ns"
                ]
                for sample in samples
            )[3],
        }
    }
    if not missing_inductor:
        comparisons[TENSOR_LAB_BACKEND_INDUCTOR] = {
            "wall_speedup_median": sorted(
                sample["measurements"][TENSOR_LAB_BACKEND_INDUCTOR][
                    "wall_ns"
                ]
                / sample["measurements"][TENSOR_LAB_BACKEND_CASULO][
                    "wall_ns"
                ]
                for sample in samples
            )[3],
        }
    backends = {
        TENSOR_LAB_BACKEND_CASULO: {"status": "AVAILABLE"},
        TENSOR_LAB_BACKEND_EAGER: {"status": "AVAILABLE"},
        TENSOR_LAB_BACKEND_INDUCTOR: {
            "status": "UNAVAILABLE" if missing_inductor else "AVAILABLE"
        },
    }
    quality = {
        **preregistration["quality_gates"],
        "inductor_vs_numpy_loss_and_gradients": (
            "INCONCLUSIVE" if missing_inductor else "PASS"
        ),
    }
    bound_keys = (
        "graph",
        "wrt",
        "loss",
        "inputs",
        "input_generator",
        "samples",
        "warmups",
        "inner_iterations",
        "workers",
        "gemm_workers",
        "gemm_provider",
        "torch_threads",
        "seed",
        "bootstrap_resamples",
        "arena_budget_bytes",
        "pairing",
        "order_policy",
        "required_baselines",
        "candidate_backend",
        "measurement_boundary",
        "memory_probe",
        "implementation",
        "measurement_calibration",
        "cpu_affinity",
        "cooldown_ms",
        "max_coefficient_of_variation",
        "telemetry_policy",
    )
    variation = {
        backend: statistics.stdev(
            [
                sample["measurements"][backend]["wall_ns"]
                / design["inner_iterations"]
                for sample in samples
            ]
        )
        / statistics.fmean(
            [
                sample["measurements"][backend]["wall_ns"]
                / design["inner_iterations"]
                for sample in samples
            ]
        )
        for backend in available
    }
    return {
        "protocol": TENSOR_LAB_REPORT_PROTOCOL,
        "scientific": {
            "experiment_id": preregistration["experiment_id"],
            "bound_design": {
                key: design[key]
                for key in bound_keys
            },
        },
        "quality": quality,
        "backends": backends,
        "samples": samples,
        "comparisons": comparisons,
        "measurement_stability": {
            "protocol": "casulo-measurement-stability/0.1",
            "selected_inner_iterations": design["inner_iterations"],
            "coefficient_of_variation": variation,
            "calibration": {
                "protocol": "casulo-measurement-stability/0.1",
                "uses_speedup_or_winner_selection": False,
                "all_backends_reached_target": True,
            },
        },
        "environment": {
            "platform": "test-platform",
            "processor": "test-processor",
        },
        "energy": {"measured": False, "joules": None},
    }


class TensorLabPreregistrationTests(unittest.TestCase):
    def test_preregistration_is_sealed_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _create_preregistration(root)
            verified = verify_tensor_lab_preregistration(created.path)

            self.assertEqual(
                verified.document["protocol"],
                TENSOR_LAB_PREREGISTRATION_PROTOCOL,
            )
            self.assertEqual(created.experiment_id, verified.experiment_id)
            self.assertFalse(
                verified.document["observed_results_at_registration"]
            )
            self.assertEqual(
                verified.document["design"]["order_policy"],
                "balanced-six-permutation-cycle",
            )
            self.assertEqual(
                verified.document["design"]["gemm_provider"]["provider_id"],
                "casulo-owned-c99",
            )
            with self.assertRaisesRegex(
                TensorLabPreregistrationError,
                "imutável",
            ):
                _create_preregistration(root)

    def test_same_design_observation_requires_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                TensorLabPreregistrationError,
                "declaração explícita",
            ):
                create_tensor_lab_preregistration(
                    GRAPH,
                    Path(temporary) / "preregistration.json",
                    wrt=("weight1", "weight2"),
                    samples=7,
                    warmups=1,
                    inner_iterations=10,
                    workers=1,
                    bootstrap_resamples=200,
                    prior_same_design_observed=True,
                )

    def test_confirmation_phase_is_explicitly_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            created = create_tensor_lab_preregistration(
                GRAPH,
                Path(temporary) / "preregistration.json",
                wrt=("weight1", "weight2"),
                samples=7,
                warmups=1,
                inner_iterations=10,
                workers=1,
                bootstrap_resamples=200,
                prior_same_design_observed=True,
                prior_exploratory_disclosure="Sprint 021 exploratório.",
            )

            self.assertEqual(
                created.document["hypothesis"]["phase"],
                "CONFIRMATORY_REPLICATION_AFTER_EXPLORATION",
            )
            self.assertTrue(
                created.document["prior_exploratory_observations"][
                    "same_registered_design_observed"
                ]
            )

    def test_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _create_preregistration(root)
            document = json.loads(
                created.path.read_text(encoding="utf-8")
            )
            document["hypothesis"]["commercial_threshold"] = 0.5
            created.path.write_text(
                json.dumps(document),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                TensorLabPreregistrationError,
                "adulterado",
            ):
                verify_tensor_lab_preregistration(created.path)


class TensorLabJudgeTests(unittest.TestCase):
    def _judge(
        self,
        root: Path,
        preregistration: object,
        report: dict,
    ):
        report_path = root / "report.json"
        report_path.write_text(
            json.dumps(report),
            encoding="utf-8",
        )
        return judge_tensor_lab(
            preregistration.path,
            report_path,
            root / "verdict.json",
        ), report_path

    def test_positive_requires_both_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration = _create_preregistration(root)
            verdict, report_path = self._judge(
                root,
                preregistration,
                _synthetic_report(preregistration.document),
            )

            self.assertEqual(verdict.classification, "POSITIVE")
            self.assertFalse(verdict.document["commercial_gate"])
            self.assertIsNotNone(verdict.document["claim"])
            self.assertEqual(
                verdict.document["baseline_classifications"],
                {
                    TENSOR_LAB_BACKEND_EAGER: "POSITIVE",
                    TENSOR_LAB_BACKEND_INDUCTOR: "POSITIVE",
                },
            )
            checks = verify_tensor_lab_chain(
                preregistration.path,
                report_path,
                verdict.path,
            )
            self.assertEqual(len(checks), 5)

    def test_positive_smoke_test_cannot_release_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration = create_tensor_lab_preregistration(
                GRAPH,
                root / "preregistration.json",
                wrt=("weight1", "weight2"),
                samples=7,
                warmups=1,
                inner_iterations=10,
                workers=1,
                bootstrap_resamples=200,
                claim_eligible=False,
                prior_exploratory_disclosure="Smoke test do Juiz.",
            )
            verdict, report_path = self._judge(
                root,
                preregistration,
                _synthetic_report(preregistration.document),
            )

            self.assertEqual(verdict.classification, "POSITIVE")
            self.assertFalse(verdict.document["claim_eligible"])
            self.assertIsNone(verdict.document["claim"])
            self.assertFalse(verdict.document["commercial_gate"])
            self.assertEqual(
                len(
                    verify_tensor_lab_chain(
                        preregistration.path,
                        report_path,
                        verdict.path,
                    )
                ),
                5,
            )

    def test_missing_inductor_is_inconclusive_not_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration = _create_preregistration(root)
            verdict, _ = self._judge(
                root,
                preregistration,
                _synthetic_report(
                    preregistration.document,
                    missing_inductor=True,
                ),
            )

            self.assertEqual(verdict.classification, "INCONCLUSIVE")
            self.assertEqual(
                verdict.document["evidence"][
                    "missing_required_baselines"
                ],
                [TENSOR_LAB_BACKEND_INDUCTOR],
            )
            self.assertEqual(
                verdict.document["evidence"]["quality_failures"],
                [],
            )

    def test_slower_candidate_is_preserved_as_negative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration = _create_preregistration(root)
            verdict, _ = self._judge(
                root,
                preregistration,
                _synthetic_report(
                    preregistration.document,
                    inductor_speedup=0.8,
                ),
            )

            self.assertEqual(verdict.classification, "NEGATIVE")
            self.assertIsNone(verdict.document["claim"])
            self.assertEqual(
                verdict.document["baseline_classifications"][
                    TENSOR_LAB_BACKEND_INDUCTOR
                ],
                "NEGATIVE",
            )

    def test_reported_median_cannot_override_raw_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration = _create_preregistration(root)
            report = _synthetic_report(preregistration.document)
            report["comparisons"][TENSOR_LAB_BACKEND_EAGER][
                "wall_speedup_median"
            ] = 30.0
            verdict, _ = self._judge(root, preregistration, report)

            self.assertEqual(verdict.classification, "INVALID")
            self.assertIn(
                f"REPORTED_MEDIAN_DIVERGES:{TENSOR_LAB_BACKEND_EAGER}",
                verdict.document["evidence"]["integrity_failures"],
            )

    def test_unstable_measurement_is_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preregistration = _create_preregistration(root)
            report = _synthetic_report(preregistration.document)
            factors = (0.1, 2.0, 0.2, 1.8, 0.3, 1.6, 0.4)
            for sample, factor in zip(report["samples"], factors):
                for measurement in sample["measurements"].values():
                    measurement["wall_ns"] = max(
                        1, round(measurement["wall_ns"] * factor)
                    )
                    measurement["cpu_ns"] = measurement["wall_ns"]
            for backend in report["measurement_stability"][
                "coefficient_of_variation"
            ]:
                values = [
                    sample["measurements"][backend]["wall_ns"]
                    / sample["measurements"][backend]["inner_iterations"]
                    for sample in report["samples"]
                ]
                report["measurement_stability"][
                    "coefficient_of_variation"
                ][backend] = statistics.stdev(values) / statistics.fmean(
                    values
                )
            for baseline in (
                TENSOR_LAB_BACKEND_EAGER,
                TENSOR_LAB_BACKEND_INDUCTOR,
            ):
                report["comparisons"][baseline][
                    "wall_speedup_median"
                ] = statistics.median(
                    sample["measurements"][baseline]["wall_ns"]
                    / sample["measurements"][TENSOR_LAB_BACKEND_CASULO][
                        "wall_ns"
                    ]
                    for sample in report["samples"]
                )
            verdict, _ = self._judge(root, preregistration, report)

            self.assertEqual(verdict.classification, "INCONCLUSIVE")
            self.assertTrue(
                verdict.document["evidence"]["stability_failures"]
            )
            self.assertIsNone(verdict.document["claim"])


class TensorLabCliTests(unittest.TestCase):
    def test_cli_creates_machine_readable_preregistration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "preregistration.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = t_main(
                    [
                        "tensor-lab-preregister",
                        str(GRAPH),
                        "--output",
                        str(output),
                        "--wrt",
                        "weight1",
                        "weight2",
                        "--samples",
                        "7",
                        "--warmups",
                        "1",
                        "--inner-iterations",
                        "10",
                        "--target-sample-ms",
                        "321",
                        "--maximum-inner-iterations",
                        "2048",
                        "--cooldown-ms",
                        "17",
                        "--cpu-affinity",
                        "0",
                        "2",
                        "--max-cv",
                        "0.12",
                        "--bootstrap-resamples",
                        "200",
                    ]
                )
            result = json.loads(stdout.getvalue())

            self.assertEqual(status, 0)
            self.assertTrue(result["ok"])
            self.assertTrue(output.is_file())
            self.assertEqual(
                verify_tensor_lab_preregistration(output).experiment_id,
                result["experiment_id"],
            )
            design = verify_tensor_lab_preregistration(output).document[
                "design"
            ]
            self.assertEqual(design["cpu_affinity"], [0, 2])
            self.assertEqual(design["cooldown_ms"], 17)
            self.assertEqual(
                design["measurement_calibration"]["target_wall_ms"],
                321.0,
            )
            self.assertEqual(
                design["measurement_calibration"][
                    "maximum_inner_iterations"
                ],
                2048,
            )
            self.assertEqual(
                design["max_coefficient_of_variation"],
                0.12,
            )


if __name__ == "__main__":
    unittest.main()
