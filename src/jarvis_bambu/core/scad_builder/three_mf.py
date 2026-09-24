"""Bounded 3MF ingestion reusing Toolbox's transform/material/mesh parser."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
import hashlib
import struct
import zipfile
import numpy as np
from ..stl_color_map import (_load_3mf_triangles, _read_3mf_extruder_settings,
                            _read_3mf_filament_palette, _read_embedded_preview, NS_3MF)
from ..height_raster import check_cancel

MAX_FACES = 2_000_000


@dataclass
class Part:
    id: str
    name: str
    triangles: np.ndarray
    colors: list
    transform: list
    fingerprint: str
    hints: list

    def metadata(self):
        lo, hi = self.triangles.min(axis=(0,1)), self.triangles.max(axis=(0,1))
        return dict(id=self.id, name=self.name, bounds_min=lo.tolist(), bounds_max=hi.tolist(),
                    dimensions=(hi-lo).tolist(), colors=self.colors, transform=self.transform,
                    fingerprint=self.fingerprint, hints=self.hints, triangle_count=len(self.triangles))


@dataclass
class Reference:
    parts: list
    palette: dict
    metadata: dict
    preview: bytes | None
    warnings: list

    @property
    def triangles(self): return np.concatenate([p.triangles for p in self.parts])


def preflight(archive):
    infos = archive.infolist()
    if len(infos) > 3000 or sum(i.file_size for i in infos) > 256_000_000:
        raise ValueError('3MF demasiado grande: máximo 3000 archivos / 256 MB descomprimidos.')
    names, roots = set(), {}
    for info in infos:
        name = info.filename
        if name in names or '\\' in name or name.startswith('/') or '..' in PurePosixPath(name).parts:
            raise ValueError('Ruta o entrada duplicada no válida dentro del 3MF.')
        names.add(name)
        if info.file_size > 96_000_000 or info.file_size/max(info.compress_size, 1) > 300:
            raise ValueError('Ratio de compresión o tamaño de archivo 3MF excesivo.')
        if name.endswith(('.model', '.config', '.rels', '.xml')):
            data = archive.read(info)
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise ValueError('Declaraciones XML externas no permitidas.')
            if name.endswith('.model'):
                root = ET.fromstring(data)
                roots[name] = root
    if '3D/3dmodel.model' not in roots: raise ValueError('Falta 3D/3dmodel.model.')
    objects = {name:{int(o.get('id')):o for o in root.findall('./m:resources/m:object', NS_3MF)} for name,root in roots.items()}
    visits = faces = 0
    def walk(name, oid, ancestors=()):
        nonlocal visits, faces
        key = (name, oid)
        visits += 1
        if key in ancestors or len(ancestors) > 12 or visits > 5000: raise ValueError('Componentes cíclicos o demasiadas instancias.')
        if name not in objects or oid not in objects[name]: raise ValueError('Componente 3MF inexistente.')
        obj = objects[name][oid]
        faces += len(obj.findall('./m:mesh/m:triangles/m:triangle', NS_3MF))
        if faces > MAX_FACES: raise ValueError('Máximo 2 millones de triángulos instanciados.')
        for c in obj.findall('./m:components/m:component', NS_3MF):
            path = next((v for k,v in c.attrib.items() if k.endswith('path')), name)
            child = path.lstrip('/') if path.startswith('/') or path == name else str(PurePosixPath(name).parent/path)
            if '..' in PurePosixPath(child).parts: raise ValueError('Ruta de componente no válida.')
            walk(child, int(c.get('objectid')), (*ancestors,key))
    main = roots['3D/3dmodel.model']
    items = main.findall('./m:build/m:item', NS_3MF)
    for item in items: walk('3D/3dmodel.model', int(item.get('objectid')))
    return dict(build_items=[dict(i.attrib) for i in items],
                objects=[dict(file=name, **o.attrib) for name,obs in objects.items() for o in obs.values()],
                metadata=[dict(name=m.get('name'), value=m.text or '') for m in main.findall('./m:metadata',NS_3MF)])


def analyze_3mf(path, *, cancel=None):
    path = Path(path)
    if path.stat().st_size > 128_000_000: raise ValueError('3MF comprimido mayor de 128 MB.')
    parts, warnings = [], []
    with zipfile.ZipFile(path) as archive:
        metadata = preflight(archive)
        check_cancel(cancel)
        palette = _read_3mf_filament_palette(archive)
        settings = _read_3mf_extruder_settings(archive)
        part_names = {}
        if 'Metadata/model_settings.config' in archive.namelist():
            root = ET.fromstring(archive.read('Metadata/model_settings.config'))
            for obj in [*root.findall('object'), *root.findall('.//part')]:
                for m in obj.findall('metadata'):
                    if m.get('key') == 'name': part_names[int(obj.get('id','0'))] = m.get('value','')
        def received(file, oid, name, geometry, slots, transform):
            check_cancel(cancel)
            if not np.isfinite(geometry).all() or np.abs(geometry).max() > 1e7:
                raise ValueError('Coordenadas 3MF inválidas o excesivas.')
            name = (name or part_names.get(oid) or f'Objeto {oid}')[:200]
            centered = geometry - geometry.min(axis=(0,1))
            fingerprint = hashlib.sha256(np.round(centered,5).tobytes()).hexdigest()
            hints = [word for word in ('text','name','base','border','ornament','hole','insert') if word in name.lower()]
            parts.append(Part(f'part_{len(parts)+1}', name, geometry,
                              [palette[s] for s in sorted(set(slots)) if s in palette],
                              transform.tolist(), fingerprint, hints))
        _load_3mf_triangles(archive, settings, warnings, palette, cancel=cancel, part_callback=received)
        preview = _read_embedded_preview(archive)
    if not parts: raise ValueError('No hay mallas imprimibles en el 3MF.')
    warnings.append('Nombres y formas son indicios; confirma las piezas de texto. No se recupera el diseño paramétrico original.')
    return Reference(parts, palette, metadata, preview, list(dict.fromkeys(warnings)))


def write_stl(path, triangles):
    triangles = np.asarray(triangles, dtype=np.float32)
    dtype = np.dtype([('normal','<f4',(3,)), ('vertices','<f4',(3,3)), ('attr','<u2')])
    records = np.zeros(len(triangles), dtype=dtype)
    records['vertices'] = triangles
    normals = np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0])
    lengths = np.linalg.norm(normals, axis=1)
    records['normal'] = normals / np.where(lengths > 0, lengths, 1)[:,None]
    Path(path).write_bytes(b'Toolbox SCAD Builder'.ljust(80,b'\0')+struct.pack('<I',len(records))+records.tobytes())
