"""Calibração segmentada da menor janela metrologicamente estável.

Este módulo mede somente o backend candidato. Ele não carrega PyTorch, não
calcula speedup e não seleciona implementação vencedora. O resultado serve
apenas para escolher, por uma regra pré-registrada, a duração mínima de cada
bloco do Sprint 025.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .autograd import compile_autograd_file
from .measurement import (
    calibrate_shared_iterations,
    coefficient_of_variation,
    system_telemetry_snapshot,
)
from .parity import NumpyTensorExecutor, compare_executions
from .tensor import TensorDType
from .tensor_cpu import prepare_tensor_cpu_executor


WINDOW_PREREGISTRATION_PROTOCOL = "casulo-window-preregistration/0.1"
WINDOW_SAMPLE_PROTOCOL = "casulo-window-sample/0.1"
WINDOW_VERDICT_PROTOCOL = "casulo-window-verdict/0.1"


class WindowCalibrationError(RuntimeError):
    """O desenho ou a evidência de calibração não é verificável."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_immutable_json(path: Path, document: Mapping[str, Any]) -> str:
    path = Path(path).expanduser().resolve()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if path.exists() or sidecar.exists():
        raise WindowCalibrationError(f"evidência já existe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    digest = _sha256_bytes(payload)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def verify_evidence(path: str | Path) -> tuple[dict[str, Any], str]:
    source = Path(path).expanduser().resolve()
    payload = source.read_bytes()
    document = json.loads(payload.decode("utf-8"))
    digest = _sha256_bytes(payload)
    sidecar = source.with_suffix(source.suffix + ".sha256")
    expected = sidecar.read_text(encoding="ascii").split()[0]
    if digest != expected:
        raise WindowCalibrationError(f"SHA-256 diverge: {source}")
    return document, digest


def create_preregistration(
    graph_path: str | Path,
    output_path: str | Path,
    *,
    wrt: Sequence[str],
    loss: str | None = None,
    windows_ms: Sequence[float] = (250.0, 500.0),
    samples_per_window: int = 7,
    warmups: int = 2,
    max_cv: float = 0.15,
    workers: int = 2,
    gemm_workers: int | str | None = None,
    provider: str = "owned",
    seed: int = 20_260_731,
    cooldown_ms: int = 100,
    maximum_inner_iterations: int = 1_000_000,
) -> dict[str, Any]:
    graph = Path(graph_path).expanduser().resolve()
    windows = tuple(float(item) for item in windows_ms)
    if not graph.is_file():
        raise WindowCalibrationError(f"grafo ausente: {graph}")
    if not wrt:
        raise WindowCalibrationError("ao menos um wrt é obrigatório")
    if (
        len(windows) < 1
        or any(not math.isfinite(item) or item <= 0 for item in windows)
        or list(windows) != sorted(set(windows))
    ):
        raise WindowCalibrationError(
            "janelas precisam ser positivas, únicas e crescentes"
        )
    if samples_per_window < 7 or warmups < 1:
        raise WindowCalibrationError("desenho exige 7 amostras e 1 warmup")
    if not math.isfinite(max_cv) or not 0 < max_cv <= 1:
        raise WindowCalibrationError("max_cv precisa estar em (0, 1]")
    if workers not in {1, 2}:
        raise WindowCalibrationError("Thermal Covenant limita workers a 1 ou 2")
    if provider not in {"owned", "openblas"}:
        raise WindowCalibrationError("provider precisa ser owned ou openblas")
    selected_gemm_workers: int | str = (
        workers if gemm_workers is None else gemm_workers
    )
    if selected_gemm_workers != "adaptive":
        selected_gemm_workers = int(selected_gemm_workers)
        if selected_gemm_workers not in {1, 2}:
            raise WindowCalibrationError(
                "gemm_workers precisa ser adaptive, 1 ou 2"
            )
        if selected_gemm_workers > workers:
            raise WindowCalibrationError(
                "gemm_workers excede o orçamento térmico de workers"
            )
    if cooldown_ms < 0 or maximum_inner_iterations < 1:
        raise WindowCalibrationError("limites de execução inválidos")
    autograd = compile_autograd_file(graph, wrt=tuple(wrt), loss=loss)
    document: dict[str, Any] = {
        "protocol": WINDOW_PREREGISTRATION_PROTOCOL,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "brand": {
            "invention": "Casulo",
            "origin": "Teloscorp",
            "specialty": "Otimização de Tráfego de Informação",
        },
        "workload": {
            "graph_path_hint": graph.name,
            "graph_sha256": _sha256_bytes(graph.read_bytes()),
            "autograd_protocol": autograd.protocol,
            "wrt": list(dict.fromkeys(wrt)),
            "loss": autograd.loss,
            "input_seed": int(seed),
            "backend": "casulo-candidate-only",
            "workers": int(workers),
            "gemm_workers": selected_gemm_workers,
            "provider": provider,
        },
        "design": {
            "windows_ms": list(windows),
            "samples_per_window": int(samples_per_window),
            "warmups": int(warmups),
            "max_coefficient_of_variation": float(max_cv),
            "cooldown_ms": int(cooldown_ms),
            "maximum_inner_iterations": int(maximum_inner_iterations),
            "selection_rule": "first-ascending-window-with-cv-at-or-below-limit",
            "stop_after_first_stable_window": True,
            "uses_speedup_or_winner_selection": False,
        },
        "scientific_scope": {
            "claim_eligible": False,
            "pytorch_loaded": False,
            "purpose": "measurement-window-calibration-only",
            "limitations": [
                "a estabilidade vale apenas para o workload e host registrados",
                "a calibração não mede superioridade nem economia de energia",
            ],
        },
        "claim": None,
    }
    _write_immutable_json(Path(output_path), document)
    return document


def _generate_inputs(autograd: Any, seed: int) -> dict[str, Any]:
    try:
        import numpy as np
    except ImportError as exc:
        raise WindowCalibrationError("NumPy é obrigatório") from exc
    rng = np.random.default_rng(seed)
    inputs: dict[str, Any] = {}
    for item in autograd.forward.inputs:
        dtype = {
            TensorDType.FLOAT32: np.float32,
            TensorDType.FLOAT64: np.float64,
        }.get(item.type.dtype)
        if dtype is None:
            raise WindowCalibrationError(
                f"dtype não suportado: {item.type.dtype.value}"
            )
        values = rng.normal(size=tuple(int(x) for x in item.type.shape))
        if item.name.lower().startswith("weight"):
            values *= 0.1
        inputs[item.name] = values.astype(dtype)
    return inputs


def _measure_batch(function: Callable[[], Any], iterations: int) -> tuple[int, int]:
    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        cpu_started = time.process_time_ns()
        wall_started = time.perf_counter_ns()
        for _ in range(iterations):
            function()
        return (
            time.perf_counter_ns() - wall_started,
            time.process_time_ns() - cpu_started,
        )
    finally:
        if was_enabled:
            gc.enable()


def run_window(
    preregistration_path: str | Path,
    graph_path: str | Path,
    output_path: str | Path,
    *,
    window_ms: float,
) -> dict[str, Any]:
    preregistration, preregistration_sha256 = verify_evidence(
        preregistration_path
    )
    if preregistration.get("protocol") != WINDOW_PREREGISTRATION_PROTOCOL:
        raise WindowCalibrationError("protocolo de pré-registro desconhecido")
    graph = Path(graph_path).expanduser().resolve()
    workload = preregistration["workload"]
    design = preregistration["design"]
    if _sha256_bytes(graph.read_bytes()) != workload["graph_sha256"]:
        raise WindowCalibrationError("grafo diverge do pré-registro")
    target = float(window_ms)
    candidates = [float(item) for item in design["windows_ms"]]
    if target not in candidates:
        raise WindowCalibrationError("janela não consta no pré-registro")

    autograd = compile_autograd_file(
        graph,
        wrt=tuple(workload["wrt"]),
        loss=workload["loss"],
    )
    inputs = _generate_inputs(autograd, int(workload["input_seed"]))
    reference = NumpyTensorExecutor().execute(autograd, inputs)
    registered_gemm_workers = workload["gemm_workers"]
    prepared = prepare_tensor_cpu_executor(
        autograd,
        inputs,
        workers=int(workload["workers"]),
        gemm_workers=(
            registered_gemm_workers
            if registered_gemm_workers == "adaptive"
            else int(registered_gemm_workers)
        ),
        provider=str(workload["provider"]),
    )
    prepared.invoke(audit=True)
    parity = compare_executions(
        reference,
        prepared.snapshot(reference),
        autograd,
    )
    if not parity.passed:
        raise WindowCalibrationError("paridade candidato versus NumPy falhou")
    for _ in range(int(design["warmups"])):
        prepared.invoke(audit=False)

    runner = lambda: prepared.invoke(audit=False)
    iterations, calibration = calibrate_shared_iterations(
        {"casulo-candidate-only": runner},
        minimum_iterations=1,
        maximum_iterations=int(design["maximum_inner_iterations"]),
        target_wall_ms=target,
        measure=_measure_batch,
    )
    if not calibration["all_backends_reached_target"]:
        raise WindowCalibrationError("janela não foi alcançada no limite selado")
    samples: list[dict[str, Any]] = []
    for index in range(int(design["samples_per_window"])):
        if index and int(design["cooldown_ms"]):
            time.sleep(int(design["cooldown_ms"]) / 1_000)
        before = system_telemetry_snapshot()
        wall_ns, cpu_ns = _measure_batch(runner, iterations)
        samples.append(
            {
                "index": index,
                "wall_ns": wall_ns,
                "cpu_ns": cpu_ns,
                "inner_iterations": iterations,
                "wall_ns_per_invocation": wall_ns / iterations,
                "cpu_ns_per_invocation": cpu_ns / iterations,
                "telemetry_before": before,
                "telemetry_after": system_telemetry_snapshot(),
            }
        )
    values = [float(item["wall_ns_per_invocation"]) for item in samples]
    cv = coefficient_of_variation(values)
    document: dict[str, Any] = {
        "protocol": WINDOW_SAMPLE_PROTOCOL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistration_sha256": preregistration_sha256,
        "window_ms": target,
        "calibration": calibration,
        "selected_inner_iterations": iterations,
        "quality": {
            "candidate_vs_numpy": parity.to_dict(),
            "finite_samples": all(math.isfinite(item) for item in values),
        },
        "samples": samples,
        "statistics": {
            "sample_count": len(values),
            "median_wall_ns_per_invocation": statistics.median(values),
            "coefficient_of_variation": cv,
            "limit": float(design["max_coefficient_of_variation"]),
            "stable": cv is not None
            and cv <= float(design["max_coefficient_of_variation"]),
        },
        "scientific_scope": {
            "claim_eligible": False,
            "speedup_computed": False,
            "baseline_loaded": False,
        },
        "claim": None,
    }
    _write_immutable_json(Path(output_path), document)
    return document


def select_smallest_stable_window(
    preregistration: Mapping[str, Any],
    reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidates = [float(item) for item in preregistration["design"]["windows_ms"]]
    by_window: dict[float, Mapping[str, Any]] = {}
    for report in reports:
        target = float(report["window_ms"])
        if target in by_window:
            raise WindowCalibrationError(f"janela duplicada: {target}")
        if target not in candidates:
            raise WindowCalibrationError(f"janela não pré-registrada: {target}")
        by_window[target] = report
    evaluated: list[dict[str, Any]] = []
    selected: float | None = None
    for target in candidates:
        report = by_window.get(target)
        if report is None:
            break
        stable = bool(report["statistics"]["stable"])
        evaluated.append(
            {
                "window_ms": target,
                "coefficient_of_variation": report["statistics"][
                    "coefficient_of_variation"
                ],
                "stable": stable,
            }
        )
        if stable:
            selected = target
            break
    return {
        "status": "PASSED" if selected is not None else "INCONCLUSIVE",
        "selected_window_ms": selected,
        "evaluated": evaluated,
        "needs_next_window": selected is None and len(evaluated) < len(candidates),
        "next_window_ms": (
            candidates[len(evaluated)]
            if selected is None and len(evaluated) < len(candidates)
            else None
        ),
        "uses_speedup_or_winner_selection": False,
    }


def judge(
    preregistration_path: str | Path,
    report_paths: Sequence[str | Path],
    output_path: str | Path,
) -> dict[str, Any]:
    preregistration, preregistration_sha256 = verify_evidence(
        preregistration_path
    )
    reports: list[dict[str, Any]] = []
    report_hashes: list[str] = []
    for path in report_paths:
        report, digest = verify_evidence(path)
        if report.get("protocol") != WINDOW_SAMPLE_PROTOCOL:
            raise WindowCalibrationError("relatório de janela desconhecido")
        if report.get("preregistration_sha256") != preregistration_sha256:
            raise WindowCalibrationError("relatório não pertence ao pré-registro")
        reports.append(report)
        report_hashes.append(digest)
    decision = select_smallest_stable_window(preregistration, reports)
    document = {
        "protocol": WINDOW_VERDICT_PROTOCOL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistration_sha256": preregistration_sha256,
        "report_sha256": report_hashes,
        **decision,
        "claim": None,
    }
    _write_immutable_json(Path(output_path), document)
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casulo-window")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preregister = subparsers.add_parser("preregister")
    preregister.add_argument("graph")
    preregister.add_argument("--output", required=True)
    preregister.add_argument("--wrt", nargs="+", required=True)
    preregister.add_argument("--loss")
    preregister.add_argument("--windows-ms", nargs="+", type=float, default=[250, 500])
    preregister.add_argument("--samples", type=int, default=7)
    preregister.add_argument("--warmups", type=int, default=2)
    preregister.add_argument("--max-cv", type=float, default=0.15)
    preregister.add_argument("--workers", type=int, default=2)
    preregister.add_argument(
        "--gemm-workers",
        choices=("adaptive", "1", "2"),
    )
    preregister.add_argument(
        "--provider",
        choices=("owned", "openblas"),
        default="owned",
    )
    preregister.add_argument("--cooldown-ms", type=int, default=100)

    run = subparsers.add_parser("run")
    run.add_argument("preregistration")
    run.add_argument("graph")
    run.add_argument("--output", required=True)
    run.add_argument("--window-ms", type=float, required=True)

    adjudicate = subparsers.add_parser("judge")
    adjudicate.add_argument("preregistration")
    adjudicate.add_argument("reports", nargs="+")
    adjudicate.add_argument("--output", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("evidence", nargs="+")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preregister":
        document = create_preregistration(
            args.graph,
            args.output,
            wrt=args.wrt,
            loss=args.loss,
            windows_ms=args.windows_ms,
            samples_per_window=args.samples,
            warmups=args.warmups,
            max_cv=args.max_cv,
            workers=args.workers,
            gemm_workers=args.gemm_workers,
            provider=args.provider,
            cooldown_ms=args.cooldown_ms,
        )
    elif args.command == "run":
        document = run_window(
            args.preregistration,
            args.graph,
            args.output,
            window_ms=args.window_ms,
        )
    elif args.command == "judge":
        document = judge(args.preregistration, args.reports, args.output)
    else:
        verified = []
        for path in args.evidence:
            document, digest = verify_evidence(path)
            verified.append(
                {"path": str(Path(path).resolve()), "sha256": digest, "protocol": document.get("protocol")}
            )
        document = {"status": "VERIFIED", "evidence": verified}
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
