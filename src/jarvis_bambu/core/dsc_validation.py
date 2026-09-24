"""Validate completed DSC exports before atomic publication (no Qt/Flask)."""
from io import BytesIO
import json
from pathlib import Path
import zipfile
import numpy as np
from PIL import Image
from .dsc_live_fields import identifier, text, validate_fields
from .height_raster import check_cancel


def validate_package(path, *, cancel=None):
    if Path(path).stat().st_size > 5 * 1024 * 1024:
        raise ValueError('El ZIP DSC supera 5 MiB; reduce la resolución.')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) > 16 or len(set(names)) != len(names) or sum(i.file_size for i in infos) > 32*1024*1024:
            raise ValueError('El ZIP DSC excede los límites o contiene duplicados.')
        if any('/' in n or '\\' in n or n in ('.','..') for n in names):
            raise ValueError('El ZIP DSC debe contener únicamente archivos en su raíz.')
        if any(i.flag_bits & 1 or (i.external_attr >> 16) & 0o170000 == 0o120000 for i in infos):
            raise ValueError('No se admiten cifrado ni enlaces en el ZIP.')
        if 'model-map.json' not in names or archive.getinfo('model-map.json').file_size > 128*1024:
            raise ValueError('Faltan metadatos DSC o superan 128 KiB.')
        m = json.loads(archive.read('model-map.json'))
        if m.get('package_schema') not in ('dsc.preview-package.v1', 'dsc.preview-package.v2'):
            raise ValueError('Versión de paquete DSC incompatible.')
        view = m['view']; size = view['width']; zones = m['zones']
        if type(size) is not int or size not in (256,512,1024) or view['height'] != size:
            raise ValueError('Resolución DSC inválida.')
        for key, value in dict(projection='orthographic',camera='+Z',image_right='+X',image_up='+Y',sampling='pixel-center',alpha='binary').items():
            if view.get(key) != value:
                raise ValueError(f'Contrato de vista incorrecto: {key}.')
        if not isinstance(zones,list) or not 1 <= len(zones) <= 12:
            raise ValueError('DSC admite entre 1 y 12 zonas.')
        ids = [identifier(z['id']) for z in zones]
        for z in zones:
            text(z['label'],100,'Nombre de zona',True)
        validate_fields(m.get('live_fields', []), ids)
        if m['package_schema'].endswith('v1') and m.get('live_fields'):
            raise ValueError('Los campos vivos requieren DSC v2.')
        expected = ['preview.png', *[f'color_{i+1}.png' for i in range(len(zones))]]
        if m['preview'] != dict(base_image='preview.png',layers=[dict(field_id=id,mask_image=expected[i+1]) for i,id in enumerate(ids)]):
            raise ValueError('La relación entre máscaras y campos DSC es incorrecta.')
        allowed = {'model-map.json','height-map-preview.png',*expected}
        if set(names)-allowed or not set(expected).issubset(names):
            raise ValueError('El ZIP tiene archivos ausentes o no permitidos.')
        union = np.zeros((size,size), dtype=bool)
        base = None
        for name in expected + (['height-map-preview.png'] if 'height-map-preview.png' in names else []):
            check_cancel(cancel)
            if archive.getinfo(name).file_size > 5*1024*1024:
                raise ValueError(f'{name} supera 5 MiB.')
            with Image.open(BytesIO(archive.read(name))) as im:
                if im.format != 'PNG' or im.mode != 'RGBA' or im.size != (size,size):
                    raise ValueError(f'{name} debe ser PNG RGBA de {size} × {size}.')
                rgba = np.asarray(im)
                if name == 'height-map-preview.png':
                    continue
                visible = rgba[:,:,3] == 255
                if np.any((rgba[:,:,3] != 0) & ~visible) or np.any(rgba[visible] != 255) or np.any(rgba[~visible] != 0):
                    raise ValueError(f'{name} debe contener solo blanco opaco y negro transparente, sin antialiasing.')
                if name == 'preview.png':
                    base = visible
                else:
                    if np.any(union & visible):
                        raise ValueError('Las máscaras DSC se solapan.')
                    union |= visible
        if not union.any() or not np.array_equal(union, base):
            raise ValueError('La unión de máscaras no coincide con la huella visible.')
    return m
