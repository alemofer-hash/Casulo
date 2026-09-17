from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    root = args.evidence.resolve(strict=True)
    target = root / "integrated-gate.json"
    if target.exists():
        raise SystemExit("TS7 integrated gate already exists")
    hosted = json.loads((root / "holdout-synthesis.json").read_text(encoding="utf-8"))
    native = json.loads((root / "native-conformance/native-conformance.json").read_text(encoding="utf-8"))
    checks = {
        "hosted": hosted["gate"] == "TS7_T_NONTRIVIAL_HOLDOUTS_HOSTED_PASS",
        "native": native["gate"] == "TS7_T_NONTRIVIAL_HOLDOUTS_NATIVE_PASS",
        "three_agents": len(hosted["agents"]) == 3 and len(native["agents"]) == 3,
        "success_events_canonically_bound": hosted["checks"]["success_events_canonically_bound"],
        "no_fake_template_replay": hosted["checks"]["no_fake_template_replay"],
        "no_external_api": hosted["checks"]["no_external_api"],
    }
    value = {
        "schema": "casulo.t85.ts7-integrated/1.0",
        "gate": "TS7_T_NONTRIVIAL_HOLDOUTS_PASS" if all(checks.values()) else "TS7_FAIL",
        "checks": checks,
        "agent_ids": [item["agent_id"] for item in hosted["agents"]],
        "holdout_case_ids": [item["case_id"] for item in hosted["agents"]],
        "hosted_receipts": sum(item["hosted_receipts"] for item in hosted["agents"]),
        "native_cases": len(native["agents"]),
        "human_proof": "NOT_EXECUTED",
    }
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(value, indent=2))
    return 0 if value["gate"].endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
