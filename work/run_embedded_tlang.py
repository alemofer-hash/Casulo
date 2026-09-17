from __future__ import annotations

import argparse
import importlib.abc
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

from PyInstaller.archive.readers import CArchiveReader


class EmbeddedPyzImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, executable: Path) -> None:
        self.executable = executable
        self.archive = CArchiveReader(str(executable)).open_embedded_archive("PYZ.pyz")
        self.names = set(self.archive.toc)

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname not in self.names:
            return None
        is_package = any(name.startswith(fullname + ".") for name in self.names)
        return importlib.util.spec_from_loader(fullname, self, is_package=is_package)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
        return None

    def exec_module(self, module: Any) -> None:
        code = self.archive.extract(module.__name__, raw=False)
        if code is None:
            raise ImportError(f"Unable to extract embedded module {module.__name__}")
        module.__file__ = f"{self.executable}!PYZ.pyz/{module.__name__.replace('.', '/')}.pyc"
        if module.__spec__ is not None and module.__spec__.submodule_search_locations is not None:
            module.__path__ = [str(self.executable) + "!PYZ.pyz"]
        exec(code, module.__dict__)


PROGRAM = """\
module casulo.bench

field HydroCell
  trace precipitation: Number
  trace evapotranspiration: Number
  trace surface_flow: Number
  trace base_flow: Number

condense WaterBalance in HydroCell
  judge precipitation >= 0
  let storage_change = precipitation - evapotranspiration - surface_flow - base_flow
  stabilize storage_change
  emit storage_change
"""


def percentile(values: list[int], p: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * p))
    return ordered[index] / 1_000.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--iterations", type=int, default=100_000)
    args = parser.parse_args()

    sys.meta_path.insert(0, EmbeddedPyzImporter(args.executable))

    from tlang.lowering.python_emitter import PythonLowerer
    from tlang.parser.api import parse_source
    from tlang.runner import compile_program_to_namespace, run_program

    parse_start = time.perf_counter_ns()
    program = parse_source(PROGRAM, file="casulo_bench.t")
    parse_ns = time.perf_counter_ns() - parse_start

    lower_start = time.perf_counter_ns()
    generated = PythonLowerer().lower_program(program)
    lower_ns = time.perf_counter_ns() - lower_start

    compile_start = time.perf_counter_ns()
    namespace = compile_program_to_namespace(program)
    compile_ns = time.perf_counter_ns() - compile_start

    field = namespace["HydroCell"]
    fn = namespace["condense_water_balance"]
    ctx = field(
        precipitation=100.0,
        evapotranspiration=4.0,
        surface_flow=21.0,
        base_flow=5.0,
    )

    assert fn(ctx) == 70.0
    assert run_program(
        program,
        entry="WaterBalance",
        context={
            "precipitation": 100.0,
            "evapotranspiration": 4.0,
            "surface_flow": 21.0,
            "base_flow": 5.0,
        },
    ) == 70.0

    direct_samples: list[int] = []
    for _ in range(args.iterations):
        start = time.perf_counter_ns()
        fn(ctx)
        direct_samples.append(time.perf_counter_ns() - start)

    full_samples: list[int] = []
    full_iterations = min(250, max(10, args.iterations // 100))
    context = {
        "precipitation": 100.0,
        "evapotranspiration": 4.0,
        "surface_flow": 21.0,
        "base_flow": 5.0,
    }
    for _ in range(full_iterations):
        start = time.perf_counter_ns()
        run_program(program, entry="WaterBalance", context=context)
        full_samples.append(time.perf_counter_ns() - start)

    report = {
        "python": sys.version,
        "program_lines": len(PROGRAM.splitlines()),
        "generated_python_lines": len(generated.splitlines()),
        "parse_ms": parse_ns / 1_000_000,
        "lower_ms": lower_ns / 1_000_000,
        "compile_with_semantic_gates_ms": compile_ns / 1_000_000,
        "direct_generated_function_us": {
            "p50": percentile(direct_samples, 0.50),
            "p95": percentile(direct_samples, 0.95),
            "iterations": len(direct_samples),
        },
        "full_parse_tree_to_run_us": {
            "p50": percentile(full_samples, 0.50),
            "p95": percentile(full_samples, 0.95),
            "iterations": len(full_samples),
        },
        "generated_python": generated,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
