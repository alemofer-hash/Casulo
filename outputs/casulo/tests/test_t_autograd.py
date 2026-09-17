from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from hypothesis import given, settings, strategies as st

from casulo.t.autograd import (
    AUTOGRAD_IR_PROTOCOL,
    GRADIENT_CHECK_PROTOCOL,
    GRADIENT_RULE_ABI,
    AutogradError,
    GradientRule,
    GradientRuleRegistry,
    check_gradients,
    compile_autograd,
    compile_autograd_file,
)
from casulo.t.cli import main as t_main
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
    shape: tuple[int | str, ...],
    *,
    dtype: TensorDType = TensorDType.FLOAT64,
) -> LarvaTensor:
    return LarvaTensor(
        dtype,
        shape,
        ownership=TensorOwnership.BORROWED,
    )


class GradientRuleRegistryTests(unittest.TestCase):
    def test_builtin_rules_have_versioned_identity(self) -> None:
        registry = GradientRuleRegistry.builtins()
        document = registry.to_dict()

        self.assertEqual(document["abi"], GRADIENT_RULE_ABI)
        self.assertEqual(
            registry.resolve("matmul", "0.1").identity,
            "matmul@0.1/matmul-rank2@0.1",
        )
        self.assertGreaterEqual(len(document["rules"]), 12)

    def test_rejects_duplicate_and_unknown_rule_kind(self) -> None:
        registry = GradientRuleRegistry()
        rule = GradientRule("custom", "0.1", "0.1", "add", (0, 1))
        registry.register(rule)

        with self.assertRaisesRegex(AutogradError, "T6001"):
            registry.register(rule)
        with self.assertRaisesRegex(AutogradError, "T6002"):
            GradientRuleRegistry().register(
                GradientRule("other", "0.1", "0.1", "opaque", (0,))
            )

    def test_missing_gradient_rule_blocks_lowering(self) -> None:
        forward = compile_tensor_graph(
            {"x": _tensor((2, 2))},
            (TensorCall("loss", "mean", ("x",)),),
            ("loss",),
        )

        with self.assertRaisesRegex(AutogradError, "T6004"):
            compile_autograd(
                forward,
                wrt=("x",),
                registry=GradientRuleRegistry(),
            )


class AutogradLoweringTests(unittest.TestCase):
    def test_forms_explicit_backward_for_training_graph(self) -> None:
        result = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )

        self.assertEqual(result.protocol, AUTOGRAD_IR_PROTOCOL)
        self.assertEqual(result.gradient_abi, GRADIENT_RULE_ABI)
        self.assertEqual(result.loss, "loss")
        self.assertEqual(result.gradients[0].target, "weight")
        self.assertEqual(result.gradients[0].type.shape, (2, 1))
        operators = [item.operator for item in result.backward]
        self.assertEqual(operators[0], "ones_like")
        self.assertIn("mean_backward", operators)
        self.assertIn("transpose", operators)
        self.assertIn("matmul", operators)

    def test_square_derivative_is_coalesced_before_accumulation(self) -> None:
        result = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )
        accumulations = [
            item
            for item in result.backward
            if item.rule == "accumulate/0.1"
        ]

        self.assertEqual(accumulations, [])
        coalesced = [
            item
            for item in result.backward
            if item.attributes.get("algebra") == "square-derivative"
        ]
        self.assertEqual(len(coalesced), 1)
        self.assertEqual(coalesced[0].operator, "add")
        self.assertEqual(coalesced[0].inputs[0], coalesced[0].inputs[1])

    def test_lowering_is_byte_deterministic(self) -> None:
        first = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("x", "weight"),
        )
        second = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("x", "weight"),
        )

        encoded_first = json.dumps(
            first.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded_second = json.dumps(
            second.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(encoded_first, encoded_second)

    def test_disconnected_input_receives_explicit_zero(self) -> None:
        forward = compile_tensor_graph(
            {
                "x": _tensor((2, 2)),
                "unused": _tensor((2, 2)),
            },
            (TensorCall("loss", "mean", ("x",)),),
            ("loss",),
        )
        result = compile_autograd(forward, wrt=("unused",))
        binding = result.gradients[0]
        producer = next(
            item
            for item in result.backward
            if item.result == binding.value
        )

        self.assertEqual(producer.operator, "zeros_like")
        self.assertEqual(producer.rule, "disconnected/0.1")

    def test_rejects_non_scalar_loss_and_invalid_wrt(self) -> None:
        forward = compile_tensor_graph(
            {"x": _tensor((2, 2))},
            (TensorCall("active", "relu", ("x",)),),
            ("active",),
        )

        with self.assertRaisesRegex(AutogradError, "T6013"):
            compile_autograd(forward, wrt=("x",))
        scalar = compile_tensor_graph(
            {"x": _tensor((2, 2))},
            (TensorCall("loss", "mean", ("x",)),),
            ("loss",),
        )
        with self.assertRaisesRegex(AutogradError, "T6016"):
            compile_autograd(scalar, wrt=("missing",))

    def test_rank_three_matmul_backward_is_explicitly_out_of_scope(self) -> None:
        forward = compile_tensor_graph(
            {
                "x": _tensor((2, 3, 4)),
                "weight": _tensor((2, 4, 1)),
            },
            (
                TensorCall("prediction", "matmul", ("x", "weight")),
                TensorCall("loss", "mean", ("prediction",)),
            ),
            ("loss",),
        )

        with self.assertRaisesRegex(AutogradError, "T6021"):
            compile_autograd(forward, wrt=("weight",))


class GradientCheckTests(unittest.TestCase):
    def test_linear_mse_matches_central_difference(self) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("x", "weight", "target"),
        )
        inputs = json.loads(TRAINING_INPUT.read_text(encoding="utf-8"))

        report = check_gradients(autograd, inputs)

        self.assertEqual(report.protocol, GRADIENT_CHECK_PROTOCOL)
        self.assertTrue(report.passed)
        self.assertEqual(report.checked_elements, 8)
        self.assertLess(
            max(item.max_absolute_error for item in report.targets),
            1e-9,
        )

    def test_broadcast_gradient_is_reduced_to_bias_shape(self) -> None:
        forward = compile_tensor_graph(
            {
                "x": _tensor((2, 2)),
                "bias": _tensor((2,)),
                "target": _tensor((2, 2)),
            },
            (
                TensorCall("prediction", "add", ("x", "bias")),
                TensorCall("residual", "sub", ("prediction", "target")),
                TensorCall("squared", "mul", ("residual", "residual")),
                TensorCall("loss", "mean", ("squared",)),
            ),
            ("loss",),
        )
        autograd = compile_autograd(forward, wrt=("bias",))
        report = check_gradients(
            autograd,
            {
                "x": [[1.0, -2.0], [0.5, 3.0]],
                "bias": [0.25, -0.5],
                "target": [[0.0, 1.0], [1.0, 1.0]],
            },
        )

        self.assertTrue(report.passed)
        self.assertEqual(autograd.gradients[0].type.shape, (2,))

    def test_activation_and_view_rules_match_finite_difference(self) -> None:
        forward = compile_tensor_graph(
            {"x": _tensor((2, 2))},
            (
                TensorCall("sigmoid_x", "sigmoid", ("x",)),
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
        autograd = compile_autograd(forward, wrt=("x",))
        report = check_gradients(
            autograd,
            {"x": [[-1.5, -0.5], [0.5, 1.5]]},
        )

        self.assertTrue(report.passed)
        self.assertLess(report.targets[0].max_absolute_error, 1e-8)

    def test_work_budget_and_numeric_input_contract_are_enforced(self) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("x",),
        )
        inputs = json.loads(TRAINING_INPUT.read_text(encoding="utf-8"))

        with self.assertRaisesRegex(AutogradError, "T6104"):
            check_gradients(autograd, inputs, max_elements=3)
        invalid = dict(inputs)
        invalid.pop("target")
        with self.assertRaisesRegex(AutogradError, "T6110"):
            check_gradients(autograd, invalid)

    def test_symbolic_dimensions_are_bound_consistently(self) -> None:
        forward = compile_tensor_graph(
            {
                "x": _tensor(("batch", 2)),
                "target": _tensor(("batch", 2)),
            },
            (
                TensorCall("residual", "sub", ("x", "target")),
                TensorCall("loss", "mean", ("residual",)),
            ),
            ("loss",),
        )
        autograd = compile_autograd(forward, wrt=("x",))

        with self.assertRaisesRegex(AutogradError, "T6117"):
            check_gradients(
                autograd,
                {
                    "x": [[1.0, 2.0], [3.0, 4.0]],
                    "target": [[1.0, 2.0]],
                },
            )

    @settings(max_examples=30, deadline=None)
    @given(
        left=st.floats(
            min_value=-3.0,
            max_value=3.0,
            allow_nan=False,
            allow_infinity=False,
            width=64,
        ),
        right=st.floats(
            min_value=-3.0,
            max_value=3.0,
            allow_nan=False,
            allow_infinity=False,
            width=64,
        ),
    )
    def test_generated_quadratic_gradients(
        self,
        left: float,
        right: float,
    ) -> None:
        forward = compile_tensor_graph(
            {"x": _tensor((2,))},
            (
                TensorCall("squared", "mul", ("x", "x")),
                TensorCall("loss", "sum", ("squared",)),
            ),
            ("loss",),
        )
        autograd = compile_autograd(forward, wrt=("x",))

        report = check_gradients(
            autograd,
            {"x": [left, right]},
            absolute_tolerance=2e-6,
        )

        self.assertTrue(report.passed)


class AutogradCliTests(unittest.TestCase):
    def test_compile_and_check_commands(self) -> None:
        compiled_stdout = io.StringIO()
        with redirect_stdout(compiled_stdout):
            compile_status = t_main(
                [
                    "autograd-compile",
                    str(TRAINING_GRAPH),
                    "--wrt",
                    "weight",
                    "--format",
                    "json",
                ]
            )
        compiled = json.loads(compiled_stdout.getvalue())

        checked_stdout = io.StringIO()
        with redirect_stdout(checked_stdout):
            check_status = t_main(
                [
                    "autograd-check",
                    str(TRAINING_GRAPH),
                    "--input",
                    str(TRAINING_INPUT),
                    "--wrt",
                    "weight",
                ]
            )
        checked = json.loads(checked_stdout.getvalue())

        self.assertEqual(compile_status, 0)
        self.assertEqual(compiled["protocol"], AUTOGRAD_IR_PROTOCOL)
        self.assertEqual(check_status, 0)
        self.assertTrue(checked["passed"])

    def test_cli_reports_blocked_non_scalar_graph(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        graph = (
            ROOT / "examples" / "tensor" / "mlp-forward.tensor.json"
        )
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = t_main(
                [
                    "autograd-compile",
                    str(graph),
                    "--wrt",
                    "weight1",
                ]
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("T6013", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
