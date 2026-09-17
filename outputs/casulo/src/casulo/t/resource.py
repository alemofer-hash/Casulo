from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


RESOURCE_CONTRACT_PROTOCOL = "casulo-resource-contract/1"


class SemanticClass(StrEnum):
    FLOW = "FLOW"
    SYSTEM = "SYSTEM"
    ATTRACTOR_AUDIT = "ATTRACTOR_AUDIT"
    ATTRACTOR_RETRY = "ATTRACTOR_RETRY"
    ATTRACTOR_LOW_CONFIDENCE = "ATTRACTOR_LOW_CONFIDENCE"
    QUARANTINE = "QUARANTINE"


@dataclass(frozen=True, slots=True)
class ResourceContract:
    memory_limit_bytes: int
    arena_bytes: int
    max_threads: int
    semantic_class: SemanticClass
    deterministic: bool
    numerical_precision: str
    permissions: tuple[str, ...]
    quality_definition: dict[str, Any]
    residual_routing: dict[str, str]
    priority: int = 0
    deadline_ns: int | None = None
    energy_budget_joules: float | None = None
    protocol: str = RESOURCE_CONTRACT_PROTOCOL

    def __post_init__(self) -> None:
        if self.protocol != RESOURCE_CONTRACT_PROTOCOL:
            raise ValueError("unsupported resource contract protocol")
        if not 4096 <= self.memory_limit_bytes <= 1 << 40:
            raise ValueError("memory_limit_bytes outside supported bounds")
        if not 0 <= self.arena_bytes <= self.memory_limit_bytes:
            raise ValueError("arena_bytes exceeds memory limit")
        if not 1 <= self.max_threads <= 256:
            raise ValueError("max_threads outside supported bounds")
        if not -20 <= self.priority <= 20:
            raise ValueError("priority outside supported bounds")
        if self.deadline_ns is not None and self.deadline_ns <= 0:
            raise ValueError("deadline_ns must be positive")
        if self.energy_budget_joules is not None and self.energy_budget_joules <= 0:
            raise ValueError("energy budget must be positive")
        allowed_precision = {"float32", "float64", "integer", "mixed-declared"}
        if self.numerical_precision not in allowed_precision:
            raise ValueError("unsupported numerical precision")
        allowed_permissions = {"console", "clock", "ipc", "memory", "telemetry"}
        if not self.permissions or len(set(self.permissions)) != len(self.permissions):
            raise ValueError("permissions must be non-empty and unique")
        unknown = set(self.permissions) - allowed_permissions
        if unknown:
            raise ValueError(f"unknown permissions: {sorted(unknown)}")
        if not self.quality_definition:
            raise ValueError("quality definition is required")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["semantic_class"] = self.semantic_class.value
        result["permissions"] = list(self.permissions)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ResourceContract":
        expected = {
            "memory_limit_bytes", "arena_bytes", "max_threads", "semantic_class",
            "deterministic", "numerical_precision", "permissions", "quality_definition",
            "residual_routing", "priority", "deadline_ns", "energy_budget_joules", "protocol",
        }
        if set(value) != expected:
            raise ValueError(f"resource contract keys differ: {sorted(set(value) ^ expected)}")
        return cls(
            memory_limit_bytes=_strict_int(value["memory_limit_bytes"], "memory_limit_bytes"),
            arena_bytes=_strict_int(value["arena_bytes"], "arena_bytes"),
            max_threads=_strict_int(value["max_threads"], "max_threads"),
            semantic_class=SemanticClass(value["semantic_class"]),
            deterministic=_strict_bool(value["deterministic"], "deterministic"),
            numerical_precision=_strict_str(value["numerical_precision"], "numerical_precision"),
            permissions=tuple(_strict_string_list(value["permissions"], "permissions")),
            quality_definition=_strict_dict(value["quality_definition"], "quality_definition"),
            residual_routing={
                _strict_str(key, "residual key"): _strict_str(item, "residual value")
                for key, item in _strict_dict(value["residual_routing"], "residual_routing").items()
            },
            priority=_strict_int(value["priority"], "priority"),
            deadline_ns=_optional_int(value["deadline_ns"], "deadline_ns"),
            energy_budget_joules=_optional_number(value["energy_budget_joules"], "energy_budget_joules"),
            protocol=_strict_str(value["protocol"], "protocol"),
        )


def _strict_int(value: Any, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _strict_str(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _strict_dict(value: Any, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{name} must be an object")
    return value


def _strict_string_list(value: Any, name: str) -> list[str]:
    if type(value) is not list:
        raise ValueError(f"{name} must be an array")
    return [_strict_str(item, name) for item in value]


def _optional_int(value: Any, name: str) -> int | None:
    return None if value is None else _strict_int(value, name)


def _optional_number(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be numeric")
    return float(value)

