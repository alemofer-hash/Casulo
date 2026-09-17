"""Artefato gerado pelo compilador T da Teloscorp / Casulo."""

from __future__ import annotations

import json
import math
import sys
from array import array
from collections.abc import Mapping

ARTIFACT_ID = 'sha256:02a1f23caa831e5a1c25b8c000daa2e8c0990a5217f2442c441d8c2e383afd9f'
BACKEND_VERSION = 'python-reference/0.4.1'
KEY_PROTOCOL = 'casulo-structural-key/0.1'
BUFFER_PROTOCOL = 'casulo-typed-buffer/0.1'
MODULE = 'entry'
FIELD_SCHEMAS = {'EntryPoint': {'value': 'Text'}}
OPERATION_SCHEMAS = {'Start': {'input_type': 'EntryPoint', 'kind': 'condense', 'output_type': 'Text', 'target_type': None}}


class CasuloRuntimeError(ValueError):
    pass


class CasuloInputError(CasuloRuntimeError):
    pass


class CasuloJudgeFailed(CasuloRuntimeError):
    pass


class CasuloRestrictionFailed(CasuloRuntimeError):
    pass


def _type_parts(type_name):
    optional = type_name.endswith('?')
    if optional:
        type_name = type_name[:-1]
    depth = 0
    while type_name.startswith('[') and type_name.endswith(']'):
        type_name = type_name[1:-1]
        depth += 1
    return type_name, optional, depth


def _validate_value(value, type_name, path):
    base, optional, depth = _type_parts(type_name)
    if value is None:
        if optional or base == 'Any':
            return
        raise CasuloInputError(f'{path}: valor obrigatório ausente')
    if depth:
        if not isinstance(value, list):
            raise CasuloInputError(f'{path}: esperado {type_name}')
        nested = '[' * (depth - 1) + base + ']' * (depth - 1)
        for index, item in enumerate(value):
            _validate_value(item, nested, f'{path}[{index}]')
        return
    valid = {
        'Any': lambda item: True,
        'Bool': lambda item: isinstance(item, bool),
        'Number': lambda item: isinstance(item, (int, float))
        and not isinstance(item, bool),
        'Text': lambda item: isinstance(item, str),
        'Time': lambda item: isinstance(item, str),
        'Date': lambda item: isinstance(item, str),
        'Duration': lambda item: (
            isinstance(item, (int, float, str))
            and not isinstance(item, bool)
        ),
    }
    if base in FIELD_SCHEMAS:
        _validate_mapping(value, FIELD_SCHEMAS[base], path)
        return
    predicate = valid.get(base)
    if predicate is None or not predicate(value):
        raise CasuloInputError(f'{path}: esperado {type_name}')


def _validate_mapping(value, schema, path):
    if not isinstance(value, Mapping):
        raise CasuloInputError(f'{path}: esperado objeto JSON')
    for name, type_name in schema.items():
        _, optional, _ = _type_parts(type_name)
        if name not in value:
            if optional:
                continue
            raise CasuloInputError(f'{path}.{name}: campo obrigatório ausente')
        _validate_value(value[name], type_name, f'{path}.{name}')


def _prepare_input(payload, input_type):
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise CasuloInputError('entrada precisa ser um objeto JSON')
    preserved = dict(payload)
    if input_type is not None:
        schema = FIELD_SCHEMAS.get(input_type)
        if schema is None:
            raise CasuloInputError(f'tipo de entrada desconhecido: {input_type}')
        _validate_mapping(preserved, schema, input_type)
    return preserved


def _new_evidence():
    return {
        'judgements': [],
        'restrictions': [],
        'projections': [],
        'bindings': [],
        'stabilized': [],
    }


def _emit(operation, original_input, result, state, evidence):
    return {
        'artifact_id': ARTIFACT_ID,
        'module': MODULE,
        'operation': operation,
        'state': state,
        'input': original_input,
        'result': result,
        'evidence': evidence,
    }


def _operation_0(payload):
    _input = _prepare_input(payload, 'EntryPoint')
    _env = dict(_input)
    _evidence = _new_evidence()
    _state = 'partial'
    return _emit('Start', _input, 'contradicao produtiva', _state, _evidence)
    raise CasuloRuntimeError(
        'operação Start terminou sem emit'
    )

def _batch_operation_0(payloads):
    _results = []
    for _payload_item in payloads:
        _input = _prepare_input(_payload_item, 'EntryPoint')
        _env = dict(_input)
        _evidence = _new_evidence()
        _state = 'partial'
        _results.append(_emit('Start', _input, 'contradicao produtiva', _state, _evidence))
        continue
        raise CasuloRuntimeError(
            'operação Start terminou sem emit'
        )
    return _results
def _key_operation_0(payload):
    return _structural_key(payload)


OPERATIONS = {
    'Start': _operation_0,
}

BATCH_OPERATIONS = {
    'Start': _batch_operation_0,
}

OPERATION_KEYS = {
    'Start': _key_operation_0,
}

BUFFER_OPERATIONS = {
}

OPERATION_CACHE = {name: {} for name in OPERATIONS}


def _structural_key(value):
    if value is None:
        return (0,)
    if isinstance(value, bool):
        return (1, value)
    if isinstance(value, int):
        return (2, value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CasuloInputError(
                'NaN e infinito não podem formar chave estrutural'
            )
        negative_zero = value == 0.0 and math.copysign(1.0, value) < 0
        return (3, value, negative_zero)
    if isinstance(value, str):
        return (4, value)
    if isinstance(value, (list, tuple)):
        return (5, tuple(_structural_key(item) for item in value))
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CasuloInputError(
                'objetos de entrada exigem chaves textuais'
            )
        return (
            6,
            frozenset(
                (key, _structural_key(item))
                for key, item in value.items()
            ),
        )
    raise CasuloInputError(
        'tipo não suportado na chave estrutural: '
        + type(value).__name__
    )


def _cache_fingerprint(structural_key):
    return hash(structural_key) & 0xffffffffffffffff


def _cache_token(structural_key):
    return f'local:{_cache_fingerprint(structural_key):016x}'


def _clone_json(value):
    if isinstance(value, dict):
        return {key: _clone_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_json(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone_json(item) for item in value)
    return value


def _cache_envelope(result, enabled, hit, key, scope=None):
    manifested = _clone_json(result)
    manifested['cache'] = {
        'enabled': enabled,
        'hit': hit,
        'key': key,
        'key_protocol': KEY_PROTOCOL if enabled else None,
        'scope': scope if enabled else None,
        'collision_verified': enabled,
    }
    return manifested


def clear_cache(operation=None):
    if operation is None:
        for cache in OPERATION_CACHE.values():
            cache.clear()
        return
    if operation not in OPERATION_CACHE:
        raise CasuloRuntimeError(f'operação desconhecida: {operation}')
    OPERATION_CACHE[operation].clear()


def cache_stats():
    return {
        name: {'entries': len(cache)}
        for name, cache in OPERATION_CACHE.items()
    }


def execute(operation, payload=None, use_cache=True):
    function = OPERATIONS.get(operation)
    if function is None:
        available = ', '.join(sorted(OPERATIONS))
        raise CasuloRuntimeError(
            f'operação desconhecida: {operation}; disponíveis: {available}'
        )
    key_function = OPERATION_KEYS[operation]
    if not use_cache:
        return _cache_envelope(function(payload), False, False, None)
    key = key_function(payload)
    token = _cache_token(key)
    cache = OPERATION_CACHE[operation]
    if key in cache:
        return _cache_envelope(
            cache[key], True, True, token, 'process'
        )
    result = function(payload)
    cache[key] = _clone_json(result)
    return _cache_envelope(result, True, False, token, 'process')


def execute_batch(operation, payloads, use_cache=True, use_buffer=True):
    function = BATCH_OPERATIONS.get(operation)
    if function is None:
        available = ', '.join(sorted(BATCH_OPERATIONS))
        raise CasuloRuntimeError(
            f'operação desconhecida: {operation}; disponíveis: {available}'
        )
    key_function = OPERATION_KEYS[operation]
    if not isinstance(payloads, list):
        raise CasuloInputError('lote precisa ser uma lista JSON')
    buffer_function = BUFFER_OPERATIONS.get(operation)
    if use_cache and use_buffer and buffer_function is not None:
        buffered = buffer_function(payloads, key_function)
        if buffered is not None:
            items, misses, buffer_metrics = buffered
            return {
                'artifact_id': ARTIFACT_ID,
                'module': MODULE,
                'operation': operation,
                'count': len(items),
                'cache': {
                    'enabled': True,
                    'hits': len(items) - misses,
                    'misses': misses,
                    'entries': misses,
                    'key_protocol': KEY_PROTOCOL,
                    'scope': 'batch',
                    'collision_verified': True,
                    'buffer_protocol': BUFFER_PROTOCOL,
                    'representation': 'columnar-typed',
                    'evidence_layout': 'lateral',
                    'hot_path': buffer_metrics,
                },
                'items': items,
            }
    if not use_cache:
        items = [
            _cache_envelope(item, False, False, None)
            for item in function(payloads)
        ]
        return {
            'artifact_id': ARTIFACT_ID,
            'module': MODULE,
            'operation': operation,
            'count': len(items),
            'cache': {
                'enabled': False,
                'hits': 0,
                'misses': len(items),
                'entries': len(OPERATION_CACHE[operation]),
                'key_protocol': None,
                'scope': None,
                'collision_verified': False,
                'buffer_protocol': None,
                'representation': 'objects',
                'evidence_layout': 'inline',
                'hot_path': None,
            },
            'items': items,
        }
    cache = {}
    slots = [None] * len(payloads)
    pending = {}
    unique_payloads = []
    unique_keys = []
    unique_tokens = []
    for index, payload in enumerate(payloads):
        key = key_function(payload)
        if key in pending:
            pending[key].append(index)
        else:
            pending[key] = [index]
            unique_keys.append(key)
            unique_tokens.append(_cache_token(key))
            unique_payloads.append(payload)
    computed = function(unique_payloads)
    for key, token, base in zip(
        unique_keys, unique_tokens, computed
    ):
        cache[key] = base
        indexes = pending[key]
        slots[indexes[0]] = _cache_envelope(
            base, True, False, token, 'batch'
        )
        for index in indexes[1:]:
            slots[index] = _cache_envelope(
                base, True, True, token, 'batch'
            )
    misses = len(unique_payloads)
    return {
        'artifact_id': ARTIFACT_ID,
        'module': MODULE,
        'operation': operation,
        'count': len(slots),
        'cache': {
            'enabled': True,
            'hits': len(slots) - misses,
            'misses': misses,
            'entries': len(cache),
            'key_protocol': KEY_PROTOCOL,
            'scope': 'batch',
            'collision_verified': True,
            'buffer_protocol': None,
            'representation': 'objects',
            'evidence_layout': 'inline',
            'hot_path': None,
        },
        'items': slots,
    }


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not 1 <= len(args) <= 2:
        print(
            'uso: python casulo_artifact.py OPERATION [INPUT.json|-]',
            file=sys.stderr,
        )
        return 2
    operation = args[0]
    input_path = args[1] if len(args) == 2 else None
    try:
        if input_path == '-':
            payload = json.load(sys.stdin)
        elif input_path is None:
            payload = {}
        else:
            with open(input_path, encoding='utf-8') as stream:
                payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f'entrada inválida: {exc}', file=sys.stderr)
        return 2
    try:
        result = (
            execute_batch(operation, payload)
            if isinstance(payload, list)
            else execute(operation, payload)
        )
    except CasuloRuntimeError as exc:
        print(f'execução bloqueada: {exc}', file=sys.stderr)
        return 3
    json.dump(
        result,
        sys.stdout,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
