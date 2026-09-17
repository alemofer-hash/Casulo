from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo.t import ArtifactBuilder, check_file, run_artifact
from casulo.t.artifact import (
    ArtifactError,
    EXECUTABLE_FILE,
    GRAPH_FILE,
    IR_FILE,
    MANIFEST_FILE,
    SOURCE_FILE,
)
from casulo.t.backend import PythonBackend
from casulo.t.native import NATIVE_ABI_FILE, NATIVE_SOURCE_FILE
from casulo.t.cli import main as t_main
from casulo.t.runner import ExecutionFailed


CANONICAL_SOURCE = ROOT / "examples" / "t" / "balanco_hidrico.t"
CANONICAL_INPUT = {
    "precipitation": 100,
    "evapotranspiration": 10,
    "surface_flow": 20,
    "base_flow": 5,
}


class TPythonBackendTests(unittest.TestCase):
    def test_generation_is_deterministic_and_valid_python(self) -> None:
        checked = check_file(CANONICAL_SOURCE)
        backend = PythonBackend()
        first = backend.generate(checked.ir, "sha256:test").source
        second = backend.generate(checked.ir, "sha256:test").source
        self.assertEqual(first, second)
        compile(first, "casulo_artifact.py", "exec")
        self.assertNotIn(str(ROOT), first)

    def test_backend_supports_all_core_instructions(self) -> None:
        source = (
            ROOT
            / "conformance"
            / "golden"
            / "valid"
            / "06_all_simple_statements.t"
        )
        with tempfile.TemporaryDirectory() as temporary:
            artifact = ArtifactBuilder().build(
                source,
                Path(temporary) / "artifact",
            )
            executed = run_artifact(
                artifact.output_dir,
                {"value": 500},
            ).payload
        self.assertEqual(executed["result"], 0.5)
        self.assertEqual(executed["state"], "stable")
        self.assertEqual(len(executed["evidence"]["judgements"]), 1)
        self.assertEqual(len(executed["evidence"]["restrictions"]), 1)
        self.assertEqual(len(executed["evidence"]["projections"]), 1)
        self.assertEqual(len(executed["evidence"]["bindings"]), 1)


class TArtifactTests(unittest.TestCase):
    def test_build_contains_source_ir_executable_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            names = {item.name for item in built.output_dir.iterdir()}
            manifest = json.loads(
                (built.output_dir / MANIFEST_FILE).read_text(encoding="utf-8")
            )
            self.assertEqual(
                names,
                {
                    SOURCE_FILE,
                    IR_FILE,
                    GRAPH_FILE,
                    EXECUTABLE_FILE,
                    NATIVE_ABI_FILE,
                    NATIVE_SOURCE_FILE,
                    MANIFEST_FILE,
                },
            )
            self.assertEqual(manifest["brand"], "Casulo")
            self.assertEqual(manifest["origin"], "Teloscorp")
            self.assertEqual(
                manifest["operations"][0]["optimization"]["estimated_cost"],
                8,
            )
            self.assertNotIn("generated_at", manifest)
            self.assertEqual(
                (built.output_dir / SOURCE_FILE).read_bytes(),
                CANONICAL_SOURCE.read_bytes(),
            )

    def test_second_build_is_a_cache_hit_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifact"
            first = ArtifactBuilder().build(CANONICAL_SOURCE, output)
            mtimes = {
                item.name: item.stat().st_mtime_ns
                for item in output.iterdir()
            }
            second = ArtifactBuilder().build(CANONICAL_SOURCE, output)
            self.assertFalse(first.cache_hit)
            self.assertTrue(second.cache_hit)
            self.assertEqual(
                mtimes,
                {
                    item.name: item.stat().st_mtime_ns
                    for item in output.iterdir()
                },
            )

    def test_identical_source_in_other_directory_has_same_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left_source = root / "left" / "program.t"
            right_source = root / "right" / "renamed.t"
            left_source.parent.mkdir()
            right_source.parent.mkdir()
            shutil.copyfile(CANONICAL_SOURCE, left_source)
            shutil.copyfile(CANONICAL_SOURCE, right_source)
            left = ArtifactBuilder().build(left_source, root / "left-build")
            right = ArtifactBuilder().build(right_source, root / "right-build")
            self.assertEqual(left.artifact_id, right.artifact_id)
            for filename in (
                SOURCE_FILE,
                IR_FILE,
                GRAPH_FILE,
                EXECUTABLE_FILE,
                NATIVE_ABI_FILE,
                NATIVE_SOURCE_FILE,
                MANIFEST_FILE,
            ):
                self.assertEqual(
                    (left.output_dir / filename).read_bytes(),
                    (right.output_dir / filename).read_bytes(),
                )

    def test_existing_unrelated_directory_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifact"
            output.mkdir()
            marker = output / "user-data.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaises(ArtifactError):
                ArtifactBuilder().build(CANONICAL_SOURCE, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


class TArtifactRunnerTests(unittest.TestCase):
    def test_canonical_balance_preserves_input_and_emits_sixty_five(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            payload = run_artifact(
                built.output_dir,
                CANONICAL_INPUT,
            ).payload
        self.assertEqual(payload["result"], 65)
        self.assertEqual(payload["input"], CANONICAL_INPUT)
        self.assertEqual(payload["state"], "stable")
        self.assertEqual(payload["operation"], "WaterBalance")
        self.assertTrue(payload["evidence"]["judgements"][0]["passed"])

    def test_generated_module_runs_without_casulo_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                root / "artifact",
            )
            input_file = root / "input.json"
            input_file.write_text(
                json.dumps(CANONICAL_INPUT),
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(built.output_dir / EXECUTABLE_FILE),
                    "WaterBalance",
                    str(input_file),
                ],
                cwd=root,
                capture_output=True,
                check=False,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["result"], 65)

    def test_failed_judge_blocks_emission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            invalid = dict(CANONICAL_INPUT, precipitation=-1)
            with self.assertRaisesRegex(ExecutionFailed, "judge falhou"):
                run_artifact(built.output_dir, invalid)

    def test_missing_required_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            with self.assertRaisesRegex(
                ExecutionFailed,
                "campo obrigatório ausente",
            ):
                run_artifact(built.output_dir, {"precipitation": 10})

    def test_optional_default_never_changes_preserved_input(self) -> None:
        source_text = """\
field Sample
  trace required: Number
  trace optional: Number?
condense OptionalValue in Sample
  emit optional
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "optional.t"
            source.write_text(source_text, encoding="utf-8")
            built = ArtifactBuilder().build(source, root / "artifact")
            original = {"required": 1, "extra": "preserved"}
            payload = run_artifact(built.output_dir, original).payload
        self.assertIsNone(payload["result"])
        self.assertEqual(payload["input"], original)

    def test_tampered_executable_is_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            executable = built.output_dir / EXECUTABLE_FILE
            executable.write_text(
                executable.read_text(encoding="utf-8") + "\n# adulterado\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ArtifactError, "integridade violada"):
                run_artifact(built.output_dir, CANONICAL_INPUT)

    def test_manifest_cannot_escape_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                root / "artifact",
            )
            manifest_path = built.output_dir / MANIFEST_FILE
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["executable"]["file"] = "../outside.py"
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ArtifactError, "caminho externo"):
                run_artifact(built.output_dir, CANONICAL_INPUT)

    def test_changing_executable_and_manifest_hash_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            executable = built.output_dir / EXECUTABLE_FILE
            changed = executable.read_bytes() + b"\n# coordinated tamper\n"
            executable.write_bytes(changed)
            manifest_path = built.output_dir / MANIFEST_FILE
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["executable"]["sha256"] = hashlib.sha256(
                changed
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ArtifactError,
                "executável não corresponde",
            ):
                run_artifact(built.output_dir, CANONICAL_INPUT)


class TCrisalidaCliTests(unittest.TestCase):
    def test_build_then_run_and_report_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            input_file = root / "input.json"
            input_file.write_text(
                json.dumps(CANONICAL_INPUT),
                encoding="utf-8",
            )

            first_stdout = io.StringIO()
            with redirect_stdout(first_stdout):
                first_status = t_main(
                    [
                        "build",
                        str(CANONICAL_SOURCE),
                        "--output",
                        str(artifact),
                        "--format",
                        "json",
                    ]
                )
            first = json.loads(first_stdout.getvalue())

            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout):
                second_status = t_main(
                    [
                        "build",
                        str(CANONICAL_SOURCE),
                        "--output",
                        str(artifact),
                        "--format",
                        "json",
                    ]
                )
            second = json.loads(second_stdout.getvalue())

            run_stdout = io.StringIO()
            with redirect_stdout(run_stdout):
                run_status = t_main(
                    [
                        "run",
                        str(artifact),
                        "--input",
                        str(input_file),
                    ]
                )
            result = json.loads(run_stdout.getvalue())

        self.assertEqual(first_status, 0)
        self.assertEqual(second_status, 0)
        self.assertEqual(run_status, 0)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["artifact_id"], second["artifact_id"])
        self.assertEqual(result["result"], 65)

    def test_invalid_source_never_creates_artifact(self) -> None:
        source = (
            ROOT
            / "conformance"
            / "golden"
            / "invalid"
            / "17_unknown_name.t"
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifact"
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = t_main(
                    ["build", str(source), "--output", str(output)]
                )
            self.assertEqual(status, 1)
            self.assertFalse(output.exists())
            self.assertIn("T3030", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
