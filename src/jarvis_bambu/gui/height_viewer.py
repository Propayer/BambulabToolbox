from __future__ import annotations
import math
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QWidget
from ..core.stl_color_map import STLHeightMap, normalize_cuts
from ..core.height_raster import DIAGNOSTIC_COLORS
_ZONE_COLORS = [QColor(c) for c in DIAGNOSTIC_COLORS]

class STLMapPreview(QWidget):
    """Optional interactive 3D software renderer.

    It stays completely unloaded until the user explicitly enables it. This is
    intentional: the color-map tool must remain safe on modest PCs.
    """

    heightPicked = Signal(float)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(440, 420)
        self.setMouseTracking(True)
        self._map: STLHeightMap | None = None
        self._cuts: list[float] = []
        self._yaw = math.radians(-28)
        self._pitch = math.radians(20)
        self._pan = np.zeros(2)
        self._zoom = 0.92
        self._last_pos = None
        self._press_pos = None
        self._selected_height: float | None = None
        self._projected: list[tuple[list[QPointF], np.ndarray, float]] = []
        self._render_geometry: list[tuple[int, np.ndarray]] = []

    def set_model(self, height_map: STLHeightMap | None):
        self._map = height_map
        self._selected_height = None

        self.update()

    def clear_model(self):
        self._map = None
        self._cuts = []
        self._projected = []
        self._render_geometry = []
        self._selected_height = None
        self.update()

    def set_cuts(self, cuts, geometry=None):
        if self._map:
            self._cuts = normalize_cuts(cuts, self._map.z_min, self._map.z_max)
        else:
            self._cuts = []
        self._render_geometry = geometry or []
        self.update()

    def view_state(self) -> dict:
        return {
            "projection": "software_3d",
            "yaw_degrees": round(math.degrees(self._yaw), 3),
            "pitch_degrees": round(math.degrees(self._pitch), 3),
            "zoom": round(self._zoom, 4),
        }

    def reset_view(self):
        self._yaw = math.radians(-28)
        self._pitch = math.radians(20)
        self._pan = np.zeros(2)
        self._zoom = 0.92
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._last_pos = event.position()
            self._press_pos = event.position()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._last_pos is not None and event.buttons() & Qt.RightButton:
            delta = event.position() - self._last_pos
            self._pan += (delta.x(), delta.y()); self._last_pos = event.position(); self.update()
            return
        if self._last_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.position() - self._last_pos
            self._yaw += delta.x() * 0.01
            self._pitch = max(-1.35, min(1.35, self._pitch + delta.y() * 0.008))
            self._last_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return
        start = self._press_pos
        self._last_pos = None
        self._press_pos = None
        if start is None or (event.position() - start).manhattanLength() > 6:
            return
        picked = self._pick_height(event.position())
        if picked is not None:
            self._selected_height = picked
            self.heightPicked.emit(float(picked))
            self.update()

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self._zoom = max(0.25, min(4.0, self._zoom * factor))
        self.update()

    def _rotation(self):
        cy, sy = math.cos(self._yaw), math.sin(self._yaw)
        cp, sp = math.cos(self._pitch), math.sin(self._pitch)
        ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
        rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], dtype=float)
        return rx @ ry

    def _scene(self, width: int, height: int):
        if not self._map:
            return []
        bounds = np.array([self._map.summary.bounds_min, self._map.summary.bounds_max])
        center = bounds.mean(axis=0)
        rotation = self._rotation()
        corners = np.array([
            [x, y, z]
            for x in (bounds[0, 0], bounds[1, 0])
            for y in (bounds[0, 1], bounds[1, 1])
            for z in (bounds[0, 2], bounds[1, 2])
        ])
        rotated_corners = (corners - center) @ rotation.T
        extent = np.ptp(rotated_corners[:, :2], axis=0)
        scale = min(width * 0.82 / max(extent[0], 1e-9), height * 0.82 / max(extent[1], 1e-9)) * self._zoom
        offset = np.array([width / 2.0, height / 2.0]) + self._pan

        scene = []
        for zone, original in self._render_geometry:
            tri = (original - center) @ rotation.T
            xy = tri[:, :2].copy()
            xy[:, 1] *= -1
            xy = xy * scale + offset
            scene.append((xy, original, tri, float(tri[:, 2].mean()), zone))
        scene.sort(key=lambda item: item[3])
        return scene

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), self.palette().window())
        if not self._map:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), Qt.AlignCenter, "Renderizado 3D detenido")
            painter.end()
            return

        scene = self._scene(self.width(), self.height())
        self._projected = []
        light = np.array([0.25, -0.4, 0.88], dtype=float)
        light /= np.linalg.norm(light)
        edge = QPen(self.palette().mid().color(), 0.6)

        for xy, original, transformed, depth, zone in scene:
            poly = QPolygonF([QPointF(float(x), float(y)) for x, y in xy])
            a, b, c = transformed
            normal = np.cross(b - a, c - a)
            length = np.linalg.norm(normal)
            brightness = 0.68 if length < 1e-9 else 0.62 + 0.30 * abs(float(np.dot(normal / length, light)))
            base = _ZONE_COLORS[zone % len(_ZONE_COLORS)]
            color = QColor(
                min(255, int(base.red() * brightness)),
                min(255, int(base.green() * brightness)),
                min(255, int(base.blue() * brightness)),
            )
            painter.setBrush(color)
            painter.setPen(edge)
            painter.drawPolygon(poly)
            self._projected.append(([QPointF(p) for p in poly], original[:, 2].copy(), transformed[:,2].copy()))

        if self._selected_height is not None:
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            painter.drawText(14, 24, f"Altura seleccionada: {self._selected_height:.3f} mm")
        painter.end()

    def _pick_height(self, point: QPointF) -> float | None:
        best_depth = -float('inf')
        picked = None
        for vertices, z_values, depths in self._projected:
            bary = _barycentric(point, vertices)
            if bary is None:
                continue
            depth = float(np.dot(bary, depths))
            if depth > best_depth:
                best_depth = depth
                picked = float(np.dot(bary, z_values))
        return picked


def _barycentric(point: QPointF, vertices: list[QPointF]):
    if len(vertices) != 3:
        return None
    x, y = point.x(), point.y()
    x1, y1 = vertices[0].x(), vertices[0].y()
    x2, y2 = vertices[1].x(), vertices[1].y()
    x3, y3 = vertices[2].x(), vertices[2].y()
    denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(denom) < 1e-9:
        return None
    a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / denom
    b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / denom
    c = 1.0 - a - b
    if a < -1e-6 or b < -1e-6 or c < -1e-6:
        return None
    return a, b, c

