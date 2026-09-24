"""Deterministic code generation and transactional ZIP export."""
from pathlib import Path
import copy
import hashlib
import io
import json
import os
import tempfile
import zipfile
import numpy as np
from PIL import Image, ImageDraw
from .model import SCHEMA, validate_parameters, literal, IDENTIFIER
from .scad_analysis import update_source
from .three_mf import write_stl


def variable(p): return p.get('scad_variable',p['id'])


def binding_variable(binding, parameters, fallback='base_color'):
    source=binding.get('source') if binding.get('mode')=='inherit' else fallback
    if source not in parameters or parameters[source]['type']!='color': raise ValueError('Color de pieza no válido.')
    seen=set()
    while parameters[source].get('color_binding',{}).get('mode')=='inherit':
        if source in seen: raise ValueError('Color circular.')
        seen.add(source);source=parameters[source]['color_binding']['source']
    return variable(parameters[source])


def generate(doc, *, pmm=False):
    params=validate_parameters(doc['parameters'])
    if doc.get('original_source'):
        return update_source(doc['original_source'],doc['parameters'])
    lines=['// reconstructed SCAD — BambuLab Toolbox. No original source recovered.', '/* [Parameters] */']
    derived=[]
    for p in doc['parameters']:
        binding=p.get('color_binding',{})
        if p['type']=='color' and binding.get('mode')=='inherit':
            derived.append(f'{variable(p)} = {binding_variable(binding,params)};');continue
        marker=' // '+p['type'] if p['type'] in ('color','font') else ''
        if p['type']=='select':
            # Labels/strings are escaped by literal in code; annotations must not introduce lines.
            options=[str(o['value']) for o in p['options']]
            if all(not any(c in o for c in '\n\r[],:') for o in options): marker=' // ['+', '.join(options)+']'
        elif p['type']=='number' and 'min' in p and 'max' in p: marker=f" // [{p['min']}:{p.get('step',.1)}:{p['max']}]"
        lines.append(f'{variable(p)} = {literal(p["default"])};{marker}')
    if pmm and any(e['mode']=='fixed' for e in doc['elements']): lines.append('base_file = "default.stl";')
    lines+=['/* [Hidden] */',*derived,'$fn = 64;','module core_model() {']
    fixed_in_pmm=False
    for e in doc['elements']:
        key=e['id'];mode=e['mode']
        if not IDENTIFIER.fullmatch(key): raise ValueError('ID de pieza inválido.')
        if mode=='ignore':continue
        if mode=='fixed' and pmm:
            if not fixed_in_pmm:lines.append('  color(base_color) import(base_file);');fixed_in_pmm=True
            continue
        color=binding_variable(e.get('color_binding',{'mode':'inherit','source':'base_color'}),params)
        if mode=='text':
            color=binding_variable(params[key].get('color_binding',{}),params,key+'_color')
            v=lambda suffix:variable(params[key+suffix])
            lines += [f'  translate([{v("_x")},{v("_y")},{v("_z")}])',
                      f'  rotate([{v("_rx")},{v("_ry")},{v("_rz")}])',
                      f'  color({color}) linear_extrude(height={v("_height")})',
                      f'  text({v("")},font={v("_font")},size={v("_size")},halign={v("_halign")},valign={v("_valign")},spacing={v("_spacing")});']
        elif mode=='fixed':
            asset=e.get('asset','')
            if not __import__('re').fullmatch(r'assets/[a-f0-9]{64}\.stl',asset): raise ValueError('Asset de pieza inválido.')
            lines.append(f'  translate({literal(e["bounds_min"])}) color({color}) import({literal(asset)});')
        elif mode in ('box','cylinder'):
            dims=[variable(params[key+'_dimension_'+axis]) for axis in 'xyz']
            if mode=='box':
                lines.append(f'  translate({literal(e["bounds_min"])}) color({color}) cube([{",".join(dims)}]);')
            else:
                lo=e['bounds_min'];hi=e['bounds_max'];center=[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]]
                lines.append(f'  translate({literal(center)}) color({color}) scale([1,{dims[1]}/{dims[0]},1]) cylinder(d={dims[0]},h={dims[2]});')
        else: raise ValueError('Modo de geometría no válido.')
    return '\n'.join([*lines,'}','core_model();',''])


def draw_preview(triangles, path):
    # Orthographic reference silhouette; actual SCAD render replaces this after validation.
    lo=triangles.min(axis=(0,1));hi=triangles.max(axis=(0,1))
    scale=460/max(float(np.max((hi-lo)[:2])),1e-9)
    im=Image.new('RGB',(512,512),'#19212b');draw=ImageDraw.Draw(im)
    step=max(1,len(triangles)//100000)
    for tri in triangles[::step]:
        pts=(tri[:,:2]-(lo[:2]+hi[:2])/2)*scale+256
        draw.polygon([(float(p[0]),512-float(p[1])) for p in pts],fill='#e9c7da')
    im.save(path)


def prepare_package(directory, document, reference=None, assets=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'assets').mkdir(exist_ok=True)
    doc=copy.deepcopy(document)
    if doc.get('schema')!=SCHEMA: raise ValueError('Versión de modelo intermedio no compatible.')
    fixed=[]
    for e in doc['elements']:
        if reference:
            part=next(p for p in reference.parts if p.id==e['id'])
            triangles=part.triangles-np.array(e['bounds_min'])
            digest=hashlib.sha256(triangles.astype('<f4').tobytes()).hexdigest()
            e['asset']='assets/'+digest+'.stl'
            write_stl(directory/e['asset'],triangles)
            if e['mode']=='fixed':fixed.append(part.triangles)
        elif assets and e.get('asset') in assets:
            name=e['asset']
            if not __import__('re').fullmatch(r'assets/[a-f0-9]{64}\.stl',name):raise ValueError('Asset no válido.')
            (directory/name).write_bytes(assets[name])
            if e['mode']=='fixed':
                from ..stl_color_map import load_stl
                fixed.append(load_stl(directory/name)+np.array(e['bounds_min']))
    # Assets for all reference parts are retained, including ignored/text pieces, for reopening.
    source=generate(doc)
    (directory/'model.scad').write_text(source,encoding='utf-8')
    if doc.get('original_source'):
        (directory/'original.scad').write_text(doc['original_source'],encoding='utf-8')
    else:
        (directory/'makerworld.scad').write_text(generate(doc,pmm=True),encoding='utf-8')
        if fixed:write_stl(directory/'default.stl',np.concatenate(fixed))
    info=doc['source_info']
    if fixed: info['warnings']=list(dict.fromkeys([*info['warnings'],'PMM: subir default.stl con makerworld.scad. El STL combinado no conserva colores separados; model.scad sí mantiene roles por pieza.']))
    info['preview_kind']='reference_silhouette' if reference or assets else 'not_rendered'
    info['configuration_id']=hashlib.sha256(source.encode()).hexdigest()
    if reference:draw_preview(reference.triangles,directory/'preview.png')
    elif assets and doc['elements']:
        from ..stl_color_map import load_stl
        combined=[load_stl(directory/e['asset'])+np.array(e['bounds_min']) for e in doc['elements'] if (directory/e.get('asset','missing')).is_file()]
        if combined:draw_preview(np.concatenate(combined),directory/'preview.png')
    if not (directory/'preview.png').exists():
        im=Image.new('RGB',(512,512),'#19212b');ImageDraw.Draw(im).text((20,245),'OpenSCAD render pending',fill='white');im.save(directory/'preview.png')
    for name,data in [('model-parameters.json',doc),('source-info.json',info)]:
        (directory/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (directory/'UPLOAD-PMM.txt').write_text('Paquete local: model.scad + assets/.\nPMM: makerworld.scad + carga manual de default.stl si existe.\nNo presupone soporte para assets arbitrarios. Comprueba fuentes, dimensiones y exportación en PMM.\npreview.png es la referencia, no prueba de equivalencia.\n',encoding='utf-8')
    return doc


def export_package(path,document,reference=None,assets=None):
    path=Path(path)
    with tempfile.TemporaryDirectory(prefix='toolbox-scad-') as temp:
        package=Path(temp)/'model'
        prepare_package(package,document,reference,assets)
        fd,staging=tempfile.mkstemp(prefix='.scad-',suffix='.zip',dir=path.parent);os.close(fd)
        try:
            with zipfile.ZipFile(staging,'w',zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(package.rglob('*')):
                    if file.is_file():archive.write(file,'model/'+file.relative_to(package).as_posix())
            os.replace(staging,path)
        finally:
            if os.path.exists(staging):os.unlink(staging)
    return path


def open_package(path):
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist()
        if len(infos)>6000 or sum(i.file_size for i in infos)>256_000_000:raise ValueError('Paquete demasiado grande.')
        seen=set()
        for i in infos:
            if i.filename in seen or '..' in Path(i.filename).parts or '\\' in i.filename or i.filename.startswith('/') or i.file_size/max(i.compress_size,1)>300:
                raise ValueError('Paquete no válido.')
            seen.add(i.filename)
        doc=json.loads(archive.read('model/model-parameters.json'))
        if doc.get('schema')!=SCHEMA:raise ValueError('Esquema no compatible.')
        validate_parameters(doc['parameters'])
        assets={i.filename[6:]:archive.read(i) for i in infos if __import__('re').fullmatch(r'model/assets/[a-f0-9]{64}\.stl',i.filename)}
    return doc,assets
