"""Laboratório reproduzível da fase Borboleta.

A Borboleta transforma um artefato compilado e um conjunto determinístico de
entradas em evidência auditável de equivalência, velocidade, trabalho de CPU,
memória e energia elétrica quando um contador real está disponível.
"""

from __future__ import annotations

import gc
import hashlib
import html
import json
import os
import platform
import random
import statistics
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .adaptativo import (
    EstrategiaMetamorfose,
    ModeloCrisalida,
    PerfilLarva,
)
from .artifact import ArtifactError
from .runner import load_artifact, select_operation


BORBOLETA_PROTOCOL = "casulo-borboleta/0.4"


class BorboletaError(RuntimeError):
    """Falha de configuração ou de equivalência no experimento."""


@dataclass(frozen=True, slots=True)
class BorboletaConfig:
    records: int = 2_000
    samples: int = 9
    iterations: int = 5
    warmups: int = 2
    seed: int = 24_052_024
    duplicate_rate: float = 0.35
    bootstrap_resamples: int = 2_000

    def validate(self) -> None:
        if min(
            self.records,
            self.samples,
            self.iterations,
            self.bootstrap_resamples,
        ) < 1:
            raise BorboletaError("records, samples, iterations e bootstrap precisam ser positivos")
        if self.warmups < 0:
            raise BorboletaError("warmups não pode ser negativo")
        if not 0.0 <= self.duplicate_rate < 1.0:
            raise BorboletaError("duplicate_rate precisa estar em [0, 1)")


@dataclass(frozen=True, slots=True)
class BorboletaDataset:
    protocol: str
    name: str
    seed: int
    records: int
    duplicate_rate: float
    sha256: str
    payloads: tuple[dict[str, float], ...]

    def manifest(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("payloads")
        return value


@dataclass(frozen=True, slots=True)
class BorboletaMeasurement:
    name: str
    wall_ns_samples: tuple[int, ...]
    cpu_ns_samples: tuple[int, ...]
    rss_observed_bytes_samples: tuple[int, ...]
    electrical_joules_samples: tuple[float | None, ...]
    median_wall_ns: int
    median_cpu_ns: int
    median_rss_observed_bytes: int
    median_electrical_joules: float | None
    throughput_records_per_second: float


@dataclass(frozen=True, slots=True)
class BorboletaReport:
    protocol: str
    generated_at_utc: str
    artifact_id: str
    operation: str
    dataset: dict[str, Any]
    config: dict[str, Any]
    environment: dict[str, Any]
    scalar: BorboletaMeasurement
    optimized: BorboletaMeasurement
    adaptive: BorboletaMeasurement
    comparison: dict[str, Any]
    adaptation: dict[str, Any]
    equivalence_sha256: str
    energy: dict[str, Any]
    caveats: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, output_dir: str | Path) -> tuple[Path, Path]:
        destination = Path(output_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        json_path = destination / "borboleta-report.json"
        html_path = destination / "borboleta-report.html"
        payload = self.to_dict()
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        html_path.write_text(_render_html(payload), encoding="utf-8")
        return json_path, html_path


class _EnergyCounter(Protocol):
    method: str
    quality: str
    warning: str | None

    def read_joules(self) -> float | None: ...


@dataclass(slots=True)
class _NullEnergy:
    method: str = "unavailable"
    quality: str = "not_measured"
    warning: str | None = (
        "nenhum contador elétrico cumulativo foi encontrado; tempo de CPU "
        "permanece apenas como proxy de trabalho, nunca como joules"
    )

    def read_joules(self) -> float | None:
        return None


@dataclass(slots=True)
class _FileEnergy:
    path: Path
    method: str = "external_cumulative_joules_file"
    quality: str = "measured_external"
    warning: str | None = None

    def read_joules(self) -> float | None:
        return float(self.path.read_text(encoding="utf-8").strip())


@dataclass(slots=True)
class _RaplEnergy:
    paths: tuple[Path, ...]
    method: str = "linux_powercap_rapl"
    quality: str = "measured_package_counter"
    warning: str | None = None

    def read_joules(self) -> float | None:
        return sum(float(path.read_text().strip()) / 1_000_000 for path in self.paths)


def detect_energy_counter() -> _EnergyCounter:
    external = os.environ.get("CASULO_ENERGY_COUNTER_FILE")
    if external:
        path = Path(external).expanduser().resolve()
        if path.is_file():
            return _FileEnergy(path)
    powercap = Path("/sys/class/powercap")
    if powercap.is_dir():
        paths = tuple(
            sorted(
                path
                for path in powercap.glob("intel-rapl*/energy_uj")
                if path.is_file()
            )
        )
        if paths:
            return _RaplEnergy(paths)
    return _NullEnergy()


def generate_hydrological_dataset(
    config: BorboletaConfig,
) -> BorboletaDataset:
    """Gera entradas realistas o bastante para exercício, não dados observados."""

    config.validate()
    rng = random.Random(config.seed)
    unique_count = max(1, round(config.records * (1.0 - config.duplicate_rate)))
    unique: list[dict[str, float]] = []
    for _ in range(unique_count):
        precipitation = round(rng.uniform(0.0, 240.0), 3)
        evapotranspiration = round(rng.uniform(0.0, min(18.0, precipitation)), 3)
        remaining = max(0.0, precipitation - evapotranspiration)
        surface_flow = round(rng.uniform(0.0, remaining * 0.72), 3)
        base_flow = round(rng.uniform(0.0, remaining * 0.20), 3)
        unique.append(
            {
                "precipitation": precipitation,
                "evapotranspiration": evapotranspiration,
                "surface_flow": surface_flow,
                "base_flow": base_flow,
            }
        )
    payloads = [unique[index % unique_count] for index in range(config.records)]
    rng.shuffle(payloads)
    digest = _digest(payloads)
    return BorboletaDataset(
        protocol="casulo-dataset/hydrological-synthetic/0.1",
        name="hydrological-water-balance-synthetic",
        seed=config.seed,
        records=len(payloads),
        duplicate_rate=config.duplicate_rate,
        sha256=digest,
        payloads=tuple(dict(item) for item in payloads),
    )


class BorboletaLaboratorio:
    """Manifesta evidência comparável entre referência escalar e lote fundido."""

    def run(
        self,
        artifact_dir: str | Path,
        *,
        operation: str | None = None,
        config: BorboletaConfig | None = None,
        dataset: BorboletaDataset | None = None,
    ) -> BorboletaReport:
        active = config or BorboletaConfig()
        active.validate()
        data = dataset or generate_hydrological_dataset(active)
        if not data.payloads:
            raise BorboletaError("dataset vazio")

        loaded = load_artifact(artifact_dir)
        selected = select_operation(loaded.manifest, operation)
        operation_entry = next(
            item
            for item in loaded.manifest["operations"]
            if item["name"] == selected
        )
        optimization = operation_entry["optimization"]
        scalar_execute = loaded.namespace.get("execute")
        batch_execute = loaded.namespace.get("execute_batch")
        clear_cache = loaded.namespace.get("clear_cache")
        key_functions = loaded.namespace.get("OPERATION_KEYS")
        buffer_functions = loaded.namespace.get("BUFFER_OPERATIONS")
        key_function = (
            key_functions.get(selected)
            if isinstance(key_functions, dict)
            else None
        )
        buffer_available = (
            isinstance(buffer_functions, dict)
            and callable(buffer_functions.get(selected))
        )
        if not callable(scalar_execute) or not callable(batch_execute):
            raise ArtifactError("artefato não expõe kernels escalar e de lote")

        payloads = list(data.payloads)
        adaptive_profile = PerfilLarva.from_payloads(
            payloads,
            key_function=key_function if callable(key_function) else None,
        )
        adaptive_decision = ModeloCrisalida().decide(
            operation=selected,
            operation_cost=optimization["estimated_cost"],
            cacheable=optimization["cacheable"],
            buffered=buffer_available,
            profile=adaptive_profile,
        )

        def scalar_call() -> list[dict[str, Any]]:
            return [
                scalar_execute(selected, item, use_cache=False)
                for item in payloads
            ]

        def optimized_call() -> list[dict[str, Any]]:
            if callable(clear_cache):
                clear_cache(selected)
            return batch_execute(selected, payloads, use_cache=True)["items"]

        def object_batch_call() -> list[dict[str, Any]]:
            if callable(clear_cache):
                clear_cache(selected)
            return batch_execute(
                selected,
                payloads,
                use_cache=True,
                use_buffer=False,
            )["items"]

        adaptive_model = ModeloCrisalida()

        def adaptive_call() -> list[dict[str, Any]]:
            current_profile = PerfilLarva.from_payloads(
                payloads,
                key_function=key_function if callable(key_function) else None,
            )
            current_decision = adaptive_model.decide(
                operation=selected,
                operation_cost=optimization["estimated_cost"],
                cacheable=optimization["cacheable"],
                buffered=buffer_available,
                profile=current_profile,
            )
            if callable(clear_cache):
                clear_cache(selected)
            if current_decision.use_cache:
                return batch_execute(
                    selected,
                    payloads,
                    use_cache=True,
                )["items"]
            return [
                scalar_execute(selected, item, use_cache=False)
                for item in payloads
            ]

        scalar_reference = scalar_call()
        optimized_reference = optimized_call()
        adaptive_reference = adaptive_call()
        object_reference = (
            object_batch_call()
            if buffer_available
            else optimized_reference
        )
        scalar_digest = _digest(_semantic_projection(scalar_reference))
        if (
            scalar_digest != _digest(_semantic_projection(optimized_reference))
            or scalar_digest != _digest(_semantic_projection(adaptive_reference))
            or scalar_digest != _digest(_semantic_projection(object_reference))
        ):
            raise BorboletaError(
                "a saída otimizada divergiu semanticamente da referência escalar"
            )
        representation = (
            _representation_probe(object_batch_call, optimized_call)
            if buffer_available
            else {
                "available": False,
                "reason": "operação sem caminho de buffer tipado",
            }
        )
        if buffer_available:
            buffer_envelope = batch_execute(
                selected,
                payloads,
                use_cache=True,
            )
            representation["hot_path"] = buffer_envelope["cache"].get(
                "hot_path"
            )

        for _ in range(active.warmups):
            scalar_call()
            optimized_call()
            adaptive_call()

        energy = detect_energy_counter()
        scalar_samples: list[tuple[int, int, int, float | None]] = []
        optimized_samples: list[tuple[int, int, int, float | None]] = []
        adaptive_samples: list[tuple[int, int, int, float | None]] = []
        gc_enabled = gc.isenabled()
        try:
            gc.disable()
            for index in range(active.samples):
                orders = (
                    (
                        ("scalar", scalar_call),
                        ("optimized", optimized_call),
                        ("adaptive", adaptive_call),
                    ),
                    (
                        ("optimized", optimized_call),
                        ("adaptive", adaptive_call),
                        ("scalar", scalar_call),
                    ),
                    (
                        ("adaptive", adaptive_call),
                        ("scalar", scalar_call),
                        ("optimized", optimized_call),
                    ),
                )
                order = orders[index % len(orders)]
                for name, function in order:
                    measured = _measure(function, active.iterations, energy)
                    target = (
                        scalar_samples
                        if name == "scalar"
                        else optimized_samples
                        if name == "optimized"
                        else adaptive_samples
                    )
                    target.append(measured)
        finally:
            if gc_enabled:
                gc.enable()

        scalar = _summarize("python_scalar_reference", scalar_samples, active)
        optimized = _summarize(
            "casulo_metamorfose_fused_batch",
            optimized_samples,
            active,
        )
        adaptive = _summarize(
            "casulo_adaptive_end_to_end",
            adaptive_samples,
            active,
        )
        ratios = [
            scalar_samples[index][0] / optimized_samples[index][0]
            for index in range(active.samples)
            if optimized_samples[index][0]
        ]
        ci_low, ci_high = _bootstrap_median_ci(
            ratios,
            active.bootstrap_resamples,
            active.seed,
        )
        verdict = (
            "improvement"
            if ci_low > 1.0
            else "regression"
            if ci_high < 1.0
            else "inconclusive"
        )
        adaptive_ratios = [
            scalar_samples[index][0] / adaptive_samples[index][0]
            for index in range(active.samples)
            if adaptive_samples[index][0]
        ]
        adaptive_ci_low, adaptive_ci_high = _bootstrap_median_ci(
            adaptive_ratios,
            active.bootstrap_resamples,
            active.seed + 1,
        )
        adaptive_verdict = (
            "improvement"
            if adaptive_ci_low > 1.0
            else "regression"
            if adaptive_ci_high < 1.0
            else "inconclusive"
        )
        electrical_ratio = _safe_ratio(
            scalar.median_electrical_joules,
            optimized.median_electrical_joules,
        )
        optimized_strategy = (
            EstrategiaMetamorfose.FUSE_TYPED_BATCH
            if (
                buffer_available
                and adaptive_profile.repetition_rate
                < adaptive_decision.repetition_threshold
                + adaptive_decision.safety_margin
            )
            else EstrategiaMetamorfose.DEDUPLICATE_BATCH
        )
        median_best = (
            optimized_strategy
            if optimized.median_wall_ns < scalar.median_wall_ns
            else EstrategiaMetamorfose.RECALCULATE
        )
        statistically_preferred = (
            optimized_strategy
            if verdict == "improvement"
            else EstrategiaMetamorfose.RECALCULATE
            if verdict == "regression"
            else None
        )
        prediction_correct = (
            adaptive_decision.strategy is statistically_preferred
            if statistically_preferred is not None
            else None
        )
        assessment = (
            "CORRECT"
            if prediction_correct is True
            else "INCORRECT"
            if prediction_correct is False
            else "INCONCLUSIVE_SAFE"
        )
        selected_kernel_wall = (
            optimized.median_wall_ns
            if adaptive_decision.use_cache
            else scalar.median_wall_ns
        )
        best_wall = min(
            scalar.median_wall_ns,
            optimized.median_wall_ns,
        )
        caveats = [
            "dataset sintético mede o runtime, não a acurácia hidrológica",
            "o ganho depende da taxa de repetição declarada no manifesto",
            "resultados de um único computador não generalizam sem replicação",
            "turbo, temperatura e processos concorrentes afetam tempo e energia",
        ]
        if energy.quality == "not_measured":
            caveats.append("energia elétrica indisponível nesta execução")
        return BorboletaReport(
            protocol=BORBOLETA_PROTOCOL,
            generated_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            artifact_id=loaded.manifest["artifact_id"],
            operation=selected,
            dataset=data.manifest(),
            config=asdict(active),
            environment=_environment(),
            scalar=scalar,
            optimized=optimized,
            adaptive=adaptive,
            comparison={
                "scope": (
                    "referência escalar sem cache versus lote Casulo com "
                    "cache frio por chamada e deduplicação intralote"
                ),
                "wall_speedup_median": statistics.median(ratios),
                "wall_speedup_ci95_bootstrap": [ci_low, ci_high],
                "wall_speedup_interpretation": (
                    "valores acima de 1 indicam que a estratégia Casulo é mais rápida"
                ),
                "verdict": verdict,
                "cpu_work_ratio": _safe_ratio(
                    scalar.median_cpu_ns,
                    optimized.median_cpu_ns,
                ),
                "electrical_energy_ratio": electrical_ratio,
                "semantically_equivalent": True,
                "semantic_projection_excludes": ["cache"],
                "representation": representation,
            },
            adaptation={
                "profile": adaptive_profile.to_dict(),
                "decision": adaptive_decision.to_dict(),
                "median_best_strategy": median_best.value,
                "statistically_preferred_strategy": (
                    statistically_preferred.value
                    if statistically_preferred is not None
                    else None
                ),
                "prediction_correct": prediction_correct,
                "assessment": assessment,
                "selected_kernel_regret_ratio": (
                    selected_kernel_wall / best_wall
                ),
                "end_to_end_wall_speedup": statistics.median(
                    adaptive_ratios
                ),
                "end_to_end_wall_speedup_ci95_bootstrap": [
                    adaptive_ci_low,
                    adaptive_ci_high,
                ],
                "end_to_end_verdict": adaptive_verdict,
                "selection_overhead_ratio": (
                    adaptive.median_wall_ns / selected_kernel_wall
                ),
                "end_to_end_regret_ratio": (
                    adaptive.median_wall_ns / best_wall
                ),
            },
            equivalence_sha256=scalar_digest,
            energy={
                "method": energy.method,
                "quality": energy.quality,
                "unit": "joules" if energy.quality != "not_measured" else None,
                "warning": energy.warning,
                "electrical_energy_measured": energy.quality != "not_measured",
            },
            caveats=tuple(caveats),
        )


def _representation_probe(
    object_function: Callable[[], Any],
    typed_function: Callable[[], Any],
) -> dict[str, Any]:
    object_metrics = _allocation_snapshot(object_function)
    typed_metrics = _allocation_snapshot(typed_function)
    object_peak = object_metrics["peak_traced_bytes"]
    typed_peak = typed_metrics["peak_traced_bytes"]
    object_blocks = object_metrics["retained_blocks"]
    typed_blocks = typed_metrics["retained_blocks"]
    return {
        "available": True,
        "method": "tracemalloc_single_cold_call",
        "object_reference": object_metrics,
        "typed_buffer": typed_metrics,
        "peak_traced_bytes_reduction": (
            1.0 - typed_peak / object_peak
            if object_peak
            else None
        ),
        "retained_blocks_reduction": (
            1.0 - typed_blocks / object_blocks
            if object_blocks
            else None
        ),
        "semantically_equivalent": True,
    }


def _allocation_snapshot(
    function: Callable[[], Any],
) -> dict[str, int]:
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.take_snapshot()
        value = function()
        current, peak = tracemalloc.get_traced_memory()
        after = tracemalloc.take_snapshot()
        differences = after.compare_to(before, "filename")
        retained_blocks = sum(item.count_diff for item in differences)
        retained_bytes = sum(item.size_diff for item in differences)
        records = len(value) if isinstance(value, list) else 1
    finally:
        tracemalloc.stop()
    del value
    return {
        "records": records,
        "current_traced_bytes": current,
        "peak_traced_bytes": peak,
        "retained_blocks": retained_blocks,
        "retained_bytes": retained_bytes,
    }


def _measure(
    function: Callable[[], Any],
    iterations: int,
    energy: _EnergyCounter,
) -> tuple[int, int, int, float | None]:
    process = _process()
    rss_start = process.memory_info().rss if process is not None else 0
    energy_start = energy.read_joules()
    wall_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    for _ in range(iterations):
        function()
    cpu_elapsed = time.process_time_ns() - cpu_start
    wall_elapsed = time.perf_counter_ns() - wall_start
    energy_end = energy.read_joules()
    rss_end = process.memory_info().rss if process is not None else rss_start
    electrical = (
        max(0.0, energy_end - energy_start)
        if energy_start is not None and energy_end is not None
        else None
    )
    return wall_elapsed, cpu_elapsed, max(rss_start, rss_end), electrical


def _summarize(
    name: str,
    samples: list[tuple[int, int, int, float | None]],
    config: BorboletaConfig,
) -> BorboletaMeasurement:
    wall = tuple(item[0] for item in samples)
    cpu = tuple(item[1] for item in samples)
    rss = tuple(item[2] for item in samples)
    electrical = tuple(item[3] for item in samples)
    valid_energy = [value for value in electrical if value is not None]
    median_wall = int(statistics.median(wall))
    processed = config.records * config.iterations
    return BorboletaMeasurement(
        name=name,
        wall_ns_samples=wall,
        cpu_ns_samples=cpu,
        rss_observed_bytes_samples=rss,
        electrical_joules_samples=electrical,
        median_wall_ns=median_wall,
        median_cpu_ns=int(statistics.median(cpu)),
        median_rss_observed_bytes=int(statistics.median(rss)),
        median_electrical_joules=(
            statistics.median(valid_energy) if valid_energy else None
        ),
        throughput_records_per_second=(
            processed / (median_wall / 1_000_000_000)
            if median_wall
            else float("inf")
        ),
    )


def _bootstrap_median_ci(
    values: list[float],
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    rng = random.Random(seed)
    boot = sorted(
        statistics.median(rng.choice(values) for _ in values)
        for _ in range(resamples)
    )
    low = boot[max(0, round(0.025 * (len(boot) - 1)))]
    high = boot[min(len(boot) - 1, round(0.975 * (len(boot) - 1)))]
    return low, high


def _process():
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process()


def _environment() -> dict[str, Any]:
    process = _process()
    memory = None
    physical = None
    logical = os.cpu_count()
    if process is not None:
        import psutil

        memory = psutil.virtual_memory().total
        physical = psutil.cpu_count(logical=False)
    return {
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "cpu_physical": physical,
        "cpu_logical": logical,
        "memory_total_bytes": memory,
    }


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _semantic_projection(value: Any) -> Any:
    """Remove somente telemetria que necessariamente difere entre estratégias."""

    if isinstance(value, dict):
        return {
            key: _semantic_projection(item)
            for key, item in value.items()
            if key != "cache"
        }
    if isinstance(value, list):
        return [_semantic_projection(item) for item in value]
    return value


def _safe_ratio(
    numerator: float | int | None,
    denominator: float | int | None,
) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def _render_html(payload: dict[str, Any]) -> str:
    comparison = payload["comparison"]
    scalar = payload["scalar"]
    optimized = payload["optimized"]
    adaptive = payload["adaptive"]
    adaptation = payload["adaptation"]
    speedup = adaptation["end_to_end_wall_speedup"]
    ci = adaptation["end_to_end_wall_speedup_ci95_bootstrap"]
    energy = payload["energy"]
    decision = adaptation["decision"]
    representation = comparison.get("representation", {})
    raw = html.escape(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )
    energy_value = (
        f'{optimized["median_electrical_joules"]:.6f} J'
        if optimized["median_electrical_joules"] is not None
        else "não medida"
    )
    representation_card = ""
    if representation.get("available"):
        peak_reduction = representation.get(
            "peak_traced_bytes_reduction"
        )
        blocks_reduction = representation.get(
            "retained_blocks_reduction"
        )
        representation_card = (
            '<article class="card"><div>Pico alocado evitado</div>'
            f'<div class="value">{peak_reduction * 100:.1f}%</div>'
            f'<div>blocos retidos: {blocks_reduction * 100:.1f}% menos</div>'
            "</article>"
        )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Casulo — Relatório Borboleta</title>
<style>
:root {{ color-scheme: dark; --ink:#eef7f0; --muted:#9db2a3; --leaf:#75e39d;
--wing:#f5c76b; --panel:#14231b; --line:#31513d; }}
* {{ box-sizing:border-box }} body {{ margin:0;background:#09110d;color:var(--ink);
font:16px/1.55 system-ui,sans-serif }} main {{ max-width:1080px;margin:auto;padding:48px 24px }}
h1 {{ font-size:clamp(2rem,6vw,4.5rem);margin:0 }} .brand {{color:var(--wing);
letter-spacing:.16em;text-transform:uppercase;font-weight:700 }} .sub {{color:var(--muted)}}
.grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;
margin:32px 0}} .card {{background:var(--panel);border:1px solid var(--line);
border-radius:16px;padding:22px}} .value {{font-size:2rem;color:var(--leaf);font-weight:750}}
.ok {{color:var(--leaf)}} .warn {{color:var(--wing)}} details {{margin-top:28px}}
pre {{white-space:pre-wrap;overflow-wrap:anywhere;background:#060b08;padding:20px;
border-radius:12px;border:1px solid var(--line)}} code {{font-family:ui-monospace,monospace}}
</style></head><body><main>
<div class="brand">Teloscorp apresenta</div>
<h1>Casulo <span class="ok">Borboleta</span></h1>
<p class="sub">Evidência reproduzível de otimização conservativa do tráfego de informação.</p>
<section class="grid">
<article class="card"><div>Fator adaptativo E2E</div><div class="value">{speedup:.3f}×</div>
<div>IC 95% bootstrap: {ci[0]:.3f}×–{ci[1]:.3f}×</div></article>
<article class="card"><div>Vazão adaptativa</div><div class="value">
{adaptive["throughput_records_per_second"]:,.0f}</div><div>registros/s</div></article>
<article class="card"><div>Equivalência</div><div class="value">provada</div>
<div>SHA-256 da projeção semântica coincidente</div></article>
<article class="card"><div>Decisão adaptativa</div><div class="value">
{html.escape(decision["strategy"])}</div>
<div>{html.escape(adaptation["assessment"])}</div></article>
<article class="card"><div>Energia elétrica</div><div class="value">{energy_value}</div>
<div class="{"ok" if energy["electrical_energy_measured"] else "warn"}">
{html.escape(energy["method"])}</div></article>
{representation_card}
</section>
<p>Referência escalar: {scalar["median_wall_ns"]/1e6:.3f} ms · lote Casulo:
{optimized["median_wall_ns"]/1e6:.3f} ms por amostra.</p>
<p>Veredito estatístico: <strong>{html.escape(comparison["verdict"])}</strong>.
Valores acima de 1× favorecem a estratégia Casulo.</p>
<p class="sub">Artefato <code>{html.escape(payload["artifact_id"])}</code> · dataset
<code>{html.escape(payload["dataset"]["sha256"])}</code></p>
<details><summary>Relatório integral em JSON</summary><pre>{raw}</pre></details>
</main></body></html>
"""
