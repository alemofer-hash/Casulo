"""Artefato gerado pelo compilador T da Teloscorp / Casulo."""

from __future__ import annotations

import copy
import json
import math
import sys
from collections.abc import Mapping

ARTIFACT_ID = 'sha256:560ff4b760b1f4e48c4dfbcbfa7b6edba2d81fb1449ec7e6578a18026a91daf4'
BACKEND_VERSION = 'python-reference/0.2'
MODULE = 'casulo.flood_rs'
FIELD_SCHEMAS = {'HydroCell': {'base_flow': 'Number', 'evapotranspiration': 'Number', 'precipitation': 'Number', 'surface_flow': 'Number'}}
OPERATION_SCHEMAS = {'WaterBalance': {'input_type': 'HydroCell', 'kind': 'condense', 'output_type': 'Number', 'target_type': None}}


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
    _input = _prepare_input(payload, 'HydroCell')
    _env = dict(_input)
    _evidence = _new_evidence()
    _state = 'partial'
    _condition = bool((_env['precipitation'] >= 0))
    if not _condition:
        raise CasuloJudgeFailed('judge falhou em WaterBalance: precipitation >= 0')
    _evidence['judgements'].append({'expression': 'precipitation >= 0', 'passed': True})
    _env['storage_change'] = (((_env['precipitation'] - _env['evapotranspiration']) - _env['surface_flow']) - _env['base_flow'])
    _stabilized_value = _env['storage_change']
    _evidence['stabilized'].append({'expression': 'storage_change', 'value': _stabilized_value})
    _state = 'stable'
    return _emit('WaterBalance', _input, _env['storage_change'], _state, _evidence)
    raise CasuloRuntimeError(
        'operação WaterBalance terminou sem emit'
    )

def _batch_operation_0(payloads):
    _results = []
    for _payload_item in payloads:
        _input = _prepare_input(_payload_item, 'HydroCell')
        _env = dict(_input)
        _evidence = _new_evidence()
        _state = 'partial'
        _condition = bool((_env['precipitation'] >= 0))
        if not _condition:
            raise CasuloJudgeFailed('judge falhou em WaterBalance: precipitation >= 0')
        _evidence['judgements'].append({'expression': 'precipitation >= 0', 'passed': True})
        _env['storage_change'] = (((_env['precipitation'] - _env['evapotranspiration']) - _env['surface_flow']) - _env['base_flow'])
        _stabilized_value = _env['storage_change']
        _evidence['stabilized'].append({'expression': 'storage_change', 'value': _stabilized_value})
        _state = 'stable'
        _results.append(_emit('WaterBalance', _input, _env['storage_change'], _state, _evidence))
        continue
        raise CasuloRuntimeError(
            'operação WaterBalance terminou sem emit'
        )
    return _results
OPERATIONS = {
    'WaterBalance': _operation_0,
}

BATCH_OPERATIONS = {
    'WaterBalance': _batch_operation_0,
}

OPERATION_CACHE = {name: {} for name in OPERATIONS}


def _cache_key(payload):
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(',', ':'),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CasuloInputError(
            f'entrada não pode formar chave de cache: {exc}'
        ) from exc


def _cache_envelope(result, enabled, hit, key):
    manifested = copy.deepcopy(result)
    manifested['cache'] = {
        'enabled': enabled,
        'hit': hit,
        'key': key,
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
    if not use_cache:
        return _cache_envelope(function(payload), False, False, None)
    key = _cache_key(payload)
    cache = OPERATION_CACHE[operation]
    if key in cache:
        return _cache_envelope(cache[key], True, True, key)
    result = function(payload)
    cache[key] = copy.deepcopy(result)
    return _cache_envelope(result, True, False, key)


def execute_batch(operation, payloads, use_cache=True):
    function = BATCH_OPERATIONS.get(operation)
    if function is None:
        available = ', '.join(sorted(BATCH_OPERATIONS))
        raise CasuloRuntimeError(
            f'operação desconhecida: {operation}; disponíveis: {available}'
        )
    if not isinstance(payloads, list):
        raise CasuloInputError('lote precisa ser uma lista JSON')
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
            },
            'items': items,
        }
    cache = OPERATION_CACHE[operation]
    slots = [None] * len(payloads)
    pending = {}
    unique_payloads = []
    unique_keys = []
    for index, payload in enumerate(payloads):
        key = _cache_key(payload)
        if key in cache:
            slots[index] = _cache_envelope(cache[key], True, True, key)
        elif key in pending:
            pending[key].append(index)
        else:
            pending[key] = [index]
            unique_keys.append(key)
            unique_payloads.append(payload)
    computed = function(unique_payloads)
    for key, base in zip(unique_keys, computed):
        cache[key] = copy.deepcopy(base)
        indexes = pending[key]
        slots[indexes[0]] = _cache_envelope(base, True, False, key)
        for index in indexes[1:]:
            slots[index] = _cache_envelope(base, True, True, key)
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
