from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .expression_ast import expression_cost, expression_names, parse_expression
from .ir import IRInstruction, IROperation, IRProgram


GRAPH_VERSION = "metamorfose-graph/0.1"
GRAPH_LEARN_VERSION = "metamorfose-graph/0.2"
GRAPH_VNEXT_VERSION = "metamorfose-graph/1.0"
_BUILTINS = frozenset({"abs", "round", "sqrt", "len", "min", "max"})


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    operation: str
    path: str
    kind: str
    label: str
    defines: tuple[str, ...]
    uses: tuple[str, ...]
    pure: bool
    effect: str
    estimated_cost: int


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class OperationGraph:
    name: str
    input_type: str | None
    output_type: str
    deterministic: bool
    cacheable: bool
    estimated_cost: int
    effects: tuple[str, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    permissions: tuple[str, ...] = ()
    shapes: tuple[tuple[str, tuple[str | int, ...]], ...] = ()
    cfg_entry: str | None = None
    cfg_blocks: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class GraphType:
    kind: str
    name: str
    members: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True, slots=True)
class MetamorfoseGraph:
    version: str
    module: str | None
    operations: tuple[OperationGraph, ...]
    capabilities: tuple[str, ...] = ()
    types: tuple[GraphType, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if not self.capabilities and self.version != GRAPH_VNEXT_VERSION:
            result.pop("capabilities")
            result.pop("types")
            for operation in result["operations"]:
                operation.pop("cfg_entry", None)
                operation.pop("cfg_blocks", None)
        return result

    def render_text(self) -> str:
        lines = [self.version]
        if self.module:
            lines.append(f"module {self.module}")
        if self.module:
            lines.append("")
        if self.capabilities:
            for capability in self.capabilities:
                lines.append(f"capability {capability}")
            lines.append("")
        for type_decl in self.types:
            members = ",".join(
                name if type_name is None else f"{name}:{type_name}"
                for name, type_name in type_decl.members
            )
            lines.append(f"type {type_decl.kind} {type_decl.name} members={members}")
        if self.types:
            lines.append("")
        for operation in self.operations:
            effects = ",".join(operation.effects) or "-"
            lines.append(
                f"operation {operation.name} "
                f"cacheable={str(operation.cacheable).lower()} "
                f"cost={operation.estimated_cost} "
                f"effects={effects}"
            )
            if operation.permissions:
                lines.append("  permissions " + ",".join(operation.permissions))
            if operation.cfg_entry is not None:
                lines.append(f"  cfg entry={operation.cfg_entry}")
                for block, successors in operation.cfg_blocks:
                    lines.append(
                        f"  cfg-block {block} successors="
                        + (",".join(successors) or "-")
                    )
            for name, shape in operation.shapes:
                lines.append(
                    f"  shape {name}=[{','.join(str(item) for item in shape)}]"
                )
            for node in operation.nodes:
                defines = ",".join(node.defines) or "-"
                uses = ",".join(node.uses) or "-"
                lines.append(
                    f"  node {node.id} kind={node.kind} "
                    f"defines={defines} uses={uses} "
                    f"effect={node.effect} cost={node.estimated_cost}"
                )
            for edge in operation.edges:
                label = f" name={edge.name}" if edge.name else ""
                lines.append(
                    f"  edge {edge.source} -> {edge.target} "
                    f"kind={edge.kind}{label}"
                )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


class MetamorfoseGraphBuilder:
    def build(self, program: IRProgram) -> MetamorfoseGraph:
        fields = {
            field.name: tuple(trace.name for trace in field.traces)
            for field in program.fields
        }
        fields.update(
            {
                record.name: tuple(trace.name for trace in record.traces)
                for record in program.records
            }
        )
        operations = tuple(
            self._build_operation(operation, fields) for operation in program.operations
        )
        return MetamorfoseGraph(
            version=(
                GRAPH_LEARN_VERSION
                if program.version == "crisalida-ir/0.2"
                else GRAPH_VNEXT_VERSION
                if program.version == "crisalida-ir/1.0"
                else GRAPH_VERSION
            ),
            module=program.module,
            operations=operations,
            capabilities=program.capabilities,
            types=tuple(
                [
                    GraphType(
                        "record",
                        record.name,
                        tuple((trace.name, trace.type_name) for trace in record.traces),
                    )
                    for record in program.records
                ]
                + [
                    GraphType(
                        "enum",
                        enum.name,
                        tuple((case, None) for case in enum.cases),
                    )
                    for enum in program.enums
                ]
            ),
        )

    def _build_operation(
        self,
        operation: IROperation,
        fields: dict[str, tuple[str, ...]],
    ) -> OperationGraph:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        definitions: dict[str, str] = {}
        for trace in fields.get(operation.input_type or "", ()):
            node_id = f"{operation.name}/input/{trace}"
            nodes.append(
                GraphNode(
                    id=node_id,
                    operation=operation.name,
                    path=f"input.{trace}",
                    kind="input",
                    label=trace,
                    defines=(trace,),
                    uses=(),
                    pure=True,
                    effect="read",
                    estimated_cost=0,
                )
            )
            definitions[trace] = node_id

        if operation.kind == "learn":
            target_id = f"{operation.name}/input/target"
            nodes.append(
                GraphNode(
                    id=target_id,
                    operation=operation.name,
                    path="input.target",
                    kind="input",
                    label=operation.target_type or "target",
                    defines=("target",),
                    uses=(),
                    pure=True,
                    effect="read",
                    estimated_cost=0,
                )
            )
            definitions["target"] = target_id

        self._walk_block(
            operation,
            operation.instructions,
            definitions,
            nodes,
            edges,
            prefix="root",
            control_parent=None,
        )
        effects = tuple(
            dict.fromkeys(
                node.effect
                for node in nodes
                if node.effect not in {"pure", "read", "control"}
            )
        )
        contract = operation.contract or {}
        effect_contract = contract.get("effect_contract", {})
        shapes = tuple(
            (name.removesuffix("_shape"), tuple(contract[name]))
            for name in ("input_shape", "hidden_shape", "output_shape")
            if name in contract
        )
        return OperationGraph(
            name=operation.name,
            input_type=operation.input_type,
            output_type=operation.output_type,
            deterministic=bool(contract.get("deterministic", True)),
            cacheable=operation.kind != "learn",
            estimated_cost=sum(node.estimated_cost for node in nodes),
            effects=effects,
            nodes=tuple(nodes),
            edges=tuple(_deduplicate_edges(edges)),
            permissions=tuple(
                effect_contract.get("declared", contract.get("permissions", ()))
            ),
            shapes=shapes,
            cfg_entry=operation.cfg.entry if operation.cfg is not None else None,
            cfg_blocks=(
                tuple((block.id, block.successors) for block in operation.cfg.blocks)
                if operation.cfg is not None
                else ()
            ),
        )

    def _walk_block(
        self,
        operation: IROperation,
        instructions: tuple[IRInstruction, ...],
        definitions: dict[str, str],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        prefix: str,
        control_parent: str | None,
    ) -> None:
        for index, instruction in enumerate(instructions):
            path = f"{prefix}.{index}"
            node_id = f"{operation.name}/instruction/{path}/{instruction.op}"
            expressions = _instruction_expressions(instruction)
            profiles = tuple(_expression_profile(item) for item in expressions)
            uses = tuple(
                sorted(
                    {name for profile_names, _ in profiles for name in profile_names}
                )
            )
            defines = (instruction.result,) if instruction.result else ()
            effect, pure = _effect_for(instruction.op)
            cost = 1 + sum(profile_cost for _, profile_cost in profiles)
            nodes.append(
                GraphNode(
                    id=node_id,
                    operation=operation.name,
                    path=path,
                    kind=instruction.op,
                    label=_instruction_label(instruction),
                    defines=defines,
                    uses=uses,
                    pure=pure,
                    effect=effect,
                    estimated_cost=cost,
                )
            )
            if control_parent is not None:
                edges.append(
                    GraphEdge(
                        source=control_parent,
                        target=node_id,
                        kind="control",
                    )
                )
            for name in uses:
                source = definitions.get(name)
                if source is not None:
                    edges.append(
                        GraphEdge(
                            source=source,
                            target=node_id,
                            kind="data",
                            name=name,
                        )
                    )
            if defines:
                definitions[defines[0]] = node_id
            if instruction.op == "if":
                self._walk_block(
                    operation,
                    instruction.then_body,
                    definitions.copy(),
                    nodes,
                    edges,
                    prefix=f"{path}.then",
                    control_parent=node_id,
                )
                self._walk_block(
                    operation,
                    instruction.else_body,
                    definitions.copy(),
                    nodes,
                    edges,
                    prefix=f"{path}.else",
                    control_parent=node_id,
                )


def _instruction_expressions(
    instruction: IRInstruction,
) -> tuple[str, ...]:
    if instruction.op == "bind":
        return instruction.arguments[:2]
    if instruction.op.startswith("learn."):
        return instruction.arguments
    if instruction.op in {
        "let",
        "judge",
        "restrict",
        "stabilize",
        "emit",
        "project",
        "if",
    }:
        return instruction.arguments[:1]
    return ()


def _effect_for(operation: str) -> tuple[str, bool]:
    return {
        "let": ("pure", True),
        "if": ("control", True),
        "judge": ("guard", False),
        "restrict": ("guard", False),
        "stabilize": ("evidence", False),
        "project": ("evidence", False),
        "bind": ("evidence", False),
        "emit": ("manifest", False),
        "learn.read": ("data-read", False),
        "learn.forward": ("compute", True),
        "learn.loss": ("compute", True),
        "learn.backward": ("compute", True),
        "learn.optimize": ("state-write", False),
        "learn.stop": ("guard", False),
    }.get(operation, ("unknown", False))


def _instruction_label(instruction: IRInstruction) -> str:
    arguments = ", ".join(instruction.arguments)
    if instruction.result:
        return f"{instruction.result} = {arguments}"
    return arguments


def _expression_profile(expression: str) -> tuple[tuple[str, ...], int]:
    root = parse_expression(expression)
    return tuple(sorted(expression_names(root))), expression_cost(root)


def _deduplicate_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    seen: set[tuple[str, str, str, str | None]] = set()
    result: list[GraphEdge] = []
    for edge in edges:
        key = (edge.source, edge.target, edge.kind, edge.name)
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result
