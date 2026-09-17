from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from hypothesis import given, strategies as st

from casulo.t.cli import main as t_main
from casulo.t.tensor import (
    TENSOR_IR_PROTOCOL,
    TENSOR_OPERATOR_ABI,
    CrisalidaTensorIR,
    LarvaTensor,
    TensorCall,
    TensorDType,
    TensorError,
    TensorLayout,
    TensorOperatorRegistry,
    TensorOperatorSchema,
    TensorOwnership,
    compile_tensor_document,
    compile_tensor_graph,
)


class LarvaTensorTypeTests(unittest.TestCase):
    def test_static_shape_computes_rank_numel_and_bytes(self) -> None:
        value = LarvaTensor(
            TensorDType.FLOAT32,
            (32, 8),
            ownership=TensorOwnership.BORROWED,
        )

        self.assertEqual(value.rank, 2)
        self.assertEqual(value.numel, 256)
        self.assertEqual(value.nbytes, 1_024)
        self.assertIn("float32[32, 8]", value.render())

    def test_symbolic_shape_has_dynamic_memory(self) -> None:
        value = LarvaTensor(TensorDType.FLOAT64, ("batch", 8))

        self.assertIsNone(value.numel)
        self.assertIsNone(value.nbytes)

    def test_rejects_invalid_dimension_and_untracked_view(self) -> None:
        with self.assertRaisesRegex(TensorError, "T5002"):
            LarvaTensor(TensorDType.FLOAT32, (0, 8))
        with self.assertRaisesRegex(TensorError, "T5004"):
            LarvaTensor(
                TensorDType.FLOAT32,
                (8, 8),
                ownership=TensorOwnership.VIEW,
            )
        with self.assertRaisesRegex(TensorError, "T5000"):
            LarvaTensor.from_dict(
                {"dtype": "float32", "shape": "32,8"}
            )


class TensorOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = TensorOperatorRegistry.builtins()

    def test_broadcast_and_matmul_inference(self) -> None:
        matrix = LarvaTensor(TensorDType.FLOAT32, (32, 8))
        bias = LarvaTensor(TensorDType.FLOAT32, (8,))
        weight = LarvaTensor(TensorDType.FLOAT32, (8, 4))

        added = self.registry.infer("add", (matrix, bias))
        multiplied = self.registry.infer("matmul", (matrix, weight))

        self.assertEqual(added.shape, (32, 8))
        self.assertEqual(multiplied.shape, (32, 4))

    def test_rejects_matmul_shape_and_dtype_mismatch(self) -> None:
        left = LarvaTensor(TensorDType.FLOAT32, (32, 8))
        wrong_shape = LarvaTensor(TensorDType.FLOAT32, (7, 4))
        wrong_dtype = LarvaTensor(TensorDType.FLOAT64, (8, 4))

        with self.assertRaisesRegex(TensorError, "T5303"):
            self.registry.infer("matmul", (left, wrong_shape))
        with self.assertRaisesRegex(TensorError, "T5111"):
            self.registry.infer("matmul", (left, wrong_dtype))

    def test_reshape_and_transpose_are_explicit_views(self) -> None:
        source = LarvaTensor(
            TensorDType.FLOAT32,
            (4, 8),
            alias_group="input:x",
        )

        reshaped = self.registry.infer(
            "reshape",
            (source,),
            {"shape": [2, 16]},
        )
        transposed = self.registry.infer("transpose", (source,))

        self.assertEqual(reshaped.ownership, TensorOwnership.VIEW)
        self.assertEqual(reshaped.alias_group, "input:x")
        self.assertEqual(transposed.shape, (8, 4))
        self.assertEqual(transposed.layout, TensorLayout.STRIDED)

    def test_extension_manifest_is_abi_gated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / "valid.toml"
            invalid = root / "invalid.toml"
            valid.write_text(
                'format = "casulo-tensor-extension/0.1"\n'
                "\n"
                "[extension]\n"
                'name = "research-ops"\n'
                'version = "1.0.0"\n'
                'abi = "casulo-tensor-operator-abi/0.1"\n'
                "\n"
                "[[operator]]\n"
                'name = "square"\n'
                "arity = 1\n"
                'shape_rule = "identity"\n',
                encoding="utf-8",
            )
            invalid.write_text(
                'format = "casulo-tensor-extension/0.1"\n'
                "\n"
                "[extension]\n"
                'name = "old"\n'
                'version = "1.0.0"\n'
                'abi = "foreign/9"\n',
                encoding="utf-8",
            )

            identity = self.registry.load_extension(valid)
            inferred = self.registry.infer(
                "square",
                (LarvaTensor(TensorDType.FLOAT32, (4, 4)),),
            )

            self.assertEqual(identity, ("research-ops", "1.0.0"))
            self.assertEqual(inferred.shape, (4, 4))
            with self.assertRaisesRegex(TensorError, "T5123"):
                TensorOperatorRegistry.builtins().load_extension(invalid)

    def test_mutating_extension_requires_owned_mutable_and_preserves_alias(self) -> None:
        self.registry.register(
            TensorOperatorSchema(
                name="relu_inplace",
                version="0.1",
                arity=1,
                shape_rule="identity",
                dtype_rule="floating",
                mutates_input=0,
            )
        )
        immutable = LarvaTensor(TensorDType.FLOAT32, (8, 8))
        mutable = LarvaTensor(
            TensorDType.FLOAT32,
            (8, 8),
            alias_group="buffer:0",
            mutable=True,
        )

        with self.assertRaisesRegex(TensorError, "T5113"):
            self.registry.infer("relu_inplace", (immutable,))
        result = self.registry.infer("relu_inplace", (mutable,))

        self.assertEqual(result.ownership, TensorOwnership.VIEW)
        self.assertEqual(result.alias_group, "buffer:0")


class TensorOperatorPropertyTests(unittest.TestCase):
    @given(
        rows=st.integers(min_value=1, max_value=4_096),
        columns=st.integers(min_value=1, max_value=4_096),
    )
    def test_vector_broadcast_preserves_matrix_shape(
        self,
        rows: int,
        columns: int,
    ) -> None:
        registry = TensorOperatorRegistry.builtins()
        matrix = LarvaTensor(TensorDType.FLOAT32, (rows, columns))
        vector = LarvaTensor(TensorDType.FLOAT32, (columns,))

        result = registry.infer("add", (matrix, vector))

        self.assertEqual(result.shape, matrix.shape)

    @given(
        rows=st.integers(min_value=1, max_value=1_024),
        shared=st.integers(min_value=1, max_value=1_024),
        columns=st.integers(min_value=1, max_value=1_024),
    )
    def test_matmul_contract_is_shape_closed(
        self,
        rows: int,
        shared: int,
        columns: int,
    ) -> None:
        registry = TensorOperatorRegistry.builtins()
        left = LarvaTensor(TensorDType.FLOAT64, (rows, shared))
        right = LarvaTensor(TensorDType.FLOAT64, (shared, columns))

        result = registry.infer("matmul", (left, right))

        self.assertEqual(result.shape, (rows, columns))

    @given(
        left=st.integers(min_value=1, max_value=512),
        right=st.integers(min_value=1, max_value=512),
    )
    def test_static_reshape_conserves_element_count(
        self,
        left: int,
        right: int,
    ) -> None:
        registry = TensorOperatorRegistry.builtins()
        source = LarvaTensor(
            TensorDType.FLOAT32,
            (left, right),
            alias_group="source",
        )

        result = registry.infer(
            "reshape",
            (source,),
            {"shape": [1, left * right]},
        )

        self.assertEqual(result.numel, source.numel)
        self.assertEqual(result.alias_group, source.alias_group)


class TensorIRTests(unittest.TestCase):
    def _compile(self) -> CrisalidaTensorIR:
        return compile_tensor_graph(
            {
                "x": LarvaTensor(
                    TensorDType.FLOAT32,
                    (32, 8),
                    ownership=TensorOwnership.BORROWED,
                ),
                "weight": LarvaTensor(
                    TensorDType.FLOAT32,
                    (8, 4),
                    ownership=TensorOwnership.BORROWED,
                ),
            },
            (
                TensorCall("hidden", "matmul", ("x", "weight")),
                TensorCall("active", "relu", ("hidden",)),
                TensorCall(
                    "flat",
                    "reshape",
                    ("active",),
                    {"shape": [16, 8]},
                ),
            ),
            ("flat",),
        )

    def test_graph_lowers_to_versioned_ir_with_memory_plan(self) -> None:
        result = self._compile()

        self.assertEqual(result.protocol, TENSOR_IR_PROTOCOL)
        self.assertEqual(result.operator_abi, TENSOR_OPERATOR_ABI)
        self.assertEqual(result.instructions[-1].output_type.ownership, TensorOwnership.VIEW)
        self.assertEqual(
            result.instructions[-1].output_type.alias_group,
            "value:active",
        )
        self.assertTrue(result.memory.known)
        self.assertEqual(result.memory.input_bytes, 1_152)
        self.assertEqual(result.memory.allocated_bytes, 1_024)
        self.assertEqual(result.memory.peak_live_bytes, 2_176)
        self.assertTrue(result.render_text().startswith(TENSOR_IR_PROTOCOL))

    def test_symbolic_graph_marks_memory_dynamic(self) -> None:
        result = compile_tensor_graph(
            {
                "x": LarvaTensor(TensorDType.FLOAT32, ("batch", 8)),
                "weight": LarvaTensor(TensorDType.FLOAT32, (8, 4)),
            },
            (TensorCall("prediction", "matmul", ("x", "weight")),),
            ("prediction",),
        )

        self.assertFalse(result.memory.known)
        self.assertIsNone(result.memory.peak_live_bytes)

    def test_rejects_unknown_value_and_duplicate_ssa_name(self) -> None:
        value = LarvaTensor(TensorDType.FLOAT32, (8, 8))
        with self.assertRaisesRegex(TensorError, "T5202"):
            compile_tensor_graph(
                {"x": value},
                (TensorCall("y", "add", ("x", "missing")),),
                ("y",),
            )
        with self.assertRaisesRegex(TensorError, "T5201"):
            compile_tensor_graph(
                {"x": value},
                (TensorCall("x", "relu", ("x",)),),
                ("x",),
            )

    def test_document_and_cli_compile_same_graph(self) -> None:
        document = {
            "format": TENSOR_IR_PROTOCOL,
            "inputs": {
                "x": {
                    "dtype": "float32",
                    "shape": [32, 8],
                    "ownership": "borrowed",
                },
                "weight": {
                    "dtype": "float32",
                    "shape": [8, 4],
                    "ownership": "borrowed",
                },
            },
            "calls": [
                {
                    "result": "prediction",
                    "operator": "matmul",
                    "inputs": ["x", "weight"],
                }
            ],
            "outputs": ["prediction"],
        }
        direct = compile_tensor_document(document)
        self.assertEqual(direct.instructions[0].output_type.shape, (32, 4))

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "graph.tensor.json"
            source.write_text(json.dumps(document), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = t_main(
                    ["tensor-compile", str(source), "--format", "json"]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(payload["protocol"], TENSOR_IR_PROTOCOL)
        self.assertEqual(payload["instructions"][0]["result"], "prediction")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
