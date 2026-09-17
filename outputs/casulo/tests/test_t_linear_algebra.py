from __future__ import annotations

import unittest

from casulo.t.linear_algebra import (
    CASULO_OWNED_GEMM_PROVIDER,
    CASULO_LINEAR_ALGEBRA_PROTOCOL,
    CasuloLinearAlgebraError,
    audit_gemm_plan,
    discover_numpy_openblas_provider,
    form_gemm_plan,
    resolve_provider_library,
)


class CasuloLinearAlgebraTests(unittest.TestCase):
    def test_numpy_openblas_provider_is_content_addressed(self) -> None:
        try:
            provider = discover_numpy_openblas_provider()
        except CasuloLinearAlgebraError as exc:
            self.skipTest(str(exc))

        library = resolve_provider_library(provider)
        self.assertTrue(provider.external)
        self.assertNotEqual(provider.version, "unknown")
        self.assertIsNotNone(library)
        self.assertTrue(library.is_file())
        self.assertEqual(len(provider.binary_sha256 or ""), 64)
        self.assertEqual(
            provider.float32_symbol,
            "scipy_cblas_sgemm64_",
        )

    def test_contiguous_right_selects_vectorizable_traffic_order(self) -> None:
        plan = form_gemm_plan(
            dtype="float32",
            left_shape=(256, 64),
            right_shape=(64, 128),
            left_strides=(64, 1),
            right_strides=(128, 1),
        )

        self.assertEqual(plan.protocol, CASULO_LINEAR_ALGEBRA_PROTOCOL)
        self.assertEqual(plan.provider, CASULO_OWNED_GEMM_PROVIDER)
        self.assertEqual(plan.loop_order, "row-inner-column")
        self.assertEqual(plan.parallel_axis, "row")
        self.assertEqual(plan.vector_axis, "column")
        self.assertFalse(plan.materializes_right)
        self.assertTrue(plan.contracts_multiply_add)
        self.assertFalse(plan.reassociates_reduction)
        self.assertTrue(audit_gemm_plan(plan).passed)
        self.assertFalse(
            audit_gemm_plan(plan).external_compute_provider
        )

    def test_transposed_right_preserves_zero_copy_product_inner_order(
        self,
    ) -> None:
        plan = form_gemm_plan(
            dtype="float32",
            left_shape=(256, 32),
            right_shape=(32, 128),
            left_strides=(32, 1),
            right_strides=(1, 32),
        )

        self.assertEqual(plan.loop_order, "row-column-inner")
        self.assertIsNone(plan.vector_axis)
        self.assertFalse(plan.materializes_right)
        self.assertTrue(plan.traffic.left_inner_contiguous)
        self.assertTrue(plan.traffic.right_inner_contiguous)

    def test_identity_is_deterministic_and_invalid_contract_is_refused(
        self,
    ) -> None:
        arguments = {
            "dtype": "float64",
            "left_shape": (8, 16),
            "right_shape": (16, 4),
            "left_strides": (16, 1),
            "right_strides": (4, 1),
        }
        first = form_gemm_plan(**arguments)
        second = form_gemm_plan(**arguments)

        self.assertEqual(first.identity, second.identity)
        self.assertEqual(first.to_dict(), second.to_dict())
        with self.assertRaises(CasuloLinearAlgebraError):
            form_gemm_plan(
                dtype="float32",
                left_shape=(8, 15),
                right_shape=(16, 4),
                left_strides=(15, 1),
                right_strides=(4, 1),
            )
