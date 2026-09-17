from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, TypeAlias

from .diagnostics import SourceSpan

if TYPE_CHECKING:
    from .expression_ast import ExpressionNode


@dataclass(frozen=True, slots=True)
class TypeRef:
    name: str
    optional: bool
    list_depth: int
    span: SourceSpan
    arguments: tuple["TypeRef", ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Expression:
    text: str
    span: SourceSpan
    root: "ExpressionNode | None" = None
    syntax_error: str | None = None


@dataclass(frozen=True, slots=True)
class LanguageDecl:
    version: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ModuleDecl:
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class UseDecl:
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CapabilityDecl:
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TraceDecl:
    name: str
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class FieldDecl:
    name: str
    traces: tuple[TraceDecl, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class RecordDecl:
    name: str
    traces: tuple[TraceDecl, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EnumCaseDecl:
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EnumDecl:
    name: str
    cases: tuple[EnumCaseDecl, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LearnProperty:
    name: str
    value: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LearnDecl:
    name: str
    properties: tuple[LearnProperty, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LetStmt:
    name: str
    value: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class JudgeStmt:
    condition: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class RestrictStmt:
    condition: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class StabilizeStmt:
    target: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EmitStmt:
    value: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ProjectStmt:
    source: Expression
    target: str | None
    into: tuple[str, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BindStmt:
    left: Expression
    right: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IfStmt:
    condition: Expression
    then_body: tuple["Statement", ...]
    else_body: tuple["Statement", ...]
    span: SourceSpan


Statement: TypeAlias = (
    LetStmt
    | JudgeStmt
    | RestrictStmt
    | StabilizeStmt
    | EmitStmt
    | ProjectStmt
    | BindStmt
    | IfStmt
)


@dataclass(frozen=True, slots=True)
class CondenseDecl:
    name: str
    input_type: str | None
    effects: tuple[str, ...]
    body: tuple[Statement, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TransitionDecl:
    name: str
    from_type: str
    to_type: str
    effects: tuple[str, ...]
    body: tuple[Statement, ...]
    span: SourceSpan


Declaration: TypeAlias = (
    FieldDecl | RecordDecl | EnumDecl | CondenseDecl | TransitionDecl | LearnDecl
)


@dataclass(frozen=True, slots=True)
class Program:
    module: ModuleDecl | None
    language: LanguageDecl | None = None
    uses: tuple[UseDecl, ...] = field(default_factory=tuple)
    capabilities: tuple[CapabilityDecl, ...] = field(default_factory=tuple)
    declarations: tuple[Declaration, ...] = field(default_factory=tuple)
    span: SourceSpan | None = None


def ast_to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        result = asdict(value)
        result["kind"] = type(value).__name__
        return _add_nested_kinds(value, result)
    if isinstance(value, tuple):
        return [ast_to_dict(item) for item in value]
    return value


def _add_nested_kinds(original: Any, serialized: dict[str, Any]) -> dict[str, Any]:
    for name in getattr(original, "__dataclass_fields__", {}):
        current = getattr(original, name)
        if hasattr(current, "__dataclass_fields__"):
            serialized[name] = ast_to_dict(current)
        elif isinstance(current, tuple):
            serialized[name] = [ast_to_dict(item) for item in current]
    return serialized
