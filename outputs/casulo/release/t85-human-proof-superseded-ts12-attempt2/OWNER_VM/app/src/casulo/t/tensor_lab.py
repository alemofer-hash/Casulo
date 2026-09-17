"""Laboratório científico pré-registrado para o backend CPU tensorial.

O runner mede; o juiz classifica. Nenhuma função deste módulo escolhe
parâmetros depois de observar o resultado.
"""

from __future__ import annotations

import gc
import hashlib
import html
import json
import math
import os
import platform
import random
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .autograd import MetamorfoseAutogradIR, compile_autograd_file
from .linear_algebra import GemmProviderDescriptor
from .measurement import (
    MEASUREMENT_STABILITY_PROTOCOL,
    calibrate_shared_iterations,
    coefficient_of_variation,
    cpu_affinity_scope,
    system_telemetry_snapshot,
)
from .parity import (
    NumpyTensorExecutor,
    compare_executions,
    run_pytorch_parity,
)
from .pytorch_runtime import (
    configure_pytorch_inductor,
    prepare_pytorch_inductor_runtime,
)
from .scientific import SCIENTIFIC_COVENANT_PROTOCOL, SCIENTIFIC_INVARIANTS
from .tensor import TensorDType
from .tensor_cpu import (
    DEFAULT_ARENA_BUDGET_BYTES,
    TENSOR_CPU_BACKEND,
    TensorCpuUnavailable,
    _load_tensor_cpu_library,
    _native_execution,
    _prepare_native_call,
    compile_tensor_cpu_artifact,
    generate_tensor_cpu_artifact,
    plan_tensor_cpu,
    TensorCpuProviderChoice,
)


TENSOR_LAB_PREREGISTRATION_PROTOCOL = (
    "casulo-tensor-lab-preregistration/0.2"
)
TENSOR_LAB_REPORT_PROTOCOL = "casulo-tensor-lab-report/0.2"
TENSOR_LAB_VERDICT_PROTOCOL = "casulo-tensor-lab-verdict/0.2"
TENSOR_LAB_INPUT_PROTOCOL = "casulo-tensor-lab-input/0.1"
TENSOR_LAB_BACKEND_CASULO = TENSOR_CPU_BACKEND
TENSOR_LAB_BACKEND_EAGER = "pytorch-eager-autograd-cpu"
TENSOR_LAB_BACKEND_INDUCTOR = "pytorch-inductor-autograd-cpu"
TENSOR_LAB_BASELINES = (
    TENSOR_LAB_BACKEND_EAGER,
    TENSOR_LAB_BACKEND_INDUCTOR,
)
_MEASUREMENT_ORDERS = (
    (
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_EAGER,
        TENSOR_LAB_BACKEND_INDUCTOR,
    ),
    (
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_INDUCTOR,
        TENSOR_LAB_BACKEND_EAGER,
    ),
    (
        TENSOR_LAB_BACKEND_EAGER,
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_INDUCTOR,
    ),
    (
        TENSOR_LAB_BACKEND_EAGER,
        TENSOR_LAB_BACKEND_INDUCTOR,
        TENSOR_LAB_BACKEND_CASULO,
    ),
    (
        TENSOR_LAB_BACKEND_INDUCTOR,
        TENSOR_LAB_BACKEND_CASULO,
        TENSOR_LAB_BACKEND_EAGER,
    ),
    (
        TENSOR_LAB_BACKEND_INDUCTOR,
        TENSOR_LAB_BACKEND_EAGER,
        TENSOR_LAB_BACKEND_CASULO,
    ),
)


class TensorLabError(RuntimeError):
    """Falha verificável do laboratório tensorial."""


class TensorLabPreregistrationError(TensorLabError):
    """Pré-registro ausente, divergente ou adulterado."""


class TensorLabVerdictError(TensorLabError):
    """Evidência incapaz de sustentar um veredito verificável."""


@dataclass(frozen=True, slots=True)
class TensorLabPreregistration:
    path: Path
    experiment_id: str
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TensorLabReport:
    directory: Path
    json_path: Path
    html_path: Path
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TensorLabVerdict:
    path: Path
    classification: str
    document: dict[str, Any]


def create_tensor_lab_preregistration(
    graph_path: str | Path,
    output_path: str | Path,
    *,
    wrt: Iterable[str],
    loss: str | None = None,
    samples: int = 21,
    warmups: int = 3,
    inner_iterations: int = 100,
    workers: int = 1,
    gemm_workers: int | None = None,
    provider: TensorCpuProviderChoice = "owned",
    seed: int = 20_260_730,
    bootstrap_resamples: int = 2_000,
    arena_budget_bytes: int = DEFAULT_ARENA_BUDGET_BYTES,
    required_baselines: Iterable[str] = TENSOR_LAB_BASELINES,
    superiority_threshold: float = 1.0,
    commercial_threshold: float = 6.0,
    prior_exploratory_disclosure: str | None = None,
    prior_same_design_observed: bool = False,
    claim_eligible: bool = True,
    target_sample_wall_ms: float = 250.0,
    maximum_inner_iterations: int = 1_000_000,
    cooldown_ms: int = 0,
    cpu_affinity: Iterable[int] | None = None,
    max_coefficient_of_variation: float = 0.15,
) -> TensorLabPreregistration:
    graph = Path(graph_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise TensorLabPreregistrationError(
            f"pré-registro já existe e é imutável: {output}"
        )
    if samples < 7 or warmups < 1 or inner_iterations < 1:
        raise TensorLabPreregistrationError(
            "desenho exige ao menos 7 amostras, 1 warmup e 1 iteração"
        )
    if bootstrap_resamples < 200:
        raise TensorLabPreregistrationError(
            "bootstrap exige ao menos 200 reamostragens"
        )
    if workers not in {1, 2, 4}:
        raise TensorLabPreregistrationError("workers precisa ser 1, 2 ou 4")
    if prior_same_design_observed and not prior_exploratory_disclosure:
        raise TensorLabPreregistrationError(
            "observação prévia do mesmo desenho exige declaração explícita"
        )
    if superiority_threshold <= 0 or commercial_threshold <= 0:
        raise TensorLabPreregistrationError(
            "limiares precisam ser positivos"
        )
    if (
        not math.isfinite(target_sample_wall_ms)
        or target_sample_wall_ms <= 0
        or maximum_inner_iterations < inner_iterations
        or cooldown_ms < 0
        or not math.isfinite(max_coefficient_of_variation)
        or max_coefficient_of_variation <= 0
    ):
        raise TensorLabPreregistrationError(
            "desenho de estabilidade metrológica inválido"
        )
    affinity = (
        list(dict.fromkeys(int(item) for item in cpu_affinity))
        if cpu_affinity is not None
        else None
    )
    if affinity is not None and (
        not affinity or any(item < 0 for item in affinity)
    ):
        raise TensorLabPreregistrationError(
            "afinidade de CPU precisa conter índices não negativos"
        )
    baselines = tuple(dict.fromkeys(required_baselines))
    if not baselines or set(baselines) - set(TENSOR_LAB_BASELINES):
        raise TensorLabPreregistrationError(
            "baseline tensorial desconhecido"
        )
    wrt_names = tuple(dict.fromkeys(wrt))
    if not wrt_names:
        raise TensorLabPreregistrationError("ao menos um wrt é obrigatório")
    autograd = compile_autograd_file(
        graph,
        wrt=wrt_names,
        loss=loss,
    )
    plan = plan_tensor_cpu(
        autograd,
        arena_budget_bytes=arena_budget_bytes,
        workers=workers,
        gemm_workers=gemm_workers,
        provider=provider,
    )
    if not plan.eligible:
        raise TensorLabPreregistrationError(
            f"grafo não é elegível ao backend candidato: {plan.reason}"
        )
    gemm_provider = _gemm_provider_from_plan(plan)
    body: dict[str, Any] = {
        "protocol": TENSOR_LAB_PREREGISTRATION_PROTOCOL,
        "covenant": {
            "protocol": SCIENTIFIC_COVENANT_PROTOCOL,
            "invariants": list(SCIENTIFIC_INVARIANTS),
        },
        "brand": {
            "invention": "Casulo",
            "origin": "Teloscorp",
            "specialty": "Otimização de Tráfego de Informação",
        },
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "observed_results_at_registration": False,
        "prior_exploratory_observations": {
            "present": prior_exploratory_disclosure is not None,
            "same_registered_design_observed": bool(
                prior_same_design_observed
            ),
            "disclosure": prior_exploratory_disclosure,
        },
        "trusted_external_timestamp": False,
        "timestamp_limitation": (
            "integridade é sustentada por SHA-256 e ordem pelo histórico Git; "
            "não existe carimbo externo confiável nesta versão"
        ),
        "hypothesis": {
            "phase": (
                "CONFIRMATORY_REPLICATION_AFTER_EXPLORATION"
                if prior_same_design_observed
                else "PREREGISTERED_UNOBSERVED_DESIGN"
            ),
            "purpose": (
                "CLAIM_ELIGIBLE_CONFIRMATORY"
                if claim_eligible
                else "EXPLORATORY_OR_SMOKE_TEST"
            ),
            "claim_eligible": bool(claim_eligible),
            "candidate": TENSOR_LAB_BACKEND_CASULO,
            "primary_metric": "paired_steady_state_wall_speedup_median",
            "direction": "greater_than",
            "superiority_threshold": float(superiority_threshold),
            "commercial_threshold": float(commercial_threshold),
            "must_pass_every_required_baseline": True,
            "quality_precedes_speed": True,
        },
        "design": {
            "graph": {
                "path_hint": graph.name,
                "sha256": _normalized_text_sha256(graph),
                "autograd_graph_sha256": plan.graph_sha256,
            },
            "wrt": list(wrt_names),
            "loss": autograd.loss,
            "inputs": _input_contract(autograd),
            "input_generator": {
                "protocol": TENSOR_LAB_INPUT_PROTOCOL,
                "algorithm": "numpy-pcg64-normal",
                "seed": int(seed),
                "weight_scale": 0.1,
            },
            "samples": int(samples),
            "warmups": int(warmups),
            "inner_iterations": int(inner_iterations),
            "measurement_calibration": {
                "protocol": MEASUREMENT_STABILITY_PROTOCOL,
                "algorithm": "per-backend-doubling-then-shared-maximum",
                "uses_speedup_or_winner_selection": False,
                "target_wall_ms": float(target_sample_wall_ms),
                "minimum_inner_iterations": int(inner_iterations),
                "maximum_inner_iterations": int(
                    maximum_inner_iterations
                ),
            },
            "cpu_affinity": affinity,
            "cooldown_ms": int(cooldown_ms),
            "max_coefficient_of_variation": float(
                max_coefficient_of_variation
            ),
            "telemetry_policy": {
                "before_and_after_each_sample": True,
                "outside_timing_boundary": True,
                "temperature_may_be_unavailable": True,
            },
            "workers": int(workers),
            "gemm_workers": int(plan.gemm_workers),
            "gemm_provider": gemm_provider.to_dict(),
            "torch_threads": int(workers),
            "seed": int(seed),
            "bootstrap_resamples": int(bootstrap_resamples),
            "arena_budget_bytes": int(arena_budget_bytes),
            "pairing": "same-input-same-process-same-sample-index",
            "order_policy": "balanced-six-permutation-cycle",
            "required_baselines": list(baselines),
            "candidate_backend": TENSOR_LAB_BACKEND_CASULO,
            "measurement_boundary": (
                "prepared forward plus backward; compilation, preparation, "
                "validation and report generation excluded"
            ),
            "memory_probe": (
                "separate-phase-process-rss-sampling-not-in-timing-samples"
            ),
            "implementation": _implementation_identity(),
        },
        "quality_gates": {
            "native_vs_numpy": "PASS",
            "numpy_vs_pytorch_eager": "PASS",
            "inductor_vs_numpy_loss_and_gradients": "PASS",
            "same_graph": True,
            "same_inputs": True,
            "same_dtype": True,
            "same_workers_or_threads": True,
            "finite_samples": True,
        },
        "secondary_metrics": [
            "paired_cpu_speedup_median",
            "compilation_wall_ns",
            "preparation_wall_ns",
            "observed_process_rss_peak_bytes",
            "break_even_invocations",
        ],
        "energy_policy": {
            "required_for_primary_verdict": False,
            "unmeasured_value": None,
            "software_estimates_forbidden": True,
        },
        "classification": {
            "POSITIVE": (
                "qualidade válida e IC95% inferior acima de 1 em todos os "
                "baselines obrigatórios"
            ),
            "NULL": (
                "qualidade válida, nenhum baseline refuta, mas ao menos um "
                "intervalo cruza 1"
            ),
            "NEGATIVE": (
                "qualidade válida e ao menos um IC95% superior abaixo de 1"
            ),
            "INCONCLUSIVE": "baseline ou evidência obrigatória ausente",
            "INVALID": "integridade, desenho ou equivalência violados",
        },
        "result_policy": {
            "selection": "all-preregistered-samples",
            "failed_runs_are_evidence": True,
            "overwrite": False,
            "correction": "new-version-new-preregistration-new-result",
        },
    }
    seal = _body_seal(body)
    document = {
        **body,
        "experiment_id": f"sha256:{seal}",
        "seal": {
            "algorithm": "sha256",
            "canonical_body_sha256": seal,
        },
    }
    _write_new_json(output, document)
    return TensorLabPreregistration(
        path=output,
        experiment_id=document["experiment_id"],
        document=document,
    )


def verify_tensor_lab_preregistration(
    path: str | Path,
) -> TensorLabPreregistration:
    source = Path(path).expanduser().resolve()
    document = json.loads(source.read_text(encoding="utf-8"))
    if document.get("protocol") != TENSOR_LAB_PREREGISTRATION_PROTOCOL:
        raise TensorLabPreregistrationError(
            "protocolo de pré-registro tensorial desconhecido"
        )
    seal = document.get("seal", {})
    if seal.get("algorithm") != "sha256":
        raise TensorLabPreregistrationError("algoritmo de selo inválido")
    body = {
        key: value
        for key, value in document.items()
        if key not in {"experiment_id", "seal"}
    }
    actual = _body_seal(body)
    if seal.get("canonical_body_sha256") != actual:
        raise TensorLabPreregistrationError(
            "pré-registro tensorial adulterado"
        )
    if document.get("experiment_id") != f"sha256:{actual}":
        raise TensorLabPreregistrationError(
            "identidade do pré-registro tensorial inválida"
        )
    if document.get("observed_results_at_registration") is not False:
        raise TensorLabPreregistrationError(
            "pré-registro contaminado por resultado observado"
        )
    return TensorLabPreregistration(
        path=source,
        experiment_id=document["experiment_id"],
        document=document,
    )


def run_tensor_lab(
    graph_path: str | Path,
    preregistration_path: str | Path,
    output_directory: str | Path,
) -> TensorLabReport:
    graph = Path(graph_path).expanduser().resolve()
    preregistration = verify_tensor_lab_preregistration(
        preregistration_path
    )
    output = Path(output_directory).expanduser().resolve()
    report_path = output / "tensor-lab-report.json"
    html_path = output / "tensor-lab-report.html"
    if report_path.exists() or html_path.exists():
        raise TensorLabError(
            f"resultado já existe e é imutável: {output}"
        )
    design = preregistration.document["design"]
    autograd = compile_autograd_file(
        graph,
        wrt=tuple(design["wrt"]),
        loss=design["loss"],
    )
    _bind_preregistration(preregistration, graph, autograd)
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "native-cache"
    previous_cache = os.environ.get("CASULO_NATIVE_CACHE")
    os.environ["CASULO_NATIVE_CACHE"] = str(cache)
    try:
        with cpu_affinity_scope(design.get("cpu_affinity")) as affinity:
            document = _run_bound_tensor_lab(
                autograd,
                preregistration,
                graph,
                affinity_state=affinity,
            )
    finally:
        if previous_cache is None:
            os.environ.pop("CASULO_NATIVE_CACHE", None)
        else:
            os.environ["CASULO_NATIVE_CACHE"] = previous_cache
    _write_new_json(report_path, document)
    html_path.write_text(
        _render_report_html(document),
        encoding="utf-8",
        newline="\n",
    )
    return TensorLabReport(
        directory=output,
        json_path=report_path,
        html_path=html_path,
        document=document,
    )


def judge_tensor_lab(
    preregistration_path: str | Path,
    report_path: str | Path,
    output_path: str | Path,
) -> TensorLabVerdict:
    preregistration = verify_tensor_lab_preregistration(
        preregistration_path
    )
    report_file = Path(report_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise TensorLabVerdictError(
            f"veredito já existe e é imutável: {output}"
        )
    report = json.loads(report_file.read_text(encoding="utf-8"))
    failures: list[str] = []
    if report.get("protocol") != TENSOR_LAB_REPORT_PROTOCOL:
        failures.append("UNKNOWN_TENSOR_LAB_REPORT_PROTOCOL")
    scientific = report.get("scientific", {})
    if scientific.get("experiment_id") != preregistration.experiment_id:
        failures.append("REPORT_NOT_BOUND_TO_PREREGISTRATION")
    design = preregistration.document["design"]
    if scientific.get("bound_design") != _bound_design(design):
        failures.append("REPORT_DESIGN_DIVERGES_FROM_PREREGISTRATION")
    backend_status = report.get("backends", {})
    missing_baselines = [
        baseline
        for baseline in design["required_baselines"]
        if backend_status.get(baseline, {}).get("status") != "AVAILABLE"
    ]
    quality = report.get("quality", {})
    required_quality = preregistration.document["quality_gates"]
    quality_failures = [
        key
        for key, expected in required_quality.items()
        if quality.get(key) != expected
        and not (
            key == "inductor_vs_numpy_loss_and_gradients"
            and TENSOR_LAB_BACKEND_INDUCTOR in missing_baselines
        )
    ]
    samples = report.get("samples", [])
    expected_samples = int(design["samples"])
    if len(samples) != expected_samples:
        failures.append("SAMPLE_COUNT_DIVERGES_FROM_PREREGISTRATION")
    expected_backends = {
        TENSOR_LAB_BACKEND_CASULO,
        *(
            baseline
            for baseline in design["required_baselines"]
            if baseline not in missing_baselines
        ),
    }
    for index, sample in enumerate(samples):
        expected_order = [
            backend
            for backend in _MEASUREMENT_ORDERS[
                index % len(_MEASUREMENT_ORDERS)
            ]
            if backend in expected_backends
        ]
        if sample.get("index") != index:
            failures.append("SAMPLE_INDEX_INVALID")
        if sample.get("order") != expected_order:
            failures.append("MEASUREMENT_ORDER_DIVERGES")
        observed = sample.get("measurements", {})
        if set(observed) != expected_backends:
            failures.append("PAIRED_BACKENDS_INVALID")
        for measurement in observed.values():
            if (
                not isinstance(measurement.get("wall_ns"), int)
                or measurement["wall_ns"] <= 0
                or not isinstance(measurement.get("cpu_ns"), int)
                or measurement["cpu_ns"] < 0
            ):
                failures.append("NON_FINITE_OR_INVALID_SAMPLE")
            if "measurement_calibration" in design and (
                measurement.get("inner_iterations")
                != report.get("measurement_stability", {}).get(
                    "selected_inner_iterations"
                )
            ):
                failures.append(
                    "MEASURED_ITERATIONS_DIVERGE_FROM_CALIBRATION"
                )
    stability_failures: list[str] = []
    if "measurement_calibration" in design:
        stability = report.get("measurement_stability", {})
        calibration = stability.get("calibration", {})
        if (
            stability.get("protocol") != MEASUREMENT_STABILITY_PROTOCOL
            or calibration.get("protocol")
            != MEASUREMENT_STABILITY_PROTOCOL
        ):
            failures.append("MEASUREMENT_STABILITY_PROTOCOL_INVALID")
        if calibration.get("uses_speedup_or_winner_selection") is not False:
            failures.append("CALIBRATION_USES_RESULT_SELECTION")
        if calibration.get("all_backends_reached_target") is not True:
            stability_failures.append(
                "CALIBRATION_TARGET_NOT_REACHED_BY_ALL_BACKENDS"
            )
        selected_iterations = stability.get("selected_inner_iterations")
        if (
            not isinstance(selected_iterations, int)
            or selected_iterations
            < int(
                design["measurement_calibration"][
                    "minimum_inner_iterations"
                ]
            )
            or selected_iterations
            > int(
                design["measurement_calibration"][
                    "maximum_inner_iterations"
                ]
            )
        ):
            failures.append("CALIBRATED_ITERATIONS_OUT_OF_BOUNDS")
        max_cv = float(design["max_coefficient_of_variation"])
        for backend in expected_backends:
            values = [
                float(sample["measurements"][backend]["wall_ns"])
                / float(
                    sample["measurements"][backend]["inner_iterations"]
                )
                for sample in samples
                if backend in sample.get("measurements", {})
                and sample["measurements"][backend].get(
                    "inner_iterations"
                )
            ]
            observed_cv = coefficient_of_variation(values)
            reported_cv = stability.get(
                "coefficient_of_variation", {}
            ).get(backend)
            if observed_cv is None or not _close(reported_cv, observed_cv):
                failures.append(f"REPORTED_CV_DIVERGES:{backend}")
            elif observed_cv > max_cv:
                stability_failures.append(
                    f"COEFFICIENT_OF_VARIATION_EXCEEDED:{backend}"
                )
    metrics: dict[str, Any] = {}
    baseline_classes: dict[str, str] = {}
    for baseline in design["required_baselines"]:
        if baseline in missing_baselines:
            metrics[baseline] = None
            baseline_classes[baseline] = "INCONCLUSIVE"
            continue
        ratios = _paired_ratios(samples, baseline)
        if len(ratios) != expected_samples:
            failures.append(f"RAW_SAMPLE_INVALID:{baseline}")
            metrics[baseline] = None
            baseline_classes[baseline] = "INVALID"
            continue
        seed = int(design["seed"]) ^ _stable_seed(baseline)
        lower, upper = _bootstrap_median_ci(
            ratios,
            seed=seed,
            resamples=10_000,
        )
        median = statistics.median(ratios)
        reported = report.get("comparisons", {}).get(baseline, {})
        if not _close(reported.get("wall_speedup_median"), median):
            failures.append(f"REPORTED_MEDIAN_DIVERGES:{baseline}")
        threshold = float(
            preregistration.document["hypothesis"][
                "superiority_threshold"
            ]
        )
        baseline_class = (
            "POSITIVE"
            if lower > threshold
            else "NEGATIVE"
            if upper < threshold
            else "NULL"
        )
        baseline_classes[baseline] = baseline_class
        metrics[baseline] = {
            "paired_samples": len(ratios),
            "wall_speedup_median": median,
            "independent_bootstrap_ci95": {
                "lower": lower,
                "upper": upper,
                "resamples": 10_000,
                "method": "independent-python-bootstrap-median",
            },
            "classification": baseline_class,
        }
    energy = report.get("energy", {})
    if energy.get("measured") is False and energy.get("joules") is not None:
        failures.append("UNMEASURED_ENERGY_HAS_VALUE")
    failures = sorted(set(failures))
    stability_failures = sorted(set(stability_failures))
    if failures or quality_failures:
        classification = "INVALID"
    elif missing_baselines or stability_failures:
        classification = "INCONCLUSIVE"
    elif any(value == "NEGATIVE" for value in baseline_classes.values()):
        classification = "NEGATIVE"
    elif all(value == "POSITIVE" for value in baseline_classes.values()):
        classification = "POSITIVE"
    else:
        classification = "NULL"
    commercial_threshold = float(
        preregistration.document["hypothesis"]["commercial_threshold"]
    )
    claim_eligible = bool(
        preregistration.document["hypothesis"]["claim_eligible"]
    )
    commercial_gate = bool(
        claim_eligible
        and classification == "POSITIVE"
        and all(
            metric is not None
            and metric["independent_bootstrap_ci95"]["lower"]
            >= commercial_threshold
            for metric in metrics.values()
        )
    )
    scope = {
        "graph_sha256": design["graph"]["sha256"],
        "autograd_graph_sha256": design["graph"][
            "autograd_graph_sha256"
        ],
        "dtype": sorted(
            {item["dtype"] for item in design["inputs"]}
        ),
        "workers": design["workers"],
        "gemm_workers": design["gemm_workers"],
        "gemm_provider": design["gemm_provider"],
        "inner_iterations": design["inner_iterations"],
        "selected_inner_iterations": report.get(
            "measurement_stability", {}
        ).get("selected_inner_iterations", design["inner_iterations"]),
        "max_coefficient_of_variation": design.get(
            "max_coefficient_of_variation"
        ),
        "cpu_affinity": design.get("cpu_affinity"),
        "hypothesis_phase": preregistration.document["hypothesis"]["phase"],
        "claim_eligible": claim_eligible,
        "machine": report.get("environment", {}).get("platform"),
        "processor": report.get("environment", {}).get("processor"),
        "required_baselines": list(design["required_baselines"]),
    }
    body = {
        "protocol": TENSOR_LAB_VERDICT_PROTOCOL,
        "covenant": SCIENTIFIC_COVENANT_PROTOCOL,
        "experiment_id": preregistration.experiment_id,
        "classification": classification,
        "judge": {
            "can_modify_experiment": False,
            "recomputed_from_raw_samples": True,
            "implementation": "python-standard-library",
        },
        "evidence": {
            "preregistration_file_sha256": _file_sha256(
                preregistration.path
            ),
            "report_file_sha256": _file_sha256(report_file),
            "observed_baselines": sorted(
                set(design["required_baselines"]) - set(missing_baselines)
            ),
            "missing_required_baselines": missing_baselines,
            "integrity_failures": failures,
            "quality_failures": quality_failures,
            "stability_failures": stability_failures,
        },
        "recomputed_metrics": metrics,
        "baseline_classifications": baseline_classes,
        "commercial_threshold": commercial_threshold,
        "commercial_gate": commercial_gate,
        "claim_eligible": claim_eligible,
        "claim": (
            _scope_bound_claim(metrics, scope)
            if classification == "POSITIVE" and claim_eligible
            else None
        ),
        "scope": scope,
        "interpretation": _verdict_interpretation(
            classification,
            missing_baselines,
            failures,
            quality_failures,
            stability_failures,
        ),
        "energy": {
            "measured": energy.get("measured", False),
            "joules": energy.get("joules"),
        },
    }
    seal = _body_seal(body)
    document = {
        **body,
        "verdict_id": f"sha256:{seal}",
        "seal": {
            "algorithm": "sha256",
            "canonical_body_sha256": seal,
        },
    }
    _write_new_json(output, document)
    return TensorLabVerdict(
        path=output,
        classification=classification,
        document=document,
    )


def verify_tensor_lab_chain(
    preregistration_path: str | Path,
    report_path: str | Path,
    verdict_path: str | Path,
) -> list[str]:
    preregistration = verify_tensor_lab_preregistration(
        preregistration_path
    )
    report_file = Path(report_path).expanduser().resolve()
    verdict_file = Path(verdict_path).expanduser().resolve()
    report = json.loads(report_file.read_text(encoding="utf-8"))
    verdict = _verify_sealed_document(
        verdict_file,
        protocol=TENSOR_LAB_VERDICT_PROTOCOL,
        identifier="verdict_id",
    )
    checks: list[str] = []
    if report.get("scientific", {}).get(
        "experiment_id"
    ) != preregistration.experiment_id:
        raise TensorLabVerdictError(
            "relatório pertence a outro pré-registro"
        )
    if verdict.get("experiment_id") != preregistration.experiment_id:
        raise TensorLabVerdictError(
            "veredito pertence a outro pré-registro"
        )
    checks.append("pré-registro, relatório e veredito possuem uma identidade")
    if verdict["evidence"]["preregistration_file_sha256"] != _file_sha256(
        preregistration.path
    ):
        raise TensorLabVerdictError("hash do pré-registro diverge")
    if verdict["evidence"]["report_file_sha256"] != _file_sha256(
        report_file
    ):
        raise TensorLabVerdictError("hash do relatório diverge")
    checks.append("hashes da cadeia coincidem")
    design = preregistration.document["design"]
    for baseline in design["required_baselines"]:
        if baseline in verdict["evidence"]["missing_required_baselines"]:
            continue
        ratios = _paired_ratios(report["samples"], baseline)
        seed = int(design["seed"]) ^ _stable_seed(baseline)
        lower, upper = _bootstrap_median_ci(
            ratios,
            seed=seed,
            resamples=10_000,
        )
        observed = verdict["recomputed_metrics"][baseline]
        if not _close(
            observed["wall_speedup_median"],
            statistics.median(ratios),
        ):
            raise TensorLabVerdictError(
                f"mediana adulterada para {baseline}"
            )
        if not _close(
            observed["independent_bootstrap_ci95"]["lower"],
            lower,
        ) or not _close(
            observed["independent_bootstrap_ci95"]["upper"],
            upper,
        ):
            raise TensorLabVerdictError(
                f"bootstrap adulterado para {baseline}"
            )
    checks.append("medianas e bootstrap foram reproduzidos das amostras")
    if (
        verdict["energy"]["measured"] is False
        and verdict["energy"]["joules"] is not None
    ):
        raise TensorLabVerdictError(
            "energia não medida possui valor inventado"
        )
    checks.append("energia não medida permanece null")
    if verdict["classification"] != _reclassify_verdict(verdict):
        raise TensorLabVerdictError(
            "classificação diverge das métricas e falhas"
        )
    expected_claim_eligible = bool(
        preregistration.document["hypothesis"]["claim_eligible"]
    )
    if verdict.get("claim_eligible") != expected_claim_eligible:
        raise TensorLabVerdictError(
            "elegibilidade de claim diverge do pré-registro"
        )
    if not expected_claim_eligible and (
        verdict.get("claim") is not None
        or verdict.get("commercial_gate") is not False
    ):
        raise TensorLabVerdictError(
            "ensaio inelegível liberou claim ou gate comercial"
        )
    checks.append("classificação deriva apenas das regras seladas")
    return checks


def _run_bound_tensor_lab(
    autograd: MetamorfoseAutogradIR,
    preregistration: TensorLabPreregistration,
    graph: Path,
    *,
    affinity_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    design = preregistration.document["design"]
    inputs = _generate_inputs(autograd, design["input_generator"])
    numpy_reference = NumpyTensorExecutor().execute(autograd, inputs)
    plan_started = time.perf_counter_ns()
    plan = plan_tensor_cpu(
        autograd,
        arena_budget_bytes=int(design["arena_budget_bytes"]),
        workers=int(design["workers"]),
        gemm_workers=int(design["gemm_workers"]),
        provider=GemmProviderDescriptor(**design["gemm_provider"]),
    )
    plan_wall_ns = time.perf_counter_ns() - plan_started
    if not plan.eligible:
        raise TensorCpuUnavailable(plan.reason or "plano inelegível")
    codegen_started = time.perf_counter_ns()
    artifact = generate_tensor_cpu_artifact(autograd, plan=plan)
    codegen_wall_ns = time.perf_counter_ns() - codegen_started
    compile_started = time.perf_counter_ns()
    build = compile_tensor_cpu_artifact(artifact)
    compile_total_wall_ns = time.perf_counter_ns() - compile_started
    native_prepare_started = time.perf_counter_ns()
    (
        prepared_inputs,
        observed,
        input_pointers,
        observed_pointers,
        arena,
    ) = _prepare_native_call(
        autograd,
        inputs,
        plan.arena_required_bytes or 0,
    )
    library, native_function = _load_tensor_cpu_library(build, plan)
    native_preparation_wall_ns = (
        time.perf_counter_ns() - native_prepare_started
    )

    def native_invoke() -> Any:
        status = native_function(
            input_pointers,
            observed_pointers,
            arena["pointer"],
            plan.arena_required_bytes or 0,
            plan.workers,
            0,
        )
        if status != 0:
            raise TensorLabError(f"backend nativo retornou status {status}")
        return observed

    status = native_function(
        input_pointers,
        observed_pointers,
        arena["pointer"],
        plan.arena_required_bytes or 0,
        plan.workers,
        1,
    )
    if status != 0:
        raise TensorLabError(f"backend nativo retornou status {status}")
    native_execution = _native_execution(
        autograd,
        observed,
        numpy_reference,
        build,
    )
    native_raw_parity = compare_executions(
        numpy_reference,
        native_execution,
        autograd,
    )
    eager_parity = run_pytorch_parity(autograd, inputs)
    torch_runtime = _prepare_torch_runners(
        autograd,
        inputs,
        threads=int(design["torch_threads"]),
    )
    inductor_quality = _validate_torch_result(
        autograd,
        numpy_reference,
        torch_runtime["inductor_first_result"],
    )
    quality = {
        "native_vs_numpy": native_raw_parity.status.value,
        "numpy_vs_pytorch_eager": eager_parity.status.value,
        "inductor_vs_numpy_loss_and_gradients": inductor_quality["status"],
        "same_graph": True,
        "same_inputs": True,
        "same_dtype": True,
        "same_workers_or_threads": (
            int(design["workers"]) == int(design["torch_threads"])
        ),
        "finite_samples": True,
        "details": {
            "native_vs_numpy": native_raw_parity.to_dict(),
            "numpy_vs_pytorch_eager": eager_parity.to_dict(),
            "inductor_vs_numpy": inductor_quality,
        },
    }
    runners: dict[str, Callable[[], Any]] = {
        TENSOR_LAB_BACKEND_CASULO: native_invoke,
        TENSOR_LAB_BACKEND_EAGER: torch_runtime["eager_invoke"],
    }
    backends: dict[str, Any] = {
        TENSOR_LAB_BACKEND_CASULO: {
            "status": "AVAILABLE",
            "version": TENSOR_CPU_BACKEND,
            "compilation": {
                "plan_wall_ns": plan_wall_ns,
                "codegen_wall_ns": codegen_wall_ns,
                "compiler_total_wall_ns": compile_total_wall_ns,
                "compiler_subprocess_wall_ns": build.compilation_wall_ns,
                "cache_hit": build.cache_hit,
            },
            "preparation_wall_ns": native_preparation_wall_ns,
            "arena_required_bytes": plan.arena_required_bytes,
            "workers": plan.workers,
            "gemm_workers": plan.gemm_workers,
            "gemm_provider": design["gemm_provider"],
            "compiler": build.to_dict(),
        },
        TENSOR_LAB_BACKEND_EAGER: {
            "status": "AVAILABLE",
            "version": torch_runtime["torch_version"],
            "compilation": None,
            "preparation_wall_ns": torch_runtime[
                "eager_preparation_wall_ns"
            ],
            "threads": int(design["torch_threads"]),
        },
        TENSOR_LAB_BACKEND_INDUCTOR: {
            "status": torch_runtime["inductor_status"],
            "version": torch_runtime["torch_version"],
            "compilation": {
                "wall_ns": torch_runtime["inductor_compilation_wall_ns"],
                "fullgraph": True,
                "backend": "inductor",
                "toolchain": torch_runtime["toolchain"],
            },
            "preparation_wall_ns": torch_runtime[
                "inductor_preparation_wall_ns"
            ],
            "threads": int(design["torch_threads"]),
            "error": torch_runtime["inductor_error"],
        },
    }
    if torch_runtime["inductor_status"] == "AVAILABLE":
        runners[TENSOR_LAB_BACKEND_INDUCTOR] = torch_runtime[
            "inductor_invoke"
        ]
    for _ in range(int(design["warmups"])):
        for backend in (
            TENSOR_LAB_BACKEND_CASULO,
            TENSOR_LAB_BACKEND_EAGER,
            TENSOR_LAB_BACKEND_INDUCTOR,
        ):
            if backend in runners:
                _measure_batch(
                    runners[backend],
                    int(design["inner_iterations"]),
                )
    calibration_design = design.get("measurement_calibration")
    if calibration_design is not None:
        selected_inner_iterations, calibration = (
            calibrate_shared_iterations(
                runners,
                minimum_iterations=int(
                    calibration_design["minimum_inner_iterations"]
                ),
                maximum_iterations=int(
                    calibration_design["maximum_inner_iterations"]
                ),
                target_wall_ms=float(
                    calibration_design["target_wall_ms"]
                ),
                measure=_measure_batch,
            )
        )
    else:
        selected_inner_iterations = int(design["inner_iterations"])
        calibration = {
            "protocol": None,
            "algorithm": "legacy-fixed-inner-iterations",
            "uses_speedup_or_winner_selection": False,
            "selected_shared_iterations": selected_inner_iterations,
            "all_backends_reached_target": None,
        }
    samples: list[dict[str, Any]] = []
    available = set(runners)
    for index in range(int(design["samples"])):
        cooldown_ms = int(design.get("cooldown_ms", 0))
        if cooldown_ms:
            time.sleep(cooldown_ms / 1_000)
        telemetry_before = system_telemetry_snapshot()
        order = [
            backend
            for backend in _MEASUREMENT_ORDERS[
                index % len(_MEASUREMENT_ORDERS)
            ]
            if backend in available
        ]
        measurements: dict[str, Any] = {}
        for backend in order:
            wall_ns, cpu_ns = _measure_batch(
                runners[backend],
                selected_inner_iterations,
            )
            measurements[backend] = {
                "wall_ns": wall_ns,
                "cpu_ns": cpu_ns,
                "inner_iterations": selected_inner_iterations,
                "wall_ns_per_invocation": (
                    wall_ns / selected_inner_iterations
                ),
                "cpu_ns_per_invocation": (
                    cpu_ns / selected_inner_iterations
                ),
            }
        telemetry_after = system_telemetry_snapshot()
        samples.append(
            {
                "index": index,
                "order": order,
                "measurements": measurements,
                "telemetry_before": telemetry_before,
                "telemetry_after": telemetry_after,
            }
        )
    finite_samples = all(
        measurement["wall_ns"] > 0
        and measurement["cpu_ns"] >= 0
        and math.isfinite(measurement["wall_ns_per_invocation"])
        for sample in samples
        for measurement in sample["measurements"].values()
    )
    quality["finite_samples"] = finite_samples
    comparisons = {
        baseline: _comparison(
            samples,
            baseline,
            seed=int(design["seed"]) ^ _stable_seed(baseline),
            resamples=int(design["bootstrap_resamples"]),
            backends=backends,
            inner_iterations=selected_inner_iterations,
        )
        for baseline in design["required_baselines"]
        if backends.get(baseline, {}).get("status") == "AVAILABLE"
    }
    memory = {
        backend: _memory_probe(
            runner,
            selected_inner_iterations,
        )
        for backend, runner in runners.items()
    }
    environment = _environment_snapshot(
        torch_runtime["torch_version"],
        build.compiler_version,
    )
    input_manifest = {
        "protocol": TENSOR_LAB_INPUT_PROTOCOL,
        "sha256": numpy_reference.input_sha256,
        "generator": dict(design["input_generator"]),
        "values": [
            {
                "name": item.name,
                "dtype": item.type.dtype.value,
                "shape": list(item.type.shape),
                "nbytes": item.type.nbytes,
            }
            for item in autograd.forward.inputs
        ],
    }
    variation = {
        backend: coefficient_of_variation(
            [
                float(
                    sample["measurements"][backend][
                        "wall_ns_per_invocation"
                    ]
                )
                for sample in samples
                if backend in sample["measurements"]
            ]
        )
        for backend in runners
    }
    measurement_stability = {
        "protocol": MEASUREMENT_STABILITY_PROTOCOL,
        "calibration": calibration,
        "selected_inner_iterations": selected_inner_iterations,
        "cooldown_ms": int(design.get("cooldown_ms", 0)),
        "max_coefficient_of_variation": design.get(
            "max_coefficient_of_variation"
        ),
        "coefficient_of_variation": variation,
        "affinity": dict(affinity_state or {}),
        "telemetry": system_telemetry_snapshot(static=True),
    }
    _ = prepared_inputs, library, arena["owner"], graph
    return {
        "protocol": TENSOR_LAB_REPORT_PROTOCOL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scientific": {
            "covenant": SCIENTIFIC_COVENANT_PROTOCOL,
            "status": "PREREGISTERED_AWAITING_INDEPENDENT_JUDGEMENT",
            "claims_allowed": False,
            "experiment_id": preregistration.experiment_id,
            "preregistration_file_sha256": _file_sha256(
                preregistration.path
            ),
            "bound_design": _bound_design(design),
        },
        "input": input_manifest,
        "environment": environment,
        "quality": quality,
        "backends": backends,
        "samples": samples,
        "comparisons": comparisons,
        "memory": memory,
        "measurement_stability": measurement_stability,
        "thermal": _thermal_snapshot(),
        "energy": {
            "measured": False,
            "joules": None,
            "method": None,
            "reason": "nenhum contador elétrico cumulativo foi integrado",
        },
        "claim": None,
    }


def _prepare_torch_runners(
    autograd: MetamorfoseAutogradIR,
    inputs: Mapping[str, Any],
    *,
    threads: int,
) -> dict[str, Any]:
    preparation_started = time.perf_counter_ns()
    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise TensorLabError(
            "NumPy e PyTorch são obrigatórios no laboratório"
        ) from exc
    torch.set_num_threads(threads)
    configure_pytorch_inductor(torch)
    input_types = {
        item.name: item.type
        for item in autograd.forward.inputs
    }
    names = [item.name for item in autograd.forward.inputs]
    tensor_inputs = tuple(
        torch.tensor(
            np.asarray(inputs[name]),
            dtype={
                TensorDType.FLOAT32: torch.float32,
                TensorDType.FLOAT64: torch.float64,
            }[input_types[name].dtype],
            device="cpu",
        )
        for name in names
    )
    wrt_indices = tuple(names.index(name) for name in autograd.wrt)

    def loss_function(*arguments: Any) -> Any:
        values = dict(zip(names, arguments, strict=True))
        for instruction in autograd.forward.instructions:
            args = [values[name] for name in instruction.inputs]
            operator = instruction.operator
            attributes = instruction.attributes
            if operator == "add":
                result = args[0] + args[1]
            elif operator == "sub":
                result = args[0] - args[1]
            elif operator == "mul":
                result = args[0] * args[1]
            elif operator == "div":
                result = args[0] / args[1]
            elif operator == "matmul":
                result = torch.matmul(args[0], args[1])
            elif operator == "relu":
                result = torch.relu(args[0])
            elif operator == "sigmoid":
                result = torch.sigmoid(args[0])
            elif operator == "tanh":
                result = torch.tanh(args[0])
            elif operator in {"sum", "mean"}:
                reducer = torch.sum if operator == "sum" else torch.mean
                axis = attributes.get("axis")
                result = (
                    reducer(args[0])
                    if axis is None
                    else reducer(
                        args[0],
                        dim=int(axis),
                        keepdim=bool(attributes.get("keepdim", False)),
                    )
                )
            elif operator == "reshape":
                result = torch.reshape(
                    args[0],
                    tuple(attributes["shape"]),
                )
            elif operator == "transpose":
                result = torch.swapaxes(
                    args[0],
                    int(attributes.get("axis0", -2)),
                    int(attributes.get("axis1", -1)),
                )
            else:
                raise TensorLabError(
                    f"runner PyTorch não suporta {operator}"
                )
            values[instruction.result] = result
        return values[autograd.loss].reshape(())

    transformed = torch.func.grad_and_value(
        loss_function,
        argnums=wrt_indices,
    )

    def eager_invoke() -> Any:
        return transformed(*tensor_inputs)

    eager_preparation_wall_ns = (
        time.perf_counter_ns() - preparation_started
    )
    toolchain = prepare_pytorch_inductor_runtime()
    inductor_preparation_started = time.perf_counter_ns()
    inductor_status = "UNAVAILABLE"
    inductor_error = None
    inductor_compilation_wall_ns = None
    inductor_first_result = None
    compiled = None
    try:
        if toolchain.get("status") == "UNAVAILABLE":
            raise TensorLabError(
                f"toolchain Inductor indisponível: {toolchain.get('error')}"
            )
        compiled = torch.compile(
            transformed,
            backend="inductor",
            fullgraph=True,
        )
        inductor_preparation_wall_ns = (
            time.perf_counter_ns() - inductor_preparation_started
        )
        compilation_started = time.perf_counter_ns()
        inductor_first_result = compiled(*tensor_inputs)
        inductor_compilation_wall_ns = (
            time.perf_counter_ns() - compilation_started
        )
        compiled(*tensor_inputs)
        inductor_status = "AVAILABLE"
    except Exception as exc:
        inductor_preparation_wall_ns = (
            time.perf_counter_ns() - inductor_preparation_started
        )
        inductor_error = {
            "type": type(exc).__name__,
            "message": _bounded_error(exc),
        }

    def inductor_invoke() -> Any:
        if compiled is None:
            raise TensorLabError("Inductor indisponível")
        return compiled(*tensor_inputs)

    return {
        "torch_version": str(torch.__version__),
        "eager_invoke": eager_invoke,
        "eager_preparation_wall_ns": eager_preparation_wall_ns,
        "inductor_invoke": inductor_invoke,
        "inductor_status": inductor_status,
        "inductor_error": inductor_error,
        "inductor_preparation_wall_ns": inductor_preparation_wall_ns,
        "inductor_compilation_wall_ns": inductor_compilation_wall_ns,
        "inductor_first_result": inductor_first_result,
        "toolchain": toolchain,
    }


def _validate_torch_result(
    autograd: MetamorfoseAutogradIR,
    reference: Any,
    result: Any,
) -> dict[str, Any]:
    if result is None:
        return {
            "status": "INCONCLUSIVE",
            "passed": False,
            "reason": "Inductor indisponível",
            "checks": [],
        }
    try:
        import numpy as np
    except ImportError as exc:
        raise TensorLabError("NumPy indisponível") from exc
    gradients, loss = result
    checks: list[dict[str, Any]] = []
    loss_reference = np.asarray(reference.outputs[autograd.loss]).reshape(-1)
    loss_candidate = loss.detach().cpu().numpy().reshape(-1)
    loss_dtype = next(
        item.output_type.dtype
        for item in autograd.forward.instructions
        if item.result == autograd.loss
    )
    tolerance = _tolerance(loss_dtype)
    checks.append(
        _array_check(
            "loss",
            autograd.loss,
            loss_reference,
            loss_candidate,
            tolerance,
        )
    )
    gradient_values = (
        gradients
        if isinstance(gradients, tuple)
        else (gradients,)
    )
    for name, candidate in zip(
        autograd.wrt,
        gradient_values,
        strict=True,
    ):
        checks.append(
            _array_check(
                "gradient",
                name,
                np.asarray(reference.gradients[name]),
                candidate.detach().cpu().numpy(),
                _tolerance(
                    next(
                        item.type.dtype
                        for item in autograd.forward.inputs
                        if item.name == name
                    )
                ),
            )
        )
    passed = all(item["passed"] for item in checks)
    return {
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "reason": None if passed else "numeric mismatch",
        "checks": checks,
    }


def _array_check(
    kind: str,
    name: str,
    reference: Any,
    candidate: Any,
    tolerance: tuple[float, float],
) -> dict[str, Any]:
    import numpy as np

    left = np.asarray(reference)
    right = np.asarray(candidate)
    shape_ok = left.shape == right.shape
    dtype_ok = left.dtype == right.dtype
    finite = bool(np.isfinite(left).all() and np.isfinite(right).all())
    if shape_ok:
        difference = np.abs(left.astype(np.float64) - right.astype(np.float64))
        max_absolute = float(difference.max(initial=0.0))
        denominator = np.maximum(np.abs(left.astype(np.float64)), 1e-30)
        max_relative = float((difference / denominator).max(initial=0.0))
        numeric = bool(
            np.allclose(
                left,
                right,
                rtol=tolerance[1],
                atol=tolerance[0],
                equal_nan=False,
            )
        )
    else:
        max_absolute = max_relative = None
        numeric = False
    return {
        "kind": kind,
        "name": name,
        "shape": list(left.shape),
        "dtype": str(left.dtype),
        "absolute_tolerance": tolerance[0],
        "relative_tolerance": tolerance[1],
        "max_absolute_error": max_absolute,
        "max_relative_error": max_relative,
        "passed": shape_ok and dtype_ok and finite and numeric,
        "shape_ok": shape_ok,
        "dtype_ok": dtype_ok,
        "finite": finite,
    }


def _measure_batch(
    function: Callable[[], Any],
    iterations: int,
) -> tuple[int, int]:
    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        cpu_started = time.process_time_ns()
        wall_started = time.perf_counter_ns()
        for _ in range(iterations):
            function()
        wall_ns = time.perf_counter_ns() - wall_started
        cpu_ns = time.process_time_ns() - cpu_started
    finally:
        if was_enabled:
            gc.enable()
    return wall_ns, cpu_ns


def _memory_probe(
    function: Callable[[], Any],
    inner_iterations: int,
) -> dict[str, Any]:
    try:
        import psutil
    except ImportError:
        return {
            "status": "UNAVAILABLE",
            "method": None,
            "rss_before_bytes": None,
            "rss_peak_observed_bytes": None,
            "rss_after_bytes": None,
            "sampling_interval_seconds": None,
            "reason": "psutil indisponível",
        }
    process = psutil.Process()
    before = int(process.memory_info().rss)
    peak = [before]
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(0.001):
            peak[0] = max(peak[0], int(process.memory_info().rss))

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        for _ in range(max(10, inner_iterations)):
            function()
    finally:
        stop.set()
        sampler.join(timeout=1)
    after = int(process.memory_info().rss)
    peak[0] = max(peak[0], after)
    return {
        "status": "OBSERVED",
        "method": "process-rss-polling-separate-from-timing",
        "rss_before_bytes": before,
        "rss_peak_observed_bytes": peak[0],
        "rss_after_bytes": after,
        "rss_peak_delta_bytes": max(0, peak[0] - before),
        "sampling_interval_seconds": 0.001,
        "limitations": (
            "RSS é do processo inteiro, a sondagem é sequencial e pode perder "
            "picos menores que o intervalo de amostragem"
        ),
    }


def _comparison(
    samples: Sequence[Mapping[str, Any]],
    baseline: str,
    *,
    seed: int,
    resamples: int,
    backends: Mapping[str, Any],
    inner_iterations: int,
) -> dict[str, Any]:
    wall_ratios = _paired_ratios(samples, baseline)
    cpu_ratios = _paired_ratios(samples, baseline, field="cpu_ns")
    lower, upper = _bootstrap_median_ci(
        wall_ratios,
        seed=seed,
        resamples=resamples,
    )
    candidate_compile = _compilation_cost(
        backends[TENSOR_LAB_BACKEND_CASULO]
    )
    baseline_compile = _compilation_cost(backends[baseline])
    candidate_per_call = statistics.median(
        sample["measurements"][TENSOR_LAB_BACKEND_CASULO]["wall_ns"]
        / inner_iterations
        for sample in samples
    )
    baseline_per_call = statistics.median(
        sample["measurements"][baseline]["wall_ns"] / inner_iterations
        for sample in samples
    )
    break_even = _break_even(
        candidate_compile,
        baseline_compile,
        candidate_per_call,
        baseline_per_call,
    )
    return {
        "baseline": baseline,
        "paired_samples": len(wall_ratios),
        "wall_speedup_median": statistics.median(wall_ratios),
        "wall_speedup_ci95": {
            "lower": lower,
            "upper": upper,
            "resamples": resamples,
            "method": "paired-bootstrap-median",
        },
        "cpu_speedup_median": (
            statistics.median(cpu_ratios)
            if len(cpu_ratios) == len(samples)
            else None
        ),
        "cpu_speedup_status": (
            "MEASURED"
            if len(cpu_ratios) == len(samples)
            else "INCONCLUSIVE_TIMER_RESOLUTION"
        ),
        "candidate_wall_ns_per_invocation_median": candidate_per_call,
        "baseline_wall_ns_per_invocation_median": baseline_per_call,
        "candidate_compilation_wall_ns": candidate_compile,
        "baseline_compilation_wall_ns": baseline_compile,
        "break_even_invocations": break_even,
    }


def _paired_ratios(
    samples: Sequence[Mapping[str, Any]],
    baseline: str,
    *,
    field: str = "wall_ns",
) -> list[float]:
    ratios: list[float] = []
    for sample in samples:
        measurements = sample.get("measurements", {})
        if (
            baseline not in measurements
            or TENSOR_LAB_BACKEND_CASULO not in measurements
        ):
            continue
        candidate = float(
            measurements[TENSOR_LAB_BACKEND_CASULO][field]
        )
        reference = float(measurements[baseline][field])
        if candidate > 0 and reference > 0:
            ratios.append(reference / candidate)
    return ratios


def _compilation_cost(backend: Mapping[str, Any]) -> int:
    compilation = backend.get("compilation")
    if compilation is None:
        return 0
    if "wall_ns" in compilation:
        return int(compilation["wall_ns"] or 0)
    return int(compilation.get("compiler_total_wall_ns") or 0)


def _break_even(
    candidate_compile: int,
    baseline_compile: int,
    candidate_per_call: float,
    baseline_per_call: float,
) -> int | None:
    saving = baseline_per_call - candidate_per_call
    extra_compile = candidate_compile - baseline_compile
    if saving <= 0:
        return None
    if extra_compile <= 0:
        return 0
    return int(math.ceil(extra_compile / saving))


def _generate_inputs(
    autograd: MetamorfoseAutogradIR,
    generator: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        import numpy as np
    except ImportError as exc:
        raise TensorLabError("NumPy é obrigatório") from exc
    if generator.get("protocol") != TENSOR_LAB_INPUT_PROTOCOL:
        raise TensorLabError("gerador de entrada desconhecido")
    rng = np.random.default_rng(int(generator["seed"]))
    inputs: dict[str, Any] = {}
    for item in autograd.forward.inputs:
        dtype = {
            TensorDType.FLOAT32: np.float32,
            TensorDType.FLOAT64: np.float64,
        }.get(item.type.dtype)
        if dtype is None:
            raise TensorLabError(
                f"dtype não suportado no laboratório: {item.type.dtype.value}"
            )
        values = rng.normal(size=tuple(int(x) for x in item.type.shape))
        if item.name.lower().startswith("weight"):
            values *= float(generator["weight_scale"])
        inputs[item.name] = values.astype(dtype)
    return inputs


def _bind_preregistration(
    preregistration: TensorLabPreregistration,
    graph: Path,
    autograd: MetamorfoseAutogradIR,
) -> None:
    design = preregistration.document["design"]
    provider = GemmProviderDescriptor(**design["gemm_provider"])
    plan = plan_tensor_cpu(
        autograd,
        arena_budget_bytes=int(design["arena_budget_bytes"]),
        workers=int(design["workers"]),
        gemm_workers=int(design["gemm_workers"]),
        provider=provider,
    )
    actual = {
        "graph_sha256": _normalized_text_sha256(graph),
        "autograd_graph_sha256": plan.graph_sha256,
        "wrt": list(autograd.wrt),
        "loss": autograd.loss,
        "inputs": _input_contract(autograd),
        "gemm_workers": plan.gemm_workers,
        "gemm_provider": _gemm_provider_from_plan(plan).to_dict(),
        "implementation": _implementation_identity(),
    }
    expected = {
        "graph_sha256": design["graph"]["sha256"],
        "autograd_graph_sha256": design["graph"][
            "autograd_graph_sha256"
        ],
        "wrt": design["wrt"],
        "loss": design["loss"],
        "inputs": design["inputs"],
        "gemm_workers": design["gemm_workers"],
        "gemm_provider": design["gemm_provider"],
        "implementation": design["implementation"],
    }
    differences = [
        key for key in expected if actual.get(key) != expected.get(key)
    ]
    if differences:
        raise TensorLabPreregistrationError(
            "execução diverge do pré-registro: "
            + ", ".join(differences)
        )


def _input_contract(
    autograd: MetamorfoseAutogradIR,
) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "dtype": item.type.dtype.value,
            "shape": list(item.type.shape),
            "device": item.type.device.value,
        }
        for item in autograd.forward.inputs
    ]


def _gemm_provider_from_plan(plan: Any) -> GemmProviderDescriptor:
    if not plan.algebra_kernels:
        raise TensorLabPreregistrationError(
            "laboratório de álgebra exige ao menos um kernel GEMM"
        )
    providers = {
        json.dumps(
            item.provider.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in plan.algebra_kernels
    }
    if len(providers) != 1:
        raise TensorLabPreregistrationError(
            "todos os kernels GEMM precisam usar o mesmo provedor"
        )
    return plan.algebra_kernels[0].provider


def _bound_design(design: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "graph",
        "wrt",
        "loss",
        "inputs",
        "input_generator",
        "samples",
        "warmups",
        "inner_iterations",
        "workers",
        "gemm_workers",
        "gemm_provider",
        "torch_threads",
        "seed",
        "bootstrap_resamples",
        "arena_budget_bytes",
        "pairing",
        "order_policy",
        "required_baselines",
        "candidate_backend",
        "measurement_boundary",
        "memory_probe",
        "implementation",
    )
    optional_keys = (
        "measurement_calibration",
        "cpu_affinity",
        "cooldown_ms",
        "max_coefficient_of_variation",
        "telemetry_policy",
    )
    return {
        key: design[key]
        for key in (*keys, *optional_keys)
        if key in design
    }


def _environment_snapshot(
    torch_version: str,
    compiler_version: str,
) -> dict[str, Any]:
    try:
        import numpy as np
    except ImportError:
        np = None
    try:
        import psutil
    except ImportError:
        psutil = None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "numpy": getattr(np, "__version__", None),
        "pytorch": torch_version,
        "compiler": compiler_version,
        "logical_cpu_count": os.cpu_count(),
        "physical_cpu_count": (
            psutil.cpu_count(logical=False) if psutil is not None else None
        ),
        "total_memory_bytes": (
            int(psutil.virtual_memory().total)
            if psutil is not None
            else None
        ),
        "process_priority": (
            str(psutil.Process().nice()) if psutil is not None else None
        ),
        "measurement_host": system_telemetry_snapshot(static=True),
    }


def _thermal_snapshot() -> dict[str, Any]:
    snapshot = system_telemetry_snapshot()
    return {
        "cpu_frequency_mhz": snapshot["cpu_frequency_mhz"],
        "temperature_celsius": snapshot["temperature_celsius"],
        "temperature_source": snapshot["temperature_source"],
        "reason": (
            None
            if snapshot["temperature_celsius"] is not None
            else "sensor de temperatura não exposto ao processo"
        ),
    }


def _tolerance(dtype: TensorDType) -> tuple[float, float]:
    return (
        (1e-5, 1e-4)
        if dtype is TensorDType.FLOAT32
        else (1e-10, 1e-9)
    )


def _bootstrap_median_ci(
    values: Sequence[float],
    *,
    seed: int,
    resamples: int,
) -> tuple[float, float]:
    if not values:
        raise TensorLabVerdictError("bootstrap sem amostras")
    generator = random.Random(seed)
    size = len(values)
    medians = [
        statistics.median(generator.choices(values, k=size))
        for _ in range(resamples)
    ]
    medians.sort()
    return (
        medians[math.floor(0.025 * (resamples - 1))],
        medians[math.floor(0.975 * (resamples - 1))],
    )


def _stable_seed(value: str) -> int:
    return int.from_bytes(
        hashlib.sha256(value.encode("utf-8")).digest()[:8],
        "big",
    )


def _scope_bound_claim(
    metrics: Mapping[str, Any],
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "allowed": True,
        "statement": (
            "No grafo, máquina, dtype, orçamento de threads e fronteira "
            "pré-registrados, o Casulo/T apresentou IC95% inferior acima de "
            "1× contra todos os baselines obrigatórios."
        ),
        "metrics": dict(metrics),
        "scope": dict(scope),
        "not_proven": [
            "superioridade geral sobre PyTorch",
            "mesmo ganho em GPU",
            "mesmo ganho em outros modelos, shapes ou dtypes",
            "economia de energia elétrica",
        ],
    }


def _verdict_interpretation(
    classification: str,
    missing: Sequence[str],
    failures: Sequence[str],
    quality_failures: Sequence[str],
    stability_failures: Sequence[str],
) -> str:
    if classification == "INVALID":
        return (
            "evidência inválida; nenhuma alegação é permitida: "
            + ", ".join([*failures, *quality_failures])
        )
    if classification == "INCONCLUSIVE":
        if stability_failures:
            return (
                "medição correta, mas metrologicamente instável; nenhuma "
                "alegação é permitida: "
                + ", ".join(stability_failures)
            )
        return "faltam baselines obrigatórios: " + ", ".join(missing)
    if classification == "POSITIVE":
        return (
            "superioridade sustentada somente dentro do escopo "
            "pré-registrado"
        )
    if classification == "NEGATIVE":
        return "a hipótese foi refutada por ao menos um baseline obrigatório"
    return "a evidência não separa superioridade de equivalência"


def _reclassify_verdict(verdict: Mapping[str, Any]) -> str:
    evidence = verdict["evidence"]
    if evidence["integrity_failures"] or evidence["quality_failures"]:
        return "INVALID"
    if (
        evidence["missing_required_baselines"]
        or evidence.get("stability_failures", [])
    ):
        return "INCONCLUSIVE"
    classes = verdict["baseline_classifications"].values()
    if any(value == "NEGATIVE" for value in classes):
        return "NEGATIVE"
    if all(value == "POSITIVE" for value in classes):
        return "POSITIVE"
    return "NULL"


def _render_report_html(document: Mapping[str, Any]) -> str:
    comparisons = document.get("comparisons", {})
    rows = "".join(
        (
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{values['wall_speedup_median']:.3f}×</td>"
            f"<td>{values['wall_speedup_ci95']['lower']:.3f}× – "
            f"{values['wall_speedup_ci95']['upper']:.3f}×</td>"
            f"<td>{values['break_even_invocations']}</td>"
            "</tr>"
        )
        for name, values in comparisons.items()
    )
    status_cards = "".join(
        (
            "<article>"
            f"<h3>{html.escape(name)}</h3>"
            f"<strong>{html.escape(str(values['status']))}</strong>"
            "</article>"
        )
        for name, values in document.get("backends", {}).items()
    )
    stability = document.get("measurement_stability", {})
    variation = stability.get("coefficient_of_variation", {})
    stability_rows = "".join(
        (
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{float(value) * 100:.2f}%</td>"
            "</tr>"
        )
        for name, value in variation.items()
        if value is not None
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Casulo/T — laboratório tensorial</title>
<style>
body{{font-family:Inter,Segoe UI,sans-serif;background:#0b1020;color:#edf2ff;
margin:0;padding:32px}}main{{max-width:1100px;margin:auto}}h1{{font-size:42px}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
article{{background:#151d35;border:1px solid #2b385e;border-radius:14px;
padding:18px}}table{{width:100%;border-collapse:collapse;margin-top:24px;
background:#11192d}}th,td{{padding:14px;border-bottom:1px solid #2b385e;
text-align:left}}.guard{{color:#ffce73}}code{{color:#8ee8d1}}
</style>
</head>
<body><main>
<p>Teloscorp · Casulo · Otimização de Tráfego de Informação</p>
<h1>Laboratório tensorial pré-registrado</h1>
<p class="guard">Este relatório ainda não é um veredito. Claims permanecem
bloqueados até o julgamento independente.</p>
<div class="cards">{status_cards}</div>
<table><thead><tr><th>Baseline</th><th>Mediana</th><th>IC95%</th>
<th>Break-even</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Estabilidade metrológica</h2>
<p>Invocações por lote:
<code>{html.escape(str(stability.get('selected_inner_iterations')))}</code>.
CV máximo selado:
<code>{html.escape(str(stability.get('max_coefficient_of_variation')))}</code>.
</p>
<table><thead><tr><th>Backend</th><th>Coeficiente de variação</th>
</tr></thead><tbody>{stability_rows}</tbody></table>
<p>Energia elétrica: <code>null</code>. Medição:
<code>{html.escape(str(document['energy']['measured']))}</code>.</p>
<p>Experimento: <code>{html.escape(document['scientific']['experiment_id'])}</code></p>
</main></body></html>
"""


def _implementation_identity() -> dict[str, Any]:
    module_dir = Path(__file__).resolve().parent
    files = (
        "tensor_lab.py",
        "measurement.py",
        "tensor_cpu.py",
        "linear_algebra.py",
        "parity.py",
        "autograd.py",
        "tensor.py",
    )
    return {
        "binding": "sha256-source-files",
        "files": {
            name: _file_sha256(module_dir / name)
            for name in files
        },
    }


def _normalized_text_sha256(path: Path) -> str:
    return hashlib.sha256(
        path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _body_seal(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_new_json(path: Path, document: Mapping[str, Any]) -> None:
    if path.exists():
        raise TensorLabError(f"arquivo imutável já existe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _verify_sealed_document(
    path: Path,
    *,
    protocol: str,
    identifier: str,
) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("protocol") != protocol:
        raise TensorLabVerdictError(f"protocolo inválido em {path.name}")
    body = {
        key: value
        for key, value in document.items()
        if key not in {identifier, "seal"}
    }
    actual = _body_seal(body)
    if document.get("seal", {}).get("canonical_body_sha256") != actual:
        raise TensorLabVerdictError(f"selo adulterado em {path.name}")
    if document.get(identifier) != f"sha256:{actual}":
        raise TensorLabVerdictError(
            f"identidade inválida em {path.name}"
        )
    return document


def _close(actual: Any, expected: float) -> bool:
    return actual is not None and math.isclose(
        float(actual),
        float(expected),
        rel_tol=0,
        abs_tol=1e-12,
    )


def _bounded_error(error: Exception, limit: int = 2_000) -> str:
    return " ".join(str(error).split())[:limit]
