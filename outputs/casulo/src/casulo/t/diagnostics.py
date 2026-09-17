from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    file: str
    line: int
    column: int
    end_line: int
    end_column: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    span: SourceSpan
    severity: Severity = Severity.ERROR
    hint: str | None = None

    def render(self) -> str:
        location = f"{self.span.file}:{self.span.line}:{self.span.column}"
        rendered = f"{location}: {self.severity.value} {self.code}: {self.message}"
        if self.hint:
            rendered += f"\n  dica: {self.hint}"
        return rendered

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "span": self.span.to_dict(),
        }
        if self.hint:
            result["hint"] = self.hint
        return result


def span_for_line(
    file: str,
    line: int,
    column: int,
    text: str,
) -> SourceSpan:
    return SourceSpan(
        file=file,
        line=line,
        column=column,
        end_line=line,
        end_column=max(column, column + len(text)),
    )
