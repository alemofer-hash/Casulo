from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from casulo.product.engine_contracts import CancellationToken
from casulo.product.intent_reconstruction import IntentTaskKind, IntentTwinRenderer
from casulo_owner.generative_model import GenerativeCandidate
from casulo_owner.intent_reconstruction import IntentReconstructionEngine
from casulo_owner.local_model_runtime import LocalModelRuntime


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run(candidate_path: Path, cache: Path, output: Path, *, threads: int) -> dict[str, object]:
    if output.exists() or output.is_symlink():
        raise RuntimeError("output já existe; evidência append-only não pode ser sobrescrita")
    output.mkdir(parents=True)
    candidate = GenerativeCandidate.load(candidate_path)
    utterance = (
        "Crie um agente local que compare duas propostas de arquitetura, explique conflitos "
        "e nunca execute alterações reais sem confirmação humana."
    )
    expectation = "A resposta deve apresentar as duas propostas, o conflito principal e pedir confirmação antes de agir."
    with LocalModelRuntime(candidate, cache, threads=threads) as runtime:
        reconstruction = IntentReconstructionEngine(runtime).propose(
            creation_id="creation:arc-neural-smoke",
            source_event_id="automated:arc-neural-contract-smoke",
            utterance=utterance,
            expected_behavior=expectation,
            cancellation=CancellationToken(),
            task_kind_hint=IntentTaskKind.CREATION,
        )
    twin = reconstruction.twin
    _write_json(output / "intent-twin.json", twin.to_dict())
    _write_json(output / "stochastic-trace.json", reconstruction.trace.to_dict())
    visual = IntentTwinRenderer.render(twin, output / "visual")
    checks = {
        "real_local_model_trace": bool(reconstruction.trace.output_sha256),
        "one_or_two_hypotheses": 1 <= len(twin.hypotheses) <= 2,
        "at_most_one_material_gap": len(twin.open_gaps) <= 1,
        "selected_hypothesis_preserves_hard": (
            twin.selected_hypothesis_id is None
            if twin.open_gaps
            else twin.selected_hypothesis_id in twin.viable_hypothesis_ids
        ),
        "creation_context_preserved": twin.task_kind is IntentTaskKind.CREATION,
        "not_human_confirmed": not twin.confirmed,
        "not_produced": True,
        "external_api_used": False,
        "scientific_benchmark_started": False,
    }
    required_true = {
        key for key in checks
        if key not in {"external_api_used", "scientific_benchmark_started"}
    }
    required_false = {"external_api_used", "scientific_benchmark_started"}
    passed = all(checks[key] is True for key in required_true) and all(
        checks[key] is False for key in required_false
    )
    report = {
        "schema": "casulo.arc-intent-twin-smoke/1.0",
        "gate": "ARC_INTENT_TWIN_NEURAL_CONTRACT_PASS" if passed else "ARC_INTENT_TWIN_NEURAL_CONTRACT_FAIL",
        "candidate_id": candidate.candidate_id,
        "candidate_manifest_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        "intent_twin_sha256": twin.to_dict()["canonical_sha256"],
        "model_task_kind": reconstruction.model_task_kind.value,
        "deterministic_overrides": list(reconstruction.deterministic_overrides),
        "candidate_rejections": list(reconstruction.candidate_rejections),
        "visual": str(visual),
        "checks": checks,
        "limits": [
            "smoke de contrato, não prova qualidade de compreensão",
            "sem confirmação humana, T, simulação ou materialização",
            "não é benchmark de desempenho ou energia",
        ],
    }
    _write_json(output / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke neural local do contrato IntentTwin")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    try:
        result = run(
            args.candidate.resolve(),
            args.cache.expanduser().resolve(),
            args.output.resolve(),
            threads=args.threads,
        )
    except BaseException as error:
        output = args.output.resolve()
        if output.is_dir() and not (output / "failure.json").exists():
            _write_json(
                output / "failure.json",
                {
                    "schema": "casulo.arc-intent-twin-smoke-failure/1.0",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "preserved": True,
                },
            )
        raise
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["gate"] == "ARC_INTENT_TWIN_NEURAL_CONTRACT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
