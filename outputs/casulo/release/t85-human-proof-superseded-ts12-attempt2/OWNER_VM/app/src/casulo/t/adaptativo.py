"""Seletor adaptativo do Casulo.

A Larva perfila o lote, a Crisálida estima o custo e a Metamorfose executa a
estratégia escolhida. Toda decisão acompanha a saída para ser auditável.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .artifact import ArtifactError
from .runner import load_artifact, select_operation


ADAPTIVE_PROTOCOL = "casulo-adaptive/0.3"
COST_MODEL_PROTOCOL = "casulo-cost-model/0.3"


class AdaptiveError(RuntimeError):
    """Entrada ou artefato incompatível com a execução adaptativa."""


class EstrategiaMetamorfose(str, Enum):
    RECALCULATE = "RECALCULATE"
    FUSE_TYPED_BATCH = "FUSE_TYPED_BATCH"
    DEDUPLICATE_BATCH = "DEDUPLICATE_BATCH"


@dataclass(frozen=True, slots=True)
class PerfilLarva:
    records: int
    sampled_records: int
    sample_unique_records: int
    sample_matching_pairs: int
    unique_records: int
    repeated_records: int
    repetition_rate: float
    total_payload_bytes: int
    mean_payload_bytes: float
    estimated_cache_bytes: int
    profile_mode: str

    @classmethod
    def from_payloads(
        cls,
        payloads: list[Any],
        *,
        sample_limit: int = 256,
        key_function: Callable[[Any], Any] | None = None,
    ) -> "PerfilLarva":
        if sample_limit < 1:
            raise ValueError("sample_limit precisa ser positivo")
        records = len(payloads)
        if records <= sample_limit:
            sample = payloads
            profile_mode = "exact"
        else:
            offset = (records ^ 0xCA5_010) % records
            stride = 0x9E37_79B1 % records or 1
            while math.gcd(stride, records) != 1:
                stride += 1
            indexes = [
                (offset + index * stride) % records
                for index in range(sample_limit)
            ]
            sample = [
                payloads[index]
                for index in indexes
            ]
            profile_mode = (
                "deterministic_compiled_collision_estimate"
                if key_function is not None
                else "deterministic_collision_estimate"
            )
        fingerprints: Counter[Any] = Counter()
        sampled_bytes = 0
        size_samples = 0
        for index, payload in enumerate(sample):
            if key_function is None:
                fingerprint, estimated_bytes = _freeze_and_size(payload)
                sampled_bytes += estimated_bytes
                size_samples += 1
            else:
                fingerprint = key_function(payload)
                if index < 8:
                    sampled_bytes += _estimate_size(payload)
                    size_samples += 1
            fingerprints[fingerprint] += 1
        sampled_records = len(sample)
        sample_unique = len(fingerprints)
        matching_pairs = sum(
            frequency * (frequency - 1) // 2
            for frequency in fingerprints.values()
        )
        unique = (
            sample_unique
            if profile_mode == "exact"
            else _estimate_population_unique(
                records,
                sampled_records,
                matching_pairs,
            )
        )
        repeated = records - unique
        mean_bytes = sampled_bytes / size_samples if size_samples else 0.0
        total_bytes = round(mean_bytes * records)
        return cls(
            records=records,
            sampled_records=sampled_records,
            sample_unique_records=sample_unique,
            sample_matching_pairs=matching_pairs,
            unique_records=unique,
            repeated_records=repeated,
            repetition_rate=repeated / records if records else 0.0,
            total_payload_bytes=total_bytes,
            mean_payload_bytes=mean_bytes,
            estimated_cache_bytes=round(unique * (mean_bytes + 256)),
            profile_mode=profile_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DecisaoCrisalida:
    protocol: str
    cost_model: str
    strategy: EstrategiaMetamorfose
    operation: str
    operation_cost: int
    cacheable: bool
    buffered: bool
    repetition_rate: float
    repetition_threshold: float
    safety_margin: float
    estimated_speedup: float
    estimated_cache_bytes: int
    memory_budget_bytes: int
    confidence: float
    reasons: tuple[str, ...]

    @property
    def use_cache(self) -> bool:
        return self.strategy in {
            EstrategiaMetamorfose.FUSE_TYPED_BATCH,
            EstrategiaMetamorfose.DEDUPLICATE_BATCH,
        }

    @property
    def use_buffer(self) -> bool:
        return self.buffered and self.use_cache

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["strategy"] = self.strategy.value
        value["use_cache"] = self.use_cache
        value["use_buffer"] = self.use_buffer
        return value


@dataclass(frozen=True, slots=True)
class ExecucaoMetamorfose:
    artifact_id: str
    operation: str
    profile: PerfilLarva
    decision: DecisaoCrisalida
    payload: dict[str, Any]


class ModeloCrisalida:
    """Heurística conservadora calibrada pela primeira curva Borboleta."""

    def __init__(
        self,
        *,
        memory_budget_bytes: int = 64 * 1024 * 1024,
        minimum_batch_records: int = 64,
        minimum_typed_records: int = 8,
        safety_margin: float = 0.01,
    ) -> None:
        if memory_budget_bytes < 1:
            raise ValueError("memory_budget_bytes precisa ser positivo")
        if minimum_batch_records < 1:
            raise ValueError("minimum_batch_records precisa ser positivo")
        if minimum_typed_records < 1:
            raise ValueError("minimum_typed_records precisa ser positivo")
        if not 0.0 <= safety_margin < 1.0:
            raise ValueError("safety_margin precisa estar em [0, 1)")
        self.memory_budget_bytes = memory_budget_bytes
        self.minimum_batch_records = minimum_batch_records
        self.minimum_typed_records = minimum_typed_records
        self.safety_margin = safety_margin

    def decide(
        self,
        *,
        operation: str,
        operation_cost: int,
        cacheable: bool,
        buffered: bool = False,
        profile: PerfilLarva,
    ) -> DecisaoCrisalida:
        cost = max(1, operation_cost)
        threshold = self._repetition_threshold(
            cost,
            profile.mean_payload_bytes,
        )
        boundary = min(0.999, threshold + self.safety_margin)
        reasons: list[str] = [
            f"custo estático da operação: {cost}",
            f"repetição perfilada/estimada: {profile.repetition_rate:.4f}",
            f"fronteira conservadora: {boundary:.4f}",
            f"buffer tipado: {'disponível' if buffered else 'indisponível'}",
            (
                f"perfil: {profile.profile_mode} "
                f"({profile.sampled_records}/{profile.records})"
            ),
        ]
        strategy = EstrategiaMetamorfose.RECALCULATE
        if not cacheable:
            reasons.append("grafo declara a operação como não cacheável")
        elif profile.records < (
            self.minimum_typed_records
            if buffered
            else self.minimum_batch_records
        ):
            reasons.append(
                "lote pequeno demais para amortizar perfil e cache"
            )
        elif profile.estimated_cache_bytes > self.memory_budget_bytes:
            reasons.append("estimativa de cache excede o orçamento de memória")
        elif buffered and profile.repetition_rate < boundary:
            strategy = EstrategiaMetamorfose.FUSE_TYPED_BATCH
            reasons.append(
                "layout tipado amortiza objetos mesmo sem repetição suficiente"
            )
        elif profile.repetition_rate < boundary:
            reasons.append("repetição insuficiente para pagar o overhead previsto")
        else:
            strategy = EstrategiaMetamorfose.DEDUPLICATE_BATCH
            reasons.append("repetição supera a fronteira com margem de segurança")

        distance = profile.repetition_rate - boundary
        estimated_speedup = (
            1.0 + distance * (1.5 + math.log2(max(1.0, cost / 8.0)) * 0.15)
            if distance >= 0
            else 1.0 / (1.0 + abs(distance) * 1.5)
        )
        sample_confidence = (
            1.0
            if profile.profile_mode == "exact"
            else min(0.8, profile.sampled_records / 512)
        )
        boundary_confidence = min(1.0, abs(distance) / 0.10)
        confidence = round(
            0.25 + 0.375 * sample_confidence + 0.375 * boundary_confidence,
            6,
        )
        return DecisaoCrisalida(
            protocol=ADAPTIVE_PROTOCOL,
            cost_model=COST_MODEL_PROTOCOL,
            strategy=strategy,
            operation=operation,
            operation_cost=cost,
            cacheable=cacheable,
            buffered=buffered,
            repetition_rate=profile.repetition_rate,
            repetition_threshold=threshold,
            safety_margin=self.safety_margin,
            estimated_speedup=estimated_speedup,
            estimated_cache_bytes=profile.estimated_cache_bytes,
            memory_budget_bytes=self.memory_budget_bytes,
            confidence=confidence,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _repetition_threshold(
        operation_cost: int,
        mean_payload_bytes: float,
    ) -> float:
        cost_relief = max(0.0, math.log2(max(8, operation_cost) / 8)) * 0.075
        size_penalty = (
            max(0.0, math.log2(max(64.0, mean_payload_bytes) / 64.0))
            * 0.005
        )
        return min(0.98, max(0.05, 0.30 - cost_relief + size_penalty))


class MetamorfoseAdaptativa:
    def __init__(self, model: ModeloCrisalida | None = None) -> None:
        self.model = model or ModeloCrisalida()

    def run(
        self,
        artifact_dir: str | Path,
        payloads: list[Any],
        *,
        operation: str | None = None,
    ) -> ExecucaoMetamorfose:
        if not isinstance(payloads, list):
            raise AdaptiveError("execução adaptativa exige um lote")
        loaded = load_artifact(artifact_dir)
        selected = select_operation(loaded.manifest, operation)
        operation_entry = next(
            (
                item
                for item in loaded.manifest.get("operations", [])
                if item.get("name") == selected
            ),
            None,
        )
        if not isinstance(operation_entry, dict):
            raise ArtifactError("operação ausente no manifesto adaptativo")
        optimization = operation_entry.get("optimization")
        if not isinstance(optimization, dict):
            raise ArtifactError("artefato não possui metadados de otimização")

        key_functions = loaded.namespace.get("OPERATION_KEYS")
        key_function = (
            key_functions.get(selected)
            if isinstance(key_functions, dict)
            else None
        )
        profile = PerfilLarva.from_payloads(
            payloads,
            key_function=key_function if callable(key_function) else None,
        )
        decision = self.model.decide(
            operation=selected,
            operation_cost=int(optimization.get("estimated_cost", 1)),
            cacheable=bool(optimization.get("cacheable", False)),
            buffered=bool(optimization.get("buffer_protocol")),
            profile=profile,
        )
        execute = loaded.namespace.get("execute_batch")
        execute_scalar = loaded.namespace.get("execute")
        clear_cache = loaded.namespace.get("clear_cache")
        if not callable(execute) or not callable(execute_scalar):
            raise ArtifactError("artefato não expõe kernels escalar e de lote")
        if callable(clear_cache):
            clear_cache(selected)
        if decision.use_cache:
            result = execute(
                selected,
                payloads,
                use_cache=True,
            )
        else:
            items = [
                execute_scalar(selected, payload, use_cache=False)
                for payload in payloads
            ]
            result = {
                "artifact_id": loaded.manifest["artifact_id"],
                "module": loaded.manifest["module"],
                "operation": selected,
                "count": len(items),
                "cache": {
                    "enabled": False,
                    "hits": 0,
                    "misses": len(items),
                    "entries": 0,
                    "key_protocol": None,
                    "scope": None,
                    "collision_verified": False,
                    "buffer_protocol": None,
                    "representation": "objects",
                    "evidence_layout": "inline",
                    "hot_path": None,
                },
                "items": items,
            }
        if not isinstance(result, dict):
            raise AdaptiveError("artefato retornou envelope inválido")
        manifested = dict(result)
        manifested["adaptation"] = {
            "profile": profile.to_dict(),
            "decision": decision.to_dict(),
        }
        return ExecucaoMetamorfose(
            artifact_id=loaded.manifest["artifact_id"],
            operation=selected,
            profile=profile,
            decision=decision,
            payload=manifested,
        )


def run_adaptive_artifact(
    artifact_dir: str | Path,
    payloads: list[Any],
    operation: str | None = None,
    *,
    memory_budget_bytes: int = 64 * 1024 * 1024,
) -> ExecucaoMetamorfose:
    return MetamorfoseAdaptativa(
        ModeloCrisalida(memory_budget_bytes=memory_budget_bytes)
    ).run(
        artifact_dir,
        payloads,
        operation=operation,
    )


def _freeze_and_size(value: Any) -> tuple[Any, int]:
    """Forma identidade estrutural tipada sem serializar o registro."""

    if value is None:
        return ("null",), 1
    if isinstance(value, bool):
        return ("bool", value), 1
    if isinstance(value, int):
        return ("int", value), max(1, (value.bit_length() + 7) // 8)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AdaptiveError("NaN e infinito não podem formar perfil")
        encoded = value.hex()
        return ("float", encoded), 8
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return ("text", value), len(encoded)
    if isinstance(value, (list, tuple)):
        frozen: list[Any] = []
        size = 2
        for item in value:
            fingerprint, item_size = _freeze_and_size(item)
            frozen.append(fingerprint)
            size += item_size
        return ("array", tuple(frozen)), size
    if isinstance(value, dict):
        frozen_items: list[tuple[str, Any]] = []
        size = 2
        if not all(isinstance(key, str) for key in value):
            raise AdaptiveError("objetos de entrada exigem chaves textuais")
        for key in sorted(value):
            fingerprint, item_size = _freeze_and_size(value[key])
            frozen_items.append((key, fingerprint))
            size += len(key.encode("utf-8")) + item_size
        return ("object", tuple(frozen_items)), size
    raise AdaptiveError(
        f"tipo não suportado no perfil estrutural: {type(value).__name__}"
    )


def _estimate_population_unique(
    records: int,
    sampled_records: int,
    matching_pairs: int,
) -> int:
    if not records or not sampled_records:
        return 0
    possible_pairs = sampled_records * (sampled_records - 1) // 2
    if not possible_pairs or not matching_pairs:
        return records
    collision_probability = matching_pairs / possible_pairs
    effective_multiplicity = 1.0 + collision_probability * (records - 1)
    return min(
        records,
        max(1, round(records / effective_multiplicity)),
    )


def _estimate_size(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return max(1, (value.bit_length() + 7) // 8)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AdaptiveError("NaN e infinito não podem formar perfil")
        return 8
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, (list, tuple)):
        return 2 + sum(_estimate_size(item) for item in value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise AdaptiveError("objetos de entrada exigem chaves textuais")
        return 2 + sum(
            len(key.encode("utf-8")) + _estimate_size(item)
            for key, item in value.items()
        )
    raise AdaptiveError(
        f"tipo não suportado no perfil estrutural: {type(value).__name__}"
    )
