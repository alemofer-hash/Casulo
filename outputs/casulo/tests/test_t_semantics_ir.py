from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo.t import check_file, check_source
from casulo.t.cli import main as t_main


class TSymbolAndTypeTests(unittest.TestCase):
    def test_symbol_table_contains_fields_traces_operations_and_locals(self) -> None:
        result = check_file(ROOT / "examples" / "t" / "balanco_hidrico.t")
        self.assertTrue(result.ok, result.diagnostics)
        self.assertIsNotNone(result.symbols)
        symbols = {
            (item.kind.value, item.qualified_name, item.type_name)
            for item in result.symbols.symbols
        }
        self.assertIn(("field", "HydroCell", "HydroCell"), symbols)
        self.assertIn(
            ("trace", "HydroCell.precipitation", "Number"),
            symbols,
        )
        self.assertIn(
            ("local", "WaterBalance.storage_change", "Number"),
            symbols,
        )

    def test_branch_local_is_visible_only_inside_branch(self) -> None:
        result = check_file(
            ROOT
            / "conformance"
            / "golden"
            / "invalid"
            / "26_branch_local_leak.t"
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["T3030"],
        )

    def test_operation_output_type_is_inferred(self) -> None:
        result = check_file(
            ROOT
            / "conformance"
            / "golden"
            / "valid"
            / "16_text_expression.t"
        )
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(
            result.analysis.operation_outputs["FullName"].render(),
            "Text",
        )

    def test_every_path_must_emit(self) -> None:
        invalid = check_file(
            ROOT
            / "conformance"
            / "golden"
            / "invalid"
            / "21_missing_emit_branch.t"
        )
        valid = check_file(
            ROOT
            / "conformance"
            / "golden"
            / "valid"
            / "14_all_paths_emit.t"
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in invalid.diagnostics],
            ["T3020"],
        )
        self.assertTrue(valid.ok, valid.diagnostics)

    def test_incompatible_emit_types_are_rejected(self) -> None:
        result = check_file(
            ROOT
            / "conformance"
            / "golden"
            / "invalid"
            / "22_inconsistent_emit_types.t"
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["T3034"],
        )
        self.assertIsNone(result.ir)


class TCrisalidaIRTests(unittest.TestCase):
    def test_canonical_ir_matches_golden_text(self) -> None:
        result = check_file(ROOT / "examples" / "t" / "balanco_hidrico.t")
        expected = (
            ROOT / "conformance" / "ir" / "balanco_hidrico.ir"
        ).read_text(encoding="utf-8")
        self.assertTrue(result.ok, result.diagnostics)
        self.assertIsNotNone(result.ir)
        self.assertEqual(result.ir.render_text().strip(), expected.strip())

    def test_ir_contains_nested_if_blocks(self) -> None:
        result = check_file(
            ROOT
            / "conformance"
            / "golden"
            / "valid"
            / "14_all_paths_emit.t"
        )
        operation = result.ir.operations[0]
        branch = operation.instructions[0]
        self.assertEqual(branch.op, "if")
        self.assertEqual(branch.type_name, "Bool")
        self.assertEqual(branch.then_body[0].op, "emit")
        self.assertEqual(branch.else_body[0].op, "emit")

    def test_ir_json_is_serializable(self) -> None:
        result = check_file(ROOT / "examples" / "t" / "balanco_hidrico.t")
        encoded = json.dumps(result.ir.to_dict(), ensure_ascii=False)
        self.assertIn("crisalida-ir/0.1", encoded)
        self.assertIn("WaterBalance", encoded)


class TInspectCliTests(unittest.TestCase):
    def test_inspect_symbols_json(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        source = ROOT / "examples" / "t" / "balanco_hidrico.t"
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = t_main(
                ["inspect", str(source), "--symbols", "--format", "json"]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(
            any(
                item["qualified_name"] == "WaterBalance.storage_change"
                for item in payload["symbols"]
            )
        )
        self.assertEqual(stderr.getvalue(), "")

    def test_inspect_ir_defaults_to_text(self) -> None:
        stdout = io.StringIO()
        source = ROOT / "examples" / "t" / "balanco_hidrico.t"
        with redirect_stdout(stdout):
            status = t_main(["inspect", str(source), "--ir"])
        self.assertEqual(status, 0)
        self.assertTrue(stdout.getvalue().startswith("crisalida-ir/0.1"))

    def test_inspect_invalid_ir_returns_diagnostics(self) -> None:
        stdout = io.StringIO()
        source = (
            ROOT
            / "conformance"
            / "golden"
            / "invalid"
            / "17_unknown_name.t"
        )
        with redirect_stdout(stdout):
            status = t_main(
                ["inspect", str(source), "--ir", "--format", "json"]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 1)
        self.assertIsNone(payload["ir"])
        self.assertEqual(payload["diagnostics"][0]["code"], "T3030")


if __name__ == "__main__":
    unittest.main()
