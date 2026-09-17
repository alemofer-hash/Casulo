from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from casulo.compression.casv_motion_campaign import run_motion_holdout_campaign


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREREGISTRATION = Path(
    r"C:\CasuloLab\campaigns\2026-09-11-casv-motion-v07-preregister-attempt1"
) / "frozen-protocol.json"
DEFAULT_OUTPUT = Path(
    r"C:\CasuloLab\campaigns\2026-09-11-casv-motion-v07-natural-holdouts-attempt1"
)
DEFAULT_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_motion.t"
DEFAULT_MUTATION = (
    ROOT / "examples" / "t-v2" / "compression_casv_motion_force_no_motion.t"
)
DEFAULT_RUNTIME = (
    ROOT
    / "t-runtime"
    / "target"
    / "release"
    / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Executa os holdouts naturais pre-registrados do CASV/0.7."
    )
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--force-no-motion", type=Path, default=DEFAULT_MUTATION)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_motion_holdout_campaign(
        args.preregistration,
        args.output,
        default_policy=args.policy,
        force_no_motion_policy=args.force_no_motion,
        runtime=args.runtime,
    )
    summary = {
        "status": result["status"],
        "engineering_status": result["engineering_status"],
        "competitive_status": result["competitive_status"],
        "ratios": result["ratios"],
        "material_wins": result["material_wins"],
        "geometric_mean_ratio": result["geometric_mean_ratio"],
        "maximum_ratio": result["maximum_ratio"],
        "output": result["output"],
        "campaign_manifest_sha256": result["campaign_manifest_sha256"],
        "campaign_sha256sums_sha256": result["campaign_sha256sums_sha256"],
        "campaign_manifest_entries": result["campaign_manifest_entries"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
