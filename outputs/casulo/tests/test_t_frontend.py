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

from casulo.t import check_file, check_source, parse_source
from casulo.t.ast import CondenseDecl, FieldDecl, IfStmt, TransitionDecl
from casulo.t.cli import main as t_main


GOLDEN_ROOT = ROOT / "conformance" / "golden"


class TGoldenConformanceTests(unittest.TestCase):
    def test_manifest_has_at_least_forty_cases(self) -> None:
        manifest = json.loads(
            (GOLDEN_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(manifest["cases"]), 40)

    def test_all_golden_cases_match_exactly(self) -> None:
        manifest = json.loads(
            (GOLDEN_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        for case in manifest["cases"]:
            with self.subTest(case=case["path"]):
                result = check_file(GOLDEN_ROOT / case["path"])
                self.assertEqual(result.ok, case["ok"])
                self.assertEqual(
                    [diagnostic.code for diagnostic in result.diagnostics],
                    case["codes"],
                )


class TLexerParserTests(unittest.TestCase):
    def test_comment_marker_inside_string_is_preserved(self) -> None:
        result = check_source(
            'field Message\n'
            '  trace text: Text\n'
            'condense Keep in Message\n'
            '  judge text == "a # b"\n'
            '  emit text\n',
            file="string.t",
        )
        self.assertTrue(result.ok, result.diagnostics)
        condense = result.program.declarations[1]
        self.assertIsInstance(condense, CondenseDecl)
        self.assertEqual(condense.body[0].condition.text, 'text == "a # b"')

    def test_parser_builds_field_condense_and_transition(self) -> None:
        source = """\
field Raw
  trace value: Number
field Stable
  trace value: Number
condense Identity in Raw
  emit value
transition Promote
  from Raw
  to Stable
  emit value
"""
        result = check_source(source, file="program.t")
        self.assertTrue(result.ok, result.diagnostics)
        self.assertIsInstance(result.program.declarations[0], FieldDecl)
        self.assertIsInstance(result.program.declarations[2], CondenseDecl)
        self.assertIsInstance(result.program.declarations[3], TransitionDecl)

    def test_if_else_is_nested_in_ast(self) -> None:
        result = check_source(
            """\
field Sample
  trace value: Number
condense Choose in Sample
  if value > 0
    emit value
  else
    emit 0
""",
            file="if.t",
        )
        self.assertTrue(result.ok, result.diagnostics)
        condense = result.program.declarations[1]
        self.assertIsInstance(condense, CondenseDecl)
        statement = condense.body[0]
        self.assertIsInstance(statement, IfStmt)
        self.assertEqual(len(statement.then_body), 1)
        self.assertEqual(len(statement.else_body), 1)

    def test_parse_only_does_not_run_semantic_gate(self) -> None:
        parsed = parse_source(
            "field Sample\n  trace value: Unknown\n",
            file="parse-only.t",
        )
        checked = check_source(
            "field Sample\n  trace value: Unknown\n",
            file="checked.t",
        )
        self.assertTrue(parsed.ok)
        self.assertEqual([item.code for item in checked.diagnostics], ["T3011"])

    def test_diagnostics_include_stable_location(self) -> None:
        result = check_source("condense Broken\n  emit value +\n", file="broken.t")
        self.assertFalse(result.ok)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.code, "T3021")
        self.assertEqual(diagnostic.span.file, "broken.t")
        self.assertEqual(diagnostic.span.line, 2)
        self.assertEqual(diagnostic.span.column, 3)


class TCliTests(unittest.TestCase):
    def test_check_valid_file_returns_zero(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        source = GOLDEN_ROOT / "valid" / "05_condense_minimal.t"
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = t_main(["check", str(source)])
        self.assertEqual(status, 0)
        self.assertIn(": ok", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_check_invalid_file_returns_one_and_json(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        source = GOLDEN_ROOT / "invalid" / "12_bad_expression.t"
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = t_main(["check", str(source), "--format", "json"])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["diagnostics"][0]["code"], "T3021")
        self.assertEqual(stderr.getvalue(), "")

    def test_doctor_reports_frontend_and_backend(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = t_main(["doctor"])
        self.assertEqual(status, 0)
        self.assertIn("Frontend Egg: disponível", stdout.getvalue())
        self.assertIn(
            "Backend Python de referência: disponível",
            stdout.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
