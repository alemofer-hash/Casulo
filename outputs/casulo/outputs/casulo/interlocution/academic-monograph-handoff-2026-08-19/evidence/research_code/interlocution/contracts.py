from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


CAMPAIGN_SCHEMA = "casulo.interlocution-campaign/1.0"
INTENT_SCHEMA = "casulo.interlocution-confirmed-intent/1.0"
GRAPH_SCHEMA = "casulo.interlocution-requirement-graph/1.0"
PLAN_SCHEMA = "casulo.interlocution-training-authority-plan/1.0"
SHA256_ZERO = "0" * 64


class ContractError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require_sha256(value: Any, label: str) -> str:
    text = str(value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ContractError(f"{label} is not a lowercase SHA-256")
    return text


def _seal(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    document = dict(payload)
    document[field] = canonical_sha256(document)
    return document


def _verify_seal(document: Mapping[str, Any], field: str) -> None:
    observed = require_sha256(document.get(field), field)
    seed = {key: value for key, value in document.items() if key != field}
    if canonical_sha256(seed) != observed:
        raise ContractError(f"{field} does not seal the canonical document")


def build_confirmed_intent(
    *,
    campaign_id: str,
    dataset_sha256: str,
    initialization_sha256: str,
    confirmation_event_sha256: str,
) -> dict[str, Any]:
    require_sha256(dataset_sha256, "dataset_sha256")
    require_sha256(initialization_sha256, "initialization_sha256")
    require_sha256(confirmation_event_sha256, "confirmation_event_sha256")
    seed = {
        "schema": INTENT_SCHEMA,
        "campaign_id": campaign_id,
        "human_owner": "Guilherme Moura Fernandes",
        "confirmation": {
            "kind": "EXPLICIT_USER_GOAL_SUBMISSION",
            "event_sha256": confirmation_event_sha256,
            "model_may_confirm": False,
        },
        "purpose": (
            "test whether causal T authority, audit and judgment can preserve "
            "the operational training contract while reducing net work"
        ),
        "material_gaps": [],
        "workload": {
            "id": "flood-surrogate-full-v1",
            "records_per_epoch": 1024,
            "input_features": 8,
            "hidden_features": 8,
            "output_features": 1,
            "activation": "relu",
            "dataset_sha256": dataset_sha256,
            "initialization_bundle_sha256": initialization_sha256,
        },
        "training": {
            "precision": "float64",
            "loss": "mse",
            "update_rule": "sgd",
            "learning_rate": 0.018,
            "optimizer_state_policy": "reset_each_case",
            "working_set_policy": "all_records",
            "stopping_policy": "fixed_epochs",
            "epochs": 400,
        },
        "equivalence": {
            "absolute_tolerance": 1e-9,
            "require_exact_counters": True,
            "require_no_nan_inf": True,
        },
        "boundaries": {
            "cloud": "RELEASE_LOCKED",
            "external_api": "PROHIBITED",
            "publication": "PRIVATE_RESEARCH_ONLY",
            "energy_claim": "BLOCKED_WITHOUT_VALID_INSTRUMENT",
        },
    }
    result = _seal(seed, "intent_sha256")
    validate_confirmed_intent(result)
    return result


def validate_confirmed_intent(value: Mapping[str, Any]) -> None:
    if value.get("schema") != INTENT_SCHEMA:
        raise ContractError("confirmed intent schema mismatch")
    _verify_seal(value, "intent_sha256")
    confirmation = value.get("confirmation", {})
    if confirmation.get("kind") != "EXPLICIT_USER_GOAL_SUBMISSION":
        raise ContractError("intent lacks explicit human confirmation")
    if confirmation.get("model_may_confirm") is not False:
        raise ContractError("model cannot confirm the intent")
    workload = value.get("workload", {})
    if workload.get("records_per_epoch") != 1024:
        raise ContractError("the scientific unit requires 1,024 records")
    require_sha256(workload.get("dataset_sha256"), "dataset_sha256")
    require_sha256(
        workload.get("initialization_bundle_sha256"),
        "initialization_bundle_sha256",
    )


def build_requirement_graph(intent: Mapping[str, Any]) -> dict[str, Any]:
    validate_confirmed_intent(intent)
    w = intent["workload"]
    t = intent["training"]
    e = intent["equivalence"]
    requirements = [
        ("R-DATASET", "dataset identity and 1,024-record integrity", w["dataset_sha256"]),
        ("R-INIT", "content-addressed independent initialization", w["initialization_bundle_sha256"]),
        ("R-PRECISION", "float64 numerical precision", t["precision"]),
        ("R-LOSS", "MSE loss", t["loss"]),
        ("R-UPDATE", "SGD update at learning rate 0.018", str(t["learning_rate"])),
        ("R-OPTSTATE", "optimizer state reset for each case", t["optimizer_state_policy"]),
        ("R-WORKSET", "all 1,024 records per fixed-count epoch", t["working_set_policy"]),
        ("R-STOP", "400 complete epochs", str(t["epochs"])),
        ("R-JUDGE", "equivalence and acceptance are fail-closed", str(e["absolute_tolerance"])),
    ]
    seed = {
        "schema": GRAPH_SCHEMA,
        "campaign_id": intent["campaign_id"],
        "intent_sha256": intent["intent_sha256"],
        "requirements": [
            {
                "id": identifier,
                "kind": "HARD",
                "description": description,
                "expected": expected,
                "state_before_execution": "UNVERIFIED",
                "missing_evidence_is": "UNKNOWN",
            }
            for identifier, description, expected in requirements
        ],
        "material_gaps": [],
        "false_hard_completion_allowed": False,
    }
    result = _seal(seed, "graph_sha256")
    validate_requirement_graph(result, intent)
    return result


def validate_requirement_graph(
    value: Mapping[str, Any], intent: Mapping[str, Any] | None = None
) -> None:
    if value.get("schema") != GRAPH_SCHEMA:
        raise ContractError("requirement graph schema mismatch")
    _verify_seal(value, "graph_sha256")
    requirements = value.get("requirements")
    if not isinstance(requirements, list) or len(requirements) != 9:
        raise ContractError("requirement graph must contain nine HARD requirements")
    if len({item.get("id") for item in requirements}) != 9:
        raise ContractError("requirement identifiers are not unique")
    if any(item.get("kind") != "HARD" for item in requirements):
        raise ContractError("all critical training requirements must be HARD")
    if value.get("false_hard_completion_allowed") is not False:
        raise ContractError("false HARD completion must be disabled")
    if intent is not None and value.get("intent_sha256") != intent.get("intent_sha256"):
        raise ContractError("requirement graph does not bind the confirmed intent")


def build_training_authority_plan(
    intent: Mapping[str, Any], graph: Mapping[str, Any]
) -> dict[str, Any]:
    validate_confirmed_intent(intent)
    validate_requirement_graph(graph, intent)
    w = intent["workload"]
    t = intent["training"]
    e = intent["equivalence"]
    decisions = [
        {"surface":"dataset_identity_integrity","dataset_sha256":w["dataset_sha256"],"records_per_epoch":w["records_per_epoch"],"input_features":w["input_features"]},
        {"surface":"initialization_bundle","bundle_sha256":w["initialization_bundle_sha256"],"state_policy":t["optimizer_state_policy"]},
        {"surface":"numerical_precision","dtype":t["precision"]},
        {"surface":"loss_function","loss":t["loss"]},
        {"surface":"update_rule","optimizer":t["update_rule"],"learning_rate":t["learning_rate"]},
        {"surface":"optimizer_state","policy":t["optimizer_state_policy"]},
        {"surface":"working_set","policy":t["working_set_policy"],"start":0,"count":w["records_per_epoch"]},
        {"surface":"stopping","policy":t["stopping_policy"],"epochs":t["epochs"]},
        {"surface":"equivalence_acceptance","absolute_tolerance":e["absolute_tolerance"],"require_exact_counters":e["require_exact_counters"],"require_no_nan_inf":e["require_no_nan_inf"]},
    ]
    seed = {
        "schema": PLAN_SCHEMA,
        "campaign_id": intent["campaign_id"],
        "intent_sha256": intent["intent_sha256"],
        "requirement_graph_sha256": graph["graph_sha256"],
        "decisions": decisions,
        "authority_rule": "T_RESULT_REQUIRED_NO_AFFIRMATIVE_FOREIGN_FALLBACK",
        "primitive_policy": "FOREIGN_EXECUTION_T_DECIDES_INVOCATION",
        "publication_policy": "T_JUDGE_RECEIPT_REQUIRED",
    }
    result = _seal(seed, "plan_sha256")
    validate_training_authority_plan(result, intent, graph)
    return result


def validate_training_authority_plan(
    value: Mapping[str, Any],
    intent: Mapping[str, Any] | None = None,
    graph: Mapping[str, Any] | None = None,
) -> None:
    if value.get("schema") != PLAN_SCHEMA:
        raise ContractError("training authority plan schema mismatch")
    _verify_seal(value, "plan_sha256")
    decisions = value.get("decisions")
    expected = {
        "dataset_identity_integrity",
        "initialization_bundle",
        "numerical_precision",
        "loss_function",
        "update_rule",
        "optimizer_state",
        "working_set",
        "stopping",
        "equivalence_acceptance",
    }
    if not isinstance(decisions, list) or {item.get("surface") for item in decisions} != expected:
        raise ContractError("training authority plan must contain exactly nine surfaces")
    if value.get("authority_rule") != "T_RESULT_REQUIRED_NO_AFFIRMATIVE_FOREIGN_FALLBACK":
        raise ContractError("training authority plan is not fail-closed")
    update = next(item for item in decisions if item["surface"] == "update_rule")
    if not math.isfinite(float(update["learning_rate"])) or float(update["learning_rate"]) <= 0:
        raise ContractError("learning rate is invalid")
    if intent is not None and value.get("intent_sha256") != intent.get("intent_sha256"):
        raise ContractError("plan does not bind the confirmed intent")
    if graph is not None and value.get("requirement_graph_sha256") != graph.get("graph_sha256"):
        raise ContractError("plan does not bind the requirement graph")

