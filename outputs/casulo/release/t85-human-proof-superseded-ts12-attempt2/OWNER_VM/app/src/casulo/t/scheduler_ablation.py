"""Ablação pareada e segmentada da agenda GEMM do Casulo/T.

Compara somente duas políticas do mesmo backend. PyTorch e Inductor não são
carregados. Cada processo mede pares alternados com o mesmo lote de iterações;
o juiz só decide depois de três reinícios e das respectivas evidências térmicas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .autograd import compile_autograd_file
from .measurement import (
    calibrate_shared_iterations,
    coefficient_of_variation,
    system_telemetry_snapshot,
)
from .parity import NumpyTensorExecutor, compare_executions
from .tensor_cpu import prepare_tensor_cpu_executor
from .thermal_watchdog import verify_evidence as verify_thermal_evidence
from .window_calibration import (
    _generate_inputs,
    _measure_batch,
    _write_immutable_json,
    verify_evidence,
)


ABLATION_PREREGISTRATION_PROTOCOL = "casulo-scheduler-ablation-preregistration/0.1"
ABLATION_BLOCK_PROTOCOL = "casulo-scheduler-ablation-block/0.1"
ABLATION_VERDICT_PROTOCOL = "casulo-scheduler-ablation-verdict/0.1"
VARIANT_FIXED = "fixed"
VARIANT_ADAPTIVE = "adaptive"
VARIANTS = (VARIANT_FIXED, VARIANT_ADAPTIVE)


class SchedulerAblationError(RuntimeError):
    """A ablação não pode prosseguir sem violar o desenho selado."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _orders_for_block(block: int, pairs: int) -> list[list[str]]:
    return [
        (
            [VARIANT_FIXED, VARIANT_ADAPTIVE]
            if (block + pair) % 2 == 0
            else [VARIANT_ADAPTIVE, VARIANT_FIXED]
        )
        for pair in range(pairs)
    ]


def create_preregistration(
    graph_path: str | Path,
    output_path: str | Path,
    *,
    wrt: Sequence[str],
    loss: str | None = None,
    blocks: int = 3,
    pairs_per_block: int = 8,
    warmups: int = 2,
    target_window_ms: float = 250.0,
    cooldown_ms: int = 100,
    max_cv: float = 0.15,
    practical_effect: float = 0.02,
    equivalence_margin: float = 0.02,
    bootstrap_resamples: int = 5_000,
    bootstrap_seed: int = 20_260_731,
    input_seed: int = 20_260_731,
    supersedes_path: str | Path | None = None,
) -> dict[str, Any]:
    graph = Path(graph_path).expanduser().resolve()
    if not graph.is_file():
        raise SchedulerAblationError(f"grafo ausente: {graph}")
    if not wrt:
        raise SchedulerAblationError("ao menos um wrt é obrigatório")
    if blocks != 3 or pairs_per_block < 8 or pairs_per_block % 2:
        raise SchedulerAblationError(
            "desenho 0.1 exige três blocos e número par de ao menos oito pares"
        )
    if warmups < 1 or cooldown_ms < 0:
        raise SchedulerAblationError("warmup ou cooldown inválido")
    if not math.isfinite(target_window_ms) or target_window_ms <= 0:
        raise SchedulerAblationError("janela precisa ser positiva")
    if not 0 < max_cv <= 1:
        raise SchedulerAblationError("max_cv precisa estar em (0, 1]")
    if not 0 < practical_effect < 1 or not 0 < equivalence_margin < 1:
        raise SchedulerAblationError("margens precisam estar em (0, 1)")
    if bootstrap_resamples < 1_000:
        raise SchedulerAblationError("bootstrap exige ao menos 1.000 reamostragens")
    autograd = compile_autograd_file(graph, wrt=tuple(wrt), loss=loss)
    supersedes: dict[str, Any] | None = None
    if supersedes_path is not None:
        prior, prior_sha256 = verify_evidence(supersedes_path)
        if prior.get("protocol") != ABLATION_PREREGISTRATION_PROTOCOL:
            raise SchedulerAblationError(
                "somente um pré-registro da mesma ablação pode ser supersedido"
            )
        supersedes = {
            "preregistration_sha256": prior_sha256,
            "executed": False,
            "reason": "power-contract-added-before-any-ablation-result",
        }
    schedule = [
        {
            "block": block,
            "session_id": f"sprint025-ablation-block-{block:02d}",
            "orders": _orders_for_block(block, pairs_per_block),
        }
        for block in range(blocks)
    ]
    document: dict[str, Any] = {
        "protocol": ABLATION_PREREGISTRATION_PROTOCOL,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "supersedes": supersedes,
        "brand": {
            "invention": "Casulo",
            "origin": "Teloscorp",
            "specialty": "Otimização de Tráfego de Informação",
        },
        "workload": {
            "graph_path_hint": graph.name,
            "graph_sha256": _sha256(graph),
            "autograd_protocol": autograd.protocol,
            "wrt": list(dict.fromkeys(wrt)),
            "loss": autograd.loss,
            "input_seed": int(input_seed),
            "provider": "openblas",
            "workers": 2,
        },
        "variants": {
            VARIANT_FIXED: {"gemm_workers": 2},
            VARIANT_ADAPTIVE: {"gemm_workers": "adaptive"},
        },
        "design": {
            "blocks": int(blocks),
            "pairs_per_block": int(pairs_per_block),
            "warmups": int(warmups),
            "target_window_ms": float(target_window_ms),
            "cooldown_ms": int(cooldown_ms),
            "maximum_inner_iterations": 1_000_000,
            "max_coefficient_of_variation": float(max_cv),
            "practical_effect": float(practical_effect),
            "equivalence_margin": float(equivalence_margin),
            "bootstrap_resamples": int(bootstrap_resamples),
            "bootstrap_seed": int(bootstrap_seed),
            "schedule": schedule,
            "ratio": "fixed_wall_ns_per_invocation/adaptive_wall_ns_per_invocation",
            "shared_iterations": True,
            "uses_paired_samples": True,
            "uses_speedup_to_select_measurement_parameters": False,
            "power_contract": {
                "same_power_plugged_state_across_blocks": True,
                "minimum_start_battery_percent_if_unplugged": 60.0,
            },
        },
        "decision": {
            "ADAPTIVE": "ci95_low>1 and median>=1+practical_effect",
            "FIXED": "ci95_high<1 and median<=1-practical_effect",
            "EQUIVALENT": "ci95_inside_equivalence_margin",
            "INCONCLUSIVE": "all_other_valid_results",
        },
        "scientific_scope": {
            "claim_eligible": False,
            "pytorch_loaded": False,
            "purpose": "internal-scheduler-policy-selection",
            "energy_joules": None,
        },
        "claim": None,
    }
    _write_immutable_json(Path(output_path), document)
    return document


def _generic_parity_document(report: Any, candidate_backend: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for item in report.checks:
        check = item.to_dict()
        check["reference_sha256"] = check.pop("numpy_sha256")
        check["candidate_sha256"] = check.pop("pytorch_sha256")
        checks.append(check)
    return {
        "protocol": "casulo-candidate-numpy-parity/0.1",
        "status": report.status.value,
        "passed": report.passed,
        "reason": report.reason,
        "graph_sha256": report.graph_sha256,
        "input_sha256": report.input_sha256,
        "reference_backend": "numpy-reference",
        "reference_version": report.numpy_version,
        "candidate_backend": candidate_backend,
        "checks": checks,
        "tolerances": [item.to_dict() for item in report.tolerances],
    }


def run_block(
    preregistration_path: str | Path,
    graph_path: str | Path,
    output_path: str | Path,
    *,
    block: int,
) -> dict[str, Any]:
    preregistration, preregistration_sha256 = verify_evidence(
        preregistration_path
    )
    if preregistration.get("protocol") != ABLATION_PREREGISTRATION_PROTOCOL:
        raise SchedulerAblationError("protocolo de pré-registro desconhecido")
    design = preregistration["design"]
    if block < 0 or block >= int(design["blocks"]):
        raise SchedulerAblationError("bloco fora do pré-registro")
    scheduled = design["schedule"][block]
    if int(scheduled["block"]) != block:
        raise SchedulerAblationError("agenda de bloco corrompida")
    graph = Path(graph_path).expanduser().resolve()
    workload = preregistration["workload"]
    if _sha256(graph) != workload["graph_sha256"]:
        raise SchedulerAblationError("grafo diverge do pré-registro")
    host_at_start = system_telemetry_snapshot()
    power_plugged = host_at_start.get("power_plugged")
    battery_percent = host_at_start.get("battery_percent")
    if power_plugged is None:
        raise SchedulerAblationError("estado de alimentação não observável")
    minimum_battery = float(
        design["power_contract"][
            "minimum_start_battery_percent_if_unplugged"
        ]
    )
    if power_plugged is False and (
        battery_percent is None or float(battery_percent) < minimum_battery
    ):
        raise SchedulerAblationError(
            f"bateria desconectada precisa iniciar em ao menos {minimum_battery:.0f}%"
        )

    autograd = compile_autograd_file(
        graph,
        wrt=tuple(workload["wrt"]),
        loss=workload["loss"],
    )
    inputs = _generate_inputs(autograd, int(workload["input_seed"]))
    reference = NumpyTensorExecutor().execute(autograd, inputs)
    executors: dict[str, Any] = {}
    variants: dict[str, Any] = {}
    for name in VARIANTS:
        specification = preregistration["variants"][name]
        gemm_workers = specification["gemm_workers"]
        prepared = prepare_tensor_cpu_executor(
            autograd,
            inputs,
            workers=int(workload["workers"]),
            gemm_workers=(
                gemm_workers
                if gemm_workers == "adaptive"
                else int(gemm_workers)
            ),
            provider=str(workload["provider"]),
        )
        prepared.invoke(audit=True)
        candidate = prepared.snapshot(reference)
        parity = compare_executions(reference, candidate, autograd)
        if not parity.passed:
            raise SchedulerAblationError(f"paridade falhou: {name}")
        executors[name] = prepared
        variants[name] = {
            "gemm_worker_policy": prepared.plan.gemm_worker_policy,
            "gemm_worker_schedule": list(prepared.plan.gemm_worker_schedule),
            "provider": prepared.plan.algebra_kernels[0].provider.to_dict(),
            "binary_sha256": prepared.build.binary_sha256,
            "cache_hit": prepared.build.cache_hit,
            "parity": _generic_parity_document(parity, candidate.backend),
        }
    for _ in range(int(design["warmups"])):
        for name in VARIANTS:
            executors[name].invoke(audit=False)

    runners = {
        name: (lambda selected=name: executors[selected].invoke(audit=False))
        for name in VARIANTS
    }
    selected_iterations, calibration = calibrate_shared_iterations(
        runners,
        minimum_iterations=1,
        maximum_iterations=int(design["maximum_inner_iterations"]),
        target_wall_ms=float(design["target_window_ms"]),
        measure=_measure_batch,
    )
    if not calibration["all_backends_reached_target"]:
        raise SchedulerAblationError("variantes não alcançaram a janela selada")
    samples: list[dict[str, Any]] = []
    for pair, order in enumerate(scheduled["orders"]):
        if pair and int(design["cooldown_ms"]):
            time.sleep(int(design["cooldown_ms"]) / 1_000)
        before = system_telemetry_snapshot()
        measurements: dict[str, Any] = {}
        for name in order:
            wall_ns, cpu_ns = _measure_batch(runners[name], selected_iterations)
            measurements[name] = {
                "wall_ns": wall_ns,
                "cpu_ns": cpu_ns,
                "inner_iterations": selected_iterations,
                "wall_ns_per_invocation": wall_ns / selected_iterations,
                "cpu_ns_per_invocation": cpu_ns / selected_iterations,
            }
        samples.append(
            {
                "pair": pair,
                "order": list(order),
                "measurements": measurements,
                "telemetry_before": before,
                "telemetry_after": system_telemetry_snapshot(),
            }
        )
    document: dict[str, Any] = {
        "protocol": ABLATION_BLOCK_PROTOCOL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistration_sha256": preregistration_sha256,
        "block": block,
        "session_id": scheduled["session_id"],
        "orders": scheduled["orders"],
        "host_at_start": host_at_start,
        "selected_shared_iterations": selected_iterations,
        "calibration": calibration,
        "variants": variants,
        "samples": samples,
        "scientific_scope": {
            "claim_eligible": False,
            "pytorch_loaded": False,
            "speedup_used_for_parameters": False,
        },
        "claim": None,
    }
    _write_immutable_json(Path(output_path), document)
    return document


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(float(item) for item in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def hierarchical_bootstrap(
    ratios_by_block: Sequence[Sequence[float]],
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    if len(ratios_by_block) < 2 or any(not block for block in ratios_by_block):
        raise SchedulerAblationError("bootstrap exige blocos não vazios")
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(resamples):
        observed: list[float] = []
        for _ in range(len(ratios_by_block)):
            block = rng.choice(ratios_by_block)
            observed.extend(rng.choice(block) for _ in range(len(block)))
        estimates.append(statistics.median(observed))
    return _quantile(estimates, 0.025), _quantile(estimates, 0.975)


def classify_statistics(
    *,
    median_ratio: float,
    ci95_low: float,
    ci95_high: float,
    fixed_cv: float | None,
    adaptive_cv: float | None,
    max_cv: float,
    practical_effect: float,
    equivalence_margin: float,
) -> str:
    if (
        fixed_cv is None
        or adaptive_cv is None
        or fixed_cv > max_cv
        or adaptive_cv > max_cv
    ):
        return "INCONCLUSIVE"
    if ci95_low > 1.0 and median_ratio >= 1.0 + practical_effect:
        return "ADAPTIVE"
    if ci95_high < 1.0 and median_ratio <= 1.0 - practical_effect:
        return "FIXED"
    if (
        ci95_low >= 1.0 - equivalence_margin
        and ci95_high <= 1.0 + equivalence_margin
    ):
        return "EQUIVALENT"
    return "INCONCLUSIVE"


def _verify_thermal_session(path: Path, expected_session_id: str) -> dict[str, Any]:
    session, session_sha256 = verify_thermal_evidence(path)
    attestation_path = path.with_suffix(".attestation.json")
    attestation, attestation_sha256 = verify_thermal_evidence(attestation_path)
    accepted = (
        session.get("session_id") == expected_session_id
        and session.get("status") == "PASSED_TELEMETRY"
        and session.get("gate_eligible_telemetry") is True
        and session.get("child_returncode") == 0
        and attestation.get("accepted") is True
        and attestation.get("session_sha256") == session_sha256
    )
    return {
        "session_id": session.get("session_id"),
        "session_sha256": session_sha256,
        "attestation_sha256": attestation_sha256,
        "peak_temperature_celsius": session.get("peak_temperature_celsius"),
        "warning_observed": session.get("warning_observed"),
        "throttling_observed": session.get("throttling_observed"),
        "power_plugged_at_start": session.get(
            "host_telemetry_at_start", {}
        ).get("power_plugged"),
        "battery_percent_at_start": session.get(
            "host_telemetry_at_start", {}
        ).get("battery_percent"),
        "accepted": accepted,
    }


def judge(
    preregistration_path: str | Path,
    report_paths: Sequence[str | Path],
    thermal_paths: Sequence[str | Path],
    output_path: str | Path,
) -> dict[str, Any]:
    preregistration, preregistration_sha256 = verify_evidence(
        preregistration_path
    )
    design = preregistration["design"]
    expected_blocks = int(design["blocks"])
    if len(report_paths) != expected_blocks or len(thermal_paths) != expected_blocks:
        raise SchedulerAblationError("todos os três blocos e sessões são obrigatórios")
    reports_by_block: dict[int, tuple[dict[str, Any], str]] = {}
    for path in report_paths:
        report, digest = verify_evidence(path)
        if report.get("protocol") != ABLATION_BLOCK_PROTOCOL:
            raise SchedulerAblationError("protocolo de bloco desconhecido")
        if report.get("preregistration_sha256") != preregistration_sha256:
            raise SchedulerAblationError("bloco não pertence ao pré-registro")
        block = int(report["block"])
        if block in reports_by_block:
            raise SchedulerAblationError("bloco duplicado")
        if report["orders"] != design["schedule"][block]["orders"]:
            raise SchedulerAblationError("ordem medida diverge do pré-registro")
        reports_by_block[block] = (report, digest)
    if set(reports_by_block) != set(range(expected_blocks)):
        raise SchedulerAblationError("sequência de blocos incompleta")

    thermal_by_session: dict[str, dict[str, Any]] = {}
    for path in thermal_paths:
        session, _ = verify_thermal_evidence(Path(path))
        session_id = str(session.get("session_id"))
        if session_id in thermal_by_session:
            raise SchedulerAblationError("sessão térmica duplicada")
        thermal_by_session[session_id] = _verify_thermal_session(
            Path(path), session_id
        )

    ratios_by_block: list[list[float]] = []
    fixed_values: list[float] = []
    adaptive_values: list[float] = []
    block_documents: list[dict[str, Any]] = []
    all_quality_passed = True
    all_thermal_accepted = True
    observed_power_states: set[bool] = set()
    for block in range(expected_blocks):
        report, digest = reports_by_block[block]
        expected_session_id = design["schedule"][block]["session_id"]
        thermal = thermal_by_session.get(expected_session_id)
        if thermal is None or not thermal["accepted"]:
            all_thermal_accepted = False
        elif thermal["power_plugged_at_start"] is None:
            all_thermal_accepted = False
        else:
            observed_power_states.add(bool(thermal["power_plugged_at_start"]))
        quality = all(
            report["variants"][name]["parity"]["passed"] is True
            for name in VARIANTS
        )
        all_quality_passed = all_quality_passed and quality
        block_ratios: list[float] = []
        for sample in report["samples"]:
            fixed = float(
                sample["measurements"][VARIANT_FIXED]["wall_ns_per_invocation"]
            )
            adaptive = float(
                sample["measurements"][VARIANT_ADAPTIVE]["wall_ns_per_invocation"]
            )
            if not all(math.isfinite(item) and item > 0 for item in (fixed, adaptive)):
                raise SchedulerAblationError("amostra não finita ou não positiva")
            fixed_values.append(fixed)
            adaptive_values.append(adaptive)
            block_ratios.append(fixed / adaptive)
        ratios_by_block.append(block_ratios)
        block_documents.append(
            {
                "block": block,
                "report_sha256": digest,
                "session_id": expected_session_id,
                "thermal": thermal,
                "paired_ratio_median": statistics.median(block_ratios),
            }
        )

    ratios = [item for block in ratios_by_block for item in block]
    median_ratio = statistics.median(ratios)
    ci95_low, ci95_high = hierarchical_bootstrap(
        ratios_by_block,
        resamples=int(design["bootstrap_resamples"]),
        seed=int(design["bootstrap_seed"]),
    )
    fixed_cv = coefficient_of_variation(fixed_values)
    adaptive_cv = coefficient_of_variation(adaptive_values)
    classification = classify_statistics(
        median_ratio=median_ratio,
        ci95_low=ci95_low,
        ci95_high=ci95_high,
        fixed_cv=fixed_cv,
        adaptive_cv=adaptive_cv,
        max_cv=float(design["max_coefficient_of_variation"]),
        practical_effect=float(design["practical_effect"]),
        equivalence_margin=float(design["equivalence_margin"]),
    )
    same_power_state = len(observed_power_states) == 1
    if not same_power_state:
        all_thermal_accepted = False
    if not all_quality_passed or not all_thermal_accepted:
        classification = "INVALID"
    document: dict[str, Any] = {
        "protocol": ABLATION_VERDICT_PROTOCOL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistration_sha256": preregistration_sha256,
        "classification": classification,
        "quality": {
            "all_parity_passed": all_quality_passed,
            "all_thermal_sessions_accepted": all_thermal_accepted,
            "same_power_state_across_blocks": same_power_state,
            "complete_blocks": len(block_documents) == expected_blocks,
        },
        "statistics": {
            "blocks": expected_blocks,
            "paired_samples": len(ratios),
            "median_fixed_over_adaptive": median_ratio,
            "hierarchical_bootstrap_ci95": [ci95_low, ci95_high],
            "fixed_coefficient_of_variation": fixed_cv,
            "adaptive_coefficient_of_variation": adaptive_cv,
            "max_coefficient_of_variation": design[
                "max_coefficient_of_variation"
            ],
            "practical_effect": design["practical_effect"],
            "equivalence_margin": design["equivalence_margin"],
        },
        "blocks": block_documents,
        "interpretation": {
            "ratio_above_one_favors": VARIANT_ADAPTIVE,
            "selected_policy": (
                VARIANT_ADAPTIVE
                if classification == "ADAPTIVE"
                else VARIANT_FIXED
                if classification == "FIXED"
                else None
            ),
            "claim_eligible": False,
            "energy_joules": None,
            "external_backend_comparison": False,
        },
        "claim": None,
    }
    _write_immutable_json(Path(output_path), document)
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casulo-ablation")
    commands = parser.add_subparsers(dest="command", required=True)
    preregister = commands.add_parser("preregister")
    preregister.add_argument("graph")
    preregister.add_argument("--output", required=True)
    preregister.add_argument("--wrt", nargs="+", required=True)
    preregister.add_argument("--loss")
    preregister.add_argument("--supersedes")

    run = commands.add_parser("run-block")
    run.add_argument("preregistration")
    run.add_argument("graph")
    run.add_argument("--block", type=int, required=True)
    run.add_argument("--output", required=True)

    adjudicate = commands.add_parser("judge")
    adjudicate.add_argument("preregistration")
    adjudicate.add_argument("--reports", nargs="+", required=True)
    adjudicate.add_argument("--thermal", nargs="+", required=True)
    adjudicate.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preregister":
        document = create_preregistration(
            args.graph,
            args.output,
            wrt=args.wrt,
            loss=args.loss,
            supersedes_path=args.supersedes,
        )
        result = {
            "ok": True,
            "protocol": document["protocol"],
            "blocks": document["design"]["blocks"],
            "pairs_per_block": document["design"]["pairs_per_block"],
            "claim": None,
        }
    elif args.command == "run-block":
        document = run_block(
            args.preregistration,
            args.graph,
            args.output,
            block=args.block,
        )
        result = {
            "ok": True,
            "protocol": document["protocol"],
            "block": document["block"],
            "pairs": len(document["samples"]),
            "parity": {
                name: document["variants"][name]["parity"]["status"]
                for name in VARIANTS
            },
            "claim": None,
        }
    else:
        document = judge(
            args.preregistration,
            args.reports,
            args.thermal,
            args.output,
        )
        result = {
            "ok": document["classification"] in {
                "ADAPTIVE",
                "FIXED",
                "EQUIVALENT",
            },
            "classification": document["classification"],
            "statistics": document["statistics"],
            "claim": None,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
