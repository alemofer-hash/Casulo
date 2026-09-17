"""Primitivas auditáveis para estabilizar medições do Casulo/T.

A calibração decide somente a duração do lote, antes das amostras oficiais.
Ela nunca observa speedup, escolhe backend vencedor ou remove amostras.
"""

from __future__ import annotations

import contextlib
import ctypes
import math
import os
import platform
import statistics
import struct
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Mapping, Sequence


MEASUREMENT_STABILITY_PROTOCOL = "casulo-measurement-stability/0.1"


class MeasurementStabilityError(RuntimeError):
    """A máquina não consegue cumprir um desenho metrológico selado."""


def calibrate_shared_iterations(
    runners: Mapping[str, Callable[[], Any]],
    *,
    minimum_iterations: int,
    maximum_iterations: int,
    target_wall_ms: float,
    measure: Callable[[Callable[[], Any], int], tuple[int, int]],
) -> tuple[int, dict[str, Any]]:
    """Encontra um lote comum que dê a cada backend a duração mínima.

    Cada backend dobra seu lote independentemente até alcançar o alvo. O maior
    lote requerido é então aplicado a todos, preservando o pareamento.
    """

    if not runners:
        raise MeasurementStabilityError("calibração sem backends")
    if minimum_iterations < 1 or maximum_iterations < minimum_iterations:
        raise MeasurementStabilityError("limites de calibração inválidos")
    if not math.isfinite(target_wall_ms) or target_wall_ms <= 0:
        raise MeasurementStabilityError("duração-alvo inválida")
    target_wall_ns = int(math.ceil(target_wall_ms * 1_000_000))
    traces: dict[str, list[dict[str, int]]] = {}
    required: dict[str, int] = {}
    reached: dict[str, bool] = {}
    for backend, runner in runners.items():
        iterations = minimum_iterations
        trace: list[dict[str, int]] = []
        while True:
            wall_ns, cpu_ns = measure(runner, iterations)
            trace.append(
                {
                    "iterations": iterations,
                    "wall_ns": wall_ns,
                    "cpu_ns": cpu_ns,
                }
            )
            if wall_ns >= target_wall_ns:
                reached[backend] = True
                break
            if iterations >= maximum_iterations:
                reached[backend] = False
                break
            iterations = min(maximum_iterations, iterations * 2)
        traces[backend] = trace
        required[backend] = iterations
    selected = max(required.values())
    verification: dict[str, dict[str, Any]] = {}
    for backend, runner in runners.items():
        wall_ns, cpu_ns = measure(runner, selected)
        verification[backend] = {
            "iterations": selected,
            "wall_ns": wall_ns,
            "cpu_ns": cpu_ns,
            "target_reached": wall_ns >= target_wall_ns,
        }
    all_reached = all(
        item["target_reached"] for item in verification.values()
    )
    return selected, {
        "protocol": MEASUREMENT_STABILITY_PROTOCOL,
        "algorithm": "per-backend-doubling-then-shared-maximum",
        "uses_speedup_or_winner_selection": False,
        "minimum_iterations": minimum_iterations,
        "maximum_iterations": maximum_iterations,
        "target_wall_ms": target_wall_ms,
        "target_wall_ns": target_wall_ns,
        "required_iterations_by_backend": required,
        "target_reached_during_search": reached,
        "search_trace": traces,
        "selected_shared_iterations": selected,
        "verification": verification,
        "all_backends_reached_target": all_reached,
    }


def coefficient_of_variation(values: Sequence[float]) -> float | None:
    finite = [
        float(value)
        for value in values
        if math.isfinite(float(value))
    ]
    if len(finite) < 2:
        return None
    mean = statistics.fmean(finite)
    if mean == 0:
        return None
    return statistics.stdev(finite) / abs(mean)


@contextlib.contextmanager
def cpu_affinity_scope(
    requested: Sequence[int] | None,
) -> Iterator[dict[str, Any]]:
    """Aplica e depois restaura afinidade do processo, quando solicitada."""

    if requested is None:
        yield {
            "requested": None,
            "applied": False,
            "original": current_cpu_affinity(),
            "effective": current_cpu_affinity(),
            "reason": "afinidade não solicitada",
        }
        return
    try:
        import psutil
    except ImportError as exc:
        raise MeasurementStabilityError(
            "psutil é obrigatório para afinidade selada"
        ) from exc
    process = psutil.Process()
    if not hasattr(process, "cpu_affinity"):
        raise MeasurementStabilityError(
            "afinidade de CPU não é suportada nesta plataforma"
        )
    original = [int(item) for item in process.cpu_affinity()]
    normalized = list(dict.fromkeys(int(item) for item in requested))
    if not normalized:
        raise MeasurementStabilityError("afinidade solicitada está vazia")
    unavailable = sorted(set(normalized) - set(original))
    if unavailable:
        raise MeasurementStabilityError(
            "CPUs fora da afinidade permitida: "
            + ", ".join(str(item) for item in unavailable)
        )
    process.cpu_affinity(normalized)
    effective = [int(item) for item in process.cpu_affinity()]
    if set(effective) != set(normalized):
        process.cpu_affinity(original)
        raise MeasurementStabilityError(
            "sistema operacional não aplicou a afinidade solicitada"
        )
    state = {
        "requested": normalized,
        "applied": True,
        "original": original,
        "effective": effective,
        "reason": None,
    }
    try:
        yield state
    finally:
        process.cpu_affinity(original)


def current_cpu_affinity() -> list[int] | None:
    try:
        import psutil
    except ImportError:
        return None
    process = psutil.Process()
    if not hasattr(process, "cpu_affinity"):
        return None
    return [int(item) for item in process.cpu_affinity()]


def system_telemetry_snapshot(*, static: bool = False) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "process_cpu_affinity": current_cpu_affinity(),
        "cpu_frequency_mhz": None,
        "cpu_frequency_per_cpu_mhz": None,
        "temperature_celsius": None,
        "temperature_source": None,
        "battery_percent": None,
        "power_plugged": None,
        "system_load_percent": None,
    }
    try:
        import psutil
    except ImportError:
        snapshot["reason"] = "psutil indisponível"
        return snapshot
    frequency = psutil.cpu_freq()
    per_cpu_frequency = psutil.cpu_freq(percpu=True)
    temperatures = (
        psutil.sensors_temperatures()
        if hasattr(psutil, "sensors_temperatures")
        else {}
    )
    observed_temperatures = [
        float(entry.current)
        for entries in temperatures.values()
        for entry in entries
        if entry.current is not None
    ]
    battery = (
        psutil.sensors_battery()
        if hasattr(psutil, "sensors_battery")
        else None
    )
    snapshot.update(
        {
            "cpu_frequency_mhz": (
                float(frequency.current) if frequency is not None else None
            ),
            "cpu_frequency_per_cpu_mhz": (
                [float(item.current) for item in per_cpu_frequency]
                if per_cpu_frequency
                else None
            ),
            "temperature_celsius": (
                max(observed_temperatures)
                if observed_temperatures
                else None
            ),
            "temperature_source": (
                "psutil.sensors_temperatures"
                if observed_temperatures
                else None
            ),
            "battery_percent": (
                float(battery.percent) if battery is not None else None
            ),
            "power_plugged": (
                bool(battery.power_plugged) if battery is not None else None
            ),
            "system_load_percent": float(psutil.cpu_percent(interval=None)),
            "available_memory_bytes": int(
                psutil.virtual_memory().available
            ),
        }
    )
    if static:
        snapshot["cpu_topology"] = cpu_topology_snapshot()
        snapshot["active_power_scheme"] = active_power_scheme()
        snapshot["platform"] = platform.platform()
    return snapshot


def active_power_scheme() -> dict[str, Any] | None:
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["powercfg", "/getactivescheme"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)}
    output = " ".join(
        (completed.stdout or completed.stderr or "").split()
    )
    return {
        "status": "OBSERVED" if completed.returncode == 0 else "UNAVAILABLE",
        "returncode": completed.returncode,
        "value": output or None,
    }


def cpu_topology_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "logical_cpu_count": os.cpu_count(),
        "current_affinity": current_cpu_affinity(),
        "cores": None,
        "method": None,
        "reason": None,
    }
    if os.name != "nt":
        result["reason"] = "topologia detalhada implementada para Windows"
        return result
    try:
        cores = _windows_processor_cores()
    except (OSError, ValueError) as exc:
        result["reason"] = str(exc)
        return result
    result["cores"] = cores
    result["method"] = "GetLogicalProcessorInformationEx"
    return result


def _windows_processor_cores() -> list[dict[str, Any]]:
    relation_processor_core = 0
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel32.GetLogicalProcessorInformationEx
    query.argtypes = [
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    query.restype = ctypes.c_bool
    size = ctypes.c_ulong(0)
    query(relation_processor_core, None, ctypes.byref(size))
    if size.value <= 0:
        raise OSError(
            ctypes.get_last_error(),
            "GetLogicalProcessorInformationEx não informou tamanho",
        )
    buffer = ctypes.create_string_buffer(size.value)
    if not query(
        relation_processor_core,
        ctypes.byref(buffer),
        ctypes.byref(size),
    ):
        raise OSError(
            ctypes.get_last_error(),
            "GetLogicalProcessorInformationEx falhou",
        )
    raw = buffer.raw[: size.value]
    offset = 0
    cores: list[dict[str, Any]] = []
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise ValueError("registro de topologia truncado")
        relation, record_size = struct.unpack_from("<II", raw, offset)
        if record_size < 32 or offset + record_size > len(raw):
            raise ValueError("tamanho de registro de topologia inválido")
        if relation == relation_processor_core:
            flags = raw[offset + 8]
            efficiency_class = raw[offset + 9]
            group_count = struct.unpack_from("<H", raw, offset + 30)[0]
            logical_processors: list[int] = []
            group_offset = offset + 32
            group_size = 16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 12
            mask_format = "<Q" if group_size == 16 else "<I"
            mask_size = 8 if group_size == 16 else 4
            for _ in range(group_count):
                if group_offset + group_size > offset + record_size:
                    raise ValueError("máscara de grupo truncada")
                mask = struct.unpack_from(mask_format, raw, group_offset)[0]
                group = struct.unpack_from(
                    "<H", raw, group_offset + mask_size
                )[0]
                logical_processors.extend(
                    group * 64 + bit
                    for bit in range(mask_size * 8)
                    if mask & (1 << bit)
                )
                group_offset += group_size
            cores.append(
                {
                    "core_index": len(cores),
                    "efficiency_class": int(efficiency_class),
                    "smt": bool(flags & 1),
                    "logical_processors": logical_processors,
                }
            )
        offset += record_size
    if not cores:
        raise ValueError("nenhum núcleo retornado pela API do Windows")
    return cores
