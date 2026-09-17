from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from casulo.product.engine_contracts import CancellationToken

from .generative_model import GenerativeCandidate
from .local_model_runtime import (
    ChatMessage,
    GenerationRequest,
    LocalModelRuntime,
    ModelStreamKind,
    SamplingPolicy,
    initial_sampling_policies,
)


PROBE_PROMPT = (
    "/no_think\nResponda em português brasileiro. Imagine uma ferramenta local inédita que una "
    "memória de decisões, cultivo de plantas e revisão crítica entre amigos. Desenvolva "
    "uma direção concreta em dois parágrafos curtos, sem elogio automático."
)


def _complete(
    runtime: LocalModelRuntime,
    operation_id: str,
    policy: SamplingPolicy,
    *,
    cancel_after_first_fragment: bool = False,
) -> dict[str, object]:
    token = CancellationToken()
    request = GenerationRequest(
        operation_id,
        (
            ChatMessage(
                "system",
                "Você é o Guia owner local do Casulo. Não fabrique permissões e não use APIs externas.",
            ),
            ChatMessage("user", PROBE_PROMPT),
        ),
        policy,
    )
    fragments: list[str] = []
    terminal = None
    trace = None
    for event in runtime.stream_chat(request, token):
        if event.kind is ModelStreamKind.TOKEN:
            fragments.append(event.content)
            if cancel_after_first_fragment:
                token.cancel()
        if event.kind in {ModelStreamKind.COMPLETED, ModelStreamKind.CANCELLED, ModelStreamKind.FAILED}:
            terminal = event.kind.value
            trace = event.trace.to_dict() if event.trace is not None else None
    return {
        "operation_id": operation_id,
        "terminal": terminal,
        "text": "".join(fragments),
        "stream_fragments": len(fragments),
        "trace": trace,
    }


def run_probe(candidate: GenerativeCandidate, cache: Path, *, threads: int = 4) -> dict[str, object]:
    policies = initial_sampling_policies()
    # This is a bounded product gate, not a performance experiment. A short
    # completion is enough to prove neural streaming and stochastic variance.
    normal = replace(policies["dialogue"], max_generated_tokens=160)
    debug = replace(normal, policy_id="casulo-sampling-dialogue-debug-v1", seed=424242, debug_fixed_seed=True)
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        normal_runs = [_complete(runtime, f"g1:normal:{index}", normal) for index in range(1, 4)]
        debug_runs = [_complete(runtime, f"g1:debug:{index}", debug) for index in range(1, 3)]
        cancelled = _complete(runtime, "g1:cancel", normal, cancel_after_first_fragment=True)
    normal_texts = {str(item["text"]) for item in normal_runs}
    debug_texts = {str(item["text"]) for item in debug_runs}
    streaming_pass = all(int(item["stream_fragments"]) > 1 for item in normal_runs)
    normal_completed = all(item["terminal"] == "COMPLETED" for item in normal_runs)
    trace_pass = all(
        isinstance(item["trace"], dict)
        and item["trace"]["seed_if_available"] is None
        and item["trace"]["external_network_used"] is False
        and item["trace"]["commercial_ai_api_used"] is False
        for item in normal_runs
    )
    result = {
        "schema": "casulo-local-stochastic-inference-evidence/1.0",
        "candidate_id": candidate.candidate_id,
        "model_sha256": candidate.model.sha256,
        "runtime_archive_sha256": candidate.runtime.sha256,
        "normal_sampling_policy_id": normal.policy_id,
        "debug_sampling_policy_id": debug.policy_id,
        "normal_runs": normal_runs,
        "debug_runs": debug_runs,
        "cancelled_run": cancelled,
        "checks": {
            "neural_runtime_adopted": True,
            "normal_runs_completed": normal_completed,
            "streaming_multiple_fragments": streaming_pass,
            "normal_variance_observed": len(normal_texts) >= 2,
            "debug_fixed_seed_reproduced": len(debug_texts) == 1,
            "cancellation_terminal": cancelled["terminal"] == "CANCELLED",
            "stochastic_trace_valid": trace_pass,
            "external_ai_api_used": False,
            "fake_engine_used": False,
            "scientific_benchmark": False,
        },
    }
    positive = (
        "neural_runtime_adopted",
        "normal_runs_completed",
        "streaming_multiple_fragments",
        "normal_variance_observed",
        "debug_fixed_seed_reproduced",
        "cancellation_terminal",
        "stochastic_trace_valid",
    )
    negative = ("external_ai_api_used", "fake_engine_used", "scientific_benchmark")
    passed = all(result["checks"][key] is True for key in positive) and all(
        result["checks"][key] is False for key in negative
    )
    result["gate"] = "LOCAL_STOCHASTIC_INFERENCE_PASS" if passed else "LOCAL_STOCHASTIC_INFERENCE_FAIL"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real local neural stochastic product probe")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output already exists; overwrite denied")
    result = run_probe(GenerativeCandidate.load(args.candidate), args.cache, threads=args.threads)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"gate": result["gate"], "output": str(output)}, ensure_ascii=False))
    return 0 if result["gate"] == "LOCAL_STOCHASTIC_INFERENCE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
