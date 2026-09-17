from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

from casulo.t.autograd import compile_autograd, compile_autograd_file
from casulo.t.cli import main as t_main
from casulo.t.parity import ParityStatus
from casulo.t.tensor import (
    LarvaTensor,
    TensorCall,
    TensorDType,
    TensorOwnership,
    compile_tensor_graph,
)
from casulo.t.tensor_cpu import (
    DEFAULT_ARENA_BUDGET_BYTES,
    TENSOR_CPU_PLAN_PROTOCOL,
    TENSOR_CPU_RUN_PROTOCOL,
    TensorCpuUnavailable,
    execute_tensor_cpu,
    generate_tensor_cpu_artifact,
    plan_tensor_cpu,
    prepare_tensor_cpu_executor,
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
    dtype: TensorDType = TensorDType.FLOAT64,
) -> LarvaTensor:
    return LarvaTensor(
        dtype,
        shape,
        ownership=TensorOwnership.BORROWED,
    )


def _training_inputs() -> dict[str, object]:
    return json.loads(TRAINING_INPUT.read_text(encoding="utf-8"))


def _require_pytorch(test: unittest.TestCase) -> None:
    try:
        import torch  # noqa: F401
    except ImportError:
        test.skipTest("runtime PyTorch opcional indisponível")


class TensorCpuPlanningTests(unittest.TestCase):
    def test_plan_is_deterministic_bounded_and_fuses_pointwise_work(
        self,
    ) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )

        first = plan_tensor_cpu(autograd, workers=1)
        second = plan_tensor_cpu(autograd, workers=1)

        self.assertEqual(first.protocol, TENSOR_CPU_PLAN_PROTOCOL)
        self.assertEqual(first.status, "NATIVE")
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertGreater(first.arena_required_bytes or 0, 0)
        self.assertLessEqual(
            first.arena_required_bytes or 0,
            DEFAULT_ARENA_BUDGET_BYTES,
        )
        self.assertEqual(first.workers, 1)
        self.assertEqual(
            first.scheduler["reason"],
            "explicit_worker_budget",
        )
        fused = [
            region
            for region in first.fusion_regions
            if region.fused
        ]
        self.assertTrue(fused)
        self.assertIn(
            ("residual", "squared"),
            [region.results for region in fused],
        )

    def test_generated_source_has_stable_identity_and_audited_fp_policy(
        self,
    ) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )
        plan = plan_tensor_cpu(autograd, workers=1)

        first = generate_tensor_cpu_artifact(autograd, plan=plan)
        second = generate_tensor_cpu_artifact(autograd, plan=plan)

        self.assertEqual(first.source_sha256, second.source_sha256)
        self.assertEqual(first.source, second.source)
        self.assertIn("casulo_tensor_execute", first.source)
        self.assertIn(
            TENSOR_CPU_PLAN_PROTOCOL.replace("plan", "abi"),
            first.source,
        )
        self.assertIn("Casulo row-inner-column", first.source)
        self.assertIn("int audit", first.source)

    def test_adaptive_gemm_schedule_is_shape_derived_and_bounded(self) -> None:
        autograd = compile_autograd_file(
            ROOT
            / "examples"
            / "tensor-suite"
            / "heldout-wide.tensor.json",
            wrt=("weight1", "weight2"),
        )

        adaptive = plan_tensor_cpu(
            autograd,
            workers=2,
            gemm_workers="adaptive",
        )
        fixed = plan_tensor_cpu(
            autograd,
            workers=2,
            gemm_workers=2,
        )

        self.assertEqual(
            adaptive.gemm_worker_policy,
            "shape-adaptive-flop-thresholds/0.1",
        )
        self.assertEqual(adaptive.gemm_worker_schedule, (2, 1, 1, 1, 2))
        self.assertTrue(
            all(item in {1, 2} for item in adaptive.gemm_worker_schedule)
        )
        self.assertEqual(fixed.gemm_worker_policy, "fixed-explicit/0.1")
        self.assertEqual(fixed.gemm_worker_schedule, (2, 2, 2, 2, 2))

        artifact = generate_tensor_cpu_artifact(autograd, plan=adaptive)
        self.assertEqual(artifact.source.count("num_threads(2)"), 2)
        self.assertEqual(artifact.source.count("num_threads(1)"), 3)

    def test_dynamic_shape_and_arena_overflow_are_explicit_fallbacks(
        self,
    ) -> None:
        forward = compile_tensor_graph(
            {"x": _tensor(("batch", 2))},
            (TensorCall("loss", "mean", ("x",)),),
            ("loss",),
        )
        dynamic = compile_autograd(forward, wrt=("x",))
        static = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )

        dynamic_plan = plan_tensor_cpu(dynamic, workers=1)
        tiny_plan = plan_tensor_cpu(
            static,
            arena_budget_bytes=1,
            workers=1,
        )

        self.assertEqual(dynamic_plan.status, "FALLBACK")
        self.assertEqual(
            dynamic_plan.reason,
            "dynamic_shape_requires_reference_executor",
        )
        self.assertEqual(tiny_plan.status, "FALLBACK")
        self.assertIn("arena_required_exceeds_budget", tiny_plan.reason or "")
        self.assertGreater(tiny_plan.arena_required_bytes or 0, 1)


class TensorCpuExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True,
        )
        self.previous_cache = os.environ.get("CASULO_NATIVE_CACHE")
        os.environ["CASULO_NATIVE_CACHE"] = self.cache.name

    def tearDown(self) -> None:
        if self.previous_cache is None:
            os.environ.pop("CASULO_NATIVE_CACHE", None)
        else:
            os.environ["CASULO_NATIVE_CACHE"] = self.previous_cache
        self.cache.cleanup()

    def _assert_native(self, report: object) -> None:
        if not report.used_native:
            self.skipTest(
                "compilador C/OpenMP opcional indisponível: "
                f"{report.fallback_reason}"
            )

    def test_small_forward_backward_is_judged_by_both_authorities(
        self,
    ) -> None:
        _require_pytorch(self)
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("x", "weight", "target"),
        )

        report = execute_tensor_cpu(
            autograd,
            _training_inputs(),
            workers=1,
        )
        self._assert_native(report)

        self.assertEqual(report.protocol, TENSOR_CPU_RUN_PROTOCOL)
        self.assertEqual(report.status, "PASS")
        self.assertTrue(report.used_native)
        self.assertEqual(
            report.native_vs_numpy.status,
            ParityStatus.PASS,
        )
        self.assertEqual(
            report.numpy_vs_pytorch.status,
            ParityStatus.PASS,
        )
        np.testing.assert_allclose(
            report.execution.gradients["weight"],
            [[0.8], [1.0]],
            rtol=0,
            atol=1e-15,
        )
        document = report.to_dict()
        self.assertEqual(
            document["timing"]["classification"],
            "EXPLORATORY_DIAGNOSTIC",
        )
        self.assertFalse(document["timing"]["claim_eligible"])
        self.assertIsNone(document["energy_joules"])
        self.assertIsNone(document["claim"])
        self.assertNotIn("speedup", document)

    def test_medium_float32_mlp_matches_numpy_and_pytorch(self) -> None:
        _require_pytorch(self)
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

        report = execute_tensor_cpu(
            autograd,
            inputs,
            workers=4,
        )
        self._assert_native(report)

        self.assertEqual(report.status, "PASS")
        self.assertEqual(
            report.native_vs_numpy.status,
            ParityStatus.PASS,
        )
        self.assertEqual(
            report.numpy_vs_pytorch.status,
            ParityStatus.PASS,
        )
        self.assertLess(
            max(
                check.max_absolute_error or 0
                for check in report.native_vs_numpy.checks
            ),
            1e-5,
        )
        self.assertGreaterEqual(
            len(report.build.vectorization_report),
            1,
        )

    def test_external_openblas_provider_is_bound_and_judged(self) -> None:
        _require_pytorch(self)
        rng = np.random.default_rng(20_260_730)
        autograd = compile_autograd_file(
            ROOT / "examples" / "tensor" / "mlp-mse-medium.tensor.json",
            wrt=("weight1", "weight2"),
        )
        inputs = {}
        for item in autograd.forward.inputs:
            values = rng.normal(
                size=tuple(int(x) for x in item.type.shape)
            )
            if item.name.startswith("weight"):
                values *= 0.1
            inputs[item.name] = values.astype(np.float32)

        report = execute_tensor_cpu(
            autograd,
            inputs,
            workers=4,
            gemm_workers=1,
            provider="openblas",
            allow_fallback=True,
        )
        if not report.used_native:
            self.skipTest(report.fallback_reason or "OpenBLAS indisponível")

        self.assertEqual(report.status, "PASS")
        self.assertTrue(report.native_vs_numpy.passed)
        providers = {
            item.provider.provider_id
            for item in report.plan.algebra_kernels
        }
        self.assertEqual(
            providers,
            {"numpy-scipy-openblas-ilp64"},
        )
        self.assertEqual(report.plan.gemm_workers, 1)

    def test_broadcast_views_and_axis_reduction_have_native_parity(
        self,
    ) -> None:
        _require_pytorch(self)
        forward = compile_tensor_graph(
            {
                "x": _tensor((2, 3)),
                "bias": _tensor((3,)),
            },
            (
                TensorCall("shifted", "add", ("x", "bias")),
                TensorCall("active", "sigmoid", ("shifted",)),
                TensorCall(
                    "row_mean",
                    "mean",
                    ("active",),
                    {"axis": 1, "keepdim": False},
                ),
                TensorCall(
                    "row",
                    "reshape",
                    ("row_mean",),
                    {"shape": [1, 2]},
                ),
                TensorCall(
                    "column",
                    "transpose",
                    ("row",),
                    {"axis0": 0, "axis1": 1},
                ),
                TensorCall("loss", "sum", ("column",)),
            ),
            ("loss",),
        )
        autograd = compile_autograd(
            forward,
            wrt=("x", "bias"),
        )

        report = execute_tensor_cpu(
            autograd,
            {
                "x": [[-1.0, 0.5, 1.0], [1.5, -0.25, 0.0]],
                "bias": [0.1, -0.2, 0.3],
            },
            workers=1,
        )
        self._assert_native(report)

        self.assertEqual(report.status, "PASS")
        self.assertTrue(report.native_vs_numpy.passed)
        self.assertEqual(
            report.numpy_vs_pytorch.status,
            ParityStatus.PASS,
        )

    def test_cache_is_content_addressed_and_second_build_is_a_hit(
        self,
    ) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )

        first = execute_tensor_cpu(
            autograd,
            _training_inputs(),
            workers=1,
        )
        self._assert_native(first)
        second = execute_tensor_cpu(
            autograd,
            _training_inputs(),
            workers=1,
        )

        self.assertFalse(first.build.cache_hit)
        self.assertTrue(second.build.cache_hit)
        self.assertEqual(
            first.build.binary_sha256,
            second.build.binary_sha256,
        )

    def test_prepared_executor_reuses_inputs_arena_and_library(self) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )
        reference = execute_tensor_cpu(
            autograd,
            _training_inputs(),
            workers=1,
        )
        self._assert_native(reference)

        prepared = prepare_tensor_cpu_executor(
            autograd,
            _training_inputs(),
            workers=1,
        )
        prepared.invoke()
        first = prepared.snapshot(reference.execution)
        prepared.invoke()
        second = prepared.snapshot(reference.execution)

        self.assertEqual(
            first.outputs["loss"].tolist(),
            second.outputs["loss"].tolist(),
        )
        np.testing.assert_allclose(
            first.gradients["weight"],
            second.gradients["weight"],
            rtol=0,
            atol=0,
        )

    def test_budget_fallback_is_explicit_and_strict_mode_refuses_it(
        self,
    ) -> None:
        autograd = compile_autograd_file(
            TRAINING_GRAPH,
            wrt=("weight",),
        )

        fallback = execute_tensor_cpu(
            autograd,
            _training_inputs(),
            arena_budget_bytes=1,
            workers=1,
        )

        self.assertEqual(fallback.status, "FALLBACK")
        self.assertFalse(fallback.used_native)
        self.assertEqual(fallback.execution.backend, "numpy-reference")
        self.assertIn(
            "arena_required_exceeds_budget",
            fallback.fallback_reason or "",
        )
        self.assertIsNone(fallback.native_vs_numpy)
        with self.assertRaises(TensorCpuUnavailable):
            execute_tensor_cpu(
                autograd,
                _training_inputs(),
                arena_budget_bytes=1,
                workers=1,
                allow_fallback=False,
            )


class TensorCpuCliTests(unittest.TestCase):
    def test_plan_and_run_are_machine_readable(self) -> None:
        _require_pytorch(self)
        with tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True,
        ) as directory:
            previous_cache = os.environ.get("CASULO_NATIVE_CACHE")
            os.environ["CASULO_NATIVE_CACHE"] = directory
            try:
                plan_stdout = io.StringIO()
                with redirect_stdout(plan_stdout):
                    plan_status = t_main(
                        [
                            "tensor-cpu-plan",
                            str(TRAINING_GRAPH),
                            "--wrt",
                            "weight",
                            "--workers",
                            "1",
                        ]
                    )
                plan = json.loads(plan_stdout.getvalue())

                run_stdout = io.StringIO()
                with redirect_stdout(run_stdout):
                    run_status = t_main(
                        [
                            "tensor-cpu-run",
                            str(TRAINING_GRAPH),
                            "--input",
                            str(TRAINING_INPUT),
                            "--wrt",
                            "weight",
                            "--workers",
                            "1",
                        ]
                    )
                run = json.loads(run_stdout.getvalue())
            finally:
                if previous_cache is None:
                    os.environ.pop("CASULO_NATIVE_CACHE", None)
                else:
                    os.environ["CASULO_NATIVE_CACHE"] = previous_cache

        self.assertEqual(plan_status, 0)
        self.assertEqual(plan["status"], "NATIVE")
        if run["status"] == "FALLBACK":
            self.skipTest(
                "compilador C/OpenMP opcional indisponível: "
                f"{run['fallback_reason']}"
            )
        self.assertEqual(run_status, 0)
        self.assertEqual(run["status"], "PASS")
        self.assertTrue(run["used_native"])
        self.assertFalse(run["timing"]["claim_eligible"])

    def test_cli_returns_distinct_fallback_exit_code(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = t_main(
                [
                    "tensor-cpu-run",
                    str(TRAINING_GRAPH),
                    "--input",
                    str(TRAINING_INPUT),
                    "--wrt",
                    "weight",
                    "--arena-budget",
                    "1",
                    "--workers",
                    "1",
                ]
            )
        document = json.loads(stdout.getvalue())

        self.assertEqual(status, 4)
        self.assertEqual(document["status"], "FALLBACK")
        self.assertFalse(document["used_native"])


if __name__ == "__main__":
    unittest.main()
