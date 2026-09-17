from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .ast import (
    BindStmt,
    CondenseDecl,
    Declaration,
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
from .diagnostics import Diagnostic
from .effects import KNOWN_CAPABILITY_EFFECTS, T_VNEXT_LANGUAGE, derived_effects
from .learn import LearnContractError, LearnSemanticContract, validate_learn_contract
from .symbols import Scope, Symbol, SymbolKind, SymbolTable
from .typesys import (
    ANY,
    BOOL,
    SemanticType,
    TypeEngine,
    compatible,
    unify_types,
)


PRIMITIVE_TYPES = frozenset(
    {"Text", "Number", "Bool", "Time", "Date", "Duration", "Any"}
)


@dataclass(slots=True)
class AnalysisResult:
    diagnostics: tuple[Diagnostic, ...]
    symbols: SymbolTable
    operation_outputs: dict[str, SemanticType] = field(default_factory=dict)
    expression_types: dict[str, SemanticType] = field(default_factory=dict)
    learn_contracts: dict[str, LearnSemanticContract] = field(default_factory=dict)
    operation_effects: dict[str, tuple[str, ...]] = field(default_factory=dict)


class LarvaAnalyzer:
    """Resolve símbolos, infere tipos e prova emissão estrutural."""

    def __init__(self) -> None:
        self.type_engine = TypeEngine()

    def analyze(
        self,
        program: Program,
        *,
        imported_types: frozenset[str] = frozenset(),
        imported_records: Mapping[str, Mapping[str, str]] | None = None,
    ) -> AnalysisResult:
        diagnostics: list[Diagnostic] = []
        symbols = SymbolTable()
        declared: dict[str, Declaration] = {}
        expression_types: dict[str, SemanticType] = {}
        operation_outputs: dict[str, SemanticType] = {}
        learn_contracts: dict[str, LearnSemanticContract] = {}
        operation_effects: dict[str, tuple[str, ...]] = {}
        linked_records = imported_records or {}

        language = (
            program.language.version if program.language is not None else "T/1.0"
        )
        if program.language is not None:
            symbols.add(
                symbols.root,
                Symbol(
                    name=program.language.version,
                    qualified_name=program.language.version,
                    kind=SymbolKind.LANGUAGE,
                    type_name=None,
                    scope="<root>",
                    span=program.language.span,
                ),
            )

        if program.module is not None:
            symbols.add(
                symbols.root,
                Symbol(
                    name=program.module.name,
                    qualified_name=program.module.name,
                    kind=SymbolKind.MODULE,
                    type_name=None,
                    scope="<root>",
                    span=program.module.span,
                ),
            )
        for use in program.uses:
            symbols.add(
                symbols.root,
                Symbol(
                    name=use.name,
                    qualified_name=use.name,
                    kind=SymbolKind.USE,
                    type_name=None,
                    scope="<root>",
                    span=use.span,
                ),
            )

        capability_names: set[str] = set()
        for capability in program.capabilities:
            if language != T_VNEXT_LANGUAGE:
                diagnostics.append(
                    Diagnostic(
                        code="T3104",
                        message="capability exige language T/1.1",
                        span=capability.span,
                    )
                )
            if capability.name not in KNOWN_CAPABILITY_EFFECTS:
                diagnostics.append(
                    Diagnostic(
                        code="T3101",
                        message=f"capability desconhecida: {capability.name}",
                        span=capability.span,
                    )
                )
            elif capability.name in capability_names:
                diagnostics.append(
                    Diagnostic(
                        code="T3101",
                        message=f"capability duplicada: {capability.name}",
                        span=capability.span,
                    )
                )
            capability_names.add(capability.name)
            symbols.add(
                symbols.root,
                Symbol(
                    name=capability.name,
                    qualified_name=capability.name,
                    kind=SymbolKind.CAPABILITY,
                    type_name="Capability",
                    scope="<root>",
                    span=capability.span,
                ),
            )

        for declaration in program.declarations:
            if declaration.name in declared:
                diagnostics.append(
                    Diagnostic(
                        code="T3001",
                        message=f"declaração duplicada: {declaration.name}",
                        span=declaration.span,
                    )
                )
            else:
                declared[declaration.name] = declaration
                symbols.add(
                    symbols.root,
                    _declaration_symbol(declaration),
                )

        fields = {
            declaration.name: declaration
            for declaration in program.declarations
            if isinstance(declaration, (FieldDecl, RecordDecl))
        }
        enums = {
            declaration.name: declaration
            for declaration in program.declarations
            if isinstance(declaration, EnumDecl)
        }
        known_types = (
            PRIMITIVE_TYPES
            | fields.keys()
            | enums.keys()
            | {"Result"}
            | imported_types
        )

        for declaration in program.declarations:
            if isinstance(declaration, (RecordDecl, EnumDecl)) and language != T_VNEXT_LANGUAGE:
                diagnostics.append(
                    Diagnostic(
                        code="T3110",
                        message=f"{type(declaration).__name__[:-4].lower()} exige language T/1.1",
                        span=declaration.span,
                    )
                )
            if isinstance(declaration, (FieldDecl, RecordDecl)):
                self._check_field(
                    declaration,
                    known_types,
                    symbols,
                    diagnostics,
                )
            elif isinstance(declaration, EnumDecl):
                self._check_enum(declaration, symbols, diagnostics)

        for declaration in program.declarations:
            if isinstance(declaration, CondenseDecl):
                operation_effects[declaration.name] = self._check_effect_contract(
                    declaration,
                    language,
                    capability_names,
                    diagnostics,
                )
                input_field = None
                if declaration.input_type is not None:
                    input_field = fields.get(declaration.input_type)
                    if (
                        input_field is None
                        and declaration.input_type not in linked_records
                    ):
                        diagnostics.append(
                            Diagnostic(
                                code="T3002",
                                message=(
                                    f"tipo de entrada desconhecido: "
                                    f"{declaration.input_type}"
                                ),
                                span=declaration.span,
                            )
                        )
                output = self._check_operation(
                    declaration,
                    input_field,
                    known_types,
                    symbols,
                    diagnostics,
                    expression_types,
                    linked_records.get(declaration.input_type or ""),
                )
                operation_outputs[declaration.name] = output
            elif isinstance(declaration, LearnDecl):
                if language == T_VNEXT_LANGUAGE:
                    diagnostics.append(
                        Diagnostic(
                            code="T3104",
                            message="learn legado não é elegível para T/1.1",
                            span=declaration.span,
                        )
                    )
                contract = self._check_learn(
                    declaration,
                    program.module.name if program.module is not None else None,
                    symbols,
                    diagnostics,
                )
                if contract is not None:
                    learn_contracts[declaration.name] = contract
            elif isinstance(declaration, TransitionDecl):
                operation_effects[declaration.name] = self._check_effect_contract(
                    declaration,
                    language,
                    capability_names,
                    diagnostics,
                )
                input_field = fields.get(declaration.from_type)
                for role, type_name in (
                    ("from", declaration.from_type),
                    ("to", declaration.to_type),
                ):
                    if (
                        type_name not in fields
                        and type_name not in imported_types
                    ):
                        diagnostics.append(
                            Diagnostic(
                                code="T3003",
                                message=f"tipo {role} desconhecido: {type_name}",
                                span=declaration.span,
                            )
                        )
                output = self._check_operation(
                    declaration,
                    input_field,
                    known_types,
                    symbols,
                    diagnostics,
                    expression_types,
                    linked_records.get(declaration.from_type),
                )
                operation_outputs[declaration.name] = output

        if not program.declarations and program.span is not None:
            diagnostics.append(
                Diagnostic(
                    code="T3004",
                    message="programa não declara field, condense ou transition",
                    span=program.span,
                )
            )

        return AnalysisResult(
            diagnostics=tuple(diagnostics),
            symbols=symbols,
            operation_outputs=operation_outputs,
            expression_types=expression_types,
            learn_contracts=learn_contracts,
            operation_effects=operation_effects,
        )

    @staticmethod
    def _check_effect_contract(
        declaration: CondenseDecl | TransitionDecl,
        language: str,
        capabilities: set[str],
        diagnostics: list[Diagnostic],
    ) -> tuple[str, ...]:
        declared = tuple(dict.fromkeys(declaration.effects))
        required = derived_effects(declaration.body)
        if language != T_VNEXT_LANGUAGE:
            if declared:
                diagnostics.append(
                    Diagnostic(
                        code="T3104",
                        message="effects exige language T/1.1",
                        span=declaration.span,
                    )
                )
            return ()
        for effect in declared:
            if effect not in KNOWN_CAPABILITY_EFFECTS:
                diagnostics.append(
                    Diagnostic(
                        code="T3101",
                        message=f"effect desconhecido: {effect}",
                        span=declaration.span,
                    )
                )
        missing = tuple(effect for effect in required if effect not in declared)
        if missing:
            diagnostics.append(
                Diagnostic(
                    code="T3100",
                    message="effects não declarados: " + ", ".join(missing),
                    span=declaration.span,
                )
            )
        for effect in declared:
            if effect in KNOWN_CAPABILITY_EFFECTS and effect not in capabilities:
                diagnostics.append(
                    Diagnostic(
                        code="T3104",
                        message=f"capability ausente para effect: {effect}",
                        span=declaration.span,
                    )
                )
        return declared

    def _check_learn(
        self,
        declaration: LearnDecl,
        module: str | None,
        symbols: SymbolTable,
        diagnostics: list[Diagnostic],
    ) -> LearnSemanticContract | None:
        learn_scope = symbols.root.child(f"learn:{declaration.name}")
        values: dict[str, str] = {}
        for property_decl in declaration.properties:
            if property_decl.name in values:
                diagnostics.append(
                    Diagnostic(
                        code="T3041",
                        message=(f"propriedade learn duplicada: {property_decl.name}"),
                        span=property_decl.span,
                    )
                )
                continue
            values[property_decl.name] = property_decl.value.text
            symbols.add(
                learn_scope,
                Symbol(
                    name=property_decl.name,
                    qualified_name=(f"{declaration.name}.{property_decl.name}"),
                    kind=SymbolKind.PROPERTY,
                    type_name=_learn_property_type(property_decl.name),
                    scope=learn_scope.name,
                    span=property_decl.span,
                ),
            )
        try:
            return validate_learn_contract(
                module=module,
                name=declaration.name,
                values=values,
            )
        except LearnContractError as error:
            diagnostics.append(
                Diagnostic(
                    code="T3040",
                    message=str(error),
                    span=declaration.span,
                )
            )
            return None

    def _check_field(
        self,
        declaration: FieldDecl | RecordDecl,
        known_types: set[str] | frozenset[str],
        symbols: SymbolTable,
        diagnostics: list[Diagnostic],
    ) -> None:
        field_scope = symbols.root.child(f"field:{declaration.name}")
        names: set[str] = set()
        for trace in declaration.traces:
            if trace.name in names:
                diagnostics.append(
                    Diagnostic(
                        code="T3010",
                        message=(
                            f"trace duplicado em {declaration.name}: "
                            f"{trace.name}"
                        ),
                        span=trace.span,
                    )
                )
            names.add(trace.name)
            if trace.type_ref.name not in known_types:
                diagnostics.append(
                    Diagnostic(
                        code="T3011",
                        message=f"tipo desconhecido: {trace.type_ref.name}",
                        span=trace.span,
                    )
                )
            if trace.type_ref.name == "Result" and len(trace.type_ref.arguments) != 2:
                diagnostics.append(
                    Diagnostic(
                        code="T3113",
                        message="Result exige exatamente dois tipos",
                        span=trace.span,
                    )
                )
            for argument in trace.type_ref.arguments:
                if argument.name not in known_types:
                    diagnostics.append(
                        Diagnostic(
                            code="T3113",
                            message=f"tipo Result desconhecido: {argument.name}",
                            span=trace.span,
                        )
                    )
            symbols.add(
                field_scope,
                Symbol(
                    name=trace.name,
                    qualified_name=f"{declaration.name}.{trace.name}",
                    kind=SymbolKind.TRACE,
                    type_name=SemanticType.from_ref(trace.type_ref).render(),
                    scope=field_scope.name,
                    span=trace.span,
                ),
            )

    @staticmethod
    def _check_enum(
        declaration: EnumDecl,
        symbols: SymbolTable,
        diagnostics: list[Diagnostic],
    ) -> None:
        enum_scope = symbols.root.child(f"enum:{declaration.name}")
        seen: set[str] = set()
        for case in declaration.cases:
            if case.name in seen:
                diagnostics.append(
                    Diagnostic(
                        code="T3112",
                        message=f"case duplicado em {declaration.name}: {case.name}",
                        span=case.span,
                    )
                )
            seen.add(case.name)
            symbols.add(
                enum_scope,
                Symbol(
                    name=case.name,
                    qualified_name=f"{declaration.name}.{case.name}",
                    kind=SymbolKind.ENUM_CASE,
                    type_name=declaration.name,
                    scope=enum_scope.name,
                    span=case.span,
                ),
            )

    def _check_operation(
        self,
        declaration: CondenseDecl | TransitionDecl,
        input_field: FieldDecl | RecordDecl | None,
        known_types: set[str] | frozenset[str],
        symbols: SymbolTable,
        diagnostics: list[Diagnostic],
        expression_types: dict[str, SemanticType],
        imported_input: Mapping[str, str] | None = None,
    ) -> SemanticType:
        operation_scope = symbols.root.child(f"operation:{declaration.name}")
        if input_field is not None:
            for trace in input_field.traces:
                symbols.add(
                    operation_scope,
                    Symbol(
                        name=trace.name,
                        qualified_name=f"{declaration.name}.{trace.name}",
                        kind=SymbolKind.TRACE,
                        type_name=SemanticType.from_ref(trace.type_ref).render(),
                        scope=operation_scope.name,
                        span=trace.span,
                    ),
                )
        elif imported_input is not None:
            for name, type_name in imported_input.items():
                symbols.add(
                    operation_scope,
                    Symbol(
                        name=name,
                        qualified_name=f"{declaration.name}.{name}",
                        kind=SymbolKind.TRACE,
                        type_name=type_name,
                        scope=operation_scope.name,
                        span=declaration.span,
                    ),
                )

        emit_types: list[SemanticType] = []
        self._check_block(
            declaration.body,
            operation_scope,
            declaration.name,
            known_types,
            symbols,
            diagnostics,
            expression_types,
            emit_types,
        )

        if not _guarantees_emit(declaration.body):
            diagnostics.append(
                Diagnostic(
                    code="T3020",
                    message=f"{declaration.name} não emite em todos os caminhos",
                    span=declaration.span,
                    hint="adicione emit após a decisão ou em ambos os ramos",
                )
            )

        if not emit_types:
            return ANY
        first_output = emit_types[0]
        if any(
            not (
                compatible(first_output, item)
                and compatible(item, first_output)
            )
            for item in emit_types[1:]
        ):
            diagnostics.append(
                Diagnostic(
                    code="T3034",
                    message=(
                        f"{declaration.name} emite tipos incompatíveis: "
                        + ", ".join(sorted({item.render() for item in emit_types}))
                    ),
                    span=declaration.span,
                )
            )
            return ANY
        return unify_types(emit_types)

    def _check_block(
        self,
        body: tuple[Statement, ...],
        scope: Scope,
        operation_name: str,
        known_types: set[str] | frozenset[str],
        symbols: SymbolTable,
        diagnostics: list[Diagnostic],
        expression_types: dict[str, SemanticType],
        emit_types: list[SemanticType],
    ) -> None:
        for statement in body:
            if isinstance(statement, LetStmt):
                inferred = self._infer(
                    statement.value,
                    scope,
                    diagnostics,
                    expression_types,
                )
                if scope.resolve(statement.name) is not None:
                    diagnostics.append(
                        Diagnostic(
                            code="T3031",
                            message=f"nome já definido no escopo: {statement.name}",
                            span=statement.span,
                        )
                    )
                else:
                    symbols.add(
                        scope,
                        Symbol(
                            name=statement.name,
                            qualified_name=f"{operation_name}.{statement.name}",
                            kind=SymbolKind.LOCAL,
                            type_name=inferred.render(),
                            scope=scope.name,
                            span=statement.span,
                        ),
                    )
                continue

            if isinstance(statement, (JudgeStmt, RestrictStmt)):
                condition = self._infer(
                    statement.condition,
                    scope,
                    diagnostics,
                    expression_types,
                )
                self._require_bool(
                    condition,
                    statement.condition,
                    diagnostics,
                )
                continue

            if isinstance(statement, StabilizeStmt):
                self._infer(
                    statement.target,
                    scope,
                    diagnostics,
                    expression_types,
                )
                continue

            if isinstance(statement, EmitStmt):
                emit_types.append(
                    self._infer(
                        statement.value,
                        scope,
                        diagnostics,
                        expression_types,
                    )
                )
                continue

            if isinstance(statement, ProjectStmt):
                self._infer(
                    statement.source,
                    scope,
                    diagnostics,
                    expression_types,
                )
                if statement.target and statement.target not in known_types:
                    diagnostics.append(
                        Diagnostic(
                            code="T3039",
                            message=(
                                f"tipo de projeção desconhecido: "
                                f"{statement.target}"
                            ),
                            span=statement.span,
                        )
                    )
                continue

            if isinstance(statement, BindStmt):
                self._infer(
                    statement.left,
                    scope,
                    diagnostics,
                    expression_types,
                )
                self._infer(
                    statement.right,
                    scope,
                    diagnostics,
                    expression_types,
                )
                continue

            if isinstance(statement, IfStmt):
                condition = self._infer(
                    statement.condition,
                    scope,
                    diagnostics,
                    expression_types,
                )
                self._require_bool(
                    condition,
                    statement.condition,
                    diagnostics,
                )
                then_scope = scope.child(
                    f"{scope.name}/if:{statement.span.line}:then"
                )
                self._check_block(
                    statement.then_body,
                    then_scope,
                    operation_name,
                    known_types,
                    symbols,
                    diagnostics,
                    expression_types,
                    emit_types,
                )
                if statement.else_body:
                    else_scope = scope.child(
                        f"{scope.name}/if:{statement.span.line}:else"
                    )
                    self._check_block(
                        statement.else_body,
                        else_scope,
                        operation_name,
                        known_types,
                        symbols,
                        diagnostics,
                        expression_types,
                        emit_types,
                    )

    def _infer(
        self,
        expression,
        scope: Scope,
        diagnostics: list[Diagnostic],
        expression_types: dict[str, SemanticType],
    ) -> SemanticType:
        result = self.type_engine.infer(expression, scope)
        diagnostics.extend(result.diagnostics)
        expression_types[expression_key(expression)] = result.type
        return result.type

    @staticmethod
    def _require_bool(
        actual: SemanticType,
        expression,
        diagnostics: list[Diagnostic],
    ) -> None:
        if compatible(actual, BOOL):
            return
        diagnostics.append(
            Diagnostic(
                code="T3032",
                message=(
                    f"condição precisa ser Bool, recebido {actual.render()}"
                ),
                span=expression.span,
            )
        )


def _declaration_symbol(declaration: Declaration) -> Symbol:
    if isinstance(declaration, FieldDecl):
        kind = SymbolKind.FIELD
        type_name = declaration.name
    elif isinstance(declaration, RecordDecl):
        kind = SymbolKind.RECORD
        type_name = declaration.name
    elif isinstance(declaration, EnumDecl):
        kind = SymbolKind.ENUM
        type_name = declaration.name
    elif isinstance(declaration, CondenseDecl):
        kind = SymbolKind.CONDENSE
        type_name = declaration.input_type
    elif isinstance(declaration, TransitionDecl):
        kind = SymbolKind.TRANSITION
        type_name = f"{declaration.from_type}->{declaration.to_type}"
    else:
        kind = SymbolKind.LEARN
        type_name = "TrainingProgram"
    return Symbol(
        name=declaration.name,
        qualified_name=declaration.name,
        kind=kind,
        type_name=type_name,
        scope="<root>",
        span=declaration.span,
    )


def _learn_property_type(name: str) -> str:
    if name in {
        "input_features",
        "hidden_features",
        "output_features",
        "epochs",
        "seed",
    }:
        return "Integer"
    if name in {"learning_rate", "target_loss"}:
        return "Number"
    return "Text"


def _guarantees_emit(body: tuple[Statement, ...]) -> bool:
    for statement in body:
        if isinstance(statement, EmitStmt):
            return True
        if (
            isinstance(statement, IfStmt)
            and statement.else_body
            and _guarantees_emit(statement.then_body)
            and _guarantees_emit(statement.else_body)
        ):
            return True
    return False


def expression_key(expression) -> str:
    return (
        f"{expression.span.file}:{expression.span.line}:"
        f"{expression.span.column}:{expression.text}"
    )
