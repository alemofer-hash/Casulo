from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from casulo.t.v2_tcap import TcapV2Build, TcapV2Builder

from .contracts import validate_training_authority_plan


POLICY_SURFACES = (
    "dataset_identity_integrity",
    "initialization_bundle",
    "numerical_precision",
    "loss_function",
    "update_rule",
    "optimizer_state",
    "working_set",
    "stopping",
    "equivalence_acceptance",
)

MODULES = {
    "dataset_identity_integrity": "research.interlocution.dataset",
    "initialization_bundle": "research.interlocution.initialization",
    "numerical_precision": "research.interlocution.precision",
    "loss_function": "research.interlocution.loss",
    "update_rule": "research.interlocution.update",
    "optimizer_state": "research.interlocution.optimizer_state",
    "working_set": "research.interlocution.working_set",
    "stopping": "research.interlocution.stopping",
    "equivalence_acceptance": "research.interlocution.judgment",
}


def _literal(value: Any) -> str:
    return repr(value)


def _header(module: str, policy_hash: str) -> list[str]:
    return [
        "language T/2.0",
        f"module {module}",
        "budget steps 4096",
        "budget deadline_ms 5000",
        "schema version 1",
        f"# training-authority-plan {policy_hash}",
        "",
    ]


def _record(lines: list[str], name: str, members: tuple[tuple[str, str], ...]) -> None:
    lines.append(f"record {name}")
    lines.extend(f"  member {field}: {type_name}" for field, type_name in members)
    lines.append("")


def _function(
    lines: list[str],
    name: str,
    record: str,
    requirements: tuple[tuple[str, str], ...],
    output: Mapping[str, Any],
) -> None:
    lines.append(f"fn {name}(input: {record}) -> Result<Map<Text,Text,32>,Text>")
    lines.append("  cancel if input.cancelled")
    for expression, error in requirements:
        lines.append(f"  requires {expression} else {json.dumps(error)}")
    lines.append(f"  return ok {_literal(dict(output))}")
    lines.append("")


def render_policy_sources(plan: Mapping[str, Any]) -> dict[str, str]:
    validate_training_authority_plan(plan)
    decisions = {item["surface"]: item for item in plan["decisions"]}
    sources: dict[str, str] = {}

    d = decisions["dataset_identity_integrity"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines, "DatasetObservation", (("observed_sha256","Text"),("records","Int"),("input_features","Int"),("cancelled","Bool")))
    _function(lines,"decide","DatasetObservation",((f"input.observed_sha256 == {_literal(d['dataset_sha256'])}","dataset_hash_mismatch"),(f"input.records == {d['records_per_epoch']}","dataset_record_count_mismatch"),(f"input.input_features == {d['input_features']}","dataset_feature_count_mismatch")),{"dataset_sha256":d["dataset_sha256"],"records":str(d["records_per_epoch"]),"input_features":str(d["input_features"])})
    sources[d["surface"]] = "\n".join(lines)

    d = decisions["initialization_bundle"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines,"InitializationObservation",(("observed_sha256","Text"),("cases_unique","Bool"),("nonces_unique","Bool"),("cancelled","Bool")))
    _function(lines,"decide","InitializationObservation",((f"input.observed_sha256 == {_literal(d['bundle_sha256'])}","initialization_hash_mismatch"),("input.cases_unique","initialization_cases_not_unique"),("input.nonces_unique","initialization_nonces_not_unique")),{"bundle_sha256":d["bundle_sha256"],"initialization_state_policy":d["state_policy"]})
    sources[d["surface"]] = "\n".join(lines)

    d = decisions["numerical_precision"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines,"PrecisionCapabilities",(("float64_supported","Bool"),("cancelled","Bool")))
    _function(lines,"decide","PrecisionCapabilities",(("input.float64_supported","float64_primitive_unavailable"),),{"dtype":d["dtype"]})
    sources[d["surface"]] = "\n".join(lines)

    d = decisions["loss_function"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines,"LossCapabilities",(("mse_supported","Bool"),("cancelled","Bool")))
    _function(lines,"decide","LossCapabilities",(("input.mse_supported","mse_primitive_unavailable"),),{"loss":d["loss"]})
    sources[d["surface"]] = "\n".join(lines)

    d = decisions["update_rule"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines,"UpdateCapabilities",(("sgd_supported","Bool"),("cancelled","Bool")))
    _function(lines,"decide","UpdateCapabilities",(("input.sgd_supported","sgd_primitive_unavailable"),),{"optimizer":d["optimizer"],"learning_rate":repr(float(d["learning_rate"]))})
    sources[d["surface"]] = "\n".join(lines)

    d = decisions["optimizer_state"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines,"OptimizerStateCapabilities",(("reset_supported","Bool"),("no_cross_case_state","Bool"),("cancelled","Bool")))
    _function(lines,"decide","OptimizerStateCapabilities",(("input.reset_supported","optimizer_reset_unavailable"),("input.no_cross_case_state","optimizer_state_contamination")),{"optimizer_state_policy":d["policy"]})
    sources[d["surface"]] = "\n".join(lines)

    d = decisions["working_set"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines,"WorkingSetObservation",(("available_records","Int"),("selection_supported","Bool"),("cancelled","Bool")))
    _function(lines,"decide","WorkingSetObservation",((f"input.available_records == {d['count']}","working_set_records_unavailable"),("input.selection_supported","working_set_selection_unavailable")),{"working_set_policy":d["policy"],"working_set_start":str(d["start"]),"working_set_count":str(d["count"])})
    sources[d["surface"]] = "\n".join(lines)

    d = decisions["stopping"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines,"StoppingCapabilities",(("fixed_epoch_supported","Bool"),("counter_supported","Bool"),("cancelled","Bool")))
    _function(lines,"decide","StoppingCapabilities",(("input.fixed_epoch_supported","fixed_epoch_stop_unavailable"),("input.counter_supported","epoch_counter_unavailable")),{"stopping_policy":d["policy"],"epochs":str(d["epochs"])})
    sources[d["surface"]] = "\n".join(lines)

    d = decisions["equivalence_acceptance"]
    lines = _header(MODULES[d["surface"]], plan["plan_sha256"])
    _record(lines,"JudgeCapabilities",(("independent_verifier_available","Bool"),("publisher_requires_t","Bool"),("cancelled","Bool")))
    _function(lines,"policy","JudgeCapabilities",(("input.independent_verifier_available","independent_verifier_unavailable"),("input.publisher_requires_t","publisher_bypass_detected")),{"absolute_tolerance":repr(float(d["absolute_tolerance"])),"require_exact_counters":str(bool(d["require_exact_counters"])).lower(),"require_no_nan_inf":str(bool(d["require_no_nan_inf"])).lower()})
    _record(lines,"JudgmentEvidence",(("equivalence_status","Text"),("counter_status","Text"),("receipt_status","Text"),("semantic_status","Text"),("human_contract_confirmed","Bool"),("cancelled","Bool")))
    _function(lines,"judge","JudgmentEvidence",(("input.equivalence_status == 'PASS'","equivalence_not_pass"),("input.counter_status == 'PASS'","counters_not_pass"),("input.receipt_status == 'PASS'","receipts_not_pass"),("input.semantic_status == 'PASS'","semantic_integrity_not_pass"),("input.human_contract_confirmed","human_contract_unconfirmed")),{"decision":"PUBLISH"})
    sources[d["surface"]] = "\n".join(lines)
    return sources


def compile_training_authority_tcap(
    plan: Mapping[str, Any], source_directory: str | Path, tcap_directory: str | Path
) -> TcapV2Build:
    validate_training_authority_plan(plan)
    source_root = Path(source_directory).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    source_paths: list[Path] = []
    rendered = render_policy_sources(plan)
    for surface in POLICY_SURFACES:
        path = source_root / f"{surface}.t"
        if path.exists():
            raise FileExistsError(f"append-only T source already exists: {path}")
        path.write_text(rendered[surface], encoding="utf-8", newline="\n")
        source_paths.append(path)
    build = TcapV2Builder().build(
        source_paths,
        tcap_directory,
        entry_module=MODULES["dataset_identity_integrity"],
        entry_function="decide",
        tests={
            "properties": [
                "nine_surfaces",
                "fail_closed",
                "human_confirmation_required_for_publish",
                "mutations_must_change_tcap_or_decision",
            ]
        },
        foreign_boundaries=(
            {
                "name": "interlocution_training_primitive",
                "kind": "foreign_primitive",
                "decision_authority": False,
                "invocation_authority": "T",
            },
        ),
    )
    return build


def source_inventory(source_directory: str | Path) -> list[dict[str, Any]]:
    root = Path(source_directory).resolve()
    result = []
    for path in sorted(root.glob("*.t")):
        raw = path.read_bytes()
        result.append(
            {
                "path": path.name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return result
