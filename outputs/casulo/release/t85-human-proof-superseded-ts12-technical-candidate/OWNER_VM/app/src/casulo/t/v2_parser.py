from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .v2_ast import (
    V2Enum,
    V2Expression,
    V2Function,
    V2Member,
    V2Module,
    V2Record,
    V2Span,
    V2State,
    V2Statement,
    V2Type,
)


IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
MODULE = rf"{IDENT}(?:\.{IDENT})*"


@dataclass(frozen=True, slots=True)
class V2Diagnostic:
    code: str
    message: str
    span: V2Span


class V2ParseError(ValueError):
    def __init__(self, diagnostics: tuple[V2Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("programa T/2.0 inválido")


@dataclass(frozen=True, slots=True)
class _Line:
    indent: int
    text: str
    span: V2Span


def _lines(source: str, source_name: str) -> tuple[_Line, ...]:
    result: list[_Line] = []
    for number, raw in enumerate(source.splitlines(), 1):
        if "\t" in raw:
            raise V2ParseError((V2Diagnostic("T2001", "tab não é permitido", V2Span(source_name, number)),))
        stripped = raw.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        spaces = len(raw) - len(stripped)
        if spaces % 2:
            raise V2ParseError((V2Diagnostic("T2002", "indentação precisa usar múltiplos de dois", V2Span(source_name, number)),))
        result.append(_Line(spaces // 2, stripped.rstrip(), V2Span(source_name, number, spaces + 1)))
    return tuple(result)


def parse_type(text: str, span: V2Span) -> V2Type:
    text = text.strip()
    if re.fullmatch(IDENT, text):
        return V2Type(text)
    match = re.fullmatch(rf"(Option|Result|List|Map|Set)<(.+)>", text)
    if not match:
        raise V2ParseError((V2Diagnostic("T2003", f"tipo inválido: {text}", span),))
    name, raw = match.groups()
    parts = _split_generic(raw)
    if name in {"List", "Set"}:
        if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            raise V2ParseError((V2Diagnostic("T2004", f"{name} exige tipo e limite positivo", span),))
        return V2Type(name, (parse_type(parts[0], span),), int(parts[1]))
    if name == "Map":
        if len(parts) != 3 or not parts[2].isdigit() or int(parts[2]) <= 0:
            raise V2ParseError((V2Diagnostic("T2005", "Map exige chave, valor e limite", span),))
        return V2Type(name, (parse_type(parts[0], span), parse_type(parts[1], span)), int(parts[2]))
    expected = 1 if name == "Option" else 2
    if len(parts) != expected:
        raise V2ParseError((V2Diagnostic("T2006", f"aridade inválida para {name}", span),))
    return V2Type(name, tuple(parse_type(item, span) for item in parts))


def _split_generic(text: str) -> list[str]:
    depth = 0
    start = 0
    result: list[str] = []
    for index, char in enumerate(text):
        if char == "<": depth += 1
        elif char == ">": depth -= 1
        elif char == "," and depth == 0:
            result.append(text[start:index].strip()); start = index + 1
    result.append(text[start:].strip())
    return result


class V2Parser:
    def parse_path(self, path: str | Path) -> V2Module:
        source_path = Path(path)
        return self.parse(source_path.read_text(encoding="utf-8"), source_path.as_posix())

    def parse(self, source: str, source_name: str = "<memory>") -> V2Module:
        lines = _lines(source, source_name)
        if len(lines) < 3 or lines[0].text != "language T/2.0":
            span = lines[0].span if lines else V2Span(source_name, 1)
            raise V2ParseError((V2Diagnostic("T2000", "esperado language T/2.0", span),))
        module_match = re.fullmatch(rf"module\s+({MODULE})", lines[1].text)
        if not module_match:
            raise V2ParseError((V2Diagnostic("T2007", "module inválido", lines[1].span),))
        module_name = module_match.group(1)
        imports: list[str] = []
        capabilities: list[str] = []
        records: list[V2Record] = []
        enums: list[V2Enum] = []
        states: list[V2State] = []
        functions: list[V2Function] = []
        step_budget: int | None = None
        deadline_ms: int | None = None
        schema_version: int | None = None
        i = 2
        while i < len(lines):
            line = lines[i]
            if line.indent != 0:
                raise V2ParseError((V2Diagnostic("T2008", "declaração de topo indentada", line.span),))
            if match := re.fullmatch(rf"use\s+({MODULE})", line.text):
                imports.append(match.group(1)); i += 1; continue
            if match := re.fullmatch(rf"capability\s+({MODULE})", line.text):
                capabilities.append(match.group(1)); i += 1; continue
            if match := re.fullmatch(r"budget\s+steps\s+([0-9]+)", line.text):
                value = int(match.group(1))
                if value <= 0 or value > 10_000_000:
                    raise V2ParseError((V2Diagnostic("T2009", "budget fora do limite", line.span),))
                step_budget = value; i += 1; continue
            if match := re.fullmatch(r"budget\s+deadline_ms\s+([0-9]+)", line.text):
                value = int(match.group(1))
                if value <= 0 or value > 3_600_000:
                    raise V2ParseError((V2Diagnostic("T2020", "deadline fora do limite", line.span),))
                deadline_ms = value; i += 1; continue
            if match := re.fullmatch(r"schema\s+version\s+([0-9]+)", line.text):
                value = int(match.group(1))
                if value <= 0:
                    raise V2ParseError((V2Diagnostic("T2021", "schema version precisa ser positiva", line.span),))
                schema_version = value; i += 1; continue
            if match := re.fullmatch(rf"record\s+({IDENT})", line.text):
                children, i = self._children(lines, i)
                members: list[V2Member] = []
                for child in children:
                    member = re.fullmatch(rf"member\s+({IDENT})\s*:\s*(.+)", child.text)
                    if not member:
                        raise V2ParseError((V2Diagnostic("T2010", "member inválido", child.span),))
                    members.append(V2Member(member.group(1), parse_type(member.group(2), child.span), child.span))
                records.append(V2Record(match.group(1), tuple(members), line.span)); continue
            if match := re.fullmatch(rf"enum\s+({IDENT})", line.text):
                children, i = self._children(lines, i)
                cases: list[str] = []
                for child in children:
                    case = re.fullmatch(rf"case\s+({IDENT})", child.text)
                    if not case: raise V2ParseError((V2Diagnostic("T2011", "case inválido", child.span),))
                    cases.append(case.group(1))
                enums.append(V2Enum(match.group(1), tuple(cases), line.span)); continue
            if match := re.fullmatch(rf"state\s+({IDENT})\s*:\s*(.+?)\s*=\s*(.+)", line.text):
                states.append(V2State(match.group(1), parse_type(match.group(2), line.span), self._json(match.group(3), line.span), line.span)); i += 1; continue
            if match := re.fullmatch(rf"fn\s+({IDENT})\(({IDENT})\s*:\s*(.+)\)\s*->\s*(.+)", line.text):
                children, i = self._children(lines, i)
                effects: tuple[str, ...] = ()
                if children and (effect_match := re.fullmatch(r"effects\s+\[([^]]*)\]", children[0].text)):
                    effects = tuple(item.strip() for item in effect_match.group(1).split(",") if item.strip())
                    children = children[1:]
                body = self._statements(children, 1)
                functions.append(V2Function(match.group(1), match.group(2), parse_type(match.group(3), line.span), parse_type(match.group(4), line.span), effects, body, line.span)); continue
            raise V2ParseError((V2Diagnostic("T2012", f"declaração desconhecida: {line.text}", line.span),))
        if step_budget is None:
            raise V2ParseError((V2Diagnostic("T2013", "budget steps obrigatório", lines[1].span),))
        if deadline_ms is None:
            raise V2ParseError((V2Diagnostic("T2022", "budget deadline_ms obrigatório", lines[1].span),))
        if schema_version is None:
            raise V2ParseError((V2Diagnostic("T2023", "schema version obrigatório", lines[1].span),))
        return V2Module(module_name, tuple(imports), tuple(capabilities), step_budget, deadline_ms, schema_version, tuple(records), tuple(enums), tuple(states), tuple(functions), source_name)

    @staticmethod
    def _children(lines: tuple[_Line, ...], index: int) -> tuple[list[_Line], int]:
        parent = lines[index]
        i = index + 1; result: list[_Line] = []
        while i < len(lines) and lines[i].indent > parent.indent:
            result.append(lines[i]); i += 1
        if not result: raise V2ParseError((V2Diagnostic("T2014", "bloco vazio", parent.span),))
        return result, i

    def _statements(self, lines: list[_Line], indent: int) -> tuple[V2Statement, ...]:
        result: list[V2Statement] = []; i = 0
        while i < len(lines):
            line = lines[i]
            if line.indent != indent:
                raise V2ParseError((V2Diagnostic("T2015", "indentação de statement inválida", line.span),))
            text = line.text
            if match := re.fullmatch(r"requires\s+(.+)\s+else\s+(.+)", text):
                result.append(V2Statement("require", (V2Expression(match.group(1), line.span), self._json(match.group(2), line.span)), span=line.span)); i += 1; continue
            if match := re.fullmatch(r"ensures\s+(.+)\s+else\s+(.+)", text):
                result.append(V2Statement("ensure", (V2Expression(match.group(1), line.span), self._json(match.group(2), line.span)), span=line.span)); i += 1; continue
            if match := re.fullmatch(rf"let\s+({IDENT})\s*=\s*(.+)", text):
                result.append(V2Statement("let", (match.group(1), V2Expression(match.group(2), line.span)), span=line.span)); i += 1; continue
            if match := re.fullmatch(rf"set\s+state\.({IDENT})\s*=\s*(.+)", text):
                result.append(V2Statement("set_state", (match.group(1), V2Expression(match.group(2), line.span)), span=line.span)); i += 1; continue
            if match := re.fullmatch(r"request\s+effect\s+([A-Za-z0-9_.]+)", text):
                result.append(V2Statement("request_effect", (match.group(1),), span=line.span)); i += 1; continue
            if match := re.fullmatch(r"emit\s+event\s+(.+)", text):
                result.append(V2Statement("emit_event", (V2Expression(match.group(1), line.span),), span=line.span)); i += 1; continue
            if match := re.fullmatch(r"cancel\s+if\s+(.+)", text):
                result.append(V2Statement("cancel_if", (V2Expression(match.group(1), line.span),), span=line.span)); i += 1; continue
            if match := re.fullmatch(rf"spawn\s+job\s+({IDENT})\s+using\s+(.+)\s+limit\s+([0-9]+)", text):
                limit = int(match.group(3))
                if limit <= 0: raise V2ParseError((V2Diagnostic("T2024", "job limit precisa ser positivo", line.span),))
                result.append(V2Statement("spawn_job", (match.group(1), V2Expression(match.group(2), line.span), limit), span=line.span)); i += 1; continue
            if match := re.fullmatch(rf"join\s+job\s+({IDENT})", text):
                result.append(V2Statement("join_job", (match.group(1),), span=line.span)); i += 1; continue
            if match := re.fullmatch(r"return\s+(ok|error)\s+(.+)", text):
                result.append(V2Statement(f"return_{match.group(1)}", (V2Expression(match.group(2), line.span),), span=line.span)); i += 1; continue
            if match := re.fullmatch(r"if\s+(.+)", text):
                body_lines, next_i = self._nested_slice(lines, i)
                otherwise: tuple[V2Statement, ...] = ()
                if next_i < len(lines) and lines[next_i].indent == indent and lines[next_i].text == "else":
                    else_lines, final_i = self._nested_slice(lines, next_i)
                    otherwise = self._statements(else_lines, indent + 1); next_i = final_i
                result.append(V2Statement("if", (V2Expression(match.group(1), line.span),), self._statements(body_lines, indent + 1), otherwise, line.span)); i = next_i; continue
            if match := re.fullmatch(rf"for\s+({IDENT})\s+in\s+(.+)\s+limit\s+([0-9]+)", text):
                limit = int(match.group(3))
                if limit <= 0: raise V2ParseError((V2Diagnostic("T2016", "loop limit precisa ser positivo", line.span),))
                body_lines, i = self._nested_slice(lines, i)
                result.append(V2Statement("for", (match.group(1), V2Expression(match.group(2), line.span), limit), self._statements(body_lines, indent + 1), span=line.span)); continue
            if match := re.fullmatch(r"match\s+(.+)", text):
                match_lines, i = self._nested_slice(lines, i)
                cases: list[V2Statement] = []
                j = 0
                while j < len(match_lines):
                    case_line = match_lines[j]
                    case_match = re.fullmatch(rf"case\s+({IDENT}|_)", case_line.text)
                    if case_line.indent != indent + 1 or not case_match:
                        raise V2ParseError((V2Diagnostic("T2025", "match exige cases", case_line.span),))
                    case_body, next_j = self._nested_slice(match_lines, j)
                    cases.append(V2Statement("case", (case_match.group(1),), self._statements(case_body, indent + 2), span=case_line.span))
                    j = next_j
                result.append(V2Statement("match", (V2Expression(match.group(1), line.span),), tuple(cases), span=line.span)); continue
            raise V2ParseError((V2Diagnostic("T2017", f"statement desconhecido: {text}", line.span),))
        return tuple(result)

    @staticmethod
    def _nested_slice(lines: list[_Line], index: int) -> tuple[list[_Line], int]:
        parent = lines[index]; i = index + 1; result: list[_Line] = []
        while i < len(lines) and lines[i].indent > parent.indent:
            result.append(lines[i]); i += 1
        if not result: raise V2ParseError((V2Diagnostic("T2018", "bloco de controle vazio", parent.span),))
        return result, i

    @staticmethod
    def _json(text: str, span: V2Span) -> Any:
        try: return json.loads(text)
        except json.JSONDecodeError as exc: raise V2ParseError((V2Diagnostic("T2019", "literal precisa ser JSON", span),)) from exc
