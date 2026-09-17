"""Pacto térmico fail-closed para experimentos do Casulo/T.

O módulo não estima temperatura nem infere ausência de throttling. Uma sessão
elegível exige observações explícitas e confiáveis para ambos os sinais.
"""

from __future__ import annotations

import csv
import json
import math
import os
import platform
import time
import urllib.error
import urllib.request
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .measurement import system_telemetry_snapshot


THERMAL_COVENANT_PROTOCOL = "casulo-thermal-covenant/0.1"
THERMAL_OBSERVATION_PROTOCOL = "casulo-thermal-observation/0.1"
THERMAL_GATE_PROTOCOL = "casulo-thermal-gate/0.1"


class ThermalCovenantError(RuntimeError):
    """O pacto térmico não pode garantir uma execução segura e auditável."""


@dataclass(frozen=True)
class ThermalPolicy:
    """Limites conservadores iniciais, não limites de projeto do fabricante."""

    warning_celsius: float = 75.0
    soft_stop_celsius: float = 80.0
    hard_stop_celsius: float = 85.0
    resume_below_celsius: float = 55.0
    sample_interval_seconds: float = 0.5
    sensor_stale_after_seconds: float = 2.0
    maximum_continuous_seconds: float = 20.0
    maximum_block_seconds: float = 60.0
    maximum_blocks_per_session: int = 3
    maximum_heavy_seconds_per_hour: float = 600.0
    maximum_workers: int = 2
    stable_start_samples: int = 3
    minimum_unplugged_battery_percent: float = 40.0

    def __post_init__(self) -> None:
        temperatures = (
            self.resume_below_celsius,
            self.warning_celsius,
            self.soft_stop_celsius,
            self.hard_stop_celsius,
        )
        if not all(math.isfinite(item) for item in temperatures):
            raise ValueError("limites térmicos precisam ser finitos")
        if not (
            self.resume_below_celsius
            < self.warning_celsius
            < self.soft_stop_celsius
            < self.hard_stop_celsius
        ):
            raise ValueError("ordem dos limites térmicos é inválida")
        if not 0.1 <= self.sample_interval_seconds <= 2.0:
            raise ValueError("intervalo de amostragem fora de 0,1–2,0 s")
        if self.sensor_stale_after_seconds < self.sample_interval_seconds:
            raise ValueError("sensor pode expirar antes da próxima amostra")
        if not (
            0 < self.maximum_continuous_seconds
            <= self.maximum_block_seconds
            <= 60
        ):
            raise ValueError("orçamento temporal térmico inválido")
        if self.maximum_workers not in {1, 2}:
            raise ValueError("gate inicial admite no máximo dois workers")
        if self.stable_start_samples < 1:
            raise ValueError("é necessária ao menos uma leitura inicial")
        if not 0 <= self.minimum_unplugged_battery_percent <= 100:
            raise ValueError("limite de bateria fora de 0–100%")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThermalObservation:
    observed_at_utc: str
    temperature_celsius: float | None
    temperature_source: str | None
    temperature_trusted: bool
    thermal_throttling: bool | None
    throttling_source: str | None
    throttling_trusted: bool
    source_status: str
    detail: str | None = None

    @property
    def gate_observable(self) -> bool:
        return (
            self.temperature_celsius is not None
            and self.temperature_trusted
            and self.thermal_throttling is not None
            and self.throttling_trusted
            and self.source_status == "OBSERVED"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": THERMAL_OBSERVATION_PROTOCOL,
            **asdict(self),
            "gate_observable": self.gate_observable,
        }


class ThermalSource(Protocol):
    source_id: str

    def sample(self) -> ThermalObservation: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PsutilThermalSource:
    """Usa sensores nativos expostos pelo SO; no Windows eles costumam faltar."""

    source_id = "psutil.sensors_temperatures"
    _TRUSTED_SENSOR_GROUPS = {
        "coretemp",
        "k10temp",
        "zenpower",
        "cpu_thermal",
    }

    def sample(self) -> ThermalObservation:
        try:
            import psutil
        except ImportError:
            return unavailable_observation(self.source_id, "psutil indisponível")
        if not hasattr(psutil, "sensors_temperatures"):
            return unavailable_observation(
                self.source_id,
                "plataforma não expõe sensors_temperatures",
            )
        groups = psutil.sensors_temperatures() or {}
        readings: list[tuple[str, float]] = []
        for group, entries in groups.items():
            for entry in entries:
                if entry.current is not None and math.isfinite(entry.current):
                    readings.append((str(group).lower(), float(entry.current)))
        trusted = [
            value
            for group, value in readings
            if group in self._TRUSTED_SENSOR_GROUPS
        ]
        if not trusted:
            detail = (
                "nenhum sensor de CPU confiável"
                if readings
                else "nenhuma temperatura exposta"
            )
            return unavailable_observation(self.source_id, detail)
        return ThermalObservation(
            observed_at_utc=utc_now(),
            temperature_celsius=max(trusted),
            temperature_source=self.source_id,
            temperature_trusted=True,
            thermal_throttling=None,
            throttling_source=None,
            throttling_trusted=False,
            source_status="PARTIAL",
            detail="temperatura observada; throttling não exposto pelo psutil",
        )


class JsonFileThermalSource:
    """Lê snapshot atômico produzido por um monitor externo confiável.

    O produtor deve atualizar ``observed_at_utc`` e declarar explicitamente a
    confiabilidade dos dois sinais. O Casulo nunca promove esses campos.
    """

    def __init__(self, path: Path, *, stale_after_seconds: float = 2.0) -> None:
        self.path = Path(path)
        self.stale_after_seconds = stale_after_seconds
        self.source_id = f"json-file:{self.path.resolve()}"

    def sample(self) -> ThermalObservation:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return unavailable_observation(self.source_id, str(exc))
        try:
            observed_at = datetime.fromisoformat(
                str(document["observed_at_utc"]).replace("Z", "+00:00")
            )
            age = (datetime.now(timezone.utc) - observed_at).total_seconds()
            temperature = float(document["temperature_celsius"])
            throttling = document["thermal_throttling"]
            if not isinstance(throttling, bool):
                raise ValueError("thermal_throttling não é booleano")
            if not math.isfinite(temperature):
                raise ValueError("temperatura não finita")
        except (KeyError, TypeError, ValueError) as exc:
            return unavailable_observation(self.source_id, str(exc))
        if age < -5 or age > self.stale_after_seconds:
            return unavailable_observation(
                self.source_id,
                f"snapshot expirado (idade={age:.3f}s)",
            )
        temperature_trusted = document.get("temperature_trusted") is True
        throttling_trusted = document.get("throttling_trusted") is True
        status = (
            "OBSERVED"
            if temperature_trusted and throttling_trusted
            else "UNTRUSTED"
        )
        return ThermalObservation(
            observed_at_utc=observed_at.astimezone(timezone.utc).isoformat(),
            temperature_celsius=temperature,
            temperature_source=str(
                document.get("temperature_source", self.source_id)
            ),
            temperature_trusted=temperature_trusted,
            thermal_throttling=throttling,
            throttling_source=str(
                document.get("throttling_source", self.source_id)
            ),
            throttling_trusted=throttling_trusted,
            source_status=status,
            detail=document.get("detail"),
        )


class HWiNFOCsvThermalSource:
    """Consome o último registro completo do logging CSV do HWiNFO."""

    _CPU_MARKERS = ("cpu", "core", "nucleo", "package", "inteira")
    _TEMPERATURE_MARKERS = (
        "temperatura",
        "temperature",
        "core max",
        "nucleo maximo",
        "cpu inteira",
        "cpu package",
    )
    _THROTTLE_MARKERS = (
        "thermal throttling",
        "estrangulamento termico",
    )
    _POWER_LIMIT_MARKERS = ("power limit", "limite de potencia")

    def __init__(self, path: Path, *, stale_after_seconds: float = 5.0) -> None:
        self.path = Path(path)
        self.stale_after_seconds = stale_after_seconds
        self.source_id = f"hwinfo-csv:{self.path.resolve()}"

    def sample(self) -> ThermalObservation:
        try:
            stat = self.path.stat()
            age = time.time() - stat.st_mtime
            with self.path.open(
                "r",
                encoding="utf-8-sig",
                errors="replace",
                newline="",
            ) as stream:
                rows = [row for row in csv.reader(stream) if row]
        except OSError as exc:
            return unavailable_observation(self.source_id, str(exc))
        if age < -5 or age > self.stale_after_seconds:
            return unavailable_observation(
                self.source_id,
                f"CSV expirado (idade={age:.3f}s)",
            )
        if len(rows) < 2:
            return unavailable_observation(
                self.source_id,
                "CSV ainda não contém amostra completa",
            )
        headers = rows[0]
        values = next(
            (row for row in reversed(rows[1:]) if len(row) >= len(headers)),
            None,
        )
        if values is None:
            return unavailable_observation(
                self.source_id,
                "última amostra CSV está incompleta",
            )
        normalized = [_normalize_sensor_name(item) for item in headers]
        temperature_columns: list[tuple[str, float]] = []
        throttle_columns: list[tuple[str, bool]] = []
        power_limit_columns: list[tuple[str, bool]] = []
        for index, header in enumerate(normalized):
            value = values[index]
            if (
                any(marker in header for marker in self._CPU_MARKERS)
                and any(
                    marker in header for marker in self._TEMPERATURE_MARKERS
                )
                and "tjmax" not in header
                and "distance" not in header
                and "distancia" not in header
                and "gpu" not in header
            ):
                parsed_temperature = _parse_number(value)
                if (
                    parsed_temperature is not None
                    and -20 <= parsed_temperature <= 130
                ):
                    temperature_columns.append(
                        (headers[index], parsed_temperature)
                    )
            if any(marker in header for marker in self._THROTTLE_MARKERS):
                parsed_throttle = _parse_bool(value)
                if parsed_throttle is not None:
                    throttle_columns.append((headers[index], parsed_throttle))
            if any(marker in header for marker in self._POWER_LIMIT_MARKERS):
                parsed_power_limit = _parse_bool(value)
                if parsed_power_limit is not None:
                    power_limit_columns.append(
                        (headers[index], parsed_power_limit)
                    )
        if not temperature_columns:
            return unavailable_observation(
                self.source_id,
                "CSV sem coluna reconhecida de temperatura da CPU",
            )
        if not throttle_columns:
            return ThermalObservation(
                observed_at_utc=datetime.fromtimestamp(
                    stat.st_mtime,
                    timezone.utc,
                ).isoformat(),
                temperature_celsius=max(
                    value for _, value in temperature_columns
                ),
                temperature_source=self.source_id,
                temperature_trusted=True,
                thermal_throttling=None,
                throttling_source=None,
                throttling_trusted=False,
                source_status="PARTIAL",
                detail=(
                    "temperatura encontrada; coluna de throttling térmico "
                    "ausente"
                ),
            )
        power_limit_active = any(value for _, value in power_limit_columns)
        return ThermalObservation(
            observed_at_utc=datetime.fromtimestamp(
                stat.st_mtime,
                timezone.utc,
            ).isoformat(),
            temperature_celsius=max(
                value for _, value in temperature_columns
            ),
            temperature_source=self.source_id,
            temperature_trusted=True,
            thermal_throttling=any(value for _, value in throttle_columns),
            throttling_source=self.source_id,
            throttling_trusted=True,
            source_status="OBSERVED",
            detail=json.dumps(
                {
                    "temperature_columns": [
                        name for name, _ in temperature_columns
                    ],
                    "throttling_columns": [
                        name for name, _ in throttle_columns
                    ],
                    "power_limit_columns": [
                        name for name, _ in power_limit_columns
                    ],
                    "power_limit_active": power_limit_active,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )


class LibreHardwareMonitorSource:
    """Consome a árvore JSON do servidor web do LibreHardwareMonitor."""

    def __init__(
        self,
        url: str = "http://127.0.0.1:8085/data.json",
        *,
        timeout_seconds: float = 0.25,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.source_id = f"libre-hardware-monitor:{url}"

    def sample(self) -> ThermalObservation:
        try:
            with urllib.request.urlopen(
                self.url,
                timeout=self.timeout_seconds,
            ) as response:
                document = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return unavailable_observation(self.source_id, str(exc))
        temperatures: list[float] = []
        throttles: list[bool] = []
        for path, item in _walk_sensor_tree(document):
            identity = " ".join(
                [path, str(item.get("Text", "")), str(item.get("Name", ""))]
            ).lower()
            value = item.get("Value")
            if "cpu" in identity and (
                "temperature" in identity
                or "package" in identity
                or "core max" in identity
            ):
                parsed = _parse_number(value)
                if parsed is not None and -20 <= parsed <= 130:
                    temperatures.append(parsed)
            if "throttl" in identity:
                parsed_bool = _parse_bool(value)
                if parsed_bool is not None:
                    throttles.append(parsed_bool)
        if not temperatures:
            return unavailable_observation(
                self.source_id,
                "árvore disponível, mas sem temperatura identificável de CPU",
            )
        throttle = any(throttles) if throttles else None
        return ThermalObservation(
            observed_at_utc=utc_now(),
            temperature_celsius=max(temperatures),
            temperature_source=self.source_id,
            temperature_trusted=True,
            thermal_throttling=throttle,
            throttling_source=self.source_id if throttles else None,
            throttling_trusted=bool(throttles),
            source_status="OBSERVED" if throttles else "PARTIAL",
            detail=(
                None
                if throttles
                else "temperatura observada; sinal de throttling ausente"
            ),
        )


class AutoThermalSource:
    source_id = "auto"

    def __init__(self, *, lhm_url: str | None = None) -> None:
        self.sources: tuple[ThermalSource, ...] = (
            LibreHardwareMonitorSource(
                lhm_url or "http://127.0.0.1:8085/data.json"
            ),
            PsutilThermalSource(),
        )

    def sample(self) -> ThermalObservation:
        partial: ThermalObservation | None = None
        details: list[str] = []
        for source in self.sources:
            observation = source.sample()
            if observation.gate_observable:
                return observation
            if (
                partial is None
                and observation.temperature_celsius is not None
                and observation.temperature_trusted
            ):
                partial = observation
            details.append(f"{source.source_id}: {observation.detail}")
        if partial is not None:
            return partial
        return unavailable_observation(self.source_id, "; ".join(details))


class SequenceThermalSource:
    """Fonte determinística exclusiva para testes; nunca é elegível ao gate."""

    source_id = "test-sequence"

    def __init__(
        self,
        temperatures: Sequence[float],
        *,
        throttling: Sequence[bool] | None = None,
        test_trusted: bool = False,
    ) -> None:
        if not temperatures:
            raise ValueError("sequência térmica vazia")
        self.temperatures = tuple(float(item) for item in temperatures)
        self.throttling = tuple(throttling or [False])
        self.test_trusted = test_trusted
        self.index = 0

    def sample(self) -> ThermalObservation:
        index = min(self.index, len(self.temperatures) - 1)
        throttle_index = min(self.index, len(self.throttling) - 1)
        self.index += 1
        return ThermalObservation(
            observed_at_utc=utc_now(),
            temperature_celsius=self.temperatures[index],
            temperature_source=self.source_id,
            temperature_trusted=self.test_trusted,
            thermal_throttling=self.throttling[throttle_index],
            throttling_source=self.source_id,
            throttling_trusted=self.test_trusted,
            source_status="OBSERVED" if self.test_trusted else "TEST_ONLY",
            detail="fonte sintética; proibida para evidência oficial",
        )


def unavailable_observation(source: str, detail: str) -> ThermalObservation:
    return ThermalObservation(
        observed_at_utc=utc_now(),
        temperature_celsius=None,
        temperature_source=None,
        temperature_trusted=False,
        thermal_throttling=None,
        throttling_source=None,
        throttling_trusted=False,
        source_status="UNAVAILABLE",
        detail=f"{source}: {detail}",
    )


def classify_observation(
    observation: ThermalObservation,
    policy: ThermalPolicy,
    *,
    starting: bool = False,
) -> str:
    if not observation.gate_observable:
        return "BLOCKED_SENSOR"
    if observation.thermal_throttling:
        return "ABORT_THROTTLING"
    assert observation.temperature_celsius is not None
    if observation.temperature_celsius >= policy.hard_stop_celsius:
        return "ABORT_TEMPERATURE"
    if observation.temperature_celsius >= policy.soft_stop_celsius:
        return "SOFT_STOP"
    if observation.temperature_celsius >= policy.warning_celsius:
        return "WARNING"
    if starting and observation.temperature_celsius > policy.resume_below_celsius:
        return "WAIT_COOLDOWN"
    return "SAFE"


def thermal_doctor(
    source: ThermalSource,
    policy: ThermalPolicy,
) -> dict[str, Any]:
    observation = source.sample()
    classification = classify_observation(observation, policy, starting=True)
    host_telemetry = system_telemetry_snapshot(static=True)
    power_classification = classify_power_state(host_telemetry, policy)
    return {
        "protocol": THERMAL_COVENANT_PROTOCOL,
        "kind": "THERMAL_DOCTOR",
        "observed_at_utc": utc_now(),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "node": platform.node(),
            "logical_cpu_count": os.cpu_count(),
        },
        "policy": policy.to_dict(),
        "source_id": source.source_id,
        "observation": observation.to_dict(),
        "classification": classification,
        "host_telemetry": host_telemetry,
        "power_classification": power_classification,
        "performance_ready": (
            classification == "SAFE" and power_classification == "SAFE"
        ),
        "claim": None,
        "scientific_invariant": (
            "missing or untrusted telemetry blocks performance execution"
        ),
    }


def classify_power_state(
    snapshot: Mapping[str, Any],
    policy: ThermalPolicy,
) -> str:
    battery = snapshot.get("battery_percent")
    plugged = snapshot.get("power_plugged")
    if battery is None:
        return "NOT_APPLICABLE_OR_UNAVAILABLE"
    try:
        battery_percent = float(battery)
    except (TypeError, ValueError):
        return "BLOCKED_POWER_TELEMETRY"
    if not math.isfinite(battery_percent) or not 0 <= battery_percent <= 100:
        return "BLOCKED_POWER_TELEMETRY"
    if (
        plugged is False
        and battery_percent < policy.minimum_unplugged_battery_percent
    ):
        return "BLOCKED_LOW_BATTERY"
    return "SAFE"


def _walk_sensor_tree(
    value: Any,
    path: str = "",
) -> Sequence[tuple[str, Mapping[str, Any]]]:
    found: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(value, Mapping):
        name = str(value.get("Text", value.get("Name", "")))
        next_path = f"{path}/{name}" if name else path
        found.append((next_path, value))
        for child in value.values():
            if isinstance(child, (Mapping, list, tuple)):
                found.extend(_walk_sensor_tree(child, next_path))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.extend(_walk_sensor_tree(child, path))
    return found


def _parse_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if not isinstance(value, str):
        return None
    normalized = value.replace("°C", "").replace("°", "").strip()
    normalized = normalized.replace(",", ".")
    try:
        parsed = float(normalized)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"yes", "true", "on", "1", "sim", "active"}:
            return True
        if normalized in {"no", "false", "off", "0", "não", "nao", "inactive"}:
            return False
    return None


def _normalize_sensor_name(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value))
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(ascii_text.casefold().split())
