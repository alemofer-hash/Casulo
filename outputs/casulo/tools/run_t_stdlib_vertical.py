from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from casulo.t.stdlib import ProductiveTStandardLibrary, STAGES  # noqa: E402
from casulo.t.v2_tcap import TcapV2Builder  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the sovereign T standard-library vertical slice")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents or output.exists():
        raise SystemExit("output must be a new directory inside the repository")
    output.mkdir(parents=True)
    boundaries = json.loads((ROOT / "docs/product/TS_FOREIGN_BOUNDARIES.json").read_text(encoding="utf-8"))["boundaries"]
    sources = tuple(sorted((ROOT / "stdlib/t-v2").glob("*.t")))
    built = TcapV2Builder().build(
        sources, output / "casulo-stdlib.tcap",
        entry_module="t.core.result", entry_function="decide",
        tests={"properties": ["decision_chain_is_causal", "effects_are_granted", "project_bleed_denied", "hard_unknown_blocks"]},
        foreign_boundaries=boundaries,
    )
    runtime = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
    run = ProductiveTStandardLibrary(runtime).run(built.directory, output / "inputs")
    report = {
        **run.to_dict(),
        "gate": "TS4_T_STDLIB_VERTICAL_SLICE",
        "runtime": "t-runtime/rust-2.0",
        "module_count": len(sources),
        "expected_modules": [stage.module for stage in STAGES],
        "receipt_chain": [stage["receipt"]["receipt_hash"] for stage in run.stages],
        "effects_requested": [effect for stage in run.stages for effect in stage["observable"]["requested_effects"]],
        "real_effects_executed": [],
        "foreign_decisions": [],
        "scientific_benchmark": "NOT_STARTED",
    }
    target = output / "vertical-slice.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": run.status, "final_value": run.final_value, "modules": len(run.stages), "receipts": len(report["receipt_chain"])}, indent=2))
    return 0 if run.status == "PASS" and run.final_value == "SEALED" and len(run.stages) == 13 else 1


if __name__ == "__main__":
    raise SystemExit(main())
