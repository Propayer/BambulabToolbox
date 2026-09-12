"""Reproducible synthetic relief benchmark; no Qt, printer or external fixtures."""
import json
from pathlib import Path
import time
import numpy as np
from jarvis_bambu.core.stl_color_map import _build_height_map


def main():
    count=100
    y,x=np.mgrid[:count,:count]
    x=x.ravel().astype(float);y=y.ravel().astype(float)
    z=1+(x>33)+(x>66)
    a=np.stack((x,y,z),axis=1);b=a+[1,0,0];c=a+[1,1,0];d=a+[0,1,0]
    triangles=np.concatenate((np.stack((a,b,c),axis=1),np.stack((a,c,d),axis=1)))
    start=time.perf_counter()
    m=_build_height_map(Path('synthetic-relief.stl'),triangles,sample_count=180,source_type='stl')
    analyzed=time.perf_counter()
    raster=m.top_raster(512);rendered=time.perf_counter()
    for i in range(50):raster.labels([1.2+i*.01,2.5])
    edited=time.perf_counter()
    print(json.dumps({'triangles':len(triangles),'resolution':512,'analysis_seconds':analyzed-start,
        'first_raster_seconds':rendered-analyzed,'cut_edit_mean_seconds':(edited-rendered)/50,
        'depth_and_face_bytes':raster.depth.nbytes+raster.face.nbytes},indent=2))

if __name__=='__main__':main()
