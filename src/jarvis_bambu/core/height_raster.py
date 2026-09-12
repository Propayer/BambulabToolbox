"""Orthographic +Z visibility, independent of Qt and of zone boundaries.

Samples pixel centres. Each covered pixel stores the maximum interpolated Z;
vertical/degenerate projected triangles cover no area. No mesh subsampling.
"""
from dataclasses import dataclass
from typing import Callable
import numpy as np

DIAGNOSTIC_COLORS = ('#72E2C0', '#FFCA65', '#70BAFF', '#FF91C3', '#BBAAFF', '#F5F7EF',
                     '#FF896B', '#C8E875', '#65E5ED', '#E8A8FF', '#AFBFFF', '#DFCAAA')


class CancelledError(Exception):
    pass


def check_cancel(cancel):
    if cancel and cancel():
        raise CancelledError('Operación cancelada.')


@dataclass(slots=True)
class TopRaster:
    depth: np.ndarray
    face: np.ndarray
    center_xy: tuple[float, float]
    pixels_per_mm: float

    def labels(self, cuts):
        labels = np.searchsorted(np.asarray(cuts), self.depth, side='right').astype(np.int16)
        labels[self.face < 0] = -1
        return labels

    def rgba(self, labels, colors=DIAGNOSTIC_COLORS, zone=None, neutral=False):
        result = np.zeros((*labels.shape, 4), dtype=np.uint8)
        visible = labels >= 0 if zone is None else labels == zone
        if neutral or zone is not None:
            color = '#FFFFFF' if neutral else colors[zone % len(colors)]
            result[visible, :3] = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
        else:
            palette = np.array([[int(c[i:i+2], 16) for i in (1, 3, 5)] for c in colors], dtype=np.uint8)
            result[visible, :3] = palette[labels[visible] % len(palette)]
        result[visible, 3] = 255
        return result


def rasterize_top(triangles, size=512, *, cancel=None, progress=None):
    if not 64 <= size <= 2048:
        raise ValueError('La resolución debe estar entre 64 y 2048 píxeles.')
    if triangles.shape[1:] != (3, 3) or not len(triangles) or not np.isfinite(triangles).all():
        raise ValueError('No se encontró mesh válida con coordenadas finitas.')
    lo = triangles.min(axis=(0, 1)); hi = triangles.max(axis=(0, 1))
    span = hi[:2] - lo[:2]
    if np.any(span <= 1e-12):
        raise ValueError('El modelo degenerado no tiene una huella XY con área.')
    center = (lo[:2] + hi[:2]) * .5
    scale = size * .88 / float(span.max())
    depth = np.full((size, size), -np.inf, dtype=np.float64)
    face = np.full((size, size), -1, dtype=np.int32)
    # Transform in bounded batches, and never allocate a mesh-sized pixel grid.
    for start in range(0, len(triangles), 1024):
        check_cancel(cancel)
        batch = triangles[start:start + 1024]
        xy = (batch[:, :, :2] - center) * (scale, -scale) + size / 2
        for j, (tri, coords) in enumerate(zip(batch, xy)):
            a, b, c = coords
            den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(den) < 1e-12:
                continue
            xmin, ymin = np.maximum(np.ceil(coords.min(axis=0)-.5).astype(int), 0)
            xmax, ymax = np.minimum(np.floor(coords.max(axis=0)-.5).astype(int), size-1)
            if xmin > xmax or ymin > ymax:
                continue
            x = np.arange(xmin, xmax+1)[None, :] + .5
            # 32 rows bounds temporary memory even for giant projected faces.
            for row in range(ymin, ymax+1, 32):
                check_cancel(cancel)
                end = min(row+32, ymax+1)
                y = np.arange(row, end)[:, None] + .5
                u = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den
                v = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den
                w = 1-u-v
                z = tri[2,2] + u*(tri[0,2]-tri[2,2]) + v*(tri[1,2]-tri[2,2])
                current = depth[row:end, xmin:xmax+1]
                use = (u >= -1e-10) & (v >= -1e-10) & (w >= -1e-10) & (z > current)
                current[use] = z[use]
                face[row:end, xmin:xmax+1][use] = start+j
        if progress:
            progress(min(100, int((start+len(batch))*100/len(triangles))))
    if not np.any(face >= 0):
        raise ValueError('El modelo degenerado no tiene superficies visibles desde +Z a esta resolución.')
    return TopRaster(depth, face, tuple(center), scale)
