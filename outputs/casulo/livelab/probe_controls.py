from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from casulo.livelab.controls import PerfCollector, SchedExtController, UClampController


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only LiveLab Linux control probe.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    reports = [UClampController().probe(), PerfCollector().probe(), SchedExtController().probe()]
    payload = {
        "schema": "casulo-livelab-control-probe/1",
        "mutation_performed": False,
        "controls": [
            {**asdict(report), "status": report.status.value, "evidence": dict(report.evidence)}
            for report in reports
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "mutation_performed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
