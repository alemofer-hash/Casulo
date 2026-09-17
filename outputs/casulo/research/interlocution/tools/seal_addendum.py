from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
C = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"


def fh(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def write(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    protocol = {
        "schema": "casulo.interlocution-frozen-protocol/1.0",
        "frozen_before_definitive_results": True,
        "confirmed_intent_sha256": json.loads((C / "confirmed_intent.json").read_text(encoding="utf-8"))["intent_sha256"],
        "requirement_graph_sha256": json.loads((C / "requirement_graph.json").read_text(encoding="utf-8"))["graph_sha256"],
        "training_authority_plan_sha256": json.loads((C / "training_authority_plan.json").read_text(encoding="utf-8"))["plan_sha256"],
        "training_tcap_hash": json.loads((C / "tcap-binding.json").read_text(encoding="utf-8"))["tcap_hash"],
        "causal_mutation_summary_with_frozen_protocol_sha256": fh(C / "causal_mutations-attempt2/summary.json"),
        "ti10_protocol_sha256": fh(C / "baselines/ti10-v2/frozen-protocol.json"),
        "holdout_set_sha256": fh(C / "holdouts/v1/holdout-specs-frozen-before-results.json"),
        "absolute_tolerance": 1e-9,
        "bootstrap": {"resamples": 20000, "seed_wall": 2026081901},
        "energy": "NOT_MEASURED",
        "publication": "PROHIBITED",
    }
    protocol["protocol_sha256"] = canonical(protocol)
    write(C / "frozen_protocol.json", protocol)
    counters = {
        "schema": "casulo.interlocution-counter-summary/1.0",
        "scope": "principal scientific artifacts; failed attempts and regression tests excluded",
        "complete_trainings": 79,
        "categories": {"full_worker_smoke": 1, "flood_equivalence_candidate_and_oracle": 6, "ti10_warmups_references_and_samples": 63, "holdout_candidates_and_oracles": 8, "live_demo_v2": 1},
        "governed_work_receipts": 39,
        "canary_eight_record_trainings": 0,
        "normalization_uses_completed_receipts": True,
    }
    counters["counters_sha256"] = canonical(counters)
    write(C / "counters/summary.json", counters)
    expanded = json.loads((C / "baselines/ti10-v2/analysis-expanded.json").read_text(encoding="utf-8"))
    ablations = {
        "schema": "casulo.interlocution-ablation-summary/1.0",
        "arms": {"A": "baseline transparent without T", "B": "post-hoc T ignored", "C": "T architect without final T judgment", "D": "T architect, auditor and consumed judge"},
        "results": expanded["ablations"],
        "D_over_A_end_to_end_wall_ratio": expanded["end_to_end"]["median_D_over_A_wall_ratio"],
        "energy": "NOT_MEASURED",
        "no_claim_that_D_must_win_every_baseline": True,
    }
    ablations["ablations_sha256"] = canonical(ablations)
    write(C / "ablations/summary.json", ablations)
    added = []
    for relative in ("frozen_protocol.json", "counters/summary.json", "ablations/summary.json"):
        path = C / relative
        added.append({"path": relative, "bytes": path.stat().st_size, "sha256": fh(path)})
    addendum = {
        "schema": "casulo.interlocution-manifest-addendum/1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "supersedes_nothing": True,
        "extends_manifest_file_sha256": fh(C / "MANIFEST.json"),
        "extends_manifest_internal_sha256": json.loads((C / "MANIFEST.json").read_text(encoding="utf-8"))["manifest_sha256"],
        "files": added,
    }
    addendum["addendum_sha256"] = canonical(addendum)
    write(C / "MANIFEST.addendum.json", addendum)
    (C / "SHA256SUMS.addendum").write_text("".join(f"{item['sha256']}  {item['path']}\n" for item in added), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "addendum_sha256": addendum["addendum_sha256"], "sha256sums_addendum_sha256": fh(C / "SHA256SUMS.addendum")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
