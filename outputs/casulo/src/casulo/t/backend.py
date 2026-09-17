from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .expression_ast import (
    BinaryNode,
    BooleanNode,
    CallNode,
    CompareNode,
    ConditionalNode,
    ExpressionNode,
    ExpressionSyntaxError,
    ListNode,
    LiteralNode,
    NameNode,
    UnaryNode,
    parse_expression,
)
from .ir import IRInstruction, IROperation, IRProgram


BACKEND_VERSION = "python-reference/0.4.1"
STRUCTURAL_KEY_PROTOCOL = "casulo-structural-key/0.1"
TYPED_BUFFER_PROTOCOL = "casulo-typed-buffer/0.1"


class BackendError(ValueError):
    """A CrisálidaIR contém algo que este backend não consegue materializar."""


@dataclass(frozen=True, slots=True)
class GeneratedModule:
    backend: str
    source: str


class PythonBackend:
    """Materializa CrisálidaIR como um módulo Python autocontido."""

    def generate(
        self,
        program: IRProgram,
        artifact_id: str,
    ) -> GeneratedModule:
        schemas = {
            field.name: {
                trace.name: trace.type_name
                for trace in field.traces
            }
            for field in program.fields
        }
        schemas.update(
            {
                record.name: {
                    trace.name: trace.type_name
                    for trace in record.traces
                }
                for record in program.records
            }
        )
        operation_schemas = {
            operation.name: {
                "kind": operation.kind,
                "input_type": operation.input_type,
                "target_type": operation.target_type,
                "output_type": operation.output_type,
            }
            for operation in program.operations
        }
        lines = [
            '"""Artefato gerado pelo compilador T da Teloscorp / Casulo."""',
            "",
            "from __future__ import annotations",
            "",
            "import json",
            "import math",
            "import sys",
            "from array import array",
            "from collections.abc import Mapping",
            "",
            f"ARTIFACT_ID = {_python_literal(artifact_id)}",
            f"BACKEND_VERSION = {_python_literal(BACKEND_VERSION)}",
            f"KEY_PROTOCOL = {_python_literal(STRUCTURAL_KEY_PROTOCOL)}",
            f"BUFFER_PROTOCOL = {_python_literal(TYPED_BUFFER_PROTOCOL)}",
            f"MODULE = {_python_literal(program.module)}",
            f"FIELD_SCHEMAS = {_python_literal(schemas)}",
            f"OPERATION_SCHEMAS = {_python_literal(operation_schemas)}",
            "",
            "",
            "class CasuloRuntimeError(ValueError):",
            "    pass",
            "",
            "",
            "class CasuloInputError(CasuloRuntimeError):",
            "    pass",
            "",
            "",
            "class CasuloJudgeFailed(CasuloRuntimeError):",
            "    pass",
            "",
            "",
            "class CasuloRestrictionFailed(CasuloRuntimeError):",
            "    pass",
            "",
            "",
            "def _type_parts(type_name):",
            "    optional = type_name.endswith('?')",
            "    if optional:",
            "        type_name = type_name[:-1]",
            "    depth = 0",
            "    while type_name.startswith('[') and type_name.endswith(']'):",
            "        type_name = type_name[1:-1]",
            "        depth += 1",
            "    return type_name, optional, depth",
            "",
            "",
            "def _validate_value(value, type_name, path):",
            "    base, optional, depth = _type_parts(type_name)",
            "    if value is None:",
            "        if optional or base == 'Any':",
            "            return",
            "        raise CasuloInputError(f'{path}: valor obrigatório ausente')",
            "    if depth:",
            "        if not isinstance(value, list):",
            "            raise CasuloInputError(f'{path}: esperado {type_name}')",
            "        nested = '[' * (depth - 1) + base + ']' * (depth - 1)",
            "        for index, item in enumerate(value):",
            "            _validate_value(item, nested, f'{path}[{index}]')",
            "        return",
            "    valid = {",
            "        'Any': lambda item: True,",
            "        'Bool': lambda item: isinstance(item, bool),",
            "        'Number': lambda item: isinstance(item, (int, float))",
            "        and not isinstance(item, bool),",
            "        'Text': lambda item: isinstance(item, str),",
            "        'Time': lambda item: isinstance(item, str),",
            "        'Date': lambda item: isinstance(item, str),",
            "        'Duration': lambda item: (",
            "            isinstance(item, (int, float, str))",
            "            and not isinstance(item, bool)",
            "        ),",
            "    }",
            "    if base in FIELD_SCHEMAS:",
            "        _validate_mapping(value, FIELD_SCHEMAS[base], path)",
            "        return",
            "    predicate = valid.get(base)",
            "    if predicate is None or not predicate(value):",
            "        raise CasuloInputError(f'{path}: esperado {type_name}')",
            "",
            "",
            "def _validate_mapping(value, schema, path):",
            "    if not isinstance(value, Mapping):",
            "        raise CasuloInputError(f'{path}: esperado objeto JSON')",
            "    for name, type_name in schema.items():",
            "        _, optional, _ = _type_parts(type_name)",
            "        if name not in value:",
            "            if optional:",
            "                continue",
            "            raise CasuloInputError(f'{path}.{name}: campo obrigatório ausente')",
            "        _validate_value(value[name], type_name, f'{path}.{name}')",
            "",
            "",
            "def _prepare_input(payload, input_type):",
            "    if payload is None:",
            "        payload = {}",
            "    if not isinstance(payload, Mapping):",
            "        raise CasuloInputError('entrada precisa ser um objeto JSON')",
            "    preserved = dict(payload)",
            "    if input_type is not None:",
            "        schema = FIELD_SCHEMAS.get(input_type)",
            "        if schema is None:",
            "            raise CasuloInputError(f'tipo de entrada desconhecido: {input_type}')",
            "        _validate_mapping(preserved, schema, input_type)",
            "    return preserved",
            "",
            "",
            "def _new_evidence():",
            "    return {",
            "        'judgements': [],",
            "        'restrictions': [],",
            "        'projections': [],",
            "        'bindings': [],",
            "        'stabilized': [],",
            "    }",
            "",
            "",
            "def _emit(operation, original_input, result, state, evidence):",
            "    return {",
            "        'artifact_id': ARTIFACT_ID,",
            "        'module': MODULE,",
            "        'operation': operation,",
            "        'state': state,",
            "        'input': original_input,",
            "        'result': result,",
            "        'evidence': evidence,",
            "    }",
            "",
        ]

        operation_functions: list[tuple[str, str, str, str, str | None]] = []
        for index, operation in enumerate(program.operations):
            function_name = f"_operation_{index}"
            batch_function_name = f"_batch_operation_{index}"
            key_function_name = f"_key_operation_{index}"
            buffer_function_name = (
                f"_buffer_operation_{index}"
                if self._supports_typed_buffer(operation, schemas)
                else None
            )
            operation_functions.append(
                (
                    operation.name,
                    function_name,
                    batch_function_name,
                    key_function_name,
                    buffer_function_name,
                )
            )
            lines.extend(
                self._render_operation(operation, function_name, schemas)
            )
            lines.extend(
                self._render_batch_operation(
                    operation,
                    batch_function_name,
                    schemas,
                )
            )
            lines.extend(
                self._render_key_operation(
                    operation,
                    key_function_name,
                    schemas,
                )
            )
            if buffer_function_name is not None:
                lines.extend(
                    self._render_buffer_operation(
                        operation,
                        buffer_function_name,
                        schemas,
                    )
                )

        lines.extend(
            [
                "OPERATIONS = {",
                *[
                    f"    {_python_literal(name)}: {function_name},"
                    for name, function_name, _, _, _ in operation_functions
                ],
                "}",
                "",
                "BATCH_OPERATIONS = {",
                *[
                    f"    {_python_literal(name)}: {batch_function_name},"
                    for name, _, batch_function_name, _, _ in operation_functions
                ],
                "}",
                "",
                "OPERATION_KEYS = {",
                *[
                    f"    {_python_literal(name)}: {key_function_name},"
                    for name, _, _, key_function_name, _ in operation_functions
                ],
                "}",
                "",
                "BUFFER_OPERATIONS = {",
                *[
                    f"    {_python_literal(name)}: {buffer_function_name},"
                    for name, _, _, _, buffer_function_name in operation_functions
                    if buffer_function_name is not None
                ],
                "}",
                "",
                "OPERATION_CACHE = {name: {} for name in OPERATIONS}",
                "",
                "",
                "def _structural_key(value):",
                "    if value is None:",
                "        return (0,)",
                "    if isinstance(value, bool):",
                "        return (1, value)",
                "    if isinstance(value, int):",
                "        return (2, value)",
                "    if isinstance(value, float):",
                "        if not math.isfinite(value):",
                "            raise CasuloInputError(",
                "                'NaN e infinito não podem formar chave estrutural'",
                "            )",
                "        negative_zero = value == 0.0 and math.copysign(1.0, value) < 0",
                "        return (3, value, negative_zero)",
                "    if isinstance(value, str):",
                "        return (4, value)",
                "    if isinstance(value, (list, tuple)):",
                "        return (5, tuple(_structural_key(item) for item in value))",
                "    if isinstance(value, Mapping):",
                "        if not all(isinstance(key, str) for key in value):",
                "            raise CasuloInputError(",
                "                'objetos de entrada exigem chaves textuais'",
                "            )",
                "        return (",
                "            6,",
                "            frozenset(",
                "                (key, _structural_key(item))",
                "                for key, item in value.items()",
                "            ),",
                "        )",
                "    raise CasuloInputError(",
                "        'tipo não suportado na chave estrutural: '",
                "        + type(value).__name__",
                "    )",
                "",
                "",
                "def _cache_fingerprint(structural_key):",
                "    return hash(structural_key) & 0xffffffffffffffff",
                "",
                "",
                "def _cache_token(structural_key):",
                "    return f'local:{_cache_fingerprint(structural_key):016x}'",
                "",
                "",
                "def _clone_json(value):",
                "    if isinstance(value, dict):",
                "        return {key: _clone_json(item) for key, item in value.items()}",
                "    if isinstance(value, list):",
                "        return [_clone_json(item) for item in value]",
                "    if isinstance(value, tuple):",
                "        return tuple(_clone_json(item) for item in value)",
                "    return value",
                "",
                "",
                "def _cache_envelope(result, enabled, hit, key, scope=None):",
                "    manifested = _clone_json(result)",
                "    manifested['cache'] = {",
                "        'enabled': enabled,",
                "        'hit': hit,",
                "        'key': key,",
                "        'key_protocol': KEY_PROTOCOL if enabled else None,",
                "        'scope': scope if enabled else None,",
                "        'collision_verified': enabled,",
                "    }",
                "    return manifested",
                "",
                "",
                "def clear_cache(operation=None):",
                "    if operation is None:",
                "        for cache in OPERATION_CACHE.values():",
                "            cache.clear()",
                "        return",
                "    if operation not in OPERATION_CACHE:",
                "        raise CasuloRuntimeError(f'operação desconhecida: {operation}')",
                "    OPERATION_CACHE[operation].clear()",
                "",
                "",
                "def cache_stats():",
                "    return {",
                "        name: {'entries': len(cache)}",
                "        for name, cache in OPERATION_CACHE.items()",
                "    }",
                "",
                "",
                "def execute(operation, payload=None, use_cache=True):",
                "    function = OPERATIONS.get(operation)",
                "    if function is None:",
                "        available = ', '.join(sorted(OPERATIONS))",
                "        raise CasuloRuntimeError(",
                "            f'operação desconhecida: {operation}; disponíveis: {available}'",
                "        )",
                "    key_function = OPERATION_KEYS[operation]",
                "    if not use_cache:",
                "        return _cache_envelope(function(payload), False, False, None)",
                "    key = key_function(payload)",
                "    token = _cache_token(key)",
                "    cache = OPERATION_CACHE[operation]",
                "    if key in cache:",
                "        return _cache_envelope(",
                "            cache[key], True, True, token, 'process'",
                "        )",
                "    result = function(payload)",
                "    cache[key] = _clone_json(result)",
                "    return _cache_envelope(result, True, False, token, 'process')",
                "",
                "",
                (
                    "def execute_batch("
                    "operation, payloads, use_cache=True, use_buffer=True"
                    "):"
                ),
                "    function = BATCH_OPERATIONS.get(operation)",
                "    if function is None:",
                "        available = ', '.join(sorted(BATCH_OPERATIONS))",
                "        raise CasuloRuntimeError(",
                "            f'operação desconhecida: {operation}; disponíveis: {available}'",
                "        )",
                "    key_function = OPERATION_KEYS[operation]",
                "    if not isinstance(payloads, list):",
                "        raise CasuloInputError('lote precisa ser uma lista JSON')",
                "    buffer_function = BUFFER_OPERATIONS.get(operation)",
                "    if use_cache and use_buffer and buffer_function is not None:",
                "        buffered = buffer_function(payloads, key_function)",
                "        if buffered is not None:",
                "            items, misses, buffer_metrics = buffered",
                "            return {",
                "                'artifact_id': ARTIFACT_ID,",
                "                'module': MODULE,",
                "                'operation': operation,",
                "                'count': len(items),",
                "                'cache': {",
                "                    'enabled': True,",
                "                    'hits': len(items) - misses,",
                "                    'misses': misses,",
                "                    'entries': misses,",
                "                    'key_protocol': KEY_PROTOCOL,",
                "                    'scope': 'batch',",
                "                    'collision_verified': True,",
                "                    'buffer_protocol': BUFFER_PROTOCOL,",
                "                    'representation': 'columnar-typed',",
                "                    'evidence_layout': 'lateral',",
                "                    'hot_path': buffer_metrics,",
                "                },",
                "                'items': items,",
                "            }",
                "    if not use_cache:",
                "        items = [",
                "            _cache_envelope(item, False, False, None)",
                "            for item in function(payloads)",
                "        ]",
                "        return {",
                "            'artifact_id': ARTIFACT_ID,",
                "            'module': MODULE,",
                "            'operation': operation,",
                "            'count': len(items),",
                "            'cache': {",
                "                'enabled': False,",
                "                'hits': 0,",
                "                'misses': len(items),",
                "                'entries': len(OPERATION_CACHE[operation]),",
                "                'key_protocol': None,",
                "                'scope': None,",
                "                'collision_verified': False,",
                "                'buffer_protocol': None,",
                "                'representation': 'objects',",
                "                'evidence_layout': 'inline',",
                "                'hot_path': None,",
                "            },",
                "            'items': items,",
                "        }",
                "    cache = {}",
                "    slots = [None] * len(payloads)",
                "    pending = {}",
                "    unique_payloads = []",
                "    unique_keys = []",
                "    unique_tokens = []",
                "    for index, payload in enumerate(payloads):",
                "        key = key_function(payload)",
                "        if key in pending:",
                "            pending[key].append(index)",
                "        else:",
                "            pending[key] = [index]",
                "            unique_keys.append(key)",
                "            unique_tokens.append(_cache_token(key))",
                "            unique_payloads.append(payload)",
                "    computed = function(unique_payloads)",
                "    for key, token, base in zip(",
                "        unique_keys, unique_tokens, computed",
                "    ):",
                "        cache[key] = base",
                "        indexes = pending[key]",
                "        slots[indexes[0]] = _cache_envelope(",
                "            base, True, False, token, 'batch'",
                "        )",
                "        for index in indexes[1:]:",
                "            slots[index] = _cache_envelope(",
                "                base, True, True, token, 'batch'",
                "            )",
                "    misses = len(unique_payloads)",
                "    return {",
                "        'artifact_id': ARTIFACT_ID,",
                "        'module': MODULE,",
                "        'operation': operation,",
                "        'count': len(slots),",
                "        'cache': {",
                "            'enabled': True,",
                "            'hits': len(slots) - misses,",
                "            'misses': misses,",
                "            'entries': len(cache),",
                "            'key_protocol': KEY_PROTOCOL,",
                "            'scope': 'batch',",
                "            'collision_verified': True,",
                "            'buffer_protocol': None,",
                "            'representation': 'objects',",
                "            'evidence_layout': 'inline',",
                "            'hot_path': None,",
                "        },",
                "        'items': slots,",
                "    }",
                "",
                "",
                "def main(argv=None):",
                "    args = list(sys.argv[1:] if argv is None else argv)",
                "    if not 1 <= len(args) <= 2:",
                "        print(",
                "            'uso: python casulo_artifact.py OPERATION [INPUT.json|-]',",
                "            file=sys.stderr,",
                "        )",
                "        return 2",
                "    operation = args[0]",
                "    input_path = args[1] if len(args) == 2 else None",
                "    try:",
                "        if input_path == '-':",
                "            payload = json.load(sys.stdin)",
                "        elif input_path is None:",
                "            payload = {}",
                "        else:",
                "            with open(input_path, encoding='utf-8') as stream:",
                "                payload = json.load(stream)",
                "    except (OSError, UnicodeError, json.JSONDecodeError) as exc:",
                "        print(f'entrada inválida: {exc}', file=sys.stderr)",
                "        return 2",
                "    try:",
                "        result = (",
                "            execute_batch(operation, payload)",
                "            if isinstance(payload, list)",
                "            else execute(operation, payload)",
                "        )",
                "    except CasuloRuntimeError as exc:",
                "        print(f'execução bloqueada: {exc}', file=sys.stderr)",
                "        return 3",
                "    json.dump(",
                "        result,",
                "        sys.stdout,",
                "        ensure_ascii=False,",
                "        indent=2,",
                "        sort_keys=True,",
                "    )",
                "    sys.stdout.write('\\n')",
                "    return 0",
                "",
                "",
                "if __name__ == '__main__':",
                "    raise SystemExit(main())",
                "",
            ]
        )
        return GeneratedModule(
            backend=BACKEND_VERSION,
            source="\n".join(lines),
        )

    @staticmethod
    def _supports_typed_buffer(
        operation: IROperation,
        schemas: dict[str, dict[str, str]],
    ) -> bool:
        schema = schemas.get(operation.input_type or "")
        if (
            not schema
            or operation.output_type != "Number"
            or any(type_name != "Number" for type_name in schema.values())
        ):
            return False
        allowed = {"let", "judge", "restrict", "stabilize", "emit"}
        return (
            bool(operation.instructions)
            and operation.instructions[-1].op == "emit"
            and sum(
                instruction.op == "emit"
                for instruction in operation.instructions
            )
            == 1
            and all(
                instruction.op in allowed
                and not instruction.then_body
                and not instruction.else_body
                for instruction in operation.instructions
            )
        )

    def _render_buffer_operation(
        self,
        operation: IROperation,
        function_name: str,
        schemas: dict[str, dict[str, str]],
    ) -> list[str]:
        schema = schemas[operation.input_type or ""]
        fields = tuple(schema)
        judgements = tuple(
            instruction
            for instruction in operation.instructions
            if instruction.op == "judge"
        )
        restrictions = tuple(
            instruction
            for instruction in operation.instructions
            if instruction.op == "restrict"
        )
        stabilized = tuple(
            instruction
            for instruction in operation.instructions
            if instruction.op == "stabilize"
        )
        names = {
            name: f"_column_value_{index}"
            for index, name in enumerate(fields)
        }
        lines = [
            "",
            f"def {function_name}(payloads, key_function):",
            "    _count = len(payloads)",
            "    if not _count:",
            "        return [], 0, {",
            "            'records': 0,",
            "            'unique_records': 0,",
            "            'column_bytes': 0,",
            "            'column_type': None,",
            "            'index_bytes': 0,",
            "            'evidence_flag_bytes': 0,",
            "            'lateral_value_cells': 0,",
            "            'reference_intermediate_mappings_avoided': 0,",
            "            'reference_intermediate_lists_avoided': 0,",
            "            'reference_field_writes_avoided': 0,",
            "        }",
            "    _missing = object()",
            "    _slot_buffer = array('I', [0]) * _count",
            "    _hit_buffer = bytearray(_count)",
            "    _key_to_slot = {}",
            "    _keys = []",
            "    _columns = None",
            "    _column_type_mask = None",
            "    for _record_index, _payload in enumerate(payloads):",
            "        _key = key_function(_payload)",
            "        if not (",
            "            type(_key) is tuple",
            "            and len(_key) == 4",
            "            and _key[0] == 7",
            "        ):",
            "            return None",
            (
                "        if _key[1] not in "
                f"(0, {(1 << len(fields)) - 1}):"
            ),
            "            return None",
            "        if _columns is None:",
            "            _column_type_mask = _key[1]",
            (
                "            _column_code = "
                f"'q' if _column_type_mask == {(1 << len(fields)) - 1} "
                "else 'd'"
            ),
            "            _columns = (",
            *["                array(_column_code)," for _ in fields],
            "            )",
            "        elif _key[1] != _column_type_mask:",
            "            return None",
            "        _unique_index = _key_to_slot.get(_key, _missing)",
            "        if _unique_index is _missing:",
            "            _unique_index = len(_keys)",
            "            _key_to_slot[_key] = _unique_index",
            "            _keys.append(_key)",
            "            _values = _key[3]",
            "            if _column_type_mask and not all(",
            "                -(1 << 63) <= _value < (1 << 63)",
            "                for _value in _values",
            "            ):",
            "                return None",
            *[
                f"            _columns[{index}].append(_values[{index}])"
                for index in range(len(fields))
            ],
            "        else:",
            "            _hit_buffer[_record_index] = 1",
            "        _slot_buffer[_record_index] = _unique_index",
            "    _unique_count = len(_keys)",
            "    _result_buffer = [None] * _unique_count",
            "    _state_buffer = bytearray(_unique_count)",
            (
                "    _judgement_buffers = "
                + _python_literal(tuple(0 for _ in judgements))
            ),
        ]
        if judgements:
            lines[-1] = (
                "    _judgement_buffers = ("
                + ", ".join("bytearray(_unique_count)" for _ in judgements)
                + ("," if len(judgements) == 1 else "")
                + ")"
            )
        lines.append(
            "    _restriction_buffers = "
            + (
                "("
                + ", ".join(
                    "bytearray(_unique_count)"
                    for _ in restrictions
                )
                + ("," if len(restrictions) == 1 else "")
                + ")"
                if restrictions
                else "()"
            )
        )
        lines.append(
            "    _stabilized_buffers = "
            + (
                "("
                + ", ".join(
                    "[None] * _unique_count"
                    for _ in stabilized
                )
                + ("," if len(stabilized) == 1 else "")
                + ")"
                if stabilized
                else "()"
            )
        )
        lines.extend(
            [
                "    for _buffer_index in range(_unique_count):",
                *[
                    (
                        f"        _column_value_{index} = "
                        f"_columns[{index}][_buffer_index]"
                    )
                    for index in range(len(fields))
                ],
            ]
        )
        let_index = 0
        judgement_index = 0
        restriction_index = 0
        stabilized_index = 0
        for instruction in operation.instructions:
            expression = _render_expression(
                instruction.arguments[0],
                names,
            )
            if instruction.op == "let":
                local_name = f"_local_value_{let_index}"
                let_index += 1
                lines.append(f"        {local_name} = {expression}")
                if instruction.result is not None:
                    names[instruction.result] = local_name
                continue
            if instruction.op in {"judge", "restrict"}:
                if instruction.op == "judge":
                    evidence_index = judgement_index
                    judgement_index += 1
                    buffer_name = "_judgement_buffers"
                    exception = "CasuloJudgeFailed"
                else:
                    evidence_index = restriction_index
                    restriction_index += 1
                    buffer_name = "_restriction_buffers"
                    exception = "CasuloRestrictionFailed"
                condition_name = (
                    f"_condition_{instruction.op}_{evidence_index}"
                )
                message = (
                    f"{instruction.op} falhou em "
                    f"{operation.name}: {instruction.arguments[0]}"
                )
                lines.extend(
                    [
                        f"        {condition_name} = bool({expression})",
                        f"        if not {condition_name}:",
                        (
                            f"            raise {exception}("
                            f"{_python_literal(message)})"
                        ),
                        (
                            f"        {buffer_name}[{evidence_index}]"
                            "[_buffer_index] = 1"
                        ),
                    ]
                )
                continue
            if instruction.op == "stabilize":
                value_name = f"_stabilized_value_{stabilized_index}"
                lines.extend(
                    [
                        f"        {value_name} = {expression}",
                        (
                            f"        _stabilized_buffers[{stabilized_index}]"
                            f"[_buffer_index] = {value_name}"
                        ),
                        "        _state_buffer[_buffer_index] = 1",
                    ]
                )
                stabilized_index += 1
                continue
            if instruction.op == "emit":
                lines.append(
                    f"        _result_buffer[_buffer_index] = {expression}"
                )
                continue
            raise BackendError(
                f"instrução incompatível com buffer tipado: {instruction.op}"
            )
        judgement_manifest = ", ".join(
            (
                "{'expression': "
                + _python_literal(instruction.arguments[0])
                + ", 'passed': bool(_judgement_buffers["
                + str(index)
                + "][_unique_index])}"
            )
            for index, instruction in enumerate(judgements)
        )
        restriction_manifest = ", ".join(
            (
                "{'expression': "
                + _python_literal(instruction.arguments[0])
                + ", 'passed': bool(_restriction_buffers["
                + str(index)
                + "][_unique_index])}"
            )
            for index, instruction in enumerate(restrictions)
        )
        stabilized_manifest = ", ".join(
            (
                "{'expression': "
                + _python_literal(instruction.arguments[0])
                + ", 'value': _stabilized_buffers["
                + str(index)
                + "][_unique_index]}"
            )
            for index, instruction in enumerate(stabilized)
        )
        lines.extend(
            [
                "    _tokens = [_cache_token(_key) for _key in _keys]",
                "    _items = [None] * _count",
                "    for _record_index, _payload in enumerate(payloads):",
                "        _unique_index = _slot_buffer[_record_index]",
                "        _evidence = {",
                f"            'judgements': [{judgement_manifest}],",
                f"            'restrictions': [{restriction_manifest}],",
                "            'projections': [],",
                "            'bindings': [],",
                f"            'stabilized': [{stabilized_manifest}],",
                "        }",
                "        _items[_record_index] = {",
                "            'artifact_id': ARTIFACT_ID,",
                "            'module': MODULE,",
                f"            'operation': {_python_literal(operation.name)},",
                "            'state': (",
                "                'stable'",
                "                if _state_buffer[_unique_index]",
                "                else 'partial'",
                "            ),",
                "            'input': dict(_payload),",
                "            'result': _result_buffer[_unique_index],",
                "            'evidence': _evidence,",
                "            'cache': {",
                "                'enabled': True,",
                "                'hit': bool(_hit_buffer[_record_index]),",
                "                'key': _tokens[_unique_index],",
                "                'key_protocol': KEY_PROTOCOL,",
                "                'scope': 'batch',",
                "                'collision_verified': True,",
                "                'buffer_protocol': BUFFER_PROTOCOL,",
                "            },",
                "        }",
                "    _column_bytes = sum(",
                "        len(_column) * _column.itemsize",
                "        for _column in _columns",
                "    )",
                "    _index_bytes = (",
                "        len(_slot_buffer) * _slot_buffer.itemsize",
                "        + len(_hit_buffer)",
                "    )",
                "    _evidence_flag_bytes = (",
                "        len(_state_buffer)",
                "        + sum(len(_buffer) for _buffer in _judgement_buffers)",
                "        + sum(len(_buffer) for _buffer in _restriction_buffers)",
                "    )",
                "    return _items, _unique_count, {",
                "        'records': _count,",
                "        'unique_records': _unique_count,",
                "        'column_bytes': _column_bytes,",
                (
                    "        'column_type': "
                    "'int64' if _column_type_mask else 'float64',"
                ),
                "        'index_bytes': _index_bytes,",
                "        'evidence_flag_bytes': _evidence_flag_bytes,",
                (
                    "        'lateral_value_cells': "
                    f"_unique_count * {len(stabilized)},"
                ),
                (
                    "        'reference_intermediate_mappings_avoided': "
                    f"_unique_count * "
                    f"{4 + len(judgements) + len(restrictions) + len(stabilized)},"
                ),
                (
                    "        'reference_intermediate_lists_avoided': "
                    "_unique_count * 5,"
                ),
                (
                    "        'reference_field_writes_avoided': "
                    f"_unique_count * {len(fields) * 2},"
                ),
                "    }",
                "",
                "",
            ]
        )
        return lines

    def _render_key_operation(
        self,
        operation: IROperation,
        function_name: str,
        schemas: dict[str, dict[str, str]],
    ) -> list[str]:
        schema = schemas.get(operation.input_type or "", {})
        fields = tuple(schema)
        lines = [f"def {function_name}(payload):"]
        if fields and all(type_name == "Number" for type_name in schema.values()):
            lines.extend(
                [
                    (
                        f"    if type(payload) is dict "
                        f"and len(payload) == {len(fields)}:"
                    ),
                    "        try:",
                    *[
                        (
                            f"            _v{index} = "
                            f"payload[{_python_literal(field)}]"
                        )
                        for index, field in enumerate(fields)
                    ],
                    "        except KeyError:",
                    "            pass",
                    "        else:",
                    "            if (",
                    *[
                        (
                            f"                (type(_v{index}) is int or "
                            f"(type(_v{index}) is float and "
                            f"math.isfinite(_v{index})))"
                            + (" and" if index < len(fields) - 1 else "")
                        )
                        for index in range(len(fields))
                    ],
                    "            ):",
                    "                return (",
                    "                    7,",
                    "                    "
                    + " | ".join(
                        f"((type(_v{index}) is int) << {index})"
                        for index in range(len(fields))
                    )
                    + ",",
                    "                    "
                    + " | ".join(
                        (
                            f"((type(_v{index}) is float "
                            f"and _v{index} == 0.0 "
                            f"and math.copysign(1.0, _v{index}) < 0) "
                            f"<< {index})"
                        )
                        for index in range(len(fields))
                    )
                    + ",",
                    "                    ("
                    + ", ".join(
                        f"_v{index}" for index in range(len(fields))
                    )
                    + ("," if len(fields) == 1 else "")
                    + "),",
                    "                )",
                ]
            )
        lines.extend(
            [
                "    return _structural_key(payload)",
                "",
                "",
            ]
        )
        return lines

    def _render_operation(
        self,
        operation: IROperation,
        function_name: str,
        schemas: dict[str, dict[str, str]],
    ) -> list[str]:
        lines = [
            "",
            f"def {function_name}(payload):",
            (
                "    _input = _prepare_input("
                f"payload, {_python_literal(operation.input_type)})"
            ),
            "    _env = dict(_input)",
            "    _evidence = _new_evidence()",
            "    _state = 'partial'",
        ]
        if operation.input_type in schemas:
            for name, type_name in schemas[operation.input_type].items():
                if type_name.endswith("?"):
                    lines.append(
                        f"    _env.setdefault({_python_literal(name)}, None)"
                    )
        lines.extend(
            self._render_block(
                operation.instructions,
                operation,
                depth=1,
                emit_mode="return",
            )
        )
        lines.extend(
            [
                "    raise CasuloRuntimeError(",
                f"        {_python_literal(f'operação {operation.name} terminou sem emit')}",
                "    )",
            ]
        )
        return lines

    def _render_batch_operation(
        self,
        operation: IROperation,
        function_name: str,
        schemas: dict[str, dict[str, str]],
    ) -> list[str]:
        lines = [
            "",
            f"def {function_name}(payloads):",
            "    _results = []",
            "    for _payload_item in payloads:",
            (
                "        _input = _prepare_input("
                f"_payload_item, {_python_literal(operation.input_type)})"
            ),
            "        _env = dict(_input)",
            "        _evidence = _new_evidence()",
            "        _state = 'partial'",
        ]
        if operation.input_type in schemas:
            for name, type_name in schemas[operation.input_type].items():
                if type_name.endswith("?"):
                    lines.append(
                        f"        _env.setdefault({_python_literal(name)}, None)"
                    )
        lines.extend(
            self._render_block(
                operation.instructions,
                operation,
                depth=2,
                emit_mode="batch",
            )
        )
        lines.extend(
            [
                "        raise CasuloRuntimeError(",
                f"            {_python_literal(f'operação {operation.name} terminou sem emit')}",
                "        )",
                "    return _results",
            ]
        )
        return lines

    def _render_block(
        self,
        instructions: tuple[IRInstruction, ...],
        operation: IROperation,
        depth: int,
        emit_mode: str,
    ) -> list[str]:
        prefix = "    " * depth
        lines: list[str] = []
        for instruction in instructions:
            args = instruction.arguments
            if instruction.op == "let":
                expression = _render_expression(args[0])
                lines.append(
                    f"{prefix}_env[{_python_literal(instruction.result)}] = "
                    f"{expression}"
                )
                continue
            if instruction.op in {"judge", "restrict"}:
                expression = _render_expression(args[0])
                variable = "_condition"
                exception = (
                    "CasuloJudgeFailed"
                    if instruction.op == "judge"
                    else "CasuloRestrictionFailed"
                )
                evidence_key = (
                    "judgements"
                    if instruction.op == "judge"
                    else "restrictions"
                )
                message = (
                    f"{instruction.op} falhou em {operation.name}: {args[0]}"
                )
                lines.extend(
                    [
                        f"{prefix}{variable} = bool({expression})",
                        f"{prefix}if not {variable}:",
                        f"{prefix}    raise {exception}({_python_literal(message)})",
                        (
                            f"{prefix}_evidence[{_python_literal(evidence_key)}]"
                            ".append({"
                            f"'expression': {_python_literal(args[0])}, "
                            "'passed': True})"
                        ),
                    ]
                )
                continue
            if instruction.op == "stabilize":
                expression = _render_expression(args[0])
                lines.extend(
                    [
                        f"{prefix}_stabilized_value = {expression}",
                        (
                            f"{prefix}_evidence['stabilized'].append({{"
                            f"'expression': {_python_literal(args[0])}, "
                            "'value': _stabilized_value})"
                        ),
                        f"{prefix}_state = 'stable'",
                    ]
                )
                continue
            if instruction.op == "emit":
                expression = _render_expression(args[0])
                emitted = (
                    f"_emit({_python_literal(operation.name)}, _input, "
                    f"{expression}, _state, _evidence)"
                )
                if emit_mode == "return":
                    lines.append(f"{prefix}return {emitted}")
                else:
                    lines.extend(
                        [
                            f"{prefix}_results.append({emitted})",
                            f"{prefix}continue",
                        ]
                    )
                continue
            if instruction.op == "project":
                expression = _render_expression(args[0])
                target = None
                into: list[str] = []
                for argument in args[1:]:
                    if argument.startswith("as:"):
                        target = argument[3:]
                    elif argument.startswith("into:"):
                        into = [
                            item
                            for item in argument[5:].split(",")
                            if item
                        ]
                lines.extend(
                    [
                        f"{prefix}_projected_value = {expression}",
                        (
                            f"{prefix}_evidence['projections'].append({{"
                            f"'expression': {_python_literal(args[0])}, "
                            "'value': _projected_value, "
                            f"'target': {_python_literal(target)}, "
                            f"'into': {_python_literal(into)}}})"
                        ),
                    ]
                )
                continue
            if instruction.op == "bind":
                left = _render_expression(args[0])
                right = _render_expression(args[1])
                lines.append(
                    f"{prefix}_evidence['bindings'].append({{"
                    f"'left_expression': {_python_literal(args[0])}, "
                    f"'left': {left}, "
                    f"'right_expression': {_python_literal(args[1])}, "
                    f"'right': {right}}})"
                )
                continue
            if instruction.op == "if":
                condition = _render_expression(args[0])
                lines.append(f"{prefix}if {condition}:")
                lines.extend(
                    self._render_block(
                        instruction.then_body,
                        operation,
                        depth + 1,
                        emit_mode,
                    )
                    or [f"{prefix}    pass"]
                )
                if instruction.else_body:
                    lines.append(f"{prefix}else:")
                    lines.extend(
                        self._render_block(
                            instruction.else_body,
                            operation,
                            depth + 1,
                            emit_mode,
                        )
                        or [f"{prefix}    pass"]
                    )
                continue
            raise BackendError(f"instrução IR não suportada: {instruction.op}")
        return lines


_BUILTINS = {
    "abs": "abs",
    "round": "round",
    "sqrt": "math.sqrt",
    "len": "len",
    "min": "min",
    "max": "max",
}


def _render_expression(
    text: str,
    names: dict[str, str] | None = None,
) -> str:
    try:
        expression = parse_expression(text)
    except ExpressionSyntaxError as exc:
        raise BackendError(f"expressão IR inválida: {text!r}") from exc
    return _render_expression_node(expression, names)


def _render_expression_node(
    node: ExpressionNode,
    names: dict[str, str] | None = None,
) -> str:
    if isinstance(node, LiteralNode):
        if node.value is None or isinstance(
            node.value,
            (bool, int, float, str),
        ):
            return repr(node.value)
        raise BackendError(f"literal não suportado: {node.value!r}")
    if isinstance(node, NameNode):
        if names is not None:
            rendered = names.get(node.name)
            if rendered is None:
                raise BackendError(
                    f"nome sem posição no buffer tipado: {node.name}"
                )
            return rendered
        return f"_env[{node.name!r}]"
    if isinstance(node, ListNode):
        return "[" + ", ".join(
            _render_expression_node(item, names)
            for item in node.items
        ) + "]"
    if isinstance(node, UnaryNode):
        if node.operator not in {"not", "+", "-"}:
            raise BackendError(
                f"operador unário não suportado: {node.operator}"
            )
        operator = "not " if node.operator == "not" else node.operator
        return f"({operator}{_render_expression_node(node.operand, names)})"
    if isinstance(node, BooleanNode):
        if node.operator not in {"and", "or"}:
            raise BackendError(
                f"operador booleano não suportado: {node.operator}"
            )
        return "(" + f" {node.operator} ".join(
            _render_expression_node(item, names)
            for item in node.values
        ) + ")"
    if isinstance(node, BinaryNode):
        if node.operator not in {"+", "-", "*", "/", "//", "%", "**"}:
            raise BackendError(
                f"operador aritmético não suportado: {node.operator}"
            )
        return (
            f"({_render_expression_node(node.left, names)} {node.operator} "
            f"{_render_expression_node(node.right, names)})"
        )
    if isinstance(node, CompareNode):
        rendered = [_render_expression_node(node.values[0], names)]
        for operator, comparator in zip(node.operators, node.values[1:]):
            rendered.extend((operator, _render_expression_node(comparator, names)))
        return "(" + " ".join(rendered) + ")"
    if isinstance(node, ConditionalNode):
        return (
            f"({_render_expression_node(node.when_true, names)} if "
            f"{_render_expression_node(node.condition, names)} else "
            f"{_render_expression_node(node.when_false, names)})"
        )
    if isinstance(node, CallNode):
        function = _BUILTINS.get(node.function)
        if function is None:
            raise BackendError(f"chamada não suportada: {node.function}")
        return (
            f"{function}("
            + ", ".join(
                _render_expression_node(arg, names)
                for arg in node.arguments
            )
            + ")"
        )
    raise BackendError(
        f"expressão não suportada pelo backend: {type(node).__name__}"
    )


def _python_literal(value: Any) -> str:
    if value is None or isinstance(value, (bool, int, float, str)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_python_literal(item) for item in value) + "]"
    if isinstance(value, tuple):
        suffix = "," if len(value) == 1 else ""
        return (
            "("
            + ", ".join(_python_literal(item) for item in value)
            + suffix
            + ")"
        )
    if isinstance(value, dict):
        items = ", ".join(
            f"{_python_literal(key)}: {_python_literal(value[key])}"
            for key in sorted(value)
        )
        return "{" + items + "}"
    raise TypeError(f"literal Python não suportado: {type(value)!r}")
