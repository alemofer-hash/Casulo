from __future__ import annotations

import argparse
import json
from pathlib import Path

from casulo.livelab.ablations import (
    PREREGISTERED_ABLATION_PLAN,
    profiling_record,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT / "evidence/casulo-os-rp01/g5/ablation-preregistration/plan.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the G5 ablation plan without running a benchmark."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    plan = PREREGISTERED_ABLATION_PLAN
    document = {
        "schema": "casulo-livelab-ablation-preregistration/1.0",
        "status": "BLOCKED_HARDWARE_TELEMETRY",
        "plan_sha256": plan.sha256,
        "plan": plan.to_dict(),
        "profiling": dict(
            profiling_record(
                {},
                status="unavailable",
                reason="Linux perf/cgroup campaign and trusted advancing thermal telemetry are absent on this host",
            )
        ),
        "performance_measured": False,
        "energy": {"status": "unavailable", "joules": None},
        "workload_invocations": 0,
        "claim": None,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
