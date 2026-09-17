from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .analyzer import AnalysisResult, LarvaAnalyzer
from .ast import Program
from .diagnostics import Diagnostic
from .graph import MetamorfoseGraph, MetamorfoseGraphBuilder
from .ir import CrisalidaLowerer, IRProgram
from .lexer import EggLexer
from .parser import EggParser
from .symbols import SymbolTable


@dataclass(frozen=True, slots=True)
class CheckResult:
    program: Program
    diagnostics: tuple[Diagnostic, ...]
    analysis: AnalysisResult | None = None
    ir: IRProgram | None = None
    graph: MetamorfoseGraph | None = None

    @property
    def ok(self) -> bool:
        return not any(item.severity.value == "error" for item in self.diagnostics)

    @property
    def symbols(self) -> SymbolTable | None:
        return self.analysis.symbols if self.analysis is not None else None


def parse_source(source: str, file: str = "<memory>") -> CheckResult:
    lexed = EggLexer().lex(source, file=file)
    parsed = EggParser(lexed).parse()
    return CheckResult(parsed.program, parsed.diagnostics)


def parse_file(path: str | Path) -> CheckResult:
    source_path = Path(path).expanduser().resolve()
    return parse_source(
        source_path.read_text(encoding="utf-8"),
        file=str(source_path),
    )


def check_source(
    source: str,
    file: str = "<memory>",
    *,
    imported_types: frozenset[str] = frozenset(),
    imported_records: Mapping[str, Mapping[str, str]] | None = None,
) -> CheckResult:
    parsed = parse_source(source, file=file)
    semantic = LarvaAnalyzer().analyze(
        parsed.program,
        imported_types=imported_types,
        imported_records=imported_records,
    )
    diagnostics = tuple((*parsed.diagnostics, *semantic.diagnostics))
    has_errors = any(item.severity.value == "error" for item in diagnostics)
    ir = (
        None
        if has_errors
        else CrisalidaLowerer().lower(parsed.program, semantic)
    )
    graph = (
        MetamorfoseGraphBuilder().build(ir)
        if ir is not None
        else None
    )
    return CheckResult(
        program=parsed.program,
        diagnostics=diagnostics,
        analysis=semantic,
        ir=ir,
        graph=graph,
    )


def check_file(
    path: str | Path,
    *,
    imported_types: frozenset[str] = frozenset(),
    imported_records: Mapping[str, Mapping[str, str]] | None = None,
) -> CheckResult:
    source_path = Path(path).expanduser().resolve()
    return check_source(
        source_path.read_text(encoding="utf-8"),
        file=str(source_path),
        imported_types=imported_types,
        imported_records=imported_records,
    )
