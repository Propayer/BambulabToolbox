"""Bounded geometry for the optional diagnostic viewer; never used for export."""
import numpy as np

def preview_geometry(height_map, cuts, limit=6000):
    triangles = height_map.triangles
    if len(triangles) > limit:
        triangles = triangles[np.linspace(0,len(triangles)-1,limit,dtype=int)]
    from .stl_color_map import split_triangles_by_height_zones
    return split_triangles_by_height_zones(triangles, cuts, height_map.z_min, height_map.z_max)
