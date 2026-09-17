from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from .authority import canonical_sha256
from .v2_ast import V2Expression, V2Module, V2Statement, V2Type


class V2LoweringError(ValueError):
    pass


def type_dict(value: V2Type) -> dict[str, Any]:
    return {"name": value.name, "arguments": [type_dict(item) for item in value.arguments], "bound": value.bound}


def expression_ir(expression: V2Expression) -> dict[str, Any]:
    return _expression_node(ast.parse(expression.source, mode="eval").body)


def _expression_node(node: ast.AST) -> dict[str, Any]:
    if isinstance(node, ast.Constant): return {"op": "const", "value": node.value}
    if isinstance(node, ast.Name): return {"op": "name", "name": node.id}
    if isinstance(node, ast.Attribute):
        path: list[str] = [node.attr]; current = node.value
        while isinstance(current, ast.Attribute): path.append(current.attr); current = current.value
        if not isinstance(current, ast.Name): raise V2LoweringError("attribute root inválido")
        return {"op": "path", "root": current.id, "path": list(reversed(path))}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not): return {"op": "not", "value": _expression_node(node.operand)}
    if isinstance(node, ast.BoolOp):
        return {"op": "and" if isinstance(node.op, ast.And) else "or", "values": [_expression_node(item) for item in node.values]}
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        names = {ast.Eq:"eq",ast.NotEq:"ne",ast.Lt:"lt",ast.LtE:"le",ast.Gt:"gt",ast.GtE:"ge"}
        return {"op": names[type(node.ops[0])], "left": _expression_node(node.left), "right": _expression_node(node.comparators[0])}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name): return {"op":"call","name":node.func.id,"args":[_expression_node(item) for item in node.args]}
    if isinstance(node, (ast.List, ast.Tuple)): return {"op":"list","items":[_expression_node(item) for item in node.elts]}
    if isinstance(node, ast.Dict): return {"op":"map","items":[[_expression_node(k),_expression_node(v)] for k,v in zip(node.keys,node.values,strict=True)]}
    raise V2LoweringError(f"expressão não suportada: {type(node).__name__}")


def statement_ir(statement: V2Statement) -> dict[str, Any]:
    result: dict[str, Any] = {"op": statement.kind}
    if statement.kind in {"require", "ensure"}:
        result.update({"condition":expression_ir(statement.arguments[0]),"error":statement.arguments[1]})
    elif statement.kind in {"cancel_if", "return_ok", "return_error", "emit_event"}:
        result["value"] = expression_ir(statement.arguments[0])
    elif statement.kind in {"let", "set_state"}:
        result.update({"name":statement.arguments[0],"value":expression_ir(statement.arguments[1])})
    elif statement.kind == "request_effect": result["effect"] = statement.arguments[0]
    elif statement.kind == "if":
        result.update({"condition":expression_ir(statement.arguments[0]),"then":[statement_ir(item) for item in statement.body],"else":[statement_ir(item) for item in statement.otherwise]})
    elif statement.kind == "for":
        result.update({"name":statement.arguments[0],"iterable":expression_ir(statement.arguments[1]),"limit":statement.arguments[2],"body":[statement_ir(item) for item in statement.body]})
    elif statement.kind == "spawn_job": result.update({"name":statement.arguments[0],"payload":expression_ir(statement.arguments[1]),"limit":statement.arguments[2]})
    elif statement.kind == "join_job": result["name"] = statement.arguments[0]
    elif statement.kind == "match":
        result.update({"value":expression_ir(statement.arguments[0]),"cases":[{"label":case.arguments[0],"body":[statement_ir(item) for item in case.body]} for case in statement.body]})
    else: raise V2LoweringError(f"statement não suportado: {statement.kind}")
    return result


@dataclass(frozen=True, slots=True)
class V2IR:
    payload: dict[str, Any]

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.payload)


def lower_module(module: V2Module) -> V2IR:
    payload = {
        "schema":"casulo.t-ir/2.0",
        "module":module.name,
        "imports":list(module.imports),
        "capabilities":list(module.capabilities),
        "budgets":{"steps":module.step_budget,"deadline_ms":module.deadline_ms},
        "schema_version":module.schema_version,
        "records":[{"name":item.name,"members":[{"name":member.name,"type":type_dict(member.type_ref)} for member in item.members]} for item in module.records],
        "enums":[{"name":item.name,"cases":list(item.cases)} for item in module.enums],
        "states":[{"name":item.name,"type":type_dict(item.type_ref),"initial":item.initial} for item in module.states],
        "functions":[{"name":item.name,"parameter":{"name":item.parameter_name,"type":type_dict(item.parameter_type)},"return_type":type_dict(item.return_type),"effects":list(item.effects),"code":[statement_ir(statement) for statement in item.body]} for item in module.functions],
    }
    return V2IR(payload)

