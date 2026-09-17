from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from .diagnostics import SourceSpan


class SymbolKind(str, Enum):
    LANGUAGE = "language"
    MODULE = "module"
    USE = "use"
    CAPABILITY = "capability"
    FIELD = "field"
    RECORD = "record"
    ENUM = "enum"
    ENUM_CASE = "enum_case"
    TRACE = "trace"
    CONDENSE = "condense"
    TRANSITION = "transition"
    LEARN = "learn"
    PROPERTY = "property"
    LOCAL = "local"


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    qualified_name: str
    kind: SymbolKind
    type_name: str | None
    scope: str
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind.value,
            "type": self.type_name,
            "scope": self.scope,
            "span": self.span.to_dict(),
        }


class Scope:
    def __init__(self, name: str, parent: Scope | None = None) -> None:
        self.name = name
        self.parent = parent
        self._symbols: dict[str, Symbol] = {}

    def define(self, symbol: Symbol) -> bool:
        if symbol.name in self._symbols:
            return False
        self._symbols[symbol.name] = symbol
        return True

    def resolve(self, name: str) -> Symbol | None:
        current: Scope | None = self
        while current is not None:
            symbol = current._symbols.get(name)
            if symbol is not None:
                return symbol
            current = current.parent
        return None

    def child(self, name: str) -> Scope:
        return Scope(name=name, parent=self)

    def clone_child(self, name: str) -> Scope:
        child = Scope(name=name, parent=self.parent)
        child._symbols.update(self._symbols)
        return child

    def local(self, name: str) -> Symbol | None:
        return self._symbols.get(name)

    def values(self) -> tuple[Symbol, ...]:
        return tuple(self._symbols.values())


class SymbolTable:
    def __init__(self) -> None:
        self.root = Scope("<root>")
        self._symbols: list[Symbol] = []

    def add(self, scope: Scope, symbol: Symbol) -> bool:
        if not scope.define(symbol):
            return False
        self._symbols.append(symbol)
        return True

    def extend(self, scope: Scope, symbols: Iterable[Symbol]) -> None:
        for symbol in symbols:
            self.add(scope, symbol)

    @property
    def symbols(self) -> tuple[Symbol, ...]:
        return tuple(self._symbols)

    def to_dict(self) -> dict[str, Any]:
        ordered = sorted(
            self._symbols,
            key=lambda item: (
                item.span.file,
                item.span.line,
                item.span.column,
                item.qualified_name,
            ),
        )
        return {"symbols": [symbol.to_dict() for symbol in ordered]}

    def render_text(self) -> str:
        rows = ["KIND        TYPE           SCOPE                NAME"]
        for symbol in sorted(
            self._symbols,
            key=lambda item: (item.scope, item.kind.value, item.name),
        ):
            rows.append(
                f"{symbol.kind.value:<11} "
                f"{(symbol.type_name or '-'):<14} "
                f"{symbol.scope:<20} "
                f"{symbol.qualified_name}"
            )
        return "\n".join(rows)
