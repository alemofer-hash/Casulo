from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo.t import ArtifactBuilder, run_artifact
from casulo.t.artifact import ArtifactError
from casulo.t.cli import main as t_main
from casulo.t.native import (
    NATIVE_ABI_FILE,
    NATIVE_ABI_PROTOCOL,
    NATIVE_ARENA_PROTOCOL,
    NATIVE_AOT_PROTOCOL,
    NATIVE_BACKEND_VERSION,
    NATIVE_SIMD_PROTOCOL,
    NATIVE_SOURCE_FILE,
    NativeError,
    NativeSemanticError,
    compile_native_artifact,
    prepare_native_executor,
    run_native_artifact,
)
from casulo.t.native_benchmark import benchmark_native_artifact
from casulo.t.simd_benchmark import benchmark_simd_artifact


CANONICAL_SOURCE = ROOT / "examples" / "t" / "balanco_hidrico.t"
FLOAT_BATCH = [
    {
        "precipitation": 100.0,
        "evapotranspiration": 10.0,
        "surface_flow": 20.0,
        "base_flow": 5.0,
    },
    {
        "precipitation": 80.0,
        "evapotranspiration": 7.5,
        "surface_flow": 9.0,
        "base_flow": 4.5,
    },
]


@unittest.skipUnless(
    any(shutil.which(name) for name in ("gcc", "clang", "clang-cl", "cl")),
    "compilador C não disponível",
)
class TNativeBackendTests(unittest.TestCase):
    def test_artifact_contains_auditable_c99_and_stable_abi(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            source = (built.output_dir / NATIVE_SOURCE_FILE).read_text(
                encoding="utf-8"
            )
            abi = json.loads(
                (built.output_dir / NATIVE_ABI_FILE).read_text(encoding="utf-8")
            )
        self.assertIn("casulo_execute_f64", source)
        self.assertIn(built.artifact_id, source)
        self.assertEqual(abi["protocol"], NATIVE_ABI_PROTOCOL)
        self.assertTrue(abi["operations"][0]["eligible"])
        self.assertIn("CASULO_RESTRICT", source)
        self.assertEqual(
            abi["operations"][0]["vectorization"]["protocol"],
            NATIVE_SIMD_PROTOCOL,
        )

    def test_compiles_real_dll_and_reuses_derivative_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            first = compile_native_artifact(artifact, force=True)
            second = compile_native_artifact(artifact, force=True)
            cached = compile_native_artifact(artifact)
        self.assertTrue(first.library.is_file())
        self.assertFalse(first.cache_hit)
        self.assertFalse(second.cache_hit)
        self.assertTrue(cached.cache_hit)
        self.assertEqual(first.binary_sha256, second.binary_sha256)

    def test_native_batch_is_equivalent_to_scalar_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            native = run_native_artifact(
                artifact,
                FLOAT_BATCH,
                batch=True,
                fallback=False,
            )
            reference = [
                run_artifact(
                    artifact,
                    item,
                    use_cache=False,
                ).payload
                for item in FLOAT_BATCH
            ]
        self.assertEqual(native.backend, NATIVE_BACKEND_VERSION)
        self.assertEqual(native.payload["items"], reference)
        self.assertEqual(native.payload["items"][0]["result"], 65.0)

    def test_integer_input_uses_explicit_python_fallback(self) -> None:
        integer_input = {
            key: int(value)
            for key, value in FLOAT_BATCH[0].items()
        }
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            executed = run_native_artifact(artifact, integer_input)
        self.assertEqual(executed.backend, "python-fallback")
        self.assertIn("exige float finito", executed.fallback_reason or "")
        self.assertEqual(executed.payload["result"], 65)

    def test_native_judge_failure_is_not_misclassified_as_fallback(self) -> None:
        invalid = dict(FLOAT_BATCH[0], precipitation=-1.0)
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            with self.assertRaisesRegex(
                NativeSemanticError,
                "judge falhou",
            ):
                run_native_artifact(artifact, invalid)

    def test_compiler_failure_falls_back_without_changing_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            with patch(
                "casulo.t.native._find_compiler",
                side_effect=NativeError("compilador indisponível"),
            ):
                executed = run_native_artifact(
                    artifact,
                    FLOAT_BATCH,
                    batch=True,
                )
            reference = [
                run_artifact(artifact, item, use_cache=False).payload
                for item in FLOAT_BATCH
            ]
        self.assertEqual(executed.backend, "python-fallback")
        self.assertEqual(executed.payload["items"], reference)

    def test_tampered_c99_source_is_rejected_before_compilation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            native_source = artifact / NATIVE_SOURCE_FILE
            native_source.write_text(
                native_source.read_text(encoding="utf-8") + "\n/* tamper */\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ArtifactError, "integridade violada"):
                compile_native_artifact(artifact)

    def test_native_benchmark_proves_semantic_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            report = benchmark_native_artifact(
                artifact,
                FLOAT_BATCH * 5,
                samples=2,
                iterations=1,
            )
        self.assertTrue(report.comparison["semantically_equivalent"])
        self.assertGreater(report.c99_native.median_wall_ns, 0)
        self.assertGreater(report.native_marshal.median_wall_ns, 0)
        self.assertGreater(report.native_kernel.median_wall_ns, 0)
        self.assertGreater(report.native_manifestation.median_wall_ns, 0)
        self.assertEqual(
            report.comparison["arena_protocol"],
            NATIVE_ARENA_PROTOCOL,
        )
        self.assertIn("lower", report.comparison["paired_wall_speedup_ci95"])
        self.assertEqual(len(report.dataset_sha256), 64)
        self.assertEqual(report.input_profile["records"], 10)
        self.assertEqual(len(report.equivalence_sha256), 64)

    def test_arena_grows_by_power_of_two_and_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            prepared, _manifest, _operation, _build = prepare_native_executor(
                artifact
            )
            first = prepared(FLOAT_BATCH)
            first_buffer = prepared.input_buffer
            first_capacity = prepared.capacity
            second = prepared(FLOAT_BATCH[:1])
        self.assertEqual(len(first), 2)
        self.assertEqual(second[0]["result"], 65.0)
        self.assertEqual(first_capacity, 2)
        self.assertIs(prepared.input_buffer, first_buffer)

    def test_scalar_and_simd_profiles_are_distinct_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            scalar = compile_native_artifact(
                artifact,
                force=True,
                profile="scalar",
            )
            simd_first = compile_native_artifact(
                artifact,
                force=True,
                profile="simd",
            )
            simd_second = compile_native_artifact(
                artifact,
                force=True,
                profile="simd",
            )
        self.assertEqual(scalar.profile, "scalar")
        self.assertEqual(simd_first.profile, "simd")
        self.assertNotEqual(scalar.target, simd_first.target)
        self.assertNotEqual(scalar.binary_sha256, simd_first.binary_sha256)
        self.assertEqual(
            simd_first.binary_sha256,
            simd_second.binary_sha256,
        )
        if "gcc" in Path(simd_first.compiler).name.lower():
            self.assertTrue(
                any(
                    "optimized: loop vectorized" in line.lower()
                    for line in simd_first.vectorization_report
                )
            )

    def test_simd_benchmark_preserves_strict_scalar_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            report = benchmark_simd_artifact(
                artifact,
                FLOAT_BATCH * 32,
                samples=2,
                iterations=10,
            )
        self.assertTrue(report.comparison["semantically_equivalent"])
        self.assertEqual(
            report.comparison["protocol"],
            NATIVE_SIMD_PROTOCOL,
        )
        self.assertEqual(len(report.equivalence_sha256), 64)
        self.assertGreater(report.scalar_kernel.median_wall_ns, 0)
        self.assertGreater(report.simd_kernel.median_wall_ns, 0)

    def test_guard_phase_preserves_first_failure_order(self) -> None:
        source_text = """\
field Sample
  trace value: Number

condense OrderedGuards in Sample
  judge value >= 0
  let shifted = value - 10
  judge shifted >= 0
  let result = shifted * 2
  stabilize result
  emit result
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "ordered_guards.t"
            source.write_text(source_text, encoding="utf-8")
            artifact = ArtifactBuilder().build(
                source,
                root / "artifact",
            ).output_dir
            c99 = (artifact / NATIVE_SOURCE_FILE).read_text(encoding="utf-8")
            with self.assertRaisesRegex(
                NativeSemanticError,
                r"shifted >= 0.*registro 0",
            ):
                run_native_artifact(
                    artifact,
                    [{"value": 5.0}, {"value": -1.0}],
                    batch=True,
                    fallback=False,
                )
        self.assertIn("casulo_guard_local", c99)
        self.assertEqual(
            c99.count(
                "for (record = 0u; record < records; ++record)"
            ),
            2,
        )

    def test_aot_removes_dead_let_and_propagates_constant_and_alias(self) -> None:
        source_text = """\
field Sample
  trace value: Number

condense Optimize in Sample
  let unused = value * 99
  let constant = 2 + 3
  let alias = value
  let result = alias + constant
  stabilize result
  emit result
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "optimize.t"
            source.write_text(source_text, encoding="utf-8")
            built = ArtifactBuilder().build(source, root / "artifact")
            abi = json.loads(
                (built.output_dir / NATIVE_ABI_FILE).read_text(
                    encoding="utf-8"
                )
            )
            c99 = (built.output_dir / NATIVE_SOURCE_FILE).read_text(
                encoding="utf-8"
            )
            executed = run_native_artifact(
                built.output_dir,
                {"value": 2.0},
                fallback=False,
            )
        aot = abi["operations"][0]["aot"]
        self.assertEqual(aot["protocol"], NATIVE_AOT_PROTOCOL)
        self.assertEqual(aot["dead_lets_removed"], 1)
        self.assertEqual(aot["constants_propagated"], 1)
        self.assertEqual(aot["aliases_propagated"], 1)
        self.assertNotIn("99.0", c99)
        self.assertIn("5.0", c99)
        self.assertEqual(executed.payload["result"], 7.0)

    def test_empty_native_batch_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            ).output_dir
            executed = run_native_artifact(
                artifact,
                [],
                batch=True,
                fallback=False,
            )
        self.assertEqual(executed.payload["count"], 0)
        self.assertEqual(executed.payload["items"], [])

    def test_cli_build_native_and_run_native(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            build_stdout = io.StringIO()
            with redirect_stdout(build_stdout):
                build_status = t_main(
                    [
                        "build",
                        str(CANONICAL_SOURCE),
                        "--output",
                        str(artifact),
                        "--native",
                        "--format",
                        "json",
                    ]
                )
            run_stdout = io.StringIO()
            with redirect_stdout(run_stdout):
                run_status = t_main(
                    [
                        "run",
                        str(artifact),
                        "--native",
                        "--data",
                        json.dumps(FLOAT_BATCH[0]),
                    ]
                )
            built = json.loads(build_stdout.getvalue())
            executed = json.loads(run_stdout.getvalue())
        self.assertEqual(build_status, 0)
        self.assertEqual(run_status, 0)
        self.assertIn("native", built)
        self.assertEqual(executed["result"], 65.0)


if __name__ == "__main__":
    unittest.main()
