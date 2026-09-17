from __future__ import annotations

import argparse
import json
from pathlib import Path

from casulo.livelab.capabilities import probe_capabilities


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = probe_capabilities()
    payload = {
        "schema": "casulo-livelab-capabilities/1.0",
        "capabilities": {key: value.to_dict() for key, value in sorted(reports.items())},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
