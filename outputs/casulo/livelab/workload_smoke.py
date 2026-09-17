from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo.livelab.workload_adapters import (  # noqa: E402
    AdapterStatus,
    available_adapters,
    run_smoke_adapter,
)
from casulo.livelab.workloads import WORKLOADS  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded correctness-only LiveLab workload adapter."
    )
    parser.add_argument("adapter", choices=available_adapters())
    parser.add_argument("workload", choices=tuple(WORKLOADS))
    parser.add_argument(
        "--allow-toolchain",
        action="store_true",
        help="Allow bounded compiler invocation. This does not enable timing.",
    )
    arguments = parser.parse_args(argv)
    result = run_smoke_adapter(
        arguments.adapter,
        arguments.workload,
        allow_toolchain=arguments.allow_toolchain,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if result.status is AdapterStatus.PASS:
        return 0
    if result.status is AdapterStatus.UNAVAILABLE:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
