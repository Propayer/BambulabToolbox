"""Conservative proposals and explicit human choices; complex parts remain meshes."""
import numpy as np
import hashlib
from .model import SCHEMA, parameter, text_parameters


def propose(part):
    t = part.triangles
    lo, hi = t.min(axis=(0,1)), t.max(axis=(0,1))
    size = hi-lo
    if np.any(size <= 1e-6): return 'fixed'
    # A box must have exactly the eight corners and six fully covered faces.
    vertices = np.unique(np.round(t.reshape(-1,3),6), axis=0)
    if len(vertices) == 8 and np.all(np.isclose(vertices,lo,atol=1e-5)|np.isclose(vertices,hi,atol=1e-5)):
        areas = np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1)/2
        for axis in range(3):
            expected = np.prod(np.delete(size,axis))
            for edge in (lo[axis],hi[axis]):
                face = np.all(np.isclose(t[:,:,axis],edge,atol=1e-5),axis=1)
                if not np.isclose(areas[face].sum(),expected,rtol=1e-5): return 'fixed'
        return 'box'
    # Cylinder proposal only: two Z planes, circular perimeter (+ optional centers).
    center=(lo+hi)/2
    r=np.linalg.norm(vertices[:,:2]-center[:2],axis=1)
    if len(vertices)>=16 and np.all(np.isclose(vertices[:,2],lo[2])|np.isclose(vertices[:,2],hi[2])) and np.all(np.isclose(r,size[0]/2,rtol=.015)|(r<1e-5)) and np.isclose(size[0],size[1],rtol=.015):
        return 'cylinder'
    return 'fixed'


def new_document(reference=None, source_info=None, source=None):
    info = dict(source_url='', source_platform='local', original_scad_available=bool(source),
                source_3mf=None, warnings=[])
    info.update(source_info or {})
    info.pop('original_scad',None)
    info['reconstruction_mode'] = 'original source recovered' if source else 'reconstructed SCAD'
    doc = dict(schema=SCHEMA, parameters=[], elements=[], source_info=info,
               original_source=source, analysis={}, reference_metadata={})
    if source:
        from .scad_analysis import analyze_scad
        analysis = analyze_scad(source)
        doc.update(parameters=analysis['parameters'], analysis={k:v for k,v in analysis.items() if k!='spans'})
        info['warnings'] += analysis['warnings']
    else:
        doc['parameters'] = [parameter('base_color','color','#E9C7DA')]
    if reference:
        doc['reference_metadata'] = reference.metadata
        info['warnings'] += reference.warnings
        for p in reference.parts:
            meta=p.metadata()
            digest=hashlib.sha256((p.triangles-np.array(meta['bounds_min'])).astype('<f4').tobytes()).hexdigest()
            meta['asset']='assets/'+digest+'.stl'
            doc['elements'].append(dict(**meta, mode='fixed', proposal=propose(p),
                                        color_binding={'mode':'inherit','source':'base_color'}))
    return doc


def set_mode(doc, element_id, mode):
    if mode not in ('fixed','text','ignore','box','cylinder'): raise ValueError('Modo de pieza no válido.')
    element=next(e for e in doc['elements'] if e['id']==element_id)
    element['mode']=mode
    if mode == 'text' and not any(p['id']==element_id for p in doc['parameters']):
        lo,hi=np.array(element['bounds_min']),np.array(element['bounds_max'])
        doc['parameters'].extend(text_parameters(element_id, ((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]),hi[2]-lo[2]))
    if mode in ('box','cylinder'):
        for axis,value in zip('xyz',element['dimensions']):
            key=element_id+'_dimension_'+axis
            if not any(p['id']==key for p in doc['parameters']): doc['parameters'].append(parameter(key,'number',float(value),min=.01,max=1e6))
