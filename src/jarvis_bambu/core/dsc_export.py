"""DSC package writer. Pillow/NumPy only; never initializes Qt."""
from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
import os
import tempfile
import zipfile
from PIL import Image
from .height_raster import check_cancel
from .dsc_live_fields import validate_fields
from .dsc_validation import validate_package


def export_dsc(destination, height_map, cuts, *, size=512, zones=None, cancel=None, progress=None, live_fields=None, version=2):
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Exportación DSC: elige versión 1 o 2.')
    if type(size) is not int or size not in (256, 512, 1024):
        raise ValueError('DSC admite resoluciones de 256, 512 o 1024 píxeles.')
    zones = zones or height_map.zones(cuts)
    if not 1 <= len(zones) <= 12:
        raise ValueError('DSC admite entre 1 y 12 zonas de color.')
    import re
    ids = [z.id for z in zones]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', i) or i in ('constructor','prototype','__proto__') for i in ids):
        raise ValueError('Los IDs deben ser únicos y compatibles con DSC.')
    live_fields = validate_fields([] if live_fields is None else live_fields, ids)
    if version == 1 and live_fields:
        raise ValueError('Los campos vivos requieren v2. No se omiten silenciosamente al exportar v1.')
    canonical = height_map.zones(cuts)
    if len(zones) != len(canonical) or any((z.z_from,z.z_to) != (c.z_from,c.z_to) for z,c in zip(zones,canonical)):
        raise ValueError('Las zonas no coinciden con los cortes actuales.')
    if any(not isinstance(z.label,str) or not z.label.strip() or len(z.label)>100 for z in zones):
        raise ValueError('Cada zona necesita un nombre de entre 1 y 100 caracteres.')
    raster = height_map.top_raster(size, cancel=cancel, progress=progress)
    normalized = [z.z_to for z in height_map.zones(cuts)[:-1]]
    labels = raster.labels(normalized)
    payload = {
        'schema': 'dsc.stl-height-map.v2',
        'package_schema': f'dsc.preview-package.v{version}',
        'source': height_map.summary.source_name, 'source_type': height_map.source_type,
        'triangle_count': height_map.summary.triangle_count,
        'bounds': {'min': list(height_map.summary.bounds_min), 'max': list(height_map.summary.bounds_max)},
        'height': height_map.summary.height,
        'zones': [asdict(z) for z in zones],
        'detected_colors': [asdict(c) for c in height_map.detected_colors],
        'warnings': list(height_map.warnings),
        'view': {'projection': 'orthographic', 'camera': '+Z', 'image_right': '+X', 'image_up': '+Y',
                 'width': size, 'height': size, 'center_xy_mm': list(raster.center_xy),
                 'pixels_per_mm': raster.pixels_per_mm, 'sampling': 'pixel-center',
                 'intervals': '[from,to); last includes maximum', 'alpha': 'binary'},
        'preview': {'base_image': 'preview.png', 'layers': [
            {'field_id': z.id, 'mask_image': f'color_{i+1}.png'} for i,z in enumerate(zones)]},
    }
    if version == 2:
        payload['live_fields'] = live_fields
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.dsc-', suffix='.zip', dir=destination.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('model-map.json', json.dumps(payload, ensure_ascii=False, indent=2))
            def png(name, rgba):
                check_cancel(cancel)
                stream = BytesIO()
                Image.fromarray(rgba).save(stream, format='PNG')
                archive.writestr(name, stream.getvalue())
            png('preview.png', raster.rgba(labels, neutral=True))
            png('height-map-preview.png', raster.rgba(labels))
            for i in range(len(zones)):
                png(f'color_{i+1}.png', raster.rgba(labels, zone=i, neutral=True))
        check_cancel(cancel)
        validate_package(temporary, cancel=cancel)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination
