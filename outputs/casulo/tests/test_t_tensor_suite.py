import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from casulo.t.tensor_lab import verify_tensor_lab_preregistration
from casulo.t.tensor_suite import (
    TENSOR_SUITE_REPORT_PROTOCOL,
    TensorSuiteError,
    create_tensor_suite_preregistration,
    judge_tensor_suite,
    verify_tensor_suite_chain,
    verify_tensor_suite_preregistration,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples" / "tensor-suite" / "cases.json"


def _create(root: Path):
    return create_tensor_suite_preregistration(
        CASES,
        root / "preregistration",
        samples=7,
        warmups=1,
        inner_iterations=1,
        restarts=3,
        workers=1,
        gemm_workers=1,
        provider="owned",
        bootstrap_resamples=200,
        prior_exploratory_disclosure=(
            "Topologia relacionada observada; shapes reservados."
        ),
        claim_eligible=False,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TensorSuitePreregistrationTests(unittest.TestCase):
    def test_all_cases_and_process_restarts_are_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            created = _create(Path(temporary))
            verified = verify_tensor_suite_preregistration(created.path)
            design = verified.document["design"]

            self.assertEqual(len(design["cases"]), 3)
            self.assertEqual(len(design["schedule"]), 9)
            self.assertEqual(
                {
                    (item["case"], item["restart"])
                    for item in design["schedule"]
                },
                {
                    (case["name"], restart)
                    for case in design["cases"]
                    for restart in range(3)
                },
            )
            self.assertEqual(
                design["process_policy"],
                "fresh-python-process-per-case-restart",
            )
            for case in design["cases"]:
                child = verify_tensor_lab_preregistration(
                    created.directory / case["child_preregistration"]
                )
                self.assertFalse(
                    child.document["hypothesis"]["claim_eligible"]
                )

    def test_child_preregistration_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            created = _create(Path(temporary))
            child = created.directory / "cases" / "tall-batch.json"
            document = json.loads(child.read_text(encoding="utf-8"))
            document["design"]["workers"] = 4
            child.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(
                TensorSuiteError,
                "filho adulterado",
            ):
                verify_tensor_suite_preregistration(created.path)


class TensorSuiteJudgeTests(unittest.TestCase):
    def test_failed_runs_are_inconclusive_and_cannot_release_claim(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _create(root)
            report = {
                "protocol": TENSOR_SUITE_REPORT_PROTOCOL,
                "experiment_id": created.experiment_id,
                "preregistration_file_sha256": _sha256(created.path),
                "schedule": created.document["design"]["schedule"],
                "runs": [
                    {**item, "status": "FAILED"}
                    for item in created.document["design"]["schedule"]
                ],
            }
            report_path = root / "suite-report.json"
            report_path.write_text(
                json.dumps(report),
                encoding="utf-8",
            )
            verdict = judge_tensor_suite(
                created.path,
                report_path,
                root / "suite-verdict.json",
            )

            self.assertEqual(verdict.classification, "INCONCLUSIVE")
            self.assertIsNone(verdict.document["claim"])
            self.assertFalse(verdict.document["commercial_gate"])
            self.assertEqual(len(verdict.document["missing_runs"]), 9)
            self.assertEqual(
                len(
                    verify_tensor_suite_chain(
                        created.path,
                        report_path,
                        verdict.path,
                    )
                ),
                5,
            )


if __name__ == "__main__":
    unittest.main()
