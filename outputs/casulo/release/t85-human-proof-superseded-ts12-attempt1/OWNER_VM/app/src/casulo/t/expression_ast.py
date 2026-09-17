from __future__ import annotations

import ast as literal_ast
import io
import tokenize
from dataclasses import dataclass
from typing import Iterable, TypeAlias


class ExpressionSyntaxError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LiteralNode:
    value: bool | int | float | str | None


@dataclass(frozen=True, slots=True)
class NameNode:
    name: str


@dataclass(frozen=True, slots=True)
class ListNode:
    items: tuple["ExpressionNode", ...]


@dataclass(frozen=True, slots=True)
class UnaryNode:
    operator: str
    operand: "ExpressionNode"


@dataclass(frozen=True, slots=True)
class BinaryNode:
    left: "ExpressionNode"
    operator: str
    right: "ExpressionNode"


@dataclass(frozen=True, slots=True)
class BooleanNode:
    operator: str
    values: tuple["ExpressionNode", ...]


@dataclass(frozen=True, slots=True)
class CompareNode:
    values: tuple["ExpressionNode", ...]
    operators: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConditionalNode:
    condition: "ExpressionNode"
    when_true: "ExpressionNode"
    when_false: "ExpressionNode"


@dataclass(frozen=True, slots=True)
class CallNode:
    function: str
    arguments: tuple["ExpressionNode", ...]


ExpressionNode: TypeAlias = (
    LiteralNode
    | NameNode
    | ListNode
    | UnaryNode
    | BinaryNode
    | BooleanNode
    | CompareNode
    | ConditionalNode
    | CallNode
)


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: str


_IGNORED = {tokenize.ENCODING, tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER}
_COMPARISONS = {"==", "!=", "<", "<=", ">", ">="}


def parse_expression(text: str) -> ExpressionNode:
    try:
        generated = tokenize.generate_tokens(io.StringIO(text).readline)
        tokens = tuple(
            _Token(tokenize.tok_name[token.type], token.string)
            for token in generated
            if token.type not in _IGNORED
        )
    except (IndentationError, tokenize.TokenError) as exc:
        raise ExpressionSyntaxError(str(exc)) from exc
    parser = _Parser(tokens)
    result = parser.parse_conditional()
    if not parser.done:
        raise ExpressionSyntaxError(f"token inesperado: {parser.current.value!r}")
    return result


class _Parser:
    def __init__(self, tokens: tuple[_Token, ...]) -> None:
        self.tokens = tokens
        self.index = 0

    @property
    def done(self) -> bool:
        return self.index >= len(self.tokens)

    @property
    def current(self) -> _Token:
        if self.done:
            return _Token("EOF", "")
        return self.tokens[self.index]

    def accept(self, value: str) -> bool:
        if self.current.value != value:
            return False
        self.index += 1
        return True

    def expect(self, value: str) -> None:
        if not self.accept(value):
            raise ExpressionSyntaxError(
                f"esperado {value!r}, recebido {self.current.value!r}"
            )

    def parse_conditional(self) -> ExpressionNode:
        when_true = self.parse_or()
        if not self.accept("if"):
            return when_true
        condition = self.parse_or()
        self.expect("else")
        when_false = self.parse_conditional()
        return ConditionalNode(condition, when_true, when_false)

    def parse_or(self) -> ExpressionNode:
        values = [self.parse_and()]
        while self.accept("or"):
            values.append(self.parse_and())
        return values[0] if len(values) == 1 else BooleanNode("or", tuple(values))

    def parse_and(self) -> ExpressionNode:
        values = [self.parse_not()]
        while self.accept("and"):
            values.append(self.parse_not())
        return values[0] if len(values) == 1 else BooleanNode("and", tuple(values))

    def parse_not(self) -> ExpressionNode:
        if self.accept("not"):
            return UnaryNode("not", self.parse_not())
        return self.parse_compare()

    def parse_compare(self) -> ExpressionNode:
        values = [self.parse_sum()]
        operators: list[str] = []
        while self.current.value in _COMPARISONS:
            operators.append(self.current.value)
            self.index += 1
            values.append(self.parse_sum())
        if not operators:
            return values[0]
        return CompareNode(tuple(values), tuple(operators))

    def parse_sum(self) -> ExpressionNode:
        node = self.parse_term()
        while self.current.value in {"+", "-"}:
            operator = self.current.value
            self.index += 1
            node = BinaryNode(node, operator, self.parse_term())
        return node

    def parse_term(self) -> ExpressionNode:
        node = self.parse_power()
        while self.current.value in {"*", "/", "//", "%"}:
            operator = self.current.value
            self.index += 1
            node = BinaryNode(node, operator, self.parse_power())
        return node

    def parse_power(self) -> ExpressionNode:
        node = self.parse_unary()
        if self.accept("**"):
            node = BinaryNode(node, "**", self.parse_power())
        return node

    def parse_unary(self) -> ExpressionNode:
        if self.current.value in {"+", "-"}:
            operator = self.current.value
            self.index += 1
            return UnaryNode(operator, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> ExpressionNode:
        token = self.current
        if token.kind == "NUMBER":
            self.index += 1
            try:
                value = literal_ast.literal_eval(token.value)
            except (SyntaxError, ValueError) as exc:
                raise ExpressionSyntaxError(f"número inválido: {token.value}") from exc
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ExpressionSyntaxError(f"número não suportado: {token.value}")
            return LiteralNode(value)
        if token.kind == "STRING":
            self.index += 1
            try:
                value = literal_ast.literal_eval(token.value)
            except (SyntaxError, ValueError) as exc:
                raise ExpressionSyntaxError("texto inválido") from exc
            if not isinstance(value, str):
                raise ExpressionSyntaxError("somente literais Text são aceitos")
            return LiteralNode(value)
        if token.kind == "NAME":
            self.index += 1
            if token.value in {"true", "True"}:
                return LiteralNode(True)
            if token.value in {"false", "False"}:
                return LiteralNode(False)
            if token.value in {"null", "None"}:
                return LiteralNode(None)
            node: ExpressionNode = NameNode(token.value)
            if self.accept("("):
                arguments: list[ExpressionNode] = []
                if not self.accept(")"):
                    while True:
                        arguments.append(self.parse_conditional())
                        if self.accept(")"):
                            break
                        self.expect(",")
                node = CallNode(token.value, tuple(arguments))
            return node
        if self.accept("["):
            items: list[ExpressionNode] = []
            if not self.accept("]"):
                while True:
                    items.append(self.parse_conditional())
                    if self.accept("]"):
                        break
                    self.expect(",")
            return ListNode(tuple(items))
        if self.accept("("):
            node = self.parse_conditional()
            self.expect(")")
            return node
        raise ExpressionSyntaxError(f"expressão esperada, recebido {token.value!r}")


def walk_expression(node: ExpressionNode) -> Iterable[ExpressionNode]:
    yield node
    children: tuple[ExpressionNode, ...]
    if isinstance(node, (LiteralNode, NameNode)):
        children = ()
    elif isinstance(node, ListNode):
        children = node.items
    elif isinstance(node, UnaryNode):
        children = (node.operand,)
    elif isinstance(node, BinaryNode):
        children = (node.left, node.right)
    elif isinstance(node, BooleanNode):
        children = node.values
    elif isinstance(node, CompareNode):
        children = node.values
    elif isinstance(node, ConditionalNode):
        children = (node.condition, node.when_true, node.when_false)
    else:
        children = node.arguments
    for child in children:
        yield from walk_expression(child)


def expression_names(node: ExpressionNode, *, include_builtins: bool = False) -> set[str]:
    builtins = {"abs", "round", "sqrt", "len", "min", "max"}
    names = {item.name for item in walk_expression(node) if isinstance(item, NameNode)}
    if include_builtins:
        names.update(
            item.function
            for item in walk_expression(node)
            if isinstance(item, CallNode)
        )
    return names - (set() if include_builtins else builtins)


def expression_cost(node: ExpressionNode) -> int:
    cost = 0
    for item in walk_expression(node):
        if isinstance(item, (UnaryNode, BinaryNode, CallNode, ConditionalNode)):
            cost += 1
        elif isinstance(item, BooleanNode):
            cost += max(1, len(item.values) - 1)
        elif isinstance(item, CompareNode):
            cost += max(1, len(item.operators))
        elif isinstance(item, ListNode):
            cost += len(item.items)
    return cost
