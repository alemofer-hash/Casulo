from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

import numpy as np

from casulo.t.autograd import compile_autograd, compile_autograd_file
from casulo.t.cli import main as t_main
from casulo.t.parity import (
    DEFAULT_TOLERANCES,
    NUMPY_EXECUTOR_PROTOCOL,
    PYTORCH_PARITY_PROTOCOL,
    DTypeTolerance,
    NumpyTensorExecutor,
    ParityError,
    ParityStatus,
    TensorExecution,
    compare_executions,
    execute_numpy_file,
    run_pytorch_parity,
)
from casulo.t.tensor import (
    LarvaTensor,
    TensorCall,
    TensorDType,
    TensorOwnership,
    compile_tensor_graph,
)


ROOT = Path(__file__).resolve().parents[1]
TRAINING_GRAPH = (
    ROOT / "examples" / "tensor" / "linear-mse-training.tensor.json"
)
TRAINING_INPUT = (
    ROOT / "examples" / "tensor" / "linear-mse-input.json"
)


def _tensor(
    shape: tuple[int, ...],
    dtype: TensorDType = TensorDType.FLOAT64,
) -> LarvaTensor:
    return LarvaTensor(
        dtype,
        shape,
        ownership=TensorOwnership.BORROWED,
    )


def _training_inputs() -> dict[str, object]:
    return json.loads(TRAINING_INPUT.read_text(encoding="utf-8"))


class NumpyExecutorTests(unittest.TestCase):
    def test_public_executor_runs_forward_and_backward(self) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("x", "weight", "target"),
        )
        execution = NumpyTensorExecutor().execute(
            autograd,
            _training_inputs(),
        )

        self.assertEqual(execution.protocol, NUMPY_EXECUTOR_PROTOCOL)
        self.assertEqual(execution.outputs["loss"].tolist(), [0.05])
        np.testing.assert_allclose(
            execution.gradients["weight"],
            [[0.8], [1.0]],
            rtol=0,
            atol=1e-15,
        )
        self.assertEqual(
            list(execution.forward_values),
            ["prediction", "residual", "squared", "loss"],
        )

    def test_execution_summary_hashes_every_value(self) -> None:
        execution = execute_numpy_file(
            TRAINING_GRAPH,
            TRAINING_INPUT,
            wrt=("weight",),
        )
        summary = execution.to_dict()
        complete = execution.to_dict(include_values=True)

        self.assertEqual(len(summary["graph_sha256"]), 64)
        self.assertEqual(len(summary["input_sha256"]), 64)
        self.assertNotIn("output_values", summary)
        self.assertEqual(complete["output_values"]["loss"], [0.05])
        self.assertIn("gradient_values", complete)
        self.assertTrue(
            all(
                value["c_contiguous"]
                for value in summary["forward_values"].values()
            )
        )

    def test_execution_identity_is_deterministic(self) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )
        first = NumpyTensorExecutor().execute(
            autograd,
            _training_inputs(),
        )
        second = NumpyTensorExecutor().execute(
            autograd,
            _training_inputs(),
        )

        self.assertEqual(first.graph_sha256, second.graph_sha256)
        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertEqual(first.to_dict(), second.to_dict())


class PyTorchParityTests(unittest.TestCase):
    def test_small_float64_graph_has_full_parity(self) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("x", "weight", "target"),
        )

        report = run_pytorch_parity(
            autograd,
            _training_inputs(),
        )

        self.assertEqual(report.protocol, PYTORCH_PARITY_PROTOCOL)
        self.assertEqual(report.status, ParityStatus.PASS)
        self.assertEqual(len(report.checks), 7)
        self.assertEqual(
            [item.kind for item in report.checks],
            [
                "intermediate",
                "intermediate",
                "intermediate",
                "loss",
                "gradient",
                "gradient",
                "gradient",
            ],
        )
        self.assertTrue(all(item.passed for item in report.checks))
        self.assertEqual(
            max(item.max_absolute_error or 0 for item in report.checks),
            0.0,
        )

    def test_medium_float32_mlp_has_intermediate_and_gradient_parity(self) -> None:
        rng = np.random.default_rng(20_260_730)
        forward = compile_tensor_graph(
            {
                "x": _tensor((64, 16), TensorDType.FLOAT32),
                "weight1": _tensor((16, 32), TensorDType.FLOAT32),
                "weight2": _tensor((32, 8), TensorDType.FLOAT32),
                "target": _tensor((64, 8), TensorDType.FLOAT32),
            },
            (
                TensorCall("hidden", "matmul", ("x", "weight1")),
                TensorCall("active", "relu", ("hidden",)),
                TensorCall(
                    "prediction",
                    "matmul",
                    ("active", "weight2"),
                ),
                TensorCall(
                    "residual",
                    "sub",
                    ("prediction", "target"),
                ),
                TensorCall(
                    "squared",
                    "mul",
                    ("residual", "residual"),
                ),
                TensorCall("loss", "mean", ("squared",)),
            ),
            ("loss",),
        )
        autograd = compile_autograd(
            forward,
            wrt=("weight1", "weight2"),
        )
        inputs = {
            "x": rng.normal(size=(64, 16)).astype(np.float32),
            "weight1": (
                rng.normal(size=(16, 32)) * 0.1
            ).astype(np.float32),
            "weight2": (
                rng.normal(size=(32, 8)) * 0.1
            ).astype(np.float32),
            "target": rng.normal(size=(64, 8)).astype(np.float32),
        }

        report = run_pytorch_parity(autograd, inputs)

        self.assertEqual(report.status, ParityStatus.PASS)
        self.assertEqual(len(report.checks), 8)
        self.assertLess(
            max(item.max_absolute_error or 0 for item in report.checks),
            1e-5,
        )

    def test_broadcast_activation_reduction_and_views_have_parity(self) -> None:
        forward = compile_tensor_graph(
            {
                "x": _tensor((2, 2)),
                "bias": _tensor((2,)),
            },
            (
                TensorCall("shifted", "add", ("x", "bias")),
                TensorCall("sigmoid_x", "sigmoid", ("shifted",)),
                TensorCall("tanh_x", "tanh", ("sigmoid_x",)),
                TensorCall(
                    "flat",
                    "reshape",
                    ("tanh_x",),
                    {"shape": [1, 4]},
                ),
                TensorCall(
                    "transposed",
                    "transpose",
                    ("flat",),
                    {"axis0": 0, "axis1": 1},
                ),
                TensorCall("loss", "sum", ("transposed",)),
            ),
            ("loss",),
        )
        autograd = compile_autograd(
            forward,
            wrt=("x", "bias"),
        )

        report = run_pytorch_parity(
            autograd,
            {
                "x": [[-1.0, 0.5], [1.5, -0.25]],
                "bias": [0.1, -0.2],
            },
        )

        self.assertEqual(report.status, ParityStatus.PASS)
        self.assertTrue(all(item.passed for item in report.checks))

    def test_disconnected_gradient_is_zero_in_both_backends(self) -> None:
        forward = compile_tensor_graph(
            {
                "x": _tensor((2, 2)),
                "unused": _tensor((2, 2)),
            },
            (TensorCall("loss", "mean", ("x",)),),
            ("loss",),
        )
        autograd = compile_autograd(forward, wrt=("unused",))

        report = run_pytorch_parity(
            autograd,
            {
                "x": [[1.0, 2.0], [3.0, 4.0]],
                "unused": [[9.0, 8.0], [7.0, 6.0]],
            },
        )

        self.assertEqual(report.status, ParityStatus.PASS)
        gradient = next(
            item
            for item in report.checks
            if item.kind == "gradient"
        )
        self.assertEqual(gradient.max_absolute_error, 0.0)

    def test_missing_pytorch_is_inconclusive_not_failure(self) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )

        report = run_pytorch_parity(
            autograd,
            _training_inputs(),
            torch_module=None,
        )

        self.assertEqual(report.status, ParityStatus.INCONCLUSIVE)
        self.assertFalse(report.passed)
        self.assertEqual(report.checks, ())
        self.assertIn("indisponível", report.reason)

    def test_report_never_claims_time_or_energy(self) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )
        report = run_pytorch_parity(
            autograd,
            _training_inputs(),
        ).to_dict()

        self.assertIsNone(report["timing"])
        self.assertIsNone(report["energy_joules"])
        self.assertNotIn("speedup", report)


class ParityComparatorNegativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )
        self.numpy_execution = NumpyTensorExecutor().execute(
            self.autograd,
            _training_inputs(),
        )

    def _mutated_execution(
        self,
        *,
        gradient: np.ndarray,
    ) -> TensorExecution:
        gradients = dict(self.numpy_execution.gradients)
        gradients["weight"] = gradient
        return replace(
            self.numpy_execution,
            protocol="casulo-pytorch-adapter/0.1",
            backend="test-double",
            backend_version="0",
            gradients=gradients,
        )

    def test_numeric_mismatch_produces_fail(self) -> None:
        changed = np.array(
            self.numpy_execution.gradients["weight"],
            copy=True,
        )
        changed[0, 0] += 1.0

        report = compare_executions(
            self.numpy_execution,
            self._mutated_execution(gradient=changed),
            self.autograd,
        )

        self.assertEqual(report.status, ParityStatus.FAIL)
        failed = [item for item in report.checks if not item.passed]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].kind, "gradient")

    def test_shape_dtype_and_non_finite_mismatches_are_not_hidden(self) -> None:
        variants = (
            (
                np.zeros((1, 2), dtype=np.float64),
                "shape mismatch",
            ),
            (
                np.asarray(
                    self.numpy_execution.gradients["weight"],
                    dtype=np.float32,
                ),
                "dtype mismatch",
            ),
            (
                np.full((2, 1), np.nan, dtype=np.float64),
                "non-finite value",
            ),
        )
        for gradient, reason in variants:
            with self.subTest(reason=reason):
                report = compare_executions(
                    self.numpy_execution,
                    self._mutated_execution(gradient=gradient),
                    self.autograd,
                )
                failed = [item for item in report.checks if not item.passed]
                self.assertEqual(report.status, ParityStatus.FAIL)
                self.assertTrue(failed[0].reason.startswith(reason))

    def test_comparator_rejects_different_execution_identity(self) -> None:
        other = replace(
            self.numpy_execution,
            backend="other",
            input_sha256="0" * 64,
        )

        with self.assertRaisesRegex(ParityError, "T7010"):
            compare_executions(
                self.numpy_execution,
                other,
                self.autograd,
            )

    def test_tolerance_contract_rejects_invalid_policy(self) -> None:
        with self.assertRaisesRegex(ParityError, "T7000"):
            DTypeTolerance(
                TensorDType.FLOAT64,
                absolute=-1.0,
                relative=0.0,
            )
        self.assertEqual(
            DEFAULT_TOLERANCES[TensorDType.FLOAT64].absolute,
            1e-10,
        )


class ParityCliTests(unittest.TestCase):
    def test_numpy_execute_and_pytorch_parity_commands(self) -> None:
        numpy_stdout = io.StringIO()
        with redirect_stdout(numpy_stdout):
            numpy_status = t_main(
                [
                    "numpy-execute",
                    str(TRAINING_GRAPH),
                    "--input",
                    str(TRAINING_INPUT),
                    "--wrt",
                    "weight",
                ]
            )
        numpy_document = json.loads(numpy_stdout.getvalue())

        parity_stdout = io.StringIO()
        with redirect_stdout(parity_stdout):
            parity_status = t_main(
                [
                    "pytorch-parity",
                    str(TRAINING_GRAPH),
                    "--input",
                    str(TRAINING_INPUT),
                    "--wrt",
                    "weight",
                ]
            )
        parity_document = json.loads(parity_stdout.getvalue())

        self.assertEqual(numpy_status, 0)
        self.assertEqual(
            numpy_document["protocol"],
            NUMPY_EXECUTOR_PROTOCOL,
        )
        self.assertIn("gradient_values", numpy_document)
        self.assertEqual(parity_status, 0)
        self.assertEqual(parity_document["status"], "PASS")

    def test_cli_can_write_summary_and_report_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            numpy_output = root / "numpy.json"
            parity_output = root / "parity.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                first = t_main(
                    [
                        "numpy-execute",
                        str(TRAINING_GRAPH),
                        "--input",
                        str(TRAINING_INPUT),
                        "--wrt",
                        "weight",
                        "--summary-only",
                        "--output",
                        str(numpy_output),
                    ]
                )
                second = t_main(
                    [
                        "pytorch-parity",
                        str(TRAINING_GRAPH),
                        "--input",
                        str(TRAINING_INPUT),
                        "--wrt",
                        "weight",
                        "--output",
                        str(parity_output),
                    ]
                )

            numpy_document = json.loads(
                numpy_output.read_text(encoding="utf-8")
            )
            parity_document = json.loads(
                parity_output.read_text(encoding="utf-8")
            )

        self.assertEqual((first, second), (0, 0))
        self.assertNotIn("output_values", numpy_document)
        self.assertEqual(parity_document["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
