from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .ast import Expression, TypeRef
from .diagnostics import Diagnostic
from .expression_ast import (
    BinaryNode,
    BooleanNode,
    CallNode,
    CompareNode,
    ConditionalNode,
    ExpressionNode,
    ListNode,
    LiteralNode,
    NameNode,
    UnaryNode,
    expression_names,
)
from .symbols import Scope


@dataclass(frozen=True, slots=True)
class SemanticType:
    name: str
    optional: bool = False
    list_depth: int = 0

    def render(self) -> str:
        value = self.name
        for _ in range(self.list_depth):
            value = f"[{value}]"
        if self.optional:
            value += "?"
        return value

    @classmethod
    def from_ref(cls, type_ref: TypeRef) -> "SemanticType":
        name = type_ref.name
        if type_ref.arguments:
            name += "[" + ",".join(
                cls.from_ref(argument).render() for argument in type_ref.arguments
            ) + "]"
        return cls(name, type_ref.optional, type_ref.list_depth)


ANY = SemanticType("Any")
BOOL = SemanticType("Bool")
NUMBER = SemanticType("Number")
TEXT = SemanticType("Text")


@dataclass(frozen=True, slots=True)
class ExpressionResult:
    type: SemanticType
    diagnostics: tuple[Diagnostic, ...]
    names: tuple[str, ...]


class TypeEngine:
    BUILTINS = {
        "abs": ((NUMBER,), NUMBER),
        "round": ((NUMBER, NUMBER), NUMBER),
        "sqrt": ((NUMBER,), NUMBER),
        "len": ((ANY,), NUMBER),
        "min": ((ANY,), ANY),
        "max": ((ANY,), ANY),
    }

    def infer(self, expression: Expression, scope: Scope) -> ExpressionResult:
        diagnostics: list[Diagnostic] = []
        if expression.root is None:
            detail = f" ({expression.syntax_error})" if expression.syntax_error else ""
            diagnostics.append(
                Diagnostic(
                    code="T3021",
                    message=f"expressão inválida: {expression.text!r}{detail}",
                    span=expression.span,
                )
            )
            return ExpressionResult(ANY, tuple(diagnostics), ())
        names = expression_names(expression.root, include_builtins=True)
        inferred = self._infer_node(expression.root, expression, scope, diagnostics)
        return ExpressionResult(inferred, tuple(diagnostics), tuple(sorted(names)))

    def _infer_node(
        self,
        node: ExpressionNode,
        expression: Expression,
        scope: Scope,
        diagnostics: list[Diagnostic],
    ) -> SemanticType:
        if isinstance(node, LiteralNode):
            if isinstance(node.value, bool):
                return BOOL
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return NUMBER
            if isinstance(node.value, str):
                return TEXT
            if node.value is None:
                return SemanticType("Any", optional=True)
            return ANY

        if isinstance(node, NameNode):
            symbol = scope.resolve(node.name)
            if symbol is None:
                if node.name in self.BUILTINS:
                    return ANY
                diagnostics.append(
                    Diagnostic("T3030", f"nome não resolvido: {node.name}", expression.span)
                )
                return ANY
            return parse_rendered_type(symbol.type_name)

        if isinstance(node, ListNode):
            if not node.items:
                return SemanticType("Any", list_depth=1)
            unified = unify_types(
                self._infer_node(item, expression, scope, diagnostics)
                for item in node.items
            )
            return SemanticType(
                unified.name,
                optional=unified.optional,
                list_depth=unified.list_depth + 1,
            )

        if isinstance(node, UnaryNode):
            operand = self._infer_node(node.operand, expression, scope, diagnostics)
            if node.operator == "not":
                self._expect(operand, BOOL, expression, diagnostics)
                return BOOL
            if node.operator not in {"+", "-"}:
                diagnostics.append(
                    Diagnostic(
                        "T3038",
                        f"operador unário ainda não suportado: {node.operator}",
                        expression.span,
                    )
                )
                return ANY
            self._expect(operand, NUMBER, expression, diagnostics)
            return NUMBER

        if isinstance(node, BooleanNode):
            for value in node.values:
                self._expect(
                    self._infer_node(value, expression, scope, diagnostics),
                    BOOL,
                    expression,
                    diagnostics,
                )
            return BOOL

        if isinstance(node, BinaryNode):
            left = self._infer_node(node.left, expression, scope, diagnostics)
            right = self._infer_node(node.right, expression, scope, diagnostics)
            if node.operator == "+" and compatible(left, TEXT) and compatible(right, TEXT):
                return TEXT
            if node.operator not in {"+", "-", "*", "/", "//", "%", "**"}:
                diagnostics.append(
                    Diagnostic(
                        "T3038",
                        f"operador aritmético ainda não suportado: {node.operator}",
                        expression.span,
                    )
                )
                return ANY
            self._expect(left, NUMBER, expression, diagnostics)
            self._expect(right, NUMBER, expression, diagnostics)
            return NUMBER

        if isinstance(node, CompareNode):
            types = [
                self._infer_node(value, expression, scope, diagnostics)
                for value in node.values
            ]
            for left, right in zip(types, types[1:]):
                if not compatible(left, right):
                    diagnostics.append(
                        Diagnostic(
                            "T3033",
                            "comparação entre tipos incompatíveis: "
                            f"{left.render()} e {right.render()}",
                            expression.span,
                        )
                    )
            return BOOL

        if isinstance(node, ConditionalNode):
            condition = self._infer_node(node.condition, expression, scope, diagnostics)
            self._expect(condition, BOOL, expression, diagnostics)
            return unify_types(
                (
                    self._infer_node(node.when_true, expression, scope, diagnostics),
                    self._infer_node(node.when_false, expression, scope, diagnostics),
                )
            )

        if isinstance(node, CallNode):
            signature = self.BUILTINS.get(node.function)
            arguments = [
                self._infer_node(item, expression, scope, diagnostics)
                for item in node.arguments
            ]
            if signature is None:
                diagnostics.append(
                    Diagnostic(
                        "T3035",
                        f"função desconhecida: {node.function}",
                        expression.span,
                    )
                )
                return ANY
            expected, result = signature
            valid_arity = (
                len(arguments) >= 1
                if node.function in {"min", "max"}
                else len(expected) - (1 if node.function == "round" else 0)
                <= len(arguments)
                <= len(expected)
            )
            if not valid_arity:
                diagnostics.append(
                    Diagnostic(
                        "T3036",
                        f"{node.function} recebeu {len(arguments)} argumento(s); "
                        f"esperado {len(expected)}",
                        expression.span,
                    )
                )
            for actual, wanted in zip(arguments, expected):
                self._expect(actual, wanted, expression, diagnostics)
            if node.function in {"min", "max"} and arguments:
                return unify_types(arguments)
            return result

        diagnostics.append(
            Diagnostic(
                "T3038",
                f"expressão ainda não suportada: {type(node).__name__}",
                expression.span,
            )
        )
        return ANY

    @staticmethod
    def _expect(
        actual: SemanticType,
        expected: SemanticType,
        expression: Expression,
        diagnostics: list[Diagnostic],
    ) -> None:
        if compatible(actual, expected):
            return
        diagnostics.append(
            Diagnostic(
                "T3033",
                f"tipo incompatível: esperado {expected.render()}, recebido {actual.render()}",
                expression.span,
            )
        )


def compatible(left: SemanticType, right: SemanticType) -> bool:
    if left.name == "Any" or right.name == "Any":
        return True
    return (
        left.name == right.name
        and left.list_depth == right.list_depth
        and (right.optional or not left.optional)
    )


def unify_types(types: Iterable[SemanticType]) -> SemanticType:
    items = tuple(types)
    if not items:
        return ANY
    first = items[0]
    if all(compatible(first, item) and compatible(item, first) for item in items[1:]):
        return SemanticType(
            first.name,
            optional=any(item.optional for item in items),
            list_depth=first.list_depth,
        )
    return ANY


def parse_rendered_type(value: str | None) -> SemanticType:
    if not value:
        return ANY
    raw = value.strip()
    optional = raw.endswith("?")
    if optional:
        raw = raw[:-1]
    depth = 0
    while raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
        depth += 1
    return SemanticType(raw, optional=optional, list_depth=depth)


def translate_literals(text: str) -> str:
    """Compatibility helper retained for external callers; parsing no longer uses it."""
    return text.replace("true", "True").replace("false", "False").replace("null", "None")
