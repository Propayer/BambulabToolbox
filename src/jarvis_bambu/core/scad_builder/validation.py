"""Approximate geometry checks: not a CAD equivalence proof."""
import numpy as np
from PIL import Image, ImageDraw


def metrics(triangles):
    t=np.asarray(triangles)
    lo,hi=t.min(axis=(0,1)),t.max(axis=(0,1))
    result=dict(bounds_min=lo.tolist(),bounds_max=hi.tolist(),dimensions=(hi-lo).tolist(),triangles=len(t),
                volume=None,components=None,watertight=None)
    if len(t)>200000:
        result['note']='Volumen/componentes omitidos para mantener el análisis ligero (>200000 caras).';return result
    points,inverse=np.unique(np.round(t.reshape(-1,3),6),axis=0,return_inverse=True)
    indices=inverse.reshape(-1,3)
    parent=np.arange(len(points))
    def root(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    edges=np.sort(np.concatenate([indices[:,[0,1]],indices[:,[1,2]],indices[:,[2,0]]]),axis=1)
    _,counts=np.unique(edges,axis=0,return_counts=True)
    for a,b in edges:parent[root(a)]=root(b)
    result['components']=len({root(i) for i in range(len(points))})
    result['watertight']=bool(np.all(counts==2))
    if result['watertight']:
        # Signed component volume avoids cancelling oppositely wound disconnected components.
        signed=np.einsum('ij,ij->i',t[:,0],np.cross(t[:,1],t[:,2]))/6
        volumes={}
        for tri,v in zip(indices,signed):
            key=root(tri[0]);volumes[key]=volumes.get(key,0.)+float(v)
        result['volume']=sum(abs(v) for v in volumes.values())
    return result


def compare(reference,generated):
    before,after=metrics(reference),metrics(generated)
    lo=np.minimum(before['bounds_min'],after['bounds_min']);hi=np.maximum(before['bounds_max'],after['bounds_max'])
    scale=120/max(float(np.max((hi-lo)[:2])),1e-9)
    def silhouette(t):
        im=Image.new('1',(128,128));draw=ImageDraw.Draw(im)
        step=max(1,len(t)//100000)
        for tri in t[::step]:
            p=(tri[:,:2]-lo[:2])*scale+4;draw.polygon([tuple(q) for q in p],fill=1)
        return np.asarray(im)
    a,b=silhouette(reference),silhouette(generated)
    union=np.logical_or(a,b).sum()
    return dict(reference=before,generated=after,
                dimensions_delta_mm=(np.array(after['dimensions'])-before['dimensions']).tolist(),
                position_delta_mm=(np.array(after['bounds_min'])-before['bounds_min']).tolist(),
                top_silhouette_iou=float(np.logical_and(a,b).sum()/union) if union else 1.,
                note='Comparación aproximada; silueta raster 128 px, muestreo en mallas grandes. No garantiza equivalencia ni imprimibilidad.')
