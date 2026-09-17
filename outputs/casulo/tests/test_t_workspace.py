from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from casulo.t.runner import run_artifact
from casulo.t.workspace import (
    WORKSPACE_BUILD_MANIFEST,
    WORKSPACE_LOCK,
    WorkspaceError,
    build_workspace,
    check_workspace,
    init_workspace,
    resolve_entry_source,
    test_workspace as run_workspace_tests,
)


class WorkspaceTests(unittest.TestCase):
    def test_init_check_build_run_and_cache_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = init_workspace(
                Path(temporary) / "traffic-lab",
                name="traffic-lab",
            )
            workspace = check_workspace(root)
            first = build_workspace(root)
            second = build_workspace(root)
            executed = run_artifact(
                first.entry_artifact,
                {},
                operation="Main",
            )
            main_source = root / "src" / "main.t"
            main_source.write_text(
                main_source.read_text(encoding="utf-8").replace(
                    "emit true",
                    "emit false",
                ),
                encoding="utf-8",
            )
            changed = build_workspace(root)

            self.assertEqual(workspace.manifest.name, "traffic-lab")
            self.assertEqual(workspace.manifest.entry, "traffic_lab.main")
            self.assertEqual(workspace.build_order, ("traffic_lab.main",))
            self.assertFalse(first.cache_hit)
            self.assertTrue(second.cache_hit)
            self.assertEqual(first.workspace_id, second.workspace_id)
            self.assertNotEqual(first.workspace_id, changed.workspace_id)
            self.assertTrue((root / WORKSPACE_LOCK).is_file())
            self.assertTrue(
                (first.output_dir / WORKSPACE_BUILD_MANIFEST).is_file()
            )
            self.assertTrue(executed.payload["result"])
            tests = run_workspace_tests(root)
            self.assertEqual(tests["tests_checked"], 1)

    def test_resolves_multifile_graph_in_dependency_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(
                root,
                entry="demo.main",
                sources={
                    "lib.t": (
                        "module demo.lib\n\n"
                        "condense Library\n"
                        "  emit true\n"
                    ),
                    "main.t": (
                        "module demo.main\n"
                        "use demo.lib\n\n"
                        "condense Main\n"
                        "  emit true\n"
                    ),
                },
            )

            workspace = check_workspace(root)
            built = build_workspace(root)
            document = json.loads(
                (built.output_dir / WORKSPACE_BUILD_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                workspace.build_order,
                ("demo.lib", "demo.main"),
            )
            self.assertEqual(
                [item["name"] for item in document["modules"]],
                ["demo.lib", "demo.main"],
            )

    def test_rejects_unresolved_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(
                root,
                entry="demo.main",
                sources={
                    "main.t": (
                        "module demo.main\n"
                        "use missing.library\n\n"
                        "condense Main\n"
                        "  emit true\n"
                    )
                },
            )

            with self.assertRaisesRegex(WorkspaceError, "T4011"):
                check_workspace(root)

    def test_loads_local_library_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            library = base / "hydrology"
            application = base / "application"
            _write_project(
                library,
                entry=None,
                kind="library",
                sources={
                    "water.t": (
                        "module hydro.water\n\n"
                        "condense Water\n"
                        "  emit true\n"
                    )
                },
            )
            _write_project(
                application,
                entry="demo.main",
                dependencies={"hydrology": "../hydrology"},
                sources={
                    "main.t": (
                        "module demo.main\n"
                        "use hydro.water\n\n"
                        "condense Main\n"
                        "  emit true\n"
                    )
                },
            )

            workspace = check_workspace(application)

            self.assertEqual(
                workspace.build_order,
                ("hydro.water", "demo.main"),
            )

    def test_rejects_module_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(
                root,
                entry="demo.a",
                sources={
                    "a.t": (
                        "module demo.a\n"
                        "use demo.b\n\n"
                        "condense A\n"
                        "  emit true\n"
                    ),
                    "b.t": (
                        "module demo.b\n"
                        "use demo.a\n\n"
                        "condense B\n"
                        "  emit true\n"
                    ),
                },
            )

            with self.assertRaisesRegex(WorkspaceError, "T4012"):
                check_workspace(root)

    def test_training_entry_is_discovered_without_running_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(
                root,
                entry="demo.training",
                sources={
                    "training.t": (
                        "module demo.training\n\n"
                        "learn FloodSurrogate\n"
                        "  input_features 8\n"
                        "  hidden_features 8\n"
                        "  output_features 1\n"
                        "  activation relu\n"
                        "  loss mse\n"
                        "  optimizer sgd\n"
                        "  learning_rate 0.018\n"
                        "  epochs 2\n"
                        "  precision float64\n"
                        "  batch full\n"
                        "  seed 260730\n"
                        "  target_loss 10.0\n"
                    )
                },
            )

            entry = resolve_entry_source(root, required_kind="training")
            built = build_workspace(root)

            self.assertEqual(entry.name, "training.t")
            self.assertEqual(built.entry_kind, "training")
            self.assertTrue((built.entry_artifact / "casulo_training.c").is_file())


def _write_project(
    root: Path,
    *,
    entry: str | None,
    sources: dict[str, str],
    kind: str = "application",
    dependencies: dict[str, str] | None = None,
) -> None:
    source_root = root / "src"
    source_root.mkdir(parents=True)
    manifest = (
        "[project]\n"
        'name = "demo"\n'
        'version = "0.1.0"\n'
        f'kind = "{kind}"\n'
        + (f'entry = "{entry}"\n' if entry is not None else "")
        + 'source = "src"\n'
        + 'external_modules = ["casulo.std"]\n'
        + "\n"
        + "[dependencies]\n"
        + "".join(
            f'{name} = {{ path = "{path}" }}\n'
            for name, path in (dependencies or {}).items()
        )
    )
    (root / "casulo.toml").write_text(
        manifest,
        encoding="utf-8",
    )
    for name, source in sources.items():
        (source_root / name).write_text(source, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
