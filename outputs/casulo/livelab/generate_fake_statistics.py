from __future__ import annotations

import argparse
import json
from pathlib import Path

from casulo.livelab.campaign import (
    CampaignPolicy, CampaignSpec, IsolationEvidence, PowerStateEvidence,
    ThermalEvidence, TrialMeasurement, evaluate_preflight,
    execute_paired_campaign, sha256_output,
)
from casulo.livelab.capabilities import Capability, CapabilityStatus
from casulo.livelab.reporting import write_campaign_reports


def _ready():
    required = CampaignPolicy().required_capabilities + ("external_power_meter",)
    capabilities = {
        name: Capability(name, CapabilityStatus.AVAILABLE, True, "synthetic_fixture", "2026-08-07T00:00:00+00:00")
        for name in required
    }
    return evaluate_preflight(
        capabilities,
        thermal=ThermalEvidence("synthetic", (1, 2, 3), (40.0, 40.0, 40.0), False, True),
        power=PowerStateEvidence("synthetic", True, "fixed", "fixed", True),
        isolation=IsolationEvidence(True, (0,), 1, "/synthetic/not-a-real-cgroup", {"synthetic": "true"}),
    )


class SyntheticExecutor:
    def __init__(self):
        self.index = {"baseline": 0, "candidate": 0}

    def safety_check(self):
        return _ready()

    def run_trial(self, label, workload, *, maximum_seconds):
        workload()
        index = self.index[label]
        self.index[label] += 1
        if label == "baseline":
            elapsed, energy, compile_ns = 2_000_000 + index * 10_000, 2.0 + index / 100, 500_000 if index == 0 else 0
        else:
            elapsed, energy, compile_ns = 1_000_000 + index * 10_000, 1.0 + index / 100, 800_000 if index == 0 else 0
        return TrialMeasurement(
            elapsed, energy, 40.0, sha256_output("synthetic-equivalent-output"),
            compile_ns, {"execute": elapsed}, "synthetic-ac-fixed",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic LiveLab statistics evidence.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    spec = CampaignSpec(
        "synthetic-statistics-v1", "baseline", "candidate", 21,
        strict_statistics=True, bootstrap_seed=20260807,
        bootstrap_resamples=10_000, compile_amortization_runs=100,
        require_power_parity=True, evidence_kind="synthetic",
    )
    result = execute_paired_campaign(
        spec, _ready(), {"baseline": lambda: None, "candidate": lambda: None}, SyntheticExecutor(),
    )
    paths = write_campaign_reports(result, args.output)
    print(json.dumps({"synthetic": True, "status": result.status.value, "files": {key: str(value) for key, value in paths.items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
