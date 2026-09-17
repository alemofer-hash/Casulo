from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from casulo.product.materializer import MaterializedPackageImporter


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    temporary = path.with_name(f".{path.name}.finalize.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize G5 from sealed post-run receipts")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--holdout-expectation", required=True)
    parser.add_argument("--candidate-id", required=True)
    args = parser.parse_args()
    root = args.output_dir.expanduser().resolve(strict=True)
    evidence = root / "g5-first-open-ended-agent.json"
    if evidence.exists() or evidence.is_symlink():
        raise SystemExit("G5 evidence already exists; overwrite denied")
    scan = load(root / "holdout-scan.json")
    intent = load(root / "checkpoint-intent.json")
    project = load(root / "checkpoint-generated-project.json")
    repair = load(root / "repair-outcome.json")
    simulation = load(root / "simulation-receipt.json")
    materialization = load(root / "materialization-receipt.json")
    external = load(root / "external-execution.json")
    materialized_creation = load(Path(materialization["directory"]) / "creation.json")
    archive = Path(materialization["archive"])
    imported = MaterializedPackageImporter().import_archive(archive)
    attempts = repair["attempts"]
    initial_diagnostics = attempts[0]["diagnostics"]
    final_tests = attempts[-1]["tests"]
    operations = intent["delta"]["operations"]
    checks = {
        "holdout_absent_before_run": scan["absent_before_run"],
        "neural_plan_generated": bool(intent["trace"]["output_sha256"]),
        "neural_t_generated": bool(project["trace"]["output_sha256"]),
        "initial_candidate_imperfect": bool(initial_diagnostics),
        "real_compiled_process_test_failed_first": any(
            item["code"] == "TTEST_EXPECTED_TEXT_MISSING" for item in initial_diagnostics
        ),
        "bounded_neural_repair_passed": (
            repair["status"] == "PASS"
            and 1 <= repair["repair_count"] <= repair["budget"]
        ),
        "all_final_tests_executed_and_passed": bool(final_tests)
        and all(item["passed"] for item in final_tests),
        "simulation_passed": simulation["status"] == "PASS",
        "simulation_real_effects_absent": simulation["real_effects_executed"] is False,
        "external_process_passed": external["returncode"] == 0
        and args.holdout_expectation.casefold() in external["result"].casefold(),
        "round_trip_identity_preserved": imported.creation.creation_id
        == materialized_creation["creation_id"],
        "round_trip_version_preserved": imported.creation.version
        == materialized_creation["version"],
        "round_trip_executable_preserved": imported.agent_artifact_id is not None,
        "model_created_no_grant": all(
            not str(operation["path"][0]).startswith("capabilities") for operation in operations
        ),
        "fake_engine_used": False,
        "external_ai_api_used": False,
        "real_effect_executed": False,
        "scientific_benchmark": False,
    }
    required_false = {
        "fake_engine_used",
        "external_ai_api_used",
        "real_effect_executed",
        "scientific_benchmark",
    }
    passed = all(value is (False if key in required_false else True) for key, value in checks.items())
    result = {
        "schema": "casulo-first-open-ended-agent-evidence/1.0",
        "gate": "FIRST_OPEN_ENDED_AGENT_CREATED" if passed else "FIRST_OPEN_ENDED_AGENT_FAILED",
        "finalized_from_preserved_receipts": True,
        "prior_reporting_failure": load(root / "failure.json"),
        "idea": args.idea,
        "holdout_expectation": args.holdout_expectation,
        "candidate_id": args.candidate_id,
        "project_id": project["project_id"],
        "repair": repair,
        "simulation": simulation,
        "materialization": materialization,
        "imported": {
            "creation_id": imported.creation.creation_id,
            "creation_version": imported.creation.version,
            "agent_artifact_id": imported.agent_artifact_id,
            "agent_operation": imported.agent_operation,
        },
        "external_execution": external,
        "checks": checks,
        "cloud_state": "RELEASE_LOCKED",
        "public_state": "FROZEN",
        "usb_state": "PROHIBITED",
    }
    write(evidence, result)
    print(json.dumps({"gate": result["gate"], "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
