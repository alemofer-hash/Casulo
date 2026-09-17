from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo.t import check_file, check_source  # noqa: E402
from casulo.t.ast import LearnDecl  # noqa: E402
from casulo.t.training import (  # noqa: E402
    TrainingSpecError,
    build_training_artifact,
    parse_training_file,
    parse_training_spec,
)


EXAMPLE = ROOT / "examples" / "t" / "flood_surrogate_training.t"


class TLearnGeneralPipelineTests(unittest.TestCase):
    def test_learn_crosses_formal_ast_semantics_ir_and_graph(self) -> None:
        checked = check_file(EXAMPLE)

        self.assertTrue(checked.ok, checked.diagnostics)
        declaration = checked.program.declarations[0]
        self.assertIsInstance(declaration, LearnDecl)
        self.assertEqual(declaration.name, "FloodSurrogate")
        self.assertEqual(len(declaration.properties), 12)

        contract = checked.analysis.learn_contracts["FloodSurrogate"]
        self.assertEqual(contract.protocol, "casulo-learn-contract/0.2")
        self.assertEqual(contract.input_shape, ("batch", 8))
        self.assertEqual(contract.hidden_shape, ("batch", 8))
        self.assertEqual(contract.output_shape, ("batch", 1))
        self.assertEqual(
            contract.permissions,
            ("cpu.compute", "memory.workspace"),
        )
        self.assertIn("write:model_parameters", contract.effects)

        self.assertEqual(checked.ir.version, "crisalida-ir/0.2")
        operation = checked.ir.operations[0]
        self.assertEqual(operation.kind, "learn")
        self.assertEqual(
            [item.op for item in operation.instructions],
            [
                "learn.read",
                "learn.forward",
                "learn.loss",
                "learn.backward",
                "learn.optimize",
                "learn.stop",
            ],
        )

        self.assertEqual(checked.graph.version, "metamorfose-graph/0.2")
        graph = checked.graph.operations[0]
        self.assertFalse(graph.cacheable)
        self.assertEqual(graph.permissions, contract.permissions)
        self.assertTrue(any(node.kind == "learn.optimize" for node in graph.nodes))
        self.assertTrue(
            any(
                edge.source.endswith("/input/target") and edge.name == "target"
                for edge in graph.edges
            )
        )

    def test_general_and_legacy_paths_share_the_same_contract(self) -> None:
        checked = check_file(EXAMPLE)
        general = checked.analysis.learn_contracts["FloodSurrogate"]
        legacy = parse_training_file(EXAMPLE)

        for name in (
            "module",
            "name",
            "input_features",
            "hidden_features",
            "output_features",
            "activation",
            "loss",
            "optimizer",
            "learning_rate",
            "epochs",
            "precision",
            "batch",
            "seed",
            "target_loss",
        ):
            with self.subTest(property=name):
                self.assertEqual(getattr(general, name), getattr(legacy, name))

    def test_invalid_learn_is_rejected_before_lowering(self) -> None:
        source = EXAMPLE.read_text(encoding="utf-8").replace(
            "  optimizer sgd\n",
            "  optimizer adam\n",
        )
        checked = check_source(source, file="invalid-learn.t")

        self.assertFalse(checked.ok)
        self.assertEqual([item.code for item in checked.diagnostics], ["T3040"])
        self.assertIn("optimizer sgd", checked.diagnostics[0].message)
        self.assertIsNone(checked.ir)
        self.assertIsNone(checked.graph)

    def test_duplicate_property_is_rejected_without_silent_override(self) -> None:
        source = EXAMPLE.read_text(encoding="utf-8").replace(
            "  epochs 400\n",
            "  epochs 400\n  epochs 401\n",
        )
        checked = check_source(source, file="duplicate-learn.t")

        self.assertFalse(checked.ok)
        self.assertEqual([item.code for item in checked.diagnostics], ["T3041"])
        self.assertIsNone(checked.ir)

    def test_old_language_program_keeps_0_1_protocols(self) -> None:
        checked = check_file(ROOT / "examples" / "t" / "balanco_hidrico.t")

        self.assertTrue(checked.ok, checked.diagnostics)
        self.assertEqual(checked.ir.version, "crisalida-ir/0.1")
        self.assertEqual(checked.graph.version, "metamorfose-graph/0.1")

    def test_legacy_codegen_is_gated_by_general_pipeline(self) -> None:
        source = EXAMPLE.read_text(encoding="utf-8").replace(
            "  input_features 8\n",
            "    input_features 8\n",
        )
        # O parser legado continua disponível para compatibilidade.
        self.assertEqual(parse_training_spec(source).input_features, 8)

        with tempfile.TemporaryDirectory() as temporary:
            source_file = Path(temporary) / "training.t"
            source_file.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(TrainingSpecError, "pipeline geral T"):
                build_training_artifact(
                    source_file,
                    Path(temporary) / "artifact",
                )


if __name__ == "__main__":
    unittest.main()
