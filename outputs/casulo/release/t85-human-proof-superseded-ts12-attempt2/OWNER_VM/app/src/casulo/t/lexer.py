from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import Diagnostic, SourceSpan, span_for_line


INDENT_WIDTH = 2


@dataclass(frozen=True, slots=True)
class EggLine:
    indent: int
    text: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LexResult:
    lines: tuple[EggLine, ...]
    diagnostics: tuple[Diagnostic, ...]


class EggLexer:
    """Lexer de linhas: preserva indentação e remove comentários com segurança."""

    def lex(self, source: str, file: str = "<memory>") -> LexResult:
        lines: list[EggLine] = []
        diagnostics: list[Diagnostic] = []

        for number, raw in enumerate(source.splitlines(), start=1):
            if "\t" in raw[: len(raw) - len(raw.lstrip(" \t"))]:
                diagnostics.append(
                    Diagnostic(
                        code="T1001",
                        message="tabulação não é permitida na indentação",
                        span=span_for_line(file, number, 1, raw),
                        hint="use dois espaços por nível",
                    )
                )
                continue

            indentation = len(raw) - len(raw.lstrip(" "))
            content = _strip_inline_comment(raw[indentation:]).rstrip()
            if not content.strip():
                continue

            if indentation % INDENT_WIDTH != 0:
                diagnostics.append(
                    Diagnostic(
                        code="T1002",
                        message=(
                            f"indentação de {indentation} espaços não é múltipla "
                            f"de {INDENT_WIDTH}"
                        ),
                        span=span_for_line(file, number, 1, raw[:indentation]),
                        hint="use exatamente dois espaços por nível",
                    )
                )

            stripped = content.lstrip()
            extra = len(content) - len(stripped)
            column = indentation + extra + 1
            lines.append(
                EggLine(
                    indent=indentation,
                    text=stripped,
                    span=span_for_line(file, number, column, stripped),
                )
            )

        return LexResult(tuple(lines), tuple(diagnostics))


def _strip_inline_comment(text: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "#":
            return text[:index]
    return text
