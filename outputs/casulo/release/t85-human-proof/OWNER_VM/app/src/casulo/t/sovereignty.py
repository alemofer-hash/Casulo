from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .artifact import ArtifactBuilder
from .runner import run_artifact


WEIGHTS: Mapping[str, int] = {
    "intent_requirements": 3,
    "agent_logic": 3,
    "tools_composition": 3,
    "memory": 3,
    "jobs_concurrency": 3,
    "effects_capabilities": 4,
    "interfaces": 2,
    "tests_simulation": 3,
    "materialization": 3,
}

CRITICAL_SURFACES = frozenset(
    {"intent_requirements", "effects_capabilities", "materialization"}
)


class SovereigntyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ForeignBoundaryManifest:
    boundary_id: str
    implementation_language: str
    artifact_sha256: str
    license: str
    api_version: str
    input_types: tuple[str, ...]
    output_types: tuple[str, ...]
    memory_ownership: str
    threading_model: str
    effects: tuple[str, ...]
    capabilities: tuple[str, ...]
    timeout_ms: int
    failure_mapping: str
    sandbox_profile: str

    def __post_init__(self) -> None:
        if not self.boundary_id or not self.implementation_language:
            raise SovereigntyError("fronteira sem identidade")
        if len(self.artifact_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.artifact_sha256):
            raise SovereigntyError("hash estrangeiro inválido")
        if not self.license or not self.api_version or not self.input_types or not self.output_types:
            raise SovereigntyError("contrato estrangeiro incompleto")
        if self.timeout_ms <= 0 or not self.failure_mapping or not self.sandbox_profile:
            raise SovereigntyError("limites estrangeiros incompletos")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.foreign-boundary/1.0",
            "boundary_id": self.boundary_id,
            "implementation_language": self.implementation_language,
            "artifact_sha256": self.artifact_sha256,
            "license": self.license,
            "api_version": self.api_version,
            "input_types": list(self.input_types),
            "output_types": list(self.output_types),
            "memory_ownership": self.memory_ownership,
            "threading_model": self.threading_model,
            "effects": list(self.effects),
            "capabilities": list(self.capabilities),
            "timeout_ms": self.timeout_ms,
            "failure_mapping": self.failure_mapping,
            "sandbox_profile": self.sandbox_profile,
        }


@dataclass(frozen=True, slots=True)
class TSurfaceReceipt:
    surface: str
    source_sha256: str
    ir_sha256: str
    graph_sha256: str
    artifact_id: str
    operation: str
    result: str

    def to_dict(self) -> dict[str, str]:
        return {
            "surface": self.surface,
            "source_sha256": self.source_sha256,
            "ir_sha256": self.ir_sha256,
            "graph_sha256": self.graph_sha256,
            "artifact_id": self.artifact_id,
            "operation": self.operation,
            "result": self.result,
        }


@dataclass(frozen=True, slots=True)
class SovereigntyAudit:
    receipts: tuple[TSurfaceReceipt, ...]
    foreign_boundaries: tuple[ForeignBoundaryManifest, ...]

    @property
    def covered_surfaces(self) -> frozenset[str]:
        return frozenset(item.surface for item in self.receipts)

    @property
    def score(self) -> float:
        covered = self.covered_surfaces
        return sum(weight for name, weight in WEIGHTS.items() if name in covered) / sum(WEIGHTS.values())

    @property
    def critical_complete(self) -> bool:
        return CRITICAL_SURFACES <= self.covered_surfaces

    @property
    def accepted(self) -> bool:
        return self.score >= 0.80 and self.critical_complete and bool(self.foreign_boundaries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.t-sovereignty-audit/1.0",
            "score": self.score,
            "threshold": 0.80,
            "accepted": self.accepted,
            "critical_complete": self.critical_complete,
            "receipts": [item.to_dict() for item in self.receipts],
            "foreign_boundaries": [item.to_dict() for item in self.foreign_boundaries],
        }


class TPolicyRuntime:
    """Builds and executes the product decision contracts through real T IR."""

    def __init__(self, source_root: Path, build_root: Path) -> None:
        self.source_root = source_root.resolve()
        self.build_root = build_root.resolve()

    def decide(self, surface: str, source_name: str, operation: str, payload: Mapping[str, Any]) -> TSurfaceReceipt:
        if surface not in WEIGHTS:
            raise SovereigntyError(f"superfície desconhecida: {surface}")
        source = (self.source_root / source_name).resolve()
        if source.parent != self.source_root or not source.is_file():
            raise SovereigntyError("fonte T fora do diretório soberano")
        build = ArtifactBuilder().build(source, self.build_root / surface)
        result = run_artifact(build.output_dir, dict(payload), operation=operation, use_cache=False)
        manifest = build.manifest
        return TSurfaceReceipt(
            surface=surface,
            source_sha256=manifest["source"]["sha256"],
            ir_sha256=manifest["ir"]["sha256"],
            graph_sha256=manifest["graph"]["sha256"],
            artifact_id=build.artifact_id,
            operation=operation,
            result=str(result.payload["result"]),
        )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_audit(path: Path, audit: SovereigntyAudit) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
