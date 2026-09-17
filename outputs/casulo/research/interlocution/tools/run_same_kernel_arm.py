from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from energy_confirmatory.same_kernel import run_static_policy_same_kernel


FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run arm E with the exact native primitive used by arm D")
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_static_policy_same_kernel(
        executable=FULL / "worker/tcap_full_worker.exe",
        tcap=FULL / "artifact/FloodSurrogate.full.tcap",
        dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
        initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
        start=args.start,
        count=args.count,
        output_directory=args.output,
    )
    print(json.dumps({"status": "PASS", **result.to_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
