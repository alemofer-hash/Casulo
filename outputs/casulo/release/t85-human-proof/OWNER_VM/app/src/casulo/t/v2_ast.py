from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class V2Span:
    file: str
    line: int
    column: int = 1


@dataclass(frozen=True, slots=True)
class V2Type:
    name: str
    arguments: tuple["V2Type", ...] = ()
    bound: int | None = None


@dataclass(frozen=True, slots=True)
class V2Member:
    name: str
    type_ref: V2Type
    span: V2Span


@dataclass(frozen=True, slots=True)
class V2Record:
    name: str
    members: tuple[V2Member, ...]
    span: V2Span


@dataclass(frozen=True, slots=True)
class V2Enum:
    name: str
    cases: tuple[str, ...]
    span: V2Span


@dataclass(frozen=True, slots=True)
class V2State:
    name: str
    type_ref: V2Type
    initial: Any
    span: V2Span


@dataclass(frozen=True, slots=True)
class V2Expression:
    source: str
    span: V2Span


@dataclass(frozen=True, slots=True)
class V2Statement:
    kind: str
    arguments: tuple[Any, ...]
    body: tuple["V2Statement", ...] = ()
    otherwise: tuple["V2Statement", ...] = ()
    span: V2Span | None = None


@dataclass(frozen=True, slots=True)
class V2Function:
    name: str
    parameter_name: str
    parameter_type: V2Type
    return_type: V2Type
    effects: tuple[str, ...]
    body: tuple[V2Statement, ...]
    span: V2Span


@dataclass(frozen=True, slots=True)
class V2Module:
    name: str
    imports: tuple[str, ...]
    capabilities: tuple[str, ...]
    step_budget: int
    deadline_ms: int
    schema_version: int
    records: tuple[V2Record, ...]
    enums: tuple[V2Enum, ...]
    states: tuple[V2State, ...]
    functions: tuple[V2Function, ...]
    source_name: str
