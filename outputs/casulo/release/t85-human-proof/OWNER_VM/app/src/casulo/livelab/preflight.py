from __future__ import annotations

import argparse
import json
from pathlib import Path

from .campaign import CampaignSpec, evaluate_preflight, execute_paired_campaign
from .capabilities import probe_capabilities
from .reporting import write_campaign_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed LiveLab campaign preflight; never starts a benchmark.")
    parser.add_argument("--output", type=Path, required=True, help="Directory for JSON, CSV and Markdown evidence")
    parser.add_argument("--campaign-id", default="livelab-preflight")
    args = parser.parse_args(argv)

    capabilities = probe_capabilities()
    preflight = evaluate_preflight(capabilities, thermal=None, power=None, isolation=None)
    spec = CampaignSpec(args.campaign_id, "pytorch-inductor", "casulo-t", repetitions=3)

    def forbidden_workload() -> None:
        raise AssertionError("preflight must not execute workloads")

    class ForbiddenExecutor:
        def safety_check(self):
            raise AssertionError("preflight must not call an executor")

        def run_trial(self, label, workload, *, maximum_seconds):
            raise AssertionError("preflight must not run a trial")

    result = execute_paired_campaign(
        spec,
        preflight,
        {spec.baseline_label: forbidden_workload, spec.candidate_label: forbidden_workload},
        ForbiddenExecutor(),
    )
    paths = write_campaign_reports(result, args.output)
    print(json.dumps({
        "status": result.status.value,
        "workload_started": result.workload_started,
        "reports": {key: str(value) for key, value in paths.items()},
    }, sort_keys=True))
    return 0 if result.preflight.ready else 2


__all__ = ["main"]
