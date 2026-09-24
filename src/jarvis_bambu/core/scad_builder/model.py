"""Versioned, JSON-serializable intermediate contract; never evaluates expressions."""
from __future__ import annotations
import json
import math
import re

SCHEMA = 'bambulab.scad-model.v1'
TYPES = {'text', 'number', 'boolean', 'select', 'color', 'font'}
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z_0-9]{0,63}$')


def literal(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('El número debe ser finito.')
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def validate_parameters(parameters):
    if len(parameters) > 250:
        raise ValueError('Máximo 250 parámetros.')
    by_id, variables = {}, set()
    for p in parameters:
        key, variable = p.get('id', ''), p.get('scad_variable', p.get('id', ''))
        if not IDENTIFIER.fullmatch(key) or not IDENTIFIER.fullmatch(variable):
            raise ValueError('ID y variable SCAD: letras, números y guion bajo; empezar por letra.')
        if key in by_id or variable in variables:
            raise ValueError('ID o variable SCAD duplicados.')
        by_id[key] = p
        variables.add(variable)
        kind, value = p.get('type'), p.get('default')
        if kind not in TYPES:
            raise ValueError('Tipo de parámetro no compatible.')
        if kind == 'number':
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e6:
                raise ValueError('Número no válido o fuera del límite ±1000000.')
            if value < p.get('min', -1e6) or value > p.get('max', 1e6):
                raise ValueError('Valor fuera del rango del parámetro.')
        elif kind == 'boolean':
            if not isinstance(value, bool): raise ValueError('Se esperaba true o false.')
        elif kind == 'select':
            if value not in [o['value'] for o in p.get('options', [])]:
                raise ValueError('Selecciona una opción válida.')
        elif not isinstance(value, str) or len(value) > 2000 or '\x00' in value:
            raise ValueError('Texto no válido (máximo 2000 caracteres).')
        if kind == 'color' and not re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
            raise ValueError('Color HEX esperado: #RRGGBB.')
    for p in parameters:
        binding = p.get('color_binding', {'mode': 'independent'})
        if binding.get('mode') not in ('independent', 'inherit'):
            raise ValueError('Modo de color no válido.')
        if binding['mode'] == 'inherit':
            target = by_id.get(binding.get('source'))
            if not target or target['type'] != 'color':
                raise ValueError('La herencia debe apuntar a un parámetro Color existente.')
            seen = {p['id']}
            while target:
                if target['id'] in seen: raise ValueError('Herencia de color circular.')
                seen.add(target['id'])
                b = target.get('color_binding', {})
                target = by_id.get(b.get('source')) if b.get('mode') == 'inherit' else None
    return by_id


def parameter(key, kind, default, **extra):
    return dict(id=key, label=key.replace('_', ' ').capitalize(), type=kind,
                default=default, scad_variable=key, **extra)


def text_parameters(prefix, position=(0, 0, 0), height=1.2):
    result = [parameter(prefix, 'text', 'LUNA', color_binding={'mode': 'inherit', 'source': 'base_color'}),
              parameter(prefix+'_font', 'font', 'Roboto'),
              parameter(prefix+'_size', 'number', 12., min=.1, max=1000),
              parameter(prefix+'_height', 'number', max(.1, height), min=.1, max=1000),
              parameter(prefix+'_spacing', 'number', 1., min=.1, max=10),
              parameter(prefix+'_color', 'color', '#FFFFFF')]
    for axis, val in zip('xyz', position): result.append(parameter(prefix+'_'+axis, 'number', float(val)))
    for axis in 'xyz': result.append(parameter(prefix+'_r'+axis, 'number', 0.))
    for axis, options, default in [('halign', ['left', 'center', 'right'], 'center'), ('valign', ['top', 'center', 'baseline', 'bottom'], 'center')]:
        result.append(parameter(prefix+'_'+axis, 'select', default, options=[dict(value=v, label=v) for v in options]))
    return result
