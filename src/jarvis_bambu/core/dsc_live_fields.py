"""DSC v2 live fields and template interchange, independent of Qt."""
import json
import math
import re
from pathlib import Path

COORDINATES = {'origin': 'top-left', 'units': 'normalized', 'reference': 'preview_canvas'}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value) or value in ('constructor', 'prototype', '__proto__'):
        raise ValueError('ID DSC inválido: usa una letra minúscula inicial y hasta 64 letras, números, guiones o guiones bajos; sin IDs reservados.')
    return value


def text(value, maximum, name, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()) or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise ValueError(f'{name}: usa texto válido de hasta {maximum} caracteres.')
    return value


def validate_hitbox(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {'x','y','width','height','rotation_deg','align','vertical_align'}:
        raise ValueError('Hitbox inválida: propiedades desconocidas.')
    box = {}
    for key in ('x', 'y', 'width', 'height'):
        value = raw.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'Hitbox: {key} debe ser un número finito.')
        box[key] = float(value)
    if box['x'] < 0 or box['y'] < 0 or box['width'] <= 0 or box['height'] <= 0 or box['x'] + box['width'] > 1 or box['y'] + box['height'] > 1:
        raise ValueError('La hitbox debe estar dentro del canvas completo (0 a 1), con ancho y alto positivos.')
    if raw.get('rotation_deg', 0) != 0 or raw.get('align', 'center') != 'center' or raw.get('vertical_align', 'middle') != 'middle':
        raise ValueError('DSC admite texto centrado sin rotación.')
    return box


def validate_field(raw):
    if not isinstance(raw, dict) or set(raw) - {'field_id','label','type','default','enabled','hitbox'}:
        raise ValueError('Campo vivo inválido: propiedades desconocidas.')
    kind = raw.get('type')
    if kind not in ('text', 'number'):
        raise ValueError('Los campos vivos deben ser texto o número.')
    default = raw.get('default', '')
    if kind == 'text':
        text(default, 200, 'Valor por defecto')
    elif default != '':
        # Match the actual DSC Python importer, including its decimal spelling.
        if type(default) not in (int, float) or not math.isfinite(default) or abs(default) > 999999999999 or not re.fullmatch(r'-?\d{1,12}(\.\d{1,6})?', str(default)):
            raise ValueError('Número por defecto: máximo 12 dígitos y 6 decimales, finito y sin notación exponencial.')
    enabled = raw.get('enabled', False)
    if type(enabled) is not bool:
        raise ValueError('El estado del campo debe ser booleano.')
    return dict(field_id=identifier(raw.get('field_id')), label=text(raw.get('label'),100,'Nombre',True),
                type=kind, default=default, enabled=enabled, hitbox=validate_hitbox(raw.get('hitbox')))


def validate_fields(raw, color_ids=()):
    if not isinstance(raw, list) or len(raw) + len(color_ids) > 40:
        raise ValueError('DSC admite un máximo de 40 campos contando los colores.')
    fields = [validate_field(f) for f in raw]
    ids = [*color_ids, *[f['field_id'] for f in fields]]
    if len(set(ids)) != len(ids):
        raise ValueError('Los IDs deben ser únicos entre colores y campos vivos.')
    return fields


def import_template(path):
    with Path(path).open('rb') as source:
        data = source.read(128 * 1024 + 1)
    if len(data) > 128 * 1024:
        raise ValueError('La plantilla supera 128 KiB.')
    try:
        raw = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('La plantilla no contiene un JSON válido.') from exc
    if not isinstance(raw, dict) or raw.get('schema') != 'dsc.live-field-template.v1' or raw.get('package_schema') != 'dsc.preview-package.v2':
        raise ValueError('Se esperaba una plantilla dsc.live-field-template.v1 para DSC v2.')
    if raw.get('coordinate_system') != COORDINATES:
        raise ValueError('La plantilla debe usar coordenadas normalizadas del canvas, con origen arriba a la izquierda.')
    field = raw.get('field')
    if not isinstance(field, dict) or set(field) - {'id','label','type','default'}:
        raise ValueError('La definición del campo en la plantilla es inválida.')
    return validate_field(dict(field_id=field.get('id'), label=field.get('label'), type=field.get('type'),
                               default=field.get('default',''), enabled=raw.get('enabled',False), hitbox=raw.get('hitbox')))
