"""Scientific fidelity invariants for Casulo/T experiments.

This module intentionally depends only on the Python standard library. The
experiment runner may produce evidence, but this module decides whether that
evidence is eligible for a claim.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import random
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .pytorch_runtime import (
    configure_pytorch_inductor,
    prepare_pytorch_inductor_runtime,
)
from .training import TrainingSpec, parse_training_file


SCIENTIFIC_COVENANT_PROTOCOL = "casulo-scientific-covenant/1.0"
PREREGISTRATION_PROTOCOL = "casulo-scientific-preregistration/1.1"
LEGACY_PREREGISTRATION_PROTOCOLS = {
    "casulo-scientific-preregistration/1.0",
}
VERDICT_PROTOCOL = "casulo-scientific-verdict/1.0"
PROBE_PROTOCOL = "casulo-baseline-capability-probe/1.1"
LEGACY_PROBE_PROTOCOLS = {
    "casulo-baseline-capability-probe/1.0",
}
PYTORCH_EAGER_BASELINE = "pytorch-eager-cpu"
PYTORCH_COMPILE_BASELINE = "pytorch-compile-inductor-cpu"

SCIENTIFIC_INVARIANTS = (
    {
        "id": "HYPOTHESIS_BEFORE_MEASUREMENT",
        "rule": "hipótese, métricas, baselines e gates são selados antes da medição",
    },
    {
        "id": "QUALITY_BEFORE_SPEED",
        "rule": "nenhum ganho é válido sem equivalência e qualidade",
    },
    {
        "id": "ALL_REGISTERED_BASELINES_REPORTED",
        "rule": "baseline obrigatório ausente torna o veredito inconclusivo",
    },
    {
        "id": "RAW_SAMPLES_PRESERVED",
        "rule": "amostras brutas e ordem pareada são parte da evidência",
    },
    {
        "id": "UNCERTAINTY_REQUIRED",
        "rule": "mediana sem intervalo de incerteza não libera alegação",
    },
    {
        "id": "NEGATIVE_AND_NULL_PRESERVED",
        "rule": "resultados negativos, nulos e falhas permanecem publicados",
    },
    {
        "id": "UNMEASURED_IS_NULL",
        "rule": "grandeza não medida é null e jamais é estimada como observação",
    },
    {
        "id": "NO_CHERRY_PICKING",
        "rule": "todas as execuções pré-registradas entram no veredito",
    },
    {
        "id": "SCOPE_BOUND_CLAIMS",
        "rule": "toda alegação nomeia carga, baseline, máquina e horizonte medidos",
    },
    {
        "id": "CORRECTION_CREATES_NEW_VERSION",
        "rule": "correção lógica gera novo protocolo e não sobrescreve evidência",
    },
    {
        "id": "INDEPENDENT_RECOMPUTATION",
        "rule": "o juiz recalcula métricas a partir das amostras brutas",
    },
    {
        "id": "JUDGE_CANNOT_OPTIMIZE",
        "rule": "o juiz classifica evidência e não altera código, dados ou parâmetros",
    },
)


class ScientificError(RuntimeError):
    pass


class PreregistrationError(ScientificError):
    pass


class ScientificVerdictError(ScientificError):
    pass


@dataclass(frozen=True, slots=True)
class EggPreRegistro:
    path: Path
    experiment_id: str
    seal_sha256: str
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BorboletaVeredito:
    classification: str
    document: dict[str, Any]
    output_path: Path


def create_training_preregistration(
    source_path: str | Path,
    output_path: str | Path,
    *,
    records: int = 1_024,
    samples: int = 21,
    warmups: int = 3,
    workers: int | str = "auto",
    seed: int = 20_260_730,
    bootstrap_resamples: int = 2_000,
    required_baselines: Iterable[str] = (
        PYTORCH_EAGER_BASELINE,
        PYTORCH_COMPILE_BASELINE,
    ),
    superiority_threshold: float = 1.0,
    commercial_threshold: float = 6.0,
) -> EggPreRegistro:
    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PreregistrationError(f"pré-registro já existe e é imutável: {output}")
    if samples < 5 or warmups < 1 or bootstrap_resamples < 200:
        raise PreregistrationError("desenho experimental abaixo dos mínimos")
    if workers not in {"auto", 1, 2, 4, "1", "2", "4"}:
        raise PreregistrationError("workers precisa ser auto, 1, 2 ou 4")
    if superiority_threshold <= 0 or commercial_threshold <= 0:
        raise PreregistrationError("limiares precisam ser positivos")

    baselines = tuple(dict.fromkeys(required_baselines))
    supported = {PYTORCH_EAGER_BASELINE, PYTORCH_COMPILE_BASELINE}
    if not baselines or set(baselines) - supported:
        raise PreregistrationError("baseline científico desconhecido")
    spec = parse_training_file(source)
    body: dict[str, Any] = {
        "protocol": PREREGISTRATION_PROTOCOL,
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
        "trusted_external_timestamp": False,
        "timestamp_limitation": (
            "ordem temporal é demonstrada pelo arquivo e pelo histórico Git; "
            "não há carimbo externo confiável neste estágio"
        ),
        "hypothesis": {
            "candidate": "casulo-t-c99-openmp-fused",
            "primary_metric": "paired_wall_speedup_median",
            "direction": "greater_than",
            "superiority_threshold": float(superiority_threshold),
            "commercial_threshold": float(commercial_threshold),
            "quality_precedes_speed": True,
        },
        "design": {
            "source": {
                "path_hint": source.name,
                "sha256": _normalized_text_sha256(source),
            },
            "model": spec.to_dict(),
            "records": int(records),
            "samples": int(samples),
            "warmups": int(warmups),
            "workers": str(workers),
            "seed": int(seed),
            "bootstrap_resamples": int(bootstrap_resamples),
            "pairing": "alternating-order-same-process",
            "required_baselines": list(baselines),
            "precision": "float64",
            "implementation": _implementation_identity(),
        },
        "quality_gates": {
            "equivalent_training": True,
            "quality_target_reached": True,
            "same_dataset": True,
            "same_architecture": True,
            "same_initial_parameters": True,
            "same_optimizer": True,
            "same_learning_rate": True,
            "same_epochs": True,
            "deterministic_backends": True,
        },
        "classification": {
            "POSITIVE": "qualidade aprovada e IC95% inferior acima do limiar",
            "NULL": "qualidade aprovada, mas intervalo cruza o limiar",
            "NEGATIVE": "qualidade aprovada e IC95% superior abaixo do limiar",
            "INCONCLUSIVE": "baseline ou evidência obrigatória ausente",
            "INVALID": "integridade, desenho ou equivalência violados",
        },
        "result_policy": {
            "selection": "all-preregistered-runs",
            "failed_runs_are_evidence": True,
            "overwrite": False,
            "correction": "new-protocol-new-preregistration-new-result",
        },
    }
    seal = _body_seal(body)
    document = {
        **body,
        "experiment_id": f"sha256:{seal}",
        "seal": {"algorithm": "sha256", "canonical_body_sha256": seal},
    }
    _write_new_json(output, document)
    return EggPreRegistro(
        path=output,
        experiment_id=document["experiment_id"],
        seal_sha256=seal,
        document=document,
    )


def verify_preregistration(path: str | Path) -> EggPreRegistro:
    source = Path(path).expanduser().resolve()
    document = json.loads(source.read_text(encoding="utf-8"))
    if document.get("protocol") not in {
        PREREGISTRATION_PROTOCOL,
        *LEGACY_PREREGISTRATION_PROTOCOLS,
    }:
        raise PreregistrationError("protocolo de pré-registro desconhecido")
    seal = document.get("seal", {})
    if seal.get("algorithm") != "sha256":
        raise PreregistrationError("algoritmo de selo inválido")
    body = {
        key: value
        for key, value in document.items()
        if key not in {"experiment_id", "seal"}
    }
    actual = _body_seal(body)
    if seal.get("canonical_body_sha256") != actual:
        raise PreregistrationError("pré-registro adulterado")
    if document.get("experiment_id") != f"sha256:{actual}":
        raise PreregistrationError("identidade do pré-registro inválida")
    if document.get("observed_results_at_registration") is not False:
        raise PreregistrationError("pré-registro contaminado por resultado observado")
    return EggPreRegistro(
        path=source,
        experiment_id=document["experiment_id"],
        seal_sha256=actual,
        document=document,
    )


def bind_training_preregistration(
    preregistration_path: str | Path | None,
    source_path: str | Path,
    spec: TrainingSpec,
    *,
    observed_baseline: str = PYTORCH_EAGER_BASELINE,
    records: int,
    samples: int,
    warmups: int,
    workers: int | str,
    seed: int,
    bootstrap_resamples: int,
) -> dict[str, Any]:
    if preregistration_path is None:
        return {
            "protocol": SCIENTIFIC_COVENANT_PROTOCOL,
            "status": "EXPLORATORY_UNREGISTERED",
            "claims_allowed": False,
            "reason": "hipótese não foi selada antes da medição",
            "invariants": list(SCIENTIFIC_INVARIANTS),
        }

    preregistration = verify_preregistration(preregistration_path)
    design = preregistration.document["design"]
    actual_design = {
        "source_sha256": _normalized_text_sha256(
            Path(source_path).expanduser().resolve()
        ),
        "model": spec.to_dict(),
        "records": int(records),
        "samples": int(samples),
        "warmups": int(warmups),
        "workers": str(workers),
        "seed": int(seed),
        "bootstrap_resamples": int(bootstrap_resamples),
    }
    expected_design = {
        "source_sha256": design["source"]["sha256"],
        "model": design["model"],
        "records": design["records"],
        "samples": design["samples"],
        "warmups": design["warmups"],
        "workers": design["workers"],
        "seed": design["seed"],
        "bootstrap_resamples": design["bootstrap_resamples"],
    }
    if "implementation" in design:
        actual_design["implementation"] = _implementation_identity()
        expected_design["implementation"] = design["implementation"]
    if actual_design != expected_design:
        differences = [
            key
            for key in expected_design
            if actual_design.get(key) != expected_design.get(key)
        ]
        raise PreregistrationError(
            "execução diverge do pré-registro: " + ", ".join(differences)
        )
    if observed_baseline not in {
        PYTORCH_EAGER_BASELINE,
        PYTORCH_COMPILE_BASELINE,
    }:
        raise PreregistrationError(
            f"baseline observado desconhecido: {observed_baseline}"
        )
    if observed_baseline not in design["required_baselines"]:
        raise PreregistrationError(
            "baseline observado não consta no pré-registro: "
            f"{observed_baseline}"
        )
    return {
        "protocol": SCIENTIFIC_COVENANT_PROTOCOL,
        "status": "PREREGISTERED",
        "claims_allowed": True,
        "experiment_id": preregistration.experiment_id,
        "preregistration_file_sha256": _file_sha256(preregistration.path),
        "observed_baseline": observed_baseline,
        "required_baselines": design["required_baselines"],
        "bound_design": actual_design,
        "invariants": list(SCIENTIFIC_INVARIANTS),
    }


def judge_training_evidence(
    preregistration_path: str | Path,
    report_path: str | Path,
    output_path: str | Path,
) -> BorboletaVeredito:
    preregistration = verify_preregistration(preregistration_path)
    report_file = Path(report_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise ScientificVerdictError(f"veredito já existe e é imutável: {output}")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    failures: list[str] = []
    if report.get("protocol") != "casulo-training-benchmark/0.1":
        failures.append("UNKNOWN_TRAINING_REPORT_PROTOCOL")
    scientific = report.get("scientific", {})
    if scientific.get("experiment_id") != preregistration.experiment_id:
        failures.append("REPORT_NOT_BOUND_TO_PREREGISTRATION")
    if scientific.get("claims_allowed") is not True:
        failures.append("REPORT_NOT_ELIGIBLE_FOR_CLAIMS")
    design = preregistration.document["design"]
    expected_bound_design = {
        "source_sha256": design["source"]["sha256"],
        "model": design["model"],
        "records": design["records"],
        "samples": design["samples"],
        "warmups": design["warmups"],
        "workers": design["workers"],
        "seed": design["seed"],
        "bootstrap_resamples": design["bootstrap_resamples"],
    }
    if "implementation" in design:
        expected_bound_design["implementation"] = design["implementation"]
    if scientific.get("bound_design") != expected_bound_design:
        failures.append("REPORT_DESIGN_DIVERGES_FROM_PREREGISTRATION")

    quality = report.get("quality", {})
    required_quality = (
        "equivalent_training",
        "quality_target_reached",
        "same_dataset",
        "same_architecture",
        "same_initial_parameters",
        "same_optimizer",
        "same_learning_rate",
        "same_epochs",
        "pytorch_deterministic",
        "casulo_t_deterministic",
    )
    quality_failures = [
        key for key in required_quality if quality.get(key) is not True
    ]
    baseline_id = report.get("outcomes", {}).get("pytorch", {}).get("backend")
    observed_baselines = {baseline_id} if baseline_id else set()
    required_baselines = set(
        preregistration.document["design"]["required_baselines"]
    )
    missing_baselines = sorted(required_baselines - observed_baselines)

    raw_reference = report.get("pytorch", {}).get("wall_ns_samples", [])
    raw_candidate = report.get("casulo_t", {}).get("wall_ns_samples", [])
    if not raw_reference or len(raw_reference) != len(raw_candidate):
        failures.append("PAIRED_RAW_SAMPLES_INVALID")
        speedups: list[float] = []
    else:
        speedups = [
            float(reference) / float(candidate)
            for reference, candidate in zip(
                raw_reference,
                raw_candidate,
                strict=True,
            )
            if float(candidate) > 0
        ]
    expected_samples = preregistration.document["design"]["samples"]
    if len(speedups) != expected_samples:
        failures.append("SAMPLE_COUNT_DIVERGES_FROM_PREREGISTRATION")

    if speedups:
        seed = preregistration.document["design"]["seed"] ^ 0x51ED
        lower, upper = _independent_bootstrap_ci(speedups, seed=seed)
        median = statistics.median(speedups)
        reported_median = report.get("comparison", {}).get(
            "paired_speedup_median"
        )
        if (
            reported_median is None
            or not math.isclose(
                float(reported_median),
                median,
                rel_tol=0,
                abs_tol=1e-12,
            )
        ):
            failures.append("REPORTED_MEDIAN_DIVERGES_FROM_RAW_SAMPLES")
    else:
        lower = upper = median = None

    threshold = preregistration.document["hypothesis"][
        "superiority_threshold"
    ]
    commercial_threshold = preregistration.document["hypothesis"][
        "commercial_threshold"
    ]
    if failures or quality_failures:
        classification = "INVALID"
    elif missing_baselines:
        classification = "INCONCLUSIVE"
    elif lower is not None and lower > threshold:
        classification = "POSITIVE"
    elif upper is not None and upper < threshold:
        classification = "NEGATIVE"
    else:
        classification = "NULL"

    body = {
        "protocol": VERDICT_PROTOCOL,
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
            "observed_baselines": sorted(observed_baselines),
            "missing_required_baselines": missing_baselines,
            "integrity_failures": failures,
            "quality_failures": quality_failures,
        },
        "recomputed_metrics": {
            "paired_samples": len(speedups),
            "paired_speedup_median": median,
            "independent_bootstrap_ci95": {
                "lower": lower,
                "upper": upper,
                "resamples": 10_000,
                "method": "independent-python-bootstrap-median",
            },
            "superiority_threshold": threshold,
            "commercial_threshold": commercial_threshold,
            "commercial_gate": bool(
                classification == "POSITIVE"
                and lower is not None
                and lower >= commercial_threshold
            ),
        },
        "interpretation": _interpretation(
            classification,
            missing_baselines,
            failures,
            quality_failures,
        ),
        "energy": {
            "measured": report.get("energy", {}).get(
                "electrical_energy_measured",
                False,
            ),
            "joules": report.get("energy", {}).get("joules"),
        },
    }
    verdict_sha256 = _body_seal(body)
    document = {
        **body,
        "verdict_id": f"sha256:{verdict_sha256}",
        "seal": {
            "algorithm": "sha256",
            "canonical_body_sha256": verdict_sha256,
        },
    }
    _write_new_json(output, document)
    return BorboletaVeredito(
        classification=classification,
        document=document,
        output_path=output,
    )


def probe_pytorch_compile(output_path: str | Path) -> dict[str, Any]:
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise ScientificError(f"sondagem já existe e é imutável: {output}")
    started = time.perf_counter()
    torch_version = None
    status = "UNAVAILABLE"
    error_type = None
    error_message = None
    toolchain: dict[str, Any] = {
        "status": "NOT_CHECKED",
        "compiler": None,
        "source": None,
        "encoding_policy": None,
        "error": None,
    }
    try:
        toolchain = prepare_pytorch_inductor_runtime()
        if toolchain["status"] == "UNAVAILABLE":
            raise ScientificError(
                f"toolchain Inductor indisponível: {toolchain['error']}"
            )
        import torch

        torch_version = torch.__version__
        torch.set_num_threads(1)
        configure_pytorch_inductor(torch)

        def operation(value: Any) -> Any:
            return torch.relu(value @ value)

        compiled = torch.compile(
            operation,
            backend="inductor",
            fullgraph=True,
        )
        value = torch.arange(256, dtype=torch.float64).reshape(16, 16)
        observed = compiled(value)
        expected = operation(value)
        if not torch.equal(observed, expected):
            raise ScientificError("torch.compile produziu saída divergente")
        compiled(value)
        status = "AVAILABLE"
    except Exception as error:  # capability probes must preserve every failure
        error_type = type(error).__name__
        error_message = _bounded_error(error)
    body = {
        "protocol": PROBE_PROTOCOL,
        "capability": PYTORCH_COMPILE_BASELINE,
        "status": status,
        "backend": "inductor",
        "fullgraph": True,
        "dtype": "float64",
        "threads": 1,
        "torch_version": torch_version,
        "toolchain": toolchain,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "duration_seconds": time.perf_counter() - started,
        "error": (
            None
            if status == "AVAILABLE"
            else {"type": error_type, "message": error_message}
        ),
        "interpretation": (
            "baseline compilado pode ser medido"
            if status == "AVAILABLE"
            else "baseline compilado não pode ser omitido; prova ampla permanece inconclusiva"
        ),
    }
    seal = _body_seal(body)
    document = {
        **body,
        "probe_id": f"sha256:{seal}",
        "seal": {"algorithm": "sha256", "canonical_body_sha256": seal},
    }
    _write_new_json(output, document)
    return document


def verify_scientific_chain(
    preregistration_path: str | Path,
    report_path: str | Path,
    probe_path: str | Path,
    verdict_path: str | Path,
) -> list[str]:
    preregistration = verify_preregistration(preregistration_path)
    report_file = Path(report_path).expanduser().resolve()
    probe_file = Path(probe_path).expanduser().resolve()
    verdict_file = Path(verdict_path).expanduser().resolve()
    report = json.loads(report_file.read_text(encoding="utf-8"))
    probe_protocol = json.loads(
        probe_file.read_text(encoding="utf-8")
    ).get("protocol")
    if probe_protocol not in {PROBE_PROTOCOL, *LEGACY_PROBE_PROTOCOLS}:
        raise ScientificVerdictError(
            "protocolo de sondagem científica desconhecido"
        )
    probe = _verify_sealed_document(
        probe_file,
        protocol=probe_protocol,
        identifier="probe_id",
    )
    verdict = _verify_sealed_document(
        verdict_file,
        protocol=VERDICT_PROTOCOL,
        identifier="verdict_id",
    )
    checks: list[str] = []

    checksum_file = preregistration.path.parent / "SHA256SUMS"
    if not checksum_file.is_file():
        raise ScientificVerdictError("cadeia científica não possui SHA256SUMS")
    repository_root = preregistration.path.parents[2]
    for line in checksum_file.read_text(encoding="ascii").splitlines():
        expected_sha256, relative_path = line.split("  ", maxsplit=1)
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ScientificVerdictError("caminho inseguro em SHA256SUMS")
        if _file_sha256(repository_root / candidate) != expected_sha256:
            raise ScientificVerdictError(
                f"checksum diverge para {relative_path}"
            )
    checks.append("todos os arquivos publicados coincidem com SHA256SUMS")

    if verdict["experiment_id"] != preregistration.experiment_id:
        raise ScientificVerdictError("veredito pertence a outro pré-registro")
    if report.get("scientific", {}).get(
        "experiment_id"
    ) != preregistration.experiment_id:
        raise ScientificVerdictError("relatório pertence a outro pré-registro")
    checks.append("pré-registro, relatório e veredito possuem a mesma identidade")

    if verdict["evidence"]["preregistration_file_sha256"] != _file_sha256(
        preregistration.path
    ):
        raise ScientificVerdictError("hash do pré-registro diverge do veredito")
    if verdict["evidence"]["report_file_sha256"] != _file_sha256(report_file):
        raise ScientificVerdictError("hash do relatório diverge do veredito")
    checks.append("cadeia de arquivos coincide com os hashes julgados")

    reference = report["pytorch"]["wall_ns_samples"]
    candidate = report["casulo_t"]["wall_ns_samples"]
    speedups = [
        float(baseline) / float(casulo)
        for baseline, casulo in zip(reference, candidate, strict=True)
    ]
    seed = preregistration.document["design"]["seed"] ^ 0x51ED
    lower, upper = _independent_bootstrap_ci(speedups, seed=seed)
    metrics = verdict["recomputed_metrics"]
    _require_close(
        "mediana pareada",
        metrics["paired_speedup_median"],
        statistics.median(speedups),
    )
    _require_close(
        "limite inferior independente",
        metrics["independent_bootstrap_ci95"]["lower"],
        lower,
    )
    _require_close(
        "limite superior independente",
        metrics["independent_bootstrap_ci95"]["upper"],
        upper,
    )
    checks.append("mediana e bootstrap foram reproduzidos das amostras brutas")

    observed = set(verdict["evidence"]["observed_baselines"])
    required = set(preregistration.document["design"]["required_baselines"])
    missing = sorted(required - observed)
    if verdict["evidence"]["missing_required_baselines"] != missing:
        raise ScientificVerdictError("lista de baselines ausentes foi alterada")
    expected_classification = (
        "INVALID"
        if (
            verdict["evidence"]["integrity_failures"]
            or verdict["evidence"]["quality_failures"]
        )
        else "INCONCLUSIVE"
        if missing
        else "POSITIVE"
        if lower
        > preregistration.document["hypothesis"]["superiority_threshold"]
        else "NEGATIVE"
        if upper
        < preregistration.document["hypothesis"]["superiority_threshold"]
        else "NULL"
    )
    if verdict["classification"] != expected_classification:
        raise ScientificVerdictError("classificação diverge das regras seladas")
    checks.append("classificação foi derivada das regras pré-registradas")

    if probe["capability"] != PYTORCH_COMPILE_BASELINE:
        raise ScientificVerdictError("sondagem não representa torch.compile")
    if (
        probe["status"] == "UNAVAILABLE"
        and PYTORCH_COMPILE_BASELINE not in missing
    ):
        raise ScientificVerdictError(
            "baseline indisponível foi ocultado do veredito"
        )
    checks.append("falha de capacidade permanece visível no veredito")

    if verdict["energy"]["measured"] is False and verdict["energy"]["joules"] is not None:
        raise ScientificVerdictError("energia não medida possui valor inventado")
    checks.append("grandeza não medida permanece null")
    return checks


def _interpretation(
    classification: str,
    missing_baselines: list[str],
    failures: list[str],
    quality_failures: list[str],
) -> str:
    if classification == "INVALID":
        return (
            "evidência inválida; não autoriza alegação: "
            + ", ".join(failures + quality_failures)
        )
    if classification == "INCONCLUSIVE":
        return "faltam baselines obrigatórios: " + ", ".join(missing_baselines)
    if classification == "POSITIVE":
        return "hipótese superou o limiar pré-registrado com qualidade válida"
    if classification == "NEGATIVE":
        return "hipótese foi refutada para o escopo pré-registrado"
    return "dados não distinguem superioridade do limiar pré-registrado"


def _independent_bootstrap_ci(
    values: list[float],
    *,
    seed: int,
    resamples: int = 10_000,
) -> tuple[float, float]:
    generator = random.Random(seed)
    size = len(values)
    medians = [
        statistics.median(generator.choices(values, k=size))
        for _ in range(resamples)
    ]
    medians.sort()
    lower = medians[math.floor(0.025 * (resamples - 1))]
    upper = medians[math.floor(0.975 * (resamples - 1))]
    return lower, upper


def _body_seal(body: dict[str, Any]) -> str:
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _verify_sealed_document(
    path: Path,
    *,
    protocol: str,
    identifier: str,
) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("protocol") != protocol:
        raise ScientificVerdictError(f"protocolo inválido em {path.name}")
    seal = document.get("seal", {})
    body = {
        key: value
        for key, value in document.items()
        if key not in {identifier, "seal"}
    }
    actual = _body_seal(body)
    if seal.get("canonical_body_sha256") != actual:
        raise ScientificVerdictError(f"selo adulterado em {path.name}")
    if document.get(identifier) != f"sha256:{actual}":
        raise ScientificVerdictError(f"identidade inválida em {path.name}")
    return document


def _require_close(label: str, actual: Any, expected: float) -> None:
    if actual is None or not math.isclose(
        float(actual),
        float(expected),
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise ScientificVerdictError(
            f"{label} diverge: {actual!r} != {expected!r}"
        )


def _implementation_identity() -> dict[str, Any]:
    module_dir = Path(__file__).resolve().parent
    files = ("scientific.py", "training.py")
    return {
        "binding": "sha256-source-files",
        "files": {
            name: _file_sha256(module_dir / name)
            for name in files
        },
    }


def _normalized_text_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_new_json(path: Path, document: dict[str, Any]) -> None:
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


def _bounded_error(error: Exception, limit: int = 2_000) -> str:
    message = " ".join(str(error).split())
    return message[:limit]
