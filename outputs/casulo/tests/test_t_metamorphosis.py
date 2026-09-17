from __future__ import annotations

import io
import json
import os
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

from casulo.t import ArtifactBuilder, check_file
from casulo.t.artifact import GRAPH_FILE, MANIFEST_FILE
from casulo.t.benchmark import benchmark_artifact
from casulo.t.cli import main as t_main
from casulo.t.runner import load_artifact, run_artifact


CANONICAL_SOURCE = ROOT / "examples" / "t" / "balanco_hidrico.t"
FIRST = {
    "precipitation": 100,
    "evapotranspiration": 10,
    "surface_flow": 20,
    "base_flow": 5,
}
SECOND = {
    "precipitation": 130,
    "evapotranspiration": 12,
    "surface_flow": 25,
    "base_flow": 8,
}


class TMetamorfoseGraphTests(unittest.TestCase):
    def test_canonical_graph_matches_golden_text(self) -> None:
        expected = (
            ROOT / "conformance" / "graph" / "balanco_hidrico.graph"
        ).read_text(encoding="utf-8")
        actual = check_file(CANONICAL_SOURCE).graph.render_text()
        self.assertEqual(actual.strip(), expected.strip())

    def test_canonical_graph_has_def_use_edges_and_effects(self) -> None:
        checked = check_file(CANONICAL_SOURCE)
        graph = checked.graph.operations[0]
        self.assertTrue(graph.deterministic)
        self.assertTrue(graph.cacheable)
        self.assertEqual(graph.estimated_cost, 8)
        self.assertEqual(graph.effects, ("guard", "evidence", "manifest"))
        let_node = next(node for node in graph.nodes if node.kind == "let")
        emit_node = next(node for node in graph.nodes if node.kind == "emit")
        self.assertEqual(let_node.defines, ("storage_change",))
        self.assertEqual(
            set(let_node.uses),
            {
                "precipitation",
                "evapotranspiration",
                "surface_flow",
                "base_flow",
            },
        )
        self.assertTrue(
            any(
                edge.source == let_node.id
                and edge.target == emit_node.id
                and edge.name == "storage_change"
                for edge in graph.edges
            )
        )

    def test_branch_graph_contains_control_edges(self) -> None:
        source = (
            ROOT
            / "conformance"
            / "golden"
            / "valid"
            / "14_all_paths_emit.t"
        )
        graph = check_file(source).graph.operations[0]
        branch = next(node for node in graph.nodes if node.kind == "if")
        controlled = {
            edge.target
            for edge in graph.edges
            if edge.kind == "control" and edge.source == branch.id
        }
        branch_emits = {
            node.id
            for node in graph.nodes
            if node.kind == "emit"
        }
        self.assertEqual(controlled, branch_emits)

    def test_inspect_graph_supports_text_and_json(self) -> None:
        text_stdout = io.StringIO()
        with redirect_stdout(text_stdout):
            text_status = t_main(
                ["inspect", str(CANONICAL_SOURCE), "--graph"]
            )
        json_stdout = io.StringIO()
        with redirect_stdout(json_stdout):
            json_status = t_main(
                [
                    "inspect",
                    str(CANONICAL_SOURCE),
                    "--graph",
                    "--format",
                    "json",
                ]
            )
        payload = json.loads(json_stdout.getvalue())
        self.assertEqual(text_status, 0)
        self.assertEqual(json_status, 0)
        self.assertTrue(
            text_stdout.getvalue().startswith("metamorfose-graph/0.1")
        )
        self.assertEqual(
            payload["graph"]["operations"][0]["name"],
            "WaterBalance",
        )

    def test_artifact_carries_verified_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            manifest = json.loads(
                (built.output_dir / MANIFEST_FILE).read_text(encoding="utf-8")
            )
            graph = json.loads(
                (built.output_dir / GRAPH_FILE).read_text(encoding="utf-8")
            )
        self.assertEqual(manifest["graph"]["version"], "metamorfose-graph/0.1")
        self.assertEqual(graph["operations"][0]["estimated_cost"], 8)


class TMetamorfoseBatchAndCacheTests(unittest.TestCase):
    def test_structural_key_is_order_independent_and_type_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            loaded = load_artifact(built.output_dir)
            structural_key = loaded.namespace["_structural_key"]
        first = structural_key({"a": 1, "b": [True, None]})
        reordered = structural_key({"b": [True, None], "a": 1})
        self.assertEqual(first, reordered)
        self.assertNotEqual(structural_key({"value": 1}), structural_key({"value": 1.0}))
        self.assertNotEqual(structural_key({"value": True}), structural_key({"value": 1}))
        self.assertNotEqual(structural_key({"value": 0.0}), structural_key({"value": -0.0}))

    def test_fingerprint_collision_is_resolved_by_structural_equality(self) -> None:
        first = {**FIRST, "collision": -1}
        second = {**FIRST, "collision": -2}
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            loaded = load_artifact(built.output_dir)
            structural_key = loaded.namespace["_structural_key"]
            fingerprint = loaded.namespace["_cache_fingerprint"]
            first_key = structural_key(first)
            second_key = structural_key(second)
            self.assertNotEqual(first_key, second_key)
            self.assertEqual(fingerprint(first_key), fingerprint(second_key))
            result = loaded.namespace["execute_batch"](
                "WaterBalance",
                [first, second],
            )
        self.assertEqual(result["cache"]["misses"], 2)
        self.assertEqual(result["cache"]["hits"], 0)
        self.assertEqual(
            [item["input"]["collision"] for item in result["items"]],
            [-1, -2],
        )
        self.assertTrue(result["cache"]["collision_verified"])

    def test_literal_words_inside_text_are_preserved(self) -> None:
        source_text = """\
condense PreserveWord
  emit "true false null"
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "words.t"
            source.write_text(source_text, encoding="utf-8")
            built = ArtifactBuilder().build(source, root / "artifact")
            result = run_artifact(built.output_dir, {}).payload
        self.assertEqual(result["result"], "true false null")
        self.assertIsNone(
            built.manifest["operations"][0]["optimization"][
                "buffer_protocol"
            ]
        )

    def test_scalar_cache_is_per_operation_and_reports_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            loaded = load_artifact(built.output_dir)
            execute = loaded.namespace["execute"]
            first = execute("WaterBalance", FIRST)
            second = execute("WaterBalance", FIRST)
            stats = loaded.namespace["cache_stats"]()
        self.assertFalse(first["cache"]["hit"])
        self.assertTrue(second["cache"]["hit"])
        self.assertEqual(stats["WaterBalance"]["entries"], 1)
        self.assertEqual(first["result"], second["result"])

    def test_fused_batch_deduplicates_and_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            result = run_artifact(
                built.output_dir,
                [FIRST, FIRST, SECOND],
                batch=True,
            ).payload
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["cache"]["hits"], 1)
        self.assertEqual(result["cache"]["misses"], 2)
        self.assertEqual(
            [item["result"] for item in result["items"]],
            [65, 65, 85],
        )
        self.assertFalse(result["items"][0]["cache"]["hit"])
        self.assertTrue(result["items"][1]["cache"]["hit"])
        self.assertEqual(result["cache"]["scope"], "batch")
        self.assertEqual(
            result["cache"]["key_protocol"],
            "casulo-structural-key/0.1",
        )
        self.assertEqual(
            result["cache"]["buffer_protocol"],
            "casulo-typed-buffer/0.1",
        )
        self.assertEqual(result["cache"]["representation"], "columnar-typed")
        self.assertEqual(
            result["cache"]["hot_path"]["column_type"],
            "int64",
        )

    def test_float_buffer_matches_object_reference_and_reports_avoided_work(
        self,
    ) -> None:
        first = {name: float(value) for name, value in FIRST.items()}
        second = {name: float(value) for name, value in SECOND.items()}
        payloads = [first, first, second]
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            execute_batch = load_artifact(
                built.output_dir
            ).namespace["execute_batch"]
            typed = execute_batch("WaterBalance", payloads)
            reference = execute_batch(
                "WaterBalance",
                payloads,
                use_buffer=False,
            )
        typed_semantic = [
            {key: value for key, value in item.items() if key != "cache"}
            for item in typed["items"]
        ]
        reference_semantic = [
            {key: value for key, value in item.items() if key != "cache"}
            for item in reference["items"]
        ]
        self.assertEqual(typed_semantic, reference_semantic)
        metrics = typed["cache"]["hot_path"]
        self.assertEqual(metrics["column_type"], "float64")
        self.assertGreater(metrics["column_bytes"], 0)
        self.assertGreater(
            metrics["reference_intermediate_mappings_avoided"],
            0,
        )
        self.assertGreater(
            metrics["reference_field_writes_avoided"],
            0,
        )

    def test_mixed_numeric_kinds_fall_back_to_object_kernel(self) -> None:
        mixed = {**FIRST, "precipitation": 100.0}
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            result = load_artifact(
                built.output_dir
            ).namespace["execute_batch"](
                "WaterBalance",
                [mixed, mixed],
            )
        self.assertIsNone(result["cache"]["buffer_protocol"])
        self.assertEqual(result["cache"]["representation"], "objects")
        self.assertEqual(
            [item["result"] for item in result["items"]],
            [65.0, 65.0],
        )

    def test_batch_cache_lifetime_is_one_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            loaded = load_artifact(built.output_dir)
            execute_batch = loaded.namespace["execute_batch"]
            first = execute_batch("WaterBalance", [FIRST, FIRST])
            second = execute_batch("WaterBalance", [FIRST, FIRST])
            stats = loaded.namespace["cache_stats"]()
        self.assertEqual(first["cache"]["misses"], 1)
        self.assertEqual(second["cache"]["misses"], 1)
        self.assertEqual(first["cache"]["hits"], 1)
        self.assertEqual(second["cache"]["hits"], 1)
        self.assertEqual(stats["WaterBalance"]["entries"], 0)

    def test_duplicate_envelopes_do_not_share_mutable_json_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            loaded = load_artifact(built.output_dir)
            result = loaded.namespace["execute_batch"](
                "WaterBalance",
                [FIRST, FIRST],
            )
        first, second = result["items"]
        first["input"]["precipitation"] = -1
        first["evidence"]["judgements"].append({"mutated": True})
        self.assertEqual(second["input"]["precipitation"], FIRST["precipitation"])
        self.assertNotIn(
            {"mutated": True},
            second["evidence"]["judgements"],
        )

    def test_batch_without_cache_is_semantically_equal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            result = run_artifact(
                built.output_dir,
                [FIRST, SECOND],
                use_cache=False,
            ).payload
        self.assertFalse(result["cache"]["enabled"])
        self.assertEqual(
            [item["result"] for item in result["items"]],
            [65, 85],
        )


class TMetamorfoseBenchmarkTests(unittest.TestCase):
    def test_benchmark_proves_equivalence_without_claiming_joules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            built = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                Path(temporary) / "artifact",
            )
            report = benchmark_artifact(
                built.output_dir,
                [FIRST, SECOND],
                samples=2,
                iterations=2,
            )
        self.assertEqual(report.batch_size, 2)
        self.assertEqual(len(report.equivalence_sha256), 64)
        self.assertGreater(report.scalar.median_wall_ns, 0)
        self.assertGreater(report.batch.median_wall_ns, 0)
        self.assertIsNone(
            report.energy_proxy["electrical_energy_joules"]
        )
        self.assertIn("não é medição elétrica", report.energy_proxy["warning"])

    def test_benchmark_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = ArtifactBuilder().build(
                CANONICAL_SOURCE,
                root / "artifact",
            ).output_dir
            input_file = root / "input.json"
            report_file = root / "report.json"
            input_file.write_text(json.dumps([FIRST, SECOND]), encoding="utf-8")
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {"CASULO_ENABLE_LEGACY_RESEARCH": "1"},
            ), redirect_stdout(stdout):
                status = t_main(
                    [
                        "benchmark",
                        str(artifact),
                        "--input",
                        str(input_file),
                        "--samples",
                        "1",
                        "--iterations",
                        "1",
                        "--output",
                        str(report_file),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            saved_payload = json.loads(
                report_file.read_text(encoding="utf-8")
            )
        self.assertEqual(status, 0)
        self.assertEqual(payload["version"], "metamorfose-benchmark/0.1")
        self.assertEqual(
            saved_payload["artifact_id"],
            payload["artifact_id"],
        )


if __name__ == "__main__":
    unittest.main()
