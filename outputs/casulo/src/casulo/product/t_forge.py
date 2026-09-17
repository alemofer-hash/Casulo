from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from casulo.t.api import check_source

from .platform_contracts import PlatformError


_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class ForgeError(PlatformError):
    pass


@dataclass(frozen=True, slots=True)
class ForgeUnit:
    unit_id: str
    source: str
    watch_paths: tuple[tuple[str, ...], ...]
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.unit_id):
            raise ForgeError("unit_id do Forge é inválido")
        if not self.source.strip() or not self.watch_paths:
            raise ForgeError("unidade do Forge exige source e watch_paths")
        if any(not path or any(not part for part in path) for path in self.watch_paths):
            raise ForgeError("watch_path do Forge é inválido")
        if self.unit_id in self.dependencies or len(set(self.dependencies)) != len(self.dependencies):
            raise ForgeError("dependências do Forge são inválidas")


@dataclass(frozen=True, slots=True)
class ForgeArtifact:
    unit_id: str
    source_sha256: str
    ir_sha256: str
    graph_sha256: str
    dependency_artifact_sha256: tuple[tuple[str, str], ...]
    artifact_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "source_sha256": self.source_sha256,
            "ir_sha256": self.ir_sha256,
            "graph_sha256": self.graph_sha256,
            "dependency_artifact_sha256": dict(self.dependency_artifact_sha256),
            "artifact_sha256": self.artifact_sha256,
        }


@dataclass(frozen=True, slots=True)
class ForgeReceipt:
    build_id: str
    affected_paths: tuple[tuple[str, ...], ...]
    rebuilt_units: tuple[str, ...]
    reused_units: tuple[str, ...]
    artifacts: tuple[ForgeArtifact, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.t-forge-receipt/1.0",
            "build_id": self.build_id,
            "affected_paths": [list(path) for path in self.affected_paths],
            "rebuilt_units": list(self.rebuilt_units),
            "reused_units": list(self.reused_units),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


class TForge:
    """Transactional incremental compiler over the real T frontend/IR/graph."""

    def __init__(self) -> None:
        self._cache: dict[str, ForgeArtifact] = {}
        self._build_sequence = 0

    def compile(
        self,
        units: Iterable[ForgeUnit],
        *,
        affected_paths: tuple[tuple[str, ...], ...] = (),
    ) -> ForgeReceipt:
        by_id = self._validate_units(tuple(units))
        order = self._topological_order(by_id)
        changed_sources = {
            unit_id
            for unit_id, unit in by_id.items()
            if unit_id not in self._cache
            or self._cache[unit_id].source_sha256 != _sha256_text(unit.source)
        }
        seeds = changed_sources | {
            unit.unit_id
            for unit in by_id.values()
            if any(
                _paths_intersect(watch, changed)
                for watch in unit.watch_paths
                for changed in affected_paths
            )
        }
        impacted = self._downstream_closure(seeds, by_id)
        provisional = dict(self._cache)
        rebuilt: list[str] = []
        reused: list[str] = []
        for unit_id in order:
            unit = by_id[unit_id]
            if unit_id not in impacted and unit_id in provisional:
                reused.append(unit_id)
                continue
            checked = check_source(unit.source, file=f"<forge:{unit_id}>")
            if not checked.ok or checked.ir is None or checked.graph is None:
                diagnostics = "; ".join(
                    f"{item.code}:{item.message}" for item in checked.diagnostics
                )
                raise ForgeError(f"unidade T {unit_id} reprovada: {diagnostics}")
            source_hash = _sha256_text(unit.source)
            ir_hash = _sha256_json(checked.ir.to_dict())
            graph_hash = _sha256_json(checked.graph.to_dict())
            dependencies = tuple(
                (dependency, provisional[dependency].artifact_sha256)
                for dependency in unit.dependencies
            )
            artifact_hash = _sha256_json(
                {
                    "unit_id": unit_id,
                    "source_sha256": source_hash,
                    "ir_sha256": ir_hash,
                    "graph_sha256": graph_hash,
                    "dependencies": dependencies,
                }
            )
            provisional[unit_id] = ForgeArtifact(
                unit_id,
                source_hash,
                ir_hash,
                graph_hash,
                dependencies,
                artifact_hash,
            )
            rebuilt.append(unit_id)
        self._cache = {unit_id: provisional[unit_id] for unit_id in by_id}
        self._build_sequence += 1
        return ForgeReceipt(
            build_id=f"forge:{self._build_sequence}",
            affected_paths=affected_paths,
            rebuilt_units=tuple(rebuilt),
            reused_units=tuple(reused),
            artifacts=tuple(self._cache[unit_id] for unit_id in order),
        )

    @staticmethod
    def _validate_units(units: tuple[ForgeUnit, ...]) -> dict[str, ForgeUnit]:
        by_id = {unit.unit_id: unit for unit in units}
        if not units or len(by_id) != len(units):
            raise ForgeError("projeto Forge vazio ou com unit_id duplicado")
        for unit in units:
            missing = set(unit.dependencies) - set(by_id)
            if missing:
                raise ForgeError(f"dependência ausente em {unit.unit_id}: {sorted(missing)}")
        return by_id

    @staticmethod
    def _topological_order(by_id: dict[str, ForgeUnit]) -> tuple[str, ...]:
        pending = {unit_id: set(unit.dependencies) for unit_id, unit in by_id.items()}
        order: list[str] = []
        while pending:
            ready = sorted(unit_id for unit_id, dependencies in pending.items() if not dependencies)
            if not ready:
                raise ForgeError("ciclo de dependências no projeto Forge")
            for unit_id in ready:
                order.append(unit_id)
                pending.pop(unit_id)
            for dependencies in pending.values():
                dependencies.difference_update(ready)
        return tuple(order)

    @staticmethod
    def _downstream_closure(seeds: set[str], by_id: dict[str, ForgeUnit]) -> set[str]:
        result = set(seeds)
        changed = True
        while changed:
            changed = False
            for unit_id, unit in by_id.items():
                if unit_id not in result and set(unit.dependencies) & result:
                    result.add(unit_id)
                    changed = True
        return result


def _paths_intersect(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    common = min(len(left), len(right))
    return left[:common] == right[:common]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
