from __future__ import annotations

import re
from dataclasses import dataclass

from .ast import (
    BindStmt,
    CapabilityDecl,
    CondenseDecl,
    Declaration,
    EmitStmt,
    EnumCaseDecl,
    EnumDecl,
    Expression,
    FieldDecl,
    IfStmt,
    JudgeStmt,
    LanguageDecl,
    LearnDecl,
    LearnProperty,
    LetStmt,
    ModuleDecl,
    Program,
    ProjectStmt,
    RecordDecl,
    RestrictStmt,
    StabilizeStmt,
    Statement,
    TraceDecl,
    TransitionDecl,
    TypeRef,
    UseDecl,
)
from .diagnostics import Diagnostic, SourceSpan
from .expression_ast import ExpressionSyntaxError, parse_expression
from .lexer import INDENT_WIDTH, LexResult, EggLine


NAME = r"[A-Za-z_][A-Za-z0-9_]*"
QUALIFIED_NAME = rf"{NAME}(?:\.{NAME})*"
TYPE_NAME = NAME


@dataclass(frozen=True, slots=True)
class ParseResult:
    program: Program
    diagnostics: tuple[Diagnostic, ...]


class EggParser:
    def __init__(self, lexed: LexResult) -> None:
        self.lines = lexed.lines
        self.diagnostics = list(lexed.diagnostics)
        self.index = 0

    def parse(self) -> ParseResult:
        language: LanguageDecl | None = None
        module: ModuleDecl | None = None
        uses: list[UseDecl] = []
        capabilities: list[CapabilityDecl] = []
        declarations: list[Declaration] = []

        while self._current() is not None:
            line = self._current()
            assert line is not None
            if line.indent != 0:
                self._error(
                    line,
                    "T2001",
                    "declaração de topo precisa começar na coluna 1",
                )
                self.index += 1
                continue

            if line.text.startswith("language "):
                parsed = self._parse_language(line)
                if language is not None:
                    self._error(line, "T2091", "apenas uma versão T pode ser declarada")
                elif module is not None or uses or capabilities or declarations:
                    self._error(
                        line,
                        "T2092",
                        "language precisa ser a primeira declaração do arquivo",
                    )
                else:
                    language = parsed
                self.index += 1
                continue

            if line.text.startswith("module "):
                parsed = self._parse_module(line)
                if module is not None:
                    self._error(line, "T2002", "apenas um módulo pode ser declarado")
                elif declarations or uses or capabilities:
                    self._error(
                        line,
                        "T2003",
                        "a declaração de módulo precisa ser a primeira do arquivo",
                    )
                else:
                    module = parsed
                self.index += 1
                continue

            if line.text.startswith("use "):
                if declarations:
                    self._error(
                        line,
                        "T2004",
                        "declarações use precisam anteceder fields e operações",
                    )
                uses.append(self._parse_use(line))
                self.index += 1
                continue

            if line.text.startswith("capability "):
                if declarations:
                    self._error(
                        line,
                        "T2094",
                        "capabilities precisam anteceder fields e operações",
                    )
                capabilities.append(self._parse_capability(line))
                self.index += 1
                continue

            if line.text.startswith("field "):
                declarations.append(self._parse_field(line))
                continue

            if line.text.startswith("record "):
                declarations.append(self._parse_record(line))
                continue

            if line.text.startswith("enum "):
                declarations.append(self._parse_enum(line))
                continue

            if line.text.startswith("condense "):
                declarations.append(self._parse_condense(line))
                continue

            if line.text.startswith("transition "):
                declarations.append(self._parse_transition(line))
                continue

            if line.text.startswith("learn "):
                declarations.append(self._parse_learn(line))
                continue

            self._error(
                line,
                "T2005",
                f"declaração de topo desconhecida: {line.text.split()[0]!r}",
            )
            self.index += 1

        program_span = _program_span(self.lines)
        return ParseResult(
            Program(
                module=module,
                language=language,
                uses=tuple(uses),
                capabilities=tuple(capabilities),
                declarations=tuple(declarations),
                span=program_span,
            ),
            tuple(self.diagnostics),
        )

    def _parse_language(self, line: EggLine) -> LanguageDecl:
        match = re.fullmatch(r"language\s+T/(1\.0|1\.1)", line.text)
        if match is None:
            self._error(
                line,
                "T2090",
                "versão inválida; esperado: language T/1.0 ou language T/1.1",
            )
            version = "<invalid>"
        else:
            version = f"T/{match.group(1)}"
        return LanguageDecl(version=version, span=line.span)

    def _parse_module(self, line: EggLine) -> ModuleDecl:
        match = re.fullmatch(rf"module\s+({QUALIFIED_NAME})", line.text)
        if match is None:
            self._error(
                line,
                "T2010",
                "módulo inválido; esperado: module nome.qualificado",
            )
            name = "<invalid>"
        else:
            name = match.group(1)
        return ModuleDecl(name=name, span=line.span)

    def _parse_use(self, line: EggLine) -> UseDecl:
        match = re.fullmatch(rf"use\s+({QUALIFIED_NAME})", line.text)
        if match is None:
            self._error(
                line,
                "T2011",
                "importação inválida; esperado: use nome.qualificado",
            )
            name = "<invalid>"
        else:
            name = match.group(1)
        return UseDecl(name=name, span=line.span)

    def _parse_capability(self, line: EggLine) -> CapabilityDecl:
        match = re.fullmatch(rf"capability\s+({QUALIFIED_NAME})", line.text)
        if match is None:
            self._error(
                line,
                "T2093",
                "capability inválida; esperado: capability namespace.ação",
            )
            name = "<invalid>"
        else:
            name = match.group(1)
        return CapabilityDecl(name=name, span=line.span)

    def _parse_field(self, header: EggLine) -> FieldDecl:
        match = re.fullmatch(rf"field\s+({TYPE_NAME})", header.text)
        if match is None:
            self._error(header, "T2020", "field inválido; esperado: field Nome")
            name = "<invalid>"
        else:
            name = match.group(1)
        self.index += 1

        traces: list[TraceDecl] = []
        expected_indent = header.indent + INDENT_WIDTH
        while (line := self._current()) is not None and line.indent > header.indent:
            if line.indent != expected_indent:
                self._error(
                    line,
                    "T2021",
                    f"trace deve possuir indentação de {expected_indent} espaços",
                )
                self.index += 1
                continue
            trace_match = re.fullmatch(rf"trace\s+({NAME})\s*:\s*(.+)", line.text)
            if trace_match is None:
                self._error(
                    line,
                    "T2022",
                    "somente trace nome: Tipo é permitido dentro de field",
                )
                self.index += 1
                continue
            type_ref = self._parse_type(trace_match.group(2).strip(), line)
            traces.append(
                TraceDecl(
                    name=trace_match.group(1),
                    type_ref=type_ref,
                    span=line.span,
                )
            )
            self.index += 1

        if not traces:
            self._error(header, "T2023", "field precisa declarar ao menos um trace")
        return FieldDecl(name=name, traces=tuple(traces), span=header.span)

    def _parse_record(self, header: EggLine) -> RecordDecl:
        match = re.fullmatch(rf"record\s+({TYPE_NAME})", header.text)
        if match is None:
            self._error(header, "T3111", "record inválido; esperado: record Nome")
            name = "<invalid>"
        else:
            name = match.group(1)
        self.index += 1
        traces = self._parse_trace_block(header, "record", "T3111")
        return RecordDecl(name=name, traces=tuple(traces), span=header.span)

    def _parse_enum(self, header: EggLine) -> EnumDecl:
        match = re.fullmatch(rf"enum\s+({TYPE_NAME})", header.text)
        if match is None:
            self._error(header, "T3112", "enum inválido; esperado: enum Nome")
            name = "<invalid>"
        else:
            name = match.group(1)
        self.index += 1
        cases: list[EnumCaseDecl] = []
        expected_indent = header.indent + INDENT_WIDTH
        while (line := self._current()) is not None and line.indent > header.indent:
            case_match = re.fullmatch(rf"case\s+({NAME})", line.text)
            if line.indent != expected_indent or case_match is None:
                self._error(line, "T3112", "esperado: case Nome dentro de enum")
            else:
                cases.append(EnumCaseDecl(case_match.group(1), line.span))
            self.index += 1
        if not cases:
            self._error(header, "T3112", "enum precisa declarar ao menos um case")
        return EnumDecl(name=name, cases=tuple(cases), span=header.span)

    def _parse_trace_block(
        self,
        header: EggLine,
        owner: str,
        code: str,
    ) -> list[TraceDecl]:
        traces: list[TraceDecl] = []
        expected_indent = header.indent + INDENT_WIDTH
        while (line := self._current()) is not None and line.indent > header.indent:
            match = re.fullmatch(rf"trace\s+({NAME})\s*:\s*(.+)", line.text)
            if line.indent != expected_indent or match is None:
                self._error(line, code, f"esperado: trace nome: Tipo dentro de {owner}")
            else:
                traces.append(
                    TraceDecl(
                        name=match.group(1),
                        type_ref=self._parse_type(match.group(2), line),
                        span=line.span,
                    )
                )
            self.index += 1
        if not traces:
            self._error(header, code, f"{owner} precisa declarar ao menos um trace")
        return traces

    def _parse_condense(self, header: EggLine) -> CondenseDecl:
        match = re.fullmatch(
            rf"condense\s+({TYPE_NAME})(?:\s+in\s+({TYPE_NAME}))?",
            header.text,
        )
        if match is None:
            self._error(
                header,
                "T2030",
                "condense inválido; esperado: condense Nome [in Tipo]",
            )
            name, input_type = "<invalid>", None
        else:
            name, input_type = match.group(1), match.group(2)
        self.index += 1
        effects = self._parse_effects_header(header)
        body = self._parse_statement_block(header.indent + INDENT_WIDTH, header)
        return CondenseDecl(
            name=name,
            input_type=input_type,
            effects=effects,
            body=tuple(body),
            span=header.span,
        )

    def _parse_transition(self, header: EggLine) -> TransitionDecl:
        match = re.fullmatch(rf"transition\s+({TYPE_NAME})", header.text)
        if match is None:
            self._error(
                header,
                "T2040",
                "transition inválida; esperado: transition Nome",
            )
            name = "<invalid>"
        else:
            name = match.group(1)
        self.index += 1
        expected_indent = header.indent + INDENT_WIDTH
        from_type = self._consume_transition_type("from", expected_indent, header)
        to_type = self._consume_transition_type("to", expected_indent, header)
        effects = self._parse_effects_header(header)
        body = self._parse_statement_block(expected_indent, header)
        return TransitionDecl(
            name=name,
            from_type=from_type,
            to_type=to_type,
            effects=effects,
            body=tuple(body),
            span=header.span,
        )

    def _parse_learn(self, header: EggLine) -> LearnDecl:
        match = re.fullmatch(rf"learn\s+({QUALIFIED_NAME})", header.text)
        if match is None:
            self._error(header, "T2080", "learn inválido; esperado: learn Nome")
            name = "<invalid>"
        else:
            name = match.group(1)
        self.index += 1

        properties: list[LearnProperty] = []
        expected_indent = header.indent + INDENT_WIDTH
        while (line := self._current()) is not None and line.indent > header.indent:
            if line.indent != expected_indent:
                self._error(
                    line,
                    "T2081",
                    f"propriedade learn deve possuir {expected_indent} espaços",
                )
                self.index += 1
                continue
            property_match = re.fullmatch(rf"({NAME})\s+(.+)", line.text)
            if property_match is None:
                self._error(
                    line,
                    "T2082",
                    "esperado: propriedade valor dentro de learn",
                )
                self.index += 1
                continue
            properties.append(
                LearnProperty(
                    name=property_match.group(1),
                    value=self._expression(property_match.group(2).strip(), line),
                    span=line.span,
                )
            )
            self.index += 1

        if not properties:
            self._error(header, "T2083", "learn precisa declarar propriedades")
        return LearnDecl(name=name, properties=tuple(properties), span=header.span)

    def _parse_effects_header(self, owner: EggLine) -> tuple[str, ...]:
        line = self._current()
        expected_indent = owner.indent + INDENT_WIDTH
        if (
            line is None
            or line.indent != expected_indent
            or not line.text.startswith("effects")
        ):
            return ()
        self.index += 1
        match = re.fullmatch(r"effects\s+\[([^]]*)\]", line.text)
        if match is None:
            self._error(
                line,
                "T2095",
                "effects inválidos; esperado: effects [memory.read, manifest]",
            )
            return ("<invalid>",)
        values = tuple(item.strip() for item in match.group(1).split(",") if item.strip())
        if not values or any(re.fullmatch(QUALIFIED_NAME, item) is None for item in values):
            self._error(line, "T2095", "effects exige uma lista de nomes válidos")
            return ("<invalid>",)
        return values

    def _consume_transition_type(
        self,
        keyword: str,
        expected_indent: int,
        header: EggLine,
    ) -> str:
        line = self._current()
        if line is None or line.indent <= header.indent:
            self._error(
                header,
                "T2041",
                f"transition precisa declarar {keyword} Tipo",
            )
            return "<missing>"
        match = re.fullmatch(rf"{keyword}\s+({TYPE_NAME})", line.text)
        if line.indent != expected_indent or match is None:
            self._error(
                line,
                "T2042",
                f"esperado {keyword} Tipo com {expected_indent} espaços",
            )
            self.index += 1
            return "<invalid>"
        self.index += 1
        return match.group(1)

    def _parse_statement_block(
        self,
        expected_indent: int,
        owner: EggLine,
    ) -> list[Statement]:
        body: list[Statement] = []
        while (line := self._current()) is not None and line.indent >= expected_indent:
            if line.indent > expected_indent:
                self._error(
                    line,
                    "T2050",
                    "indentação inesperada; não existe bloco aberto neste ponto",
                )
                self.index += 1
                continue
            if line.text == "else" or line.text.startswith("else "):
                break
            statement = self._parse_statement(line, expected_indent)
            if statement is not None:
                body.append(statement)
        if not body:
            self._error(owner, "T2051", "bloco precisa conter ao menos uma instrução")
        return body

    def _parse_statement(
        self,
        line: EggLine,
        expected_indent: int,
    ) -> Statement | None:
        if line.text.startswith("let "):
            match = re.fullmatch(rf"let\s+({NAME})\s*=\s*(.+)", line.text)
            self.index += 1
            if match is None:
                self._error(line, "T2060", "esperado: let nome = expressão")
                return None
            return LetStmt(
                name=match.group(1),
                value=self._expression(match.group(2), line),
                span=line.span,
            )

        simple = (
            ("judge", JudgeStmt, "condition"),
            ("restrict", RestrictStmt, "condition"),
            ("stabilize", StabilizeStmt, "target"),
            ("emit", EmitStmt, "value"),
        )
        for keyword, node_type, argument in simple:
            if line.text == keyword or line.text.startswith(keyword + " "):
                self.index += 1
                value = line.text[len(keyword) :].strip()
                if not value:
                    self._error(
                        line,
                        "T2061",
                        f"{keyword} exige uma expressão",
                    )
                expression = self._expression(value, line)
                return node_type(**{argument: expression, "span": line.span})

        if line.text == "project" or line.text.startswith("project "):
            self.index += 1
            body = line.text[len("project") :].strip()
            source_text = body
            target: str | None = None
            into: tuple[str, ...] = ()
            if " into " in body:
                source_text, into_text = body.split(" into ", 1)
                names = [item.strip() for item in into_text.split(",")]
                if not names or any(not re.fullmatch(NAME, item) for item in names):
                    self._error(
                        line,
                        "T2064",
                        "project into exige uma lista de nomes",
                    )
                else:
                    into = tuple(names)
            elif " as " in body:
                source_text, target_text = body.split(" as ", 1)
                target_text = target_text.strip()
                if not re.fullmatch(TYPE_NAME, target_text):
                    self._error(
                        line,
                        "T2065",
                        "project as exige um nome de tipo",
                    )
                else:
                    target = target_text
            if not source_text.strip():
                self._error(line, "T2061", "project exige uma expressão")
            return ProjectStmt(
                source=self._expression(source_text.strip(), line),
                target=target,
                into=into,
                span=line.span,
            )

        if line.text == "bind" or line.text.startswith("bind "):
            self.index += 1
            body = line.text[len("bind") :].strip()
            if " with " not in body:
                self._error(
                    line,
                    "T2066",
                    "bind exige: bind expressão with expressão",
                )
                left_text, right_text = body, ""
            else:
                left_text, right_text = body.split(" with ", 1)
            return BindStmt(
                left=self._expression(left_text.strip(), line),
                right=self._expression(right_text.strip(), line),
                span=line.span,
            )

        if line.text == "if" or line.text.startswith("if "):
            condition_text = line.text[2:].strip()
            if not condition_text:
                self._error(line, "T2062", "if exige uma condição")
            condition = self._expression(condition_text, line)
            self.index += 1
            then_body = self._parse_statement_block(
                expected_indent + INDENT_WIDTH,
                line,
            )
            else_body: list[Statement] = []
            current = self._current()
            if (
                current is not None
                and current.indent == expected_indent
                and current.text == "else"
            ):
                self.index += 1
                else_body = self._parse_statement_block(
                    expected_indent + INDENT_WIDTH,
                    current,
                )
            return IfStmt(
                condition=condition,
                then_body=tuple(then_body),
                else_body=tuple(else_body),
                span=line.span,
            )

        self._error(
            line,
            "T2063",
            f"instrução desconhecida: {line.text.split()[0]!r}",
        )
        self.index += 1
        return None

    def _parse_type(self, raw: str, line: EggLine) -> TypeRef:
        value = raw.strip()
        optional = value.endswith("?")
        if optional:
            value = value[:-1].strip()
        list_depth = 0
        while value.startswith("[") and value.endswith("]"):
            value = value[1:-1].strip()
            list_depth += 1
        arguments: tuple[TypeRef, ...] = ()
        generic = re.fullmatch(rf"({TYPE_NAME})\[(.+)\]", value)
        if generic is not None and generic.group(1) == "Result":
            parts = tuple(item.strip() for item in generic.group(2).split(","))
            if len(parts) != 2 or any(not part for part in parts):
                self._error(line, "T3113", "Result exige Result[Ok, Error]")
            else:
                arguments = tuple(self._parse_type(part, line) for part in parts)
            value = "Result"
        if not re.fullmatch(TYPE_NAME, value):
            self._error(
                line,
                "T2070",
                f"tipo inválido: {raw!r}",
            )
            value = "<invalid>"
        return TypeRef(
            name=value,
            optional=optional,
            list_depth=list_depth,
            span=line.span,
            arguments=arguments,
        )

    def _expression(self, text: str, line: EggLine) -> Expression:
        try:
            root = parse_expression(text)
        except ExpressionSyntaxError as exc:
            return Expression(
                text=text,
                span=line.span,
                syntax_error=str(exc),
            )
        return Expression(text=text, span=line.span, root=root)

    def _current(self) -> EggLine | None:
        if self.index >= len(self.lines):
            return None
        return self.lines[self.index]

    def _error(
        self,
        line: EggLine,
        code: str,
        message: str,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(code=code, message=message, span=line.span)
        )


def _program_span(lines: tuple[EggLine, ...]) -> SourceSpan | None:
    if not lines:
        return None
    first, last = lines[0].span, lines[-1].span
    return SourceSpan(
        file=first.file,
        line=first.line,
        column=first.column,
        end_line=last.end_line,
        end_column=last.end_column,
    )
