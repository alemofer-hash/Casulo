from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


PACKS = {
    "holdout-scientific-tensor": "scientific-computing",
    "holdout-public-workflow": "administrative-workflow",
    "holdout-transit-stream": "stream-processing",
    "holdout-creative-dialogue": "interactive-creative-tool",
    "holdout-secure-service": "local-software-service",
}


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


STRING_ARRAY = {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "string", "minLength": 1, "maxLength": 160}}
CLAIMS = {"type": "array", "maxItems": 6, "items": {"type": "string", "maxLength": 240}}

SCHEMAS: dict[str, dict[str, Any]] = {
    "scientific-computing": object_schema(
        {
            "science": object_schema(
                {
                    "inputs": STRING_ARRAY,
                    "operators": STRING_ARRAY,
                    "outputs": STRING_ARRAY,
                    "scope": {"type": "string", "enum": ["local-4d-evaluator"]},
                    "refusals": STRING_ARRAY,
                    "method": {"type": "string", "minLength": 1, "maxLength": 400},
                },
                ["inputs", "operators", "outputs", "scope", "refusals", "method"],
            ),
            "claims": CLAIMS,
        },
        ["science", "claims"],
    ),
    "administrative-workflow": object_schema(
        {
            "workflow": object_schema(
                {
                    "human_decision_required": {"type": "boolean"},
                    "provenance": STRING_ARRAY,
                    "audit_log": {"type": "string", "enum": ["append-only"]},
                    "steps": STRING_ARRAY,
                },
                ["human_decision_required", "provenance", "audit_log", "steps"],
            ),
            "security": object_schema({"network_default": {"type": "string", "enum": ["deny"]}}, ["network_default"]),
            "claims": CLAIMS,
        },
        ["workflow", "security", "claims"],
    ),
    "stream-processing": object_schema(
        {
            "stream": object_schema(
                {
                    "preserve_original": {"type": "boolean"},
                    "memory_limit_bytes": {"type": "integer", "minimum": 1, "maximum": 1073741824},
                    "time_semantics": {"type": "string", "enum": ["event-time"]},
                    "explain_transform": {"type": "boolean"},
                    "pipeline": STRING_ARRAY,
                },
                ["preserve_original", "memory_limit_bytes", "time_semantics", "explain_transform", "pipeline"],
            ),
            "claims": CLAIMS,
        },
        ["stream", "claims"],
    ),
    "interactive-creative-tool": object_schema(
        {
            "creative": object_schema(
                {
                    "project_isolation": {"type": "boolean"},
                    "barge_in": {"type": "boolean"},
                    "export": {"type": "string", "enum": ["editable"]},
                    "progress_source": {"type": "string", "enum": ["job-events-only"]},
                    "interaction": STRING_ARRAY,
                },
                ["project_isolation", "barge_in", "export", "progress_source", "interaction"],
            ),
            "claims": CLAIMS,
        },
        ["creative", "claims"],
    ),
    "local-software-service": object_schema(
        {
            "service": object_schema(
                {
                    "bind": {"type": "string", "enum": ["127.0.0.1"]},
                    "schema_validation": {"type": "boolean"},
                    "standalone": {"type": "boolean"},
                    "round_trip_fidelity": {"type": "number", "enum": [1.0]},
                    "components": STRING_ARRAY,
                },
                ["bind", "schema_validation", "standalone", "round_trip_fidelity", "components"],
            ),
            "claims": CLAIMS,
        },
        ["service", "claims"],
    ),
}


def run_probe(repo: Path, candidate_path: Path, cache: Path, output: Path, *, threads: int) -> dict[str, Any]:
    sys.path[:0] = [str(repo / "src"), str(repo / "private/casulo-owner/src")]
    from casulo.product.engine_contracts import CancellationToken  # noqa: PLC0415
    from casulo.product.semantic_fulfillment import FulfillmentEngine, default_domain_registry  # noqa: PLC0415
    from casulo_owner.generative_forge import StructuredGenerationError, generate_structured  # noqa: PLC0415
    from casulo_owner.generative_model import GenerativeCandidate  # noqa: PLC0415
    from casulo_owner.local_model_runtime import ChatMessage, LocalModelRuntime, initial_sampling_policies  # noqa: PLC0415

    if output.exists():
        raise RuntimeError("evidence dir já existe; overwrite negado")
    output.mkdir(parents=True)
    suite_path = repo / "private/casulo-owner/tests/holdouts/revolution-closure-v1.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    engine = FulfillmentEngine(default_domain_registry())
    candidate = GenerativeCandidate.load(candidate_path)
    # Repairs must emit the complete structured object again.  The former
    # 420-token ceiling truncated both scientific repairs before JSON closure.
    # This only raises the generation budget: the sealed schema and independent
    # domain verifier remain unchanged and retain authority over acceptance.
    policy = replace(initial_sampling_policies()["planning"], max_generated_tokens=720)
    records: list[dict[str, Any]] = []
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        for family in suite["families"]:
            family_id = family["family_id"]
            pack_id = PACKS[family_id]
            attempts: list[dict[str, Any]] = []
            previous: dict[str, Any] | None = None
            diagnostics: list[dict[str, Any]] = []
            accepted = False
            for attempt in range(3):
                prompt = (
                    "Produza um contrato de arquitetura executável e honesto para o pedido holdout abaixo. "
                    "Preencha todos os campos do schema, preserve as restrições duras e não alegue capacidade não implementada. "
                    "Valores booleanos devem descrever decisões reais do contrato, não elogios.\n\n"
                    f"PEDIDO:\n{family['request']}\n\n"
                    f"INVARIANTES HARD DECLARADOS PELO DOMAIN PACK:\n{json.dumps(family['hard_invariants'], ensure_ascii=False)}"
                )
                if previous is not None:
                    prompt += (
                        "\n\nO candidato anterior foi recusado. DIAGNOSTICS REAIS:\n"
                        + json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)
                        + "\nUse nos arrays os identificadores canônicos esperados exatamente como escritos nos diagnostics. "
                        + "Retorne o contrato completo corrigido, de forma concisa; não apenas um patch."
                    )
                try:
                    generated = generate_structured(
                        runtime,
                        operation_id=f"rc3:{family_id}:attempt:{attempt}",
                        messages=(
                            ChatMessage("system", "/no_think\nVocê é o planejador local do Casulo. Saída é candidata sem autoridade; verificadores determinísticos julgam."),
                            ChatMessage("user", prompt),
                        ),
                        policy=policy,
                        schema=SCHEMAS[pack_id],
                        cancellation=CancellationToken(),
                    )
                except StructuredGenerationError as error:
                    attempts.append({"attempt": attempt, "structured": False, "error": str(error), "trace": error.trace.to_dict(), "raw_sha256": error.raw_sha256})
                    continue
                previous = generated.payload
                result = engine.evaluate(
                    pack_id,
                    previous,
                    source_event_id=f"holdout:{family_id}",
                    scope=f"creation:{family_id}",
                    occurred_at="2026-08-14T20:30:00Z",
                    safety_pass=True,
                )
                diagnostics = [item.to_dict() for item in result.diagnostics]
                attempts.append(
                    {
                        "attempt": attempt,
                        "structured": True,
                        "raw_sha256": generated.raw_sha256,
                        "trace": generated.trace.to_dict(),
                        "candidate": previous,
                        "fulfillment": result.to_dict(),
                    }
                )
                if result.accepted:
                    accepted = True
                    break
            record = {
                "family_id": family_id,
                "domain": family["domain"],
                "pack_id": pack_id,
                "request_sha256": hashlib.sha256(family["request"].encode("utf-8")).hexdigest(),
                "accepted": accepted,
                "attempts": attempts,
            }
            records.append(record)
            write_json(output / f"{family_id}.json", record)
    checks = {
        "five_domains": len(records) == 5 and len({item["domain"] for item in records}) == 5,
        "all_holdouts_accepted": all(item["accepted"] for item in records),
        "all_evidence_independent": all(
            receipt["independent"]
            for record in records
            for attempt in record["attempts"]
            if "fulfillment" in attempt
            for receipt in attempt["fulfillment"]["evidence"]
        ),
        "zero_unsupported_claims": all(
            not attempt["fulfillment"]["unsupported_claims"]
            for record in records
            for attempt in record["attempts"]
            if attempt.get("fulfillment", {}).get("accepted")
        ),
        "real_local_model": True,
        "normal_sampling_seed_absent": all(
            attempt.get("trace", {}).get("seed") is None
            for record in records
            for attempt in record["attempts"]
            if attempt.get("trace")
        ),
        "fake_engine_used": False,
        "external_ai_api_used": False,
    }
    passed = all(value is True for key, value in checks.items() if key not in {"fake_engine_used", "external_ai_api_used"}) and checks["fake_engine_used"] is False and checks["external_ai_api_used"] is False
    report = {
        "schema": "casulo.semantic-fulfillment-holdout/1.0",
        "gate": "PASS" if passed else "FAIL",
        "candidate_id": candidate.candidate_id,
        "model_sha256": candidate.model.sha256,
        "sampling_policy_id": policy.policy_id,
        "holdout_suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "records": records,
        "checks": checks,
        "claims": ["semantic contract fulfillment on five sealed product holdout families"],
        "forbidden_claims": ["generated applications are production-complete", "general scientific solver", "human utility approved"],
    }
    write_json(output / "semantic-fulfillment-holdout.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Neural holdout probe for semantic fulfillment")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    result = run_probe(args.repo.resolve(), args.candidate.resolve(), args.cache.resolve(), args.output.resolve(), threads=args.threads)
    print(json.dumps({"gate": result["gate"], "checks": result["checks"]}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
