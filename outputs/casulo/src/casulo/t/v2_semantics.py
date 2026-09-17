from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable

from .v2_ast import V2Expression, V2Function, V2Module, V2Span, V2Statement, V2Type
from .v2_parser import V2Diagnostic


PRIMITIVES = frozenset({"Bool", "Int", "Float", "Decimal", "Text", "Bytes", "Timestamp"})
CONTAINERS = frozenset({"Option", "Result", "List", "Map", "Set"})
PURE_CALLS = frozenset({"len", "all_equal", "contains", "add", "get"})
ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.UnaryOp,
    ast.Not, ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Call, ast.List, ast.Tuple, ast.Dict,
)


@dataclass(frozen=True, slots=True)
class V2SemanticResult:
    module: V2Module
    diagnostics: tuple[V2Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return not self.diagnostics


class V2Analyzer:
    def analyze(self, module: V2Module, imported_types: Iterable[str] = ()) -> V2SemanticResult:
        diagnostics: list[V2Diagnostic] = []
        declared = set(PRIMITIVES) | set(imported_types)
        names: set[str] = set()
        for declaration in (*module.records, *module.enums):
            if declaration.name in names or declaration.name in PRIMITIVES | CONTAINERS:
                diagnostics.append(V2Diagnostic("T2100", f"tipo duplicado ou reservado: {declaration.name}", declaration.span))
            names.add(declaration.name); declared.add(declaration.name)
        for record in module.records:
            member_names: set[str] = set()
            if not record.members:
                diagnostics.append(V2Diagnostic("T2101", f"record vazio: {record.name}", record.span))
            for member in record.members:
                if member.name in member_names:
                    diagnostics.append(V2Diagnostic("T2102", f"member duplicado: {member.name}", member.span))
                member_names.add(member.name)
                self._type(member.type_ref, declared, member.span, diagnostics)
        for enum in module.enums:
            if not enum.cases or len(set(enum.cases)) != len(enum.cases):
                diagnostics.append(V2Diagnostic("T2103", f"enum vazio ou duplicado: {enum.name}", enum.span))
        state_names: set[str] = set()
        for state in module.states:
            if state.name in state_names:
                diagnostics.append(V2Diagnostic("T2104", f"state duplicado: {state.name}", state.span))
            state_names.add(state.name); self._type(state.type_ref, declared, state.span, diagnostics)
        function_names: set[str] = set()
        for function in module.functions:
            if function.name in function_names:
                diagnostics.append(V2Diagnostic("T2105", f"função duplicada: {function.name}", function.span))
            function_names.add(function.name)
            self._function(function, module, declared, state_names, diagnostics)
        if not module.functions:
            diagnostics.append(
                V2Diagnostic(
                    "T2106",
                    "módulo sem função",
                    module.records[0].span
                    if module.records
                    else module.enums[0].span
                    if module.enums
                    else module.states[0].span
                    if module.states
                    else V2Span(module.source_name, 1),
                )
            )
        return V2SemanticResult(module, tuple(diagnostics))

    def _function(self, function: V2Function, module: V2Module, declared: set[str], state_names: set[str], diagnostics: list[V2Diagnostic]) -> None:
        self._type(function.parameter_type, declared, function.span, diagnostics)
        self._type(function.return_type, declared, function.span, diagnostics)
        undeclared = set(function.effects) - set(module.capabilities)
        if undeclared:
            diagnostics.append(V2Diagnostic("T2107", f"effects sem capability: {', '.join(sorted(undeclared))}", function.span))
        if function.return_type.name != "Result":
            diagnostics.append(V2Diagnostic("T2108", "função produtiva precisa retornar Result<T,E>", function.span))
        names = {function.parameter_name, "state"}
        self._block(function.body, names, state_names, set(function.effects), diagnostics)
        if not self._returns(function.body):
            diagnostics.append(V2Diagnostic("T2109", f"função pode terminar sem return: {function.name}", function.span))

    def _block(self, body: tuple[V2Statement, ...], names: set[str], state_names: set[str], effects: set[str], diagnostics: list[V2Diagnostic]) -> None:
        local = set(names)
        for statement in body:
            if statement.kind in {"require", "ensure", "cancel_if", "return_ok", "return_error", "emit_event"}:
                self._expr(statement.arguments[0], local, diagnostics)
            elif statement.kind == "let":
                name, expression = statement.arguments
                if name in local:
                    diagnostics.append(V2Diagnostic("T2110", f"local duplicado: {name}", statement.span))
                self._expr(expression, local, diagnostics); local.add(name)
            elif statement.kind == "set_state":
                name, expression = statement.arguments
                if name not in state_names:
                    diagnostics.append(V2Diagnostic("T2111", f"state desconhecido: {name}", statement.span))
                self._expr(expression, local, diagnostics)
            elif statement.kind == "request_effect":
                if statement.arguments[0] not in effects:
                    diagnostics.append(V2Diagnostic("T2112", f"effect não declarado na função: {statement.arguments[0]}", statement.span))
            elif statement.kind == "spawn_job":
                name, expression, limit = statement.arguments
                self._expr(expression, local, diagnostics)
                if name in local or limit <= 0 or limit > 100_000:
                    diagnostics.append(V2Diagnostic("T2120", "job duplicado ou limite inválido", statement.span))
                local.add(name)
            elif statement.kind == "join_job":
                if statement.arguments[0] not in local:
                    diagnostics.append(V2Diagnostic("T2121", f"job desconhecido: {statement.arguments[0]}", statement.span))
            elif statement.kind == "if":
                self._expr(statement.arguments[0], local, diagnostics)
                self._block(statement.body, set(local), state_names, effects, diagnostics)
                self._block(statement.otherwise, set(local), state_names, effects, diagnostics)
            elif statement.kind == "for":
                name, expression, limit = statement.arguments
                self._expr(expression, local, diagnostics)
                if limit <= 0 or limit > 100_000:
                    diagnostics.append(V2Diagnostic("T2113", "loop limit fora do limite", statement.span))
                self._block(statement.body, local | {name}, state_names, effects, diagnostics)
            elif statement.kind == "match":
                self._expr(statement.arguments[0], local, diagnostics)
                labels = [case.arguments[0] for case in statement.body]
                if len(labels) != len(set(labels)) or "_" not in labels:
                    diagnostics.append(V2Diagnostic("T2122", "match precisa de cases únicos e fallback exaustivo _", statement.span))
                for case in statement.body:
                    self._block(case.body, set(local), state_names, effects, diagnostics)

    def _expr(self, expression: V2Expression, names: set[str], diagnostics: list[V2Diagnostic]) -> None:
        try:
            tree = ast.parse(expression.source, mode="eval")
        except SyntaxError:
            diagnostics.append(V2Diagnostic("T2114", f"expressão inválida: {expression.source}", expression.span)); return
        for node in ast.walk(tree):
            if not isinstance(node, ALLOWED_NODES):
                diagnostics.append(V2Diagnostic("T2115", f"nó de expressão proibido: {type(node).__name__}", expression.span)); return
            if isinstance(node, ast.Name) and node.id not in names and node.id not in PURE_CALLS and node.id not in {"True", "False", "None"}:
                diagnostics.append(V2Diagnostic("T2116", f"nome desconhecido: {node.id}", expression.span)); return
            if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in PURE_CALLS):
                diagnostics.append(V2Diagnostic("T2117", "chamada não allowlisted", expression.span)); return

    @staticmethod
    def _returns(body: tuple[V2Statement, ...]) -> bool:
        for statement in body:
            if statement.kind in {"return_ok", "return_error"}:
                return True
            if statement.kind == "if" and statement.otherwise and V2Analyzer._returns(statement.body) and V2Analyzer._returns(statement.otherwise):
                return True
            if statement.kind == "match" and statement.body and all(V2Analyzer._returns(case.body) for case in statement.body):
                return True
        return False

    def _type(self, value: V2Type, declared: set[str], span, diagnostics: list[V2Diagnostic]) -> None:
        if value.name not in declared and value.name not in CONTAINERS:
            diagnostics.append(V2Diagnostic("T2118", f"tipo desconhecido: {value.name}", span))
        if value.name in {"List", "Set", "Map"} and (value.bound is None or value.bound <= 0):
            diagnostics.append(V2Diagnostic("T2119", f"coleção sem limite: {value.name}", span))
        for argument in value.arguments:
            self._type(argument, declared, span, diagnostics)
