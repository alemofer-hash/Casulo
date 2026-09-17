from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .analyzer import AnalysisResult, expression_key
from .ast import (
    BindStmt,
    CondenseDecl,
    EmitStmt,
    EnumDecl,
    FieldDecl,
    IfStmt,
    JudgeStmt,
    LearnDecl,
    LetStmt,
    Program,
    ProjectStmt,
    RecordDecl,
    RestrictStmt,
    StabilizeStmt,
    Statement,
    TransitionDecl,
)
from .diagnostics import SourceSpan
from .effects import T_VNEXT_LANGUAGE


IR_VERSION = "crisalida-ir/0.1"
IR_LEARN_VERSION = "crisalida-ir/0.2"
IR_VNEXT_VERSION = "crisalida-ir/1.0"


@dataclass(frozen=True, slots=True)
class IRTrace:
    name: str
    type_name: str


@dataclass(frozen=True, slots=True)
class IRField:
    name: str
    traces: tuple[IRTrace, ...]


@dataclass(frozen=True, slots=True)
class IRRecord:
    name: str
    traces: tuple[IRTrace, ...]


@dataclass(frozen=True, slots=True)
class IREnum:
    name: str
    cases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IRInstruction:
    op: str
    arguments: tuple[str, ...] = ()
    result: str | None = None
    type_name: str | None = None
    then_body: tuple["IRInstruction", ...] = ()
    else_body: tuple["IRInstruction", ...] = ()
    span: SourceSpan | None = None


@dataclass(frozen=True, slots=True)
class IRBasicBlock:
    id: str
    instruction_paths: tuple[str, ...]
    successors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IRControlFlow:
    entry: str
    exit: str
    blocks: tuple[IRBasicBlock, ...]


@dataclass(frozen=True, slots=True)
class IROperation:
    kind: str
    name: str
    input_type: str | None
    target_type: str | None
    output_type: str
    instructions: tuple[IRInstruction, ...]
    contract: dict[str, Any] | None = None
    cfg: IRControlFlow | None = None


@dataclass(frozen=True, slots=True)
class IRProgram:
    version: str
    module: str | None
    uses: tuple[str, ...]
    fields: tuple[IRField, ...]
    operations: tuple[IROperation, ...]
    records: tuple[IRRecord, ...] = ()
    enums: tuple[IREnum, ...] = ()
    language: str = "T/1.0"
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.language == "T/1.0" and not self.capabilities:
            result.pop("language")
            result.pop("capabilities")
            result.pop("records")
            result.pop("enums")
            for operation in result["operations"]:
                operation.pop("cfg", None)
        return result

    def render_text(self) -> str:
        lines = [self.version]
        if self.language == T_VNEXT_LANGUAGE:
            lines.append(f"language {self.language}")
            for capability in self.capabilities:
                lines.append(f"capability {capability}")
        if self.module:
            lines.append(f"module {self.module}")
        for use in self.uses:
            lines.append(f"use {use}")
        if self.module or self.uses:
            lines.append("")

        for field_decl in self.fields:
            lines.append(f"field {field_decl.name} {{")
            for trace in field_decl.traces:
                lines.append(f"  {trace.name}: {trace.type_name}")
            lines.append("}")
            lines.append("")

        for record in self.records:
            lines.append(f"record {record.name} {{")
            for trace in record.traces:
                lines.append(f"  {trace.name}: {trace.type_name}")
            lines.append("}")
            lines.append("")

        for enum in self.enums:
            lines.append(f"enum {enum.name} {{ {', '.join(enum.cases)} }}")
            lines.append("")

        for operation in self.operations:
            if operation.kind == "transition":
                signature = (
                    f"transition {operation.name}("
                    f"{operation.input_type} -> {operation.target_type}"
                    f") -> {operation.output_type}"
                )
            elif operation.kind == "condense":
                input_rendered = operation.input_type or "-"
                signature = (
                    f"condense {operation.name}("
                    f"{input_rendered}) -> {operation.output_type}"
                )
            else:
                signature = (
                    f"learn {operation.name}("
                    f"{operation.input_type} -> {operation.target_type}"
                    f") -> {operation.output_type}"
                )
            lines.append(signature + " {")
            if operation.cfg is not None:
                lines.append(
                    f"  cfg entry={operation.cfg.entry} exit={operation.cfg.exit}"
                )
                for block in operation.cfg.blocks:
                    paths = ",".join(block.instruction_paths) or "-"
                    successors = ",".join(block.successors) or "-"
                    lines.append(
                        f"  block {block.id} instructions={paths} successors={successors}"
                    )
            lines.extend(_render_instructions(operation.instructions, 1))
            lines.append("}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


class CrisalidaLowerer:
    def lower(self, program: Program, analysis: AnalysisResult) -> IRProgram:
        fields: list[IRField] = []
        records: list[IRRecord] = []
        enums: list[IREnum] = []
        operations: list[IROperation] = []

        for declaration in program.declarations:
            if isinstance(declaration, FieldDecl):
                fields.append(
                    IRField(
                        name=declaration.name,
                        traces=tuple(
                            IRTrace(
                                name=trace.name,
                                type_name=_render_type_ref(trace.type_ref),
                            )
                            for trace in declaration.traces
                        ),
                    )
                )
            elif isinstance(declaration, RecordDecl):
                records.append(
                    IRRecord(
                        name=declaration.name,
                        traces=tuple(
                            IRTrace(trace.name, _render_type_ref(trace.type_ref))
                            for trace in declaration.traces
                        ),
                    )
                )
            elif isinstance(declaration, EnumDecl):
                enums.append(
                    IREnum(
                        name=declaration.name,
                        cases=tuple(case.name for case in declaration.cases),
                    )
                )
            elif isinstance(declaration, CondenseDecl):
                contract = self._effect_contract(declaration.name, analysis)
                instructions = self._lower_block(declaration.body, analysis)
                operations.append(
                    IROperation(
                        kind="condense",
                        name=declaration.name,
                        input_type=declaration.input_type,
                        target_type=None,
                        output_type=analysis.operation_outputs[
                            declaration.name
                        ].render(),
                        instructions=instructions,
                        contract=contract,
                        cfg=(
                            _build_cfg(instructions)
                            if program.language is not None
                            and program.language.version == T_VNEXT_LANGUAGE
                            else None
                        ),
                    )
                )
            elif isinstance(declaration, TransitionDecl):
                contract = self._effect_contract(declaration.name, analysis)
                instructions = self._lower_block(declaration.body, analysis)
                operations.append(
                    IROperation(
                        kind="transition",
                        name=declaration.name,
                        input_type=declaration.from_type,
                        target_type=declaration.to_type,
                        output_type=analysis.operation_outputs[
                            declaration.name
                        ].render(),
                        instructions=instructions,
                        contract=contract,
                        cfg=(
                            _build_cfg(instructions)
                            if program.language is not None
                            and program.language.version == T_VNEXT_LANGUAGE
                            else None
                        ),
                    )
                )
            elif isinstance(declaration, LearnDecl):
                contract = analysis.learn_contracts[declaration.name]
                operations.append(
                    IROperation(
                        kind="learn",
                        name=declaration.name,
                        input_type=_render_shape(
                            contract.input_shape,
                            contract.precision,
                        ),
                        target_type=_render_shape(
                            contract.output_shape,
                            contract.precision,
                        ),
                        output_type=(
                            f"Model[{contract.input_features},"
                            f"{contract.hidden_features},"
                            f"{contract.output_features}]"
                            f":{contract.precision}"
                        ),
                        instructions=_lower_learn_contract(contract, declaration.span),
                        contract=contract.to_dict(),
                    )
                )

        language = program.language.version if program.language else "T/1.0"
        return IRProgram(
            version=(
                IR_LEARN_VERSION
                if analysis.learn_contracts
                else IR_VNEXT_VERSION if language == T_VNEXT_LANGUAGE else IR_VERSION
            ),
            module=program.module.name if program.module else None,
            uses=tuple(use.name for use in program.uses),
            fields=tuple(fields),
            operations=tuple(operations),
            records=tuple(records),
            enums=tuple(enums),
            language=language,
            capabilities=tuple(capability.name for capability in program.capabilities),
        )

    @staticmethod
    def _effect_contract(
        operation_name: str,
        analysis: AnalysisResult,
    ) -> dict[str, Any] | None:
        declared = analysis.operation_effects.get(operation_name, ())
        if not declared:
            return None
        return {
            "effect_contract": {
                "schema": "casulo-t-effects/1.0",
                "declared": list(declared),
            }
        }

    def _lower_block(
        self,
        body: tuple[Statement, ...],
        analysis: AnalysisResult,
    ) -> tuple[IRInstruction, ...]:
        return tuple(
            self._lower_statement(statement, analysis)
            for statement in body
        )

    def _lower_statement(
        self,
        statement: Statement,
        analysis: AnalysisResult,
    ) -> IRInstruction:
        if isinstance(statement, LetStmt):
            return IRInstruction(
                op="let",
                result=statement.name,
                arguments=(statement.value.text,),
                type_name=self._expression_type(statement.value, analysis),
                span=statement.span,
            )
        if isinstance(statement, JudgeStmt):
            return IRInstruction(
                op="judge",
                arguments=(statement.condition.text,),
                type_name="Bool",
                span=statement.span,
            )
        if isinstance(statement, RestrictStmt):
            return IRInstruction(
                op="restrict",
                arguments=(statement.condition.text,),
                type_name="Bool",
                span=statement.span,
            )
        if isinstance(statement, StabilizeStmt):
            return IRInstruction(
                op="stabilize",
                arguments=(statement.target.text,),
                type_name=self._expression_type(statement.target, analysis),
                span=statement.span,
            )
        if isinstance(statement, EmitStmt):
            return IRInstruction(
                op="emit",
                arguments=(statement.value.text,),
                type_name=self._expression_type(statement.value, analysis),
                span=statement.span,
            )
        if isinstance(statement, ProjectStmt):
            arguments = [statement.source.text]
            if statement.target:
                arguments.append(f"as:{statement.target}")
            if statement.into:
                arguments.append("into:" + ",".join(statement.into))
            return IRInstruction(
                op="project",
                arguments=tuple(arguments),
                type_name=self._expression_type(statement.source, analysis),
                span=statement.span,
            )
        if isinstance(statement, BindStmt):
            return IRInstruction(
                op="bind",
                arguments=(statement.left.text, statement.right.text),
                span=statement.span,
            )
        if isinstance(statement, IfStmt):
            return IRInstruction(
                op="if",
                arguments=(statement.condition.text,),
                type_name="Bool",
                then_body=self._lower_block(statement.then_body, analysis),
                else_body=self._lower_block(statement.else_body, analysis),
                span=statement.span,
            )
        raise TypeError(f"unsupported statement: {type(statement)!r}")

    @staticmethod
    def _expression_type(expression, analysis: AnalysisResult) -> str:
        inferred = analysis.expression_types.get(expression_key(expression))
        return inferred.render() if inferred is not None else "Any"


def _render_type_ref(type_ref) -> str:
    value = type_ref.name
    if type_ref.arguments:
        value += "[" + ",".join(
            _render_type_ref(argument) for argument in type_ref.arguments
        ) + "]"
    for _ in range(type_ref.list_depth):
        value = f"[{value}]"
    if type_ref.optional:
        value += "?"
    return value


def _render_shape(shape: tuple[str | int, ...], precision: str) -> str:
    dimensions = ",".join(str(item) for item in shape)
    return f"Tensor[{dimensions}]:{precision}"


def _lower_learn_contract(contract, span: SourceSpan) -> tuple[IRInstruction, ...]:
    input_type = _render_shape(contract.input_shape, contract.precision)
    output_type = _render_shape(contract.output_shape, contract.precision)
    return (
        IRInstruction(
            op="learn.read",
            result="batch",
            type_name=input_type,
            span=span,
        ),
        IRInstruction(
            op="learn.forward",
            arguments=("batch",),
            result="prediction",
            type_name=output_type,
            span=span,
        ),
        IRInstruction(
            op="learn.loss",
            arguments=("prediction", "target"),
            result="loss",
            type_name="Number",
            span=span,
        ),
        IRInstruction(
            op="learn.backward",
            arguments=("loss",),
            result="gradients",
            type_name=f"Gradients:{contract.precision}",
            span=span,
        ),
        IRInstruction(
            op="learn.optimize",
            arguments=("gradients",),
            result="model",
            type_name=(
                f"Model[{contract.input_features},"
                f"{contract.hidden_features},"
                f"{contract.output_features}]:{contract.precision}"
            ),
            span=span,
        ),
        IRInstruction(
            op="learn.stop",
            arguments=("loss",),
            type_name="Bool",
            span=span,
        ),
    )


def _build_cfg(instructions: tuple[IRInstruction, ...]) -> IRControlFlow:
    blocks: dict[str, IRBasicBlock] = {
        "exit": IRBasicBlock("exit", (), ()),
    }

    def lower_sequence(
        items: tuple[IRInstruction, ...],
        prefix: str,
        continuation: str,
    ) -> str:
        entry = continuation
        for index in range(len(items) - 1, -1, -1):
            instruction = items[index]
            path = f"{prefix}.{index}"
            block_id = "block/" + path
            if instruction.op == "if":
                then_entry = lower_sequence(
                    instruction.then_body,
                    path + ".then",
                    entry,
                )
                else_entry = lower_sequence(
                    instruction.else_body,
                    path + ".else",
                    entry,
                )
                successors = (then_entry, else_entry)
            else:
                successors = (entry,)
            blocks[block_id] = IRBasicBlock(
                id=block_id,
                instruction_paths=(path,),
                successors=successors,
            )
            entry = block_id
        return entry

    entry = lower_sequence(instructions, "root", "exit")
    return IRControlFlow(
        entry=entry,
        exit="exit",
        blocks=tuple(blocks[name] for name in sorted(blocks)),
    )


def _render_instructions(
    instructions: tuple[IRInstruction, ...],
    depth: int,
) -> list[str]:
    prefix = "  " * depth
    lines: list[str] = []
    for instruction in instructions:
        if instruction.op == "if":
            lines.append(
                f"{prefix}if {instruction.arguments[0]} : Bool {{"
            )
            lines.extend(_render_instructions(instruction.then_body, depth + 1))
            lines.append(f"{prefix}}}")
            if instruction.else_body:
                lines.append(f"{prefix}else {{")
                lines.extend(
                    _render_instructions(instruction.else_body, depth + 1)
                )
                lines.append(f"{prefix}}}")
            continue
        rendered_args = ", ".join(instruction.arguments)
        rendered_type = (
            f" : {instruction.type_name}"
            if instruction.type_name
            else ""
        )
        if instruction.result:
            lines.append(
                f"{prefix}%{instruction.result} = "
                f"{instruction.op} {rendered_args}{rendered_type}"
            )
        else:
            lines.append(
                f"{prefix}{instruction.op} {rendered_args}{rendered_type}"
            )
    return lines
