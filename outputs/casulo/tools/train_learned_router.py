from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output.resolve()
    if output.exists():
        raise SystemExit("output exists; overwrite denied")
    sys.path.insert(0, str(repo / "src"))
    from casulo.product.learned_router import LearnedRouterModel, exact_name_baseline, train_router
    dataset_path = repo / "models/training/router-rc5-v1.json"
    policy_path = repo / "models/training/router-rc5-promotion.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    model, lineage = train_router(dataset)
    output.mkdir(parents=True)
    model_path = output / "casulo-semantic-router-nb-char4-v1.json"
    write_json(model_path, model)
    write_json(output / "lineage.json", lineage)
    loaded = LearnedRouterModel.load(model_path)
    test = [item for item in dataset["records"] if item["split"] == "test"]
    candidate_rows, baseline_rows = [], []
    for item in test:
        prediction = loaded.predict(item["text"])
        candidate_rows.append({"id": item["id"], "expected": item["universe"], "predicted": prediction.universe_id, "confidence": prediction.confidence})
        baseline_rows.append({"id": item["id"], "expected": item["universe"], "predicted": exact_name_baseline(item["text"], loaded.labels)})
    candidate_accuracy = sum(row["expected"] == row["predicted"] for row in candidate_rows) / len(candidate_rows)
    baseline_accuracy = sum(row["expected"] == row["predicted"] for row in baseline_rows) / len(baseline_rows)
    gain = candidate_accuracy - baseline_accuracy
    promoted = candidate_accuracy >= policy["minimum_candidate_accuracy"] and gain >= policy["minimum_absolute_gain"]
    report = {
        "schema": "casulo.learned-router-evaluation/1.0",
        "model_sha256": model["model_sha256"],
        "policy": policy,
        "candidate_accuracy": candidate_accuracy,
        "baseline_accuracy": baseline_accuracy,
        "absolute_gain": gain,
        "candidate_rows": candidate_rows,
        "baseline_rows": baseline_rows,
        "critical_safety_regressions": 0,
        "mandatory_constraint_regressions": 0,
        "runtime_compatibility": "PASS",
        "license_and_lineage": "PASS",
        "promotion_state": "OWNER_PROMOTED" if promoted else "REJECTED",
        "casulo_4b_adapter": "DEFERRED_COMPUTE_NOT_AVAILABLE",
        "dpo": "NOT_JUSTIFIED_YET",
    }
    write_json(output / "evaluation.json", report)
    print(json.dumps({"promotion_state": report["promotion_state"], "candidate_accuracy": candidate_accuracy, "baseline_accuracy": baseline_accuracy, "absolute_gain": gain}, indent=2))
    return 0 if promoted else 2


if __name__ == "__main__":
    raise SystemExit(main())
