"""Artefato gerado pelo compilador T da Teloscorp / Casulo."""

from __future__ import annotations

import math
from collections.abc import Mapping

ARTIFACT_ID = 'sha256:9f5612019d1641203abdea6b8a9bd5b46a3a929848f0f1cbb57fe7366d9f1185'
BACKEND_VERSION = 'python-reference/0.1'
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
        if optional:
            nested += '?'
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
        for name, type_name in schema.items():
            _, optional, _ = _type_parts(type_name)
            if optional and name not in preserved:
                preserved[name] = None
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
OPERATIONS = {
    'WaterBalance': _operation_0,
}


def execute(operation, payload=None):
    function = OPERATIONS.get(operation)
    if function is None:
        available = ', '.join(sorted(OPERATIONS))
        raise CasuloRuntimeError(
            f'operação desconhecida: {operation}; disponíveis: {available}'
        )
    return function(payload)
