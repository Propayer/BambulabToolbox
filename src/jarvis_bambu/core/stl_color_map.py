from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
import json
import struct
import zipfile
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET

import numpy as np
from .height_raster import check_cancel


CORE_3MF = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PRODUCTION_3MF = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
NS_3MF = {"m": CORE_3MF, "p": PRODUCTION_3MF}


@dataclass(frozen=True, slots=True)
class HeightZone:
    id: str
    label: str
    z_from: float
    z_to: float


@dataclass(frozen=True, slots=True)
class HeightMapProposal:
    id: str
    name: str
    description: str
    cuts: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MeshSummary:
    source_name: str
    triangle_count: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]

    @property
    def height(self) -> float:
        return self.bounds_max[2] - self.bounds_min[2]


@dataclass(frozen=True, slots=True)
class DetectedColor:
    slot: int
    color: str
    triangle_count: int
    z_min: float
    z_max: float
    median_z: float


@dataclass(slots=True)
class STLHeightMap:
    """Common analyzed model used by the STL/3MF color-map tool.

    The historical class name is kept for compatibility with the first tool
    version, but instances may now come from either STL or 3MF sources.
    """

    triangles: np.ndarray
    summary: MeshSummary
    proposals: tuple[HeightMapProposal, ...]
    source_type: str = "stl"
    embedded_preview: bytes | None = None
    triangle_slots: np.ndarray | None = None
    detected_colors: tuple[DetectedColor, ...] = ()

    warnings: tuple[str, ...] = ()
    profile: np.ndarray | None = None
    _rasters: dict = field(default_factory=dict, repr=False)

    def top_raster(self, size=512, *, cancel=None, progress=None):
        from .height_raster import rasterize_top, check_cancel
        check_cancel(cancel)
        if size not in self._rasters:
            raster = rasterize_top(self.triangles, size, cancel=cancel, progress=progress)
            # Keep at most two resolutions (light + current export).
            if len(self._rasters) >= 2:
                self._rasters.pop(next(iter(self._rasters)))
            self._rasters[size] = raster
        return self._rasters[size]

    @property
    def z_min(self) -> float:
        return self.summary.bounds_min[2]

    @property
    def z_max(self) -> float:
        return self.summary.bounds_max[2]

    def zones(self, cuts: Sequence[float]) -> list[HeightZone]:
        normalized = normalize_cuts(cuts, self.z_min, self.z_max)
        bounds = [self.z_min, *normalized, self.z_max]
        return [
            HeightZone(
                id=f"color_{index + 1}",
                label=f"Color {index + 1}",
                z_from=float(bounds[index]),
                z_to=float(bounds[index + 1]),
            )
            for index in range(len(bounds) - 1)
        ]


SUPPORTED_MODEL_EXTENSIONS = frozenset({".stl", ".3mf"})


def analyze_model(path: str | Path, sample_count: int = 180, *, cancel=None) -> STLHeightMap:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".stl":
        return analyze_stl(path, sample_count=sample_count, cancel=cancel)
    if suffix == ".3mf":
        return analyze_3mf(path, sample_count=sample_count, cancel=cancel)
    raise ValueError("Formato no compatible. Usa STL o 3MF.")


def load_stl(path: str | Path, *, cancel=None) -> np.ndarray:
    path = Path(path)
    check_cancel(cancel)
    data = path.read_bytes()
    check_cancel(cancel)
    if len(data) < 15:
        raise ValueError("El STL está vacío o incompleto.")

    triangles = _load_binary_stl(data)
    if triangles is None:
        triangles = _load_ascii_stl(data, cancel=cancel)

    if triangles.size == 0:
        raise ValueError("No se encontraron triángulos válidos en el STL.")
    if not np.isfinite(triangles).all():
        raise ValueError("El STL contiene coordenadas no válidas.")
    return triangles.astype(np.float64, copy=False)


def _load_binary_stl(data: bytes) -> np.ndarray | None:
    if len(data) < 84:
        return None
    count = struct.unpack_from("<I", data, 80)[0]
    expected = 84 + count * 50
    if count <= 0 or expected != len(data):
        return None

    dtype = np.dtype([
        ("normal", "<f4", (3,)),
        ("vertices", "<f4", (3, 3)),
        ("attr", "<u2"),
    ])
    records = np.frombuffer(data, dtype=dtype, count=count, offset=84)
    return records["vertices"].astype(np.float64)


def _load_ascii_stl(data: bytes, *, cancel=None) -> np.ndarray:
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception as exc:
        raise ValueError("No se pudo leer el STL.") from exc

    vertices: list[list[float]] = []
    for index, raw in enumerate(text.splitlines()):
        if index % 8192 == 0: check_cancel(cancel)
        line = raw.strip()
        if not line.lower().startswith("vertex "):
            continue
        parts = line.split()
        if len(parts) != 4:
            continue
        try:
            vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
        except ValueError:
            continue

    usable = len(vertices) - (len(vertices) % 3)
    if usable == 0:
        return np.empty((0, 3, 3), dtype=np.float64)
    return np.asarray(vertices[:usable], dtype=np.float64).reshape((-1, 3, 3))


def analyze_stl(path: str | Path, sample_count: int = 180, *, cancel=None) -> STLHeightMap:
    path = Path(path)
    triangles = load_stl(path, cancel=cancel)
    check_cancel(cancel)
    return _build_height_map(path, triangles, sample_count=sample_count, source_type="stl")


def analyze_3mf(path: str | Path, sample_count: int = 180, *, cancel=None) -> STLHeightMap:
    path = Path(path)
    check_cancel(cancel)
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "3D/3dmodel.model" not in names:
                raise ValueError("El 3MF no contiene 3D/3dmodel.model.")
            palette = _read_3mf_filament_palette(archive)
            settings = _read_3mf_extruder_settings(archive)
            warnings = []
            triangles, slots = _load_3mf_triangles(archive, settings, warnings, palette, cancel=cancel)
            preview = _read_embedded_preview(archive)
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo 3MF no es un contenedor válido.") from exc

    except ET.ParseError as exc:
        raise ValueError("El 3MF contiene XML inválido o incompleto.") from exc
    check_cancel(cancel)
    if triangles.size == 0:
        raise ValueError("No se encontraron mallas utilizables en el 3MF.")
    detected = _detected_colors(triangles, slots, palette)
    return _build_height_map(
        path,
        triangles,
        sample_count=sample_count,
        source_type="3mf",
        embedded_preview=preview,
        triangle_slots=slots,
        detected_colors=detected,
        warnings=tuple(warnings),
    )


def _build_height_map(
    path: Path,
    triangles: np.ndarray,
    *,
    sample_count: int,
    source_type: str,
    embedded_preview: bytes | None = None,
    triangle_slots: np.ndarray | None = None,
    detected_colors: tuple[DetectedColor, ...] = (),
    warnings: tuple[str, ...] = (),
) -> STLHeightMap:
    if not triangles.size or not np.isfinite(triangles).all():
        raise ValueError("No se encontró mesh válida con coordenadas finitas.")
    valid = np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0]), axis=1) > 1e-12
    if not valid.any():
        raise ValueError("El modelo degenerado no contiene triángulos con área.")
    if not valid.all():
        triangles = triangles[valid]
        if triangle_slots is not None:
            triangle_slots = triangle_slots[valid]
    if triangle_slots is not None and detected_colors:
        detected_colors = _detected_colors(triangles, triangle_slots, {c.slot:c.color for c in detected_colors})
    mins = triangles.reshape(-1, 3).min(axis=0)
    maxs = triangles.reshape(-1, 3).max(axis=0)
    height = float(maxs[2] - mins[2])
    if height <= 1e-7:
        raise ValueError("El modelo no tiene altura Z suficiente para crear un mapa.")

    summary = MeshSummary(
        source_name=path.name,
        triangle_count=int(len(triangles)),
        bounds_min=tuple(float(x) for x in mins),
        bounds_max=tuple(float(x) for x in maxs),
    )
    profile = geometry_profile(triangles, float(mins[2]), float(maxs[2]), sample_count)
    proposals = list(propose_height_maps(profile, float(mins[2]), float(maxs[2])))
    guided = propose_color_guided_map(triangles, triangle_slots, detected_colors, float(mins[2]), float(maxs[2]))
    if guided is not None:
        proposals.insert(0, guided)
    return STLHeightMap(
        triangles=triangles,
        summary=summary,
        proposals=tuple(proposals),
        source_type=source_type,
        embedded_preview=embedded_preview,
        triangle_slots=triangle_slots,
        detected_colors=detected_colors,
        warnings=tuple(dict.fromkeys((*warnings, *color_height_warnings(triangles, triangle_slots)))),
        profile=profile,
    )


def _read_embedded_preview(archive: zipfile.ZipFile) -> bytes | None:
    from ..model_preview import read_3mf_preview
    return read_3mf_preview(archive)


def _read_3mf_filament_palette(archive: zipfile.ZipFile) -> dict[int, str]:
    colors: dict[int, str] = {}
    if "Metadata/slice_info.config" in archive.namelist():
        try:
            root = ET.fromstring(archive.read("Metadata/slice_info.config"))
            for node in root.findall(".//filament"):
                slot = int(node.attrib.get("id", "0") or 0)
                color = _normalize_hex(node.attrib.get("color", ""))
                if slot > 0 and color:
                    colors[slot] = color
        except (ET.ParseError, ValueError):
            pass
    if "Metadata/project_settings.config" in archive.namelist():
        try:
            data = json.loads(archive.read("Metadata/project_settings.config"))
            values = data.get("filament_colour") or data.get("filament_multi_colour") or []
            if isinstance(values, str):
                values = [values]
            for index, raw in enumerate(values, 1):
                color = _normalize_hex(str(raw))
                if color and index not in colors:
                    colors[index] = color
        except (json.JSONDecodeError, TypeError):
            pass
    return colors


def _normalize_hex(value: str) -> str:
    value = value.strip().upper()
    if len(value) == 9 and value.startswith("#"):
        value = value[:7]
    if len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
            return value
        except ValueError:
            return ""
    return ""


def _read_3mf_extruder_settings(archive: zipfile.ZipFile) -> dict[int, tuple[int, dict[int, int]]]:
    result: dict[int, tuple[int, dict[int, int]]] = {}
    name = "Metadata/model_settings.config"
    if name not in archive.namelist():
        return result
    try:
        root = ET.fromstring(archive.read(name))
    except ET.ParseError:
        return result

    for obj in root.findall("object"):
        try:
            object_id = int(obj.attrib["id"])
        except (KeyError, ValueError):
            continue
        default_slot = _metadata_int(obj, "extruder", 0)
        part_slots: dict[int, int] = {}
        for part in obj.findall("part"):
            try:
                part_id = int(part.attrib.get("id", "0") or 0)
            except ValueError:
                continue
            part_slots[part_id] = _metadata_int(part, "extruder", default_slot)
        result[object_id] = (default_slot, part_slots)
    return result


def _metadata_int(parent: ET.Element, key: str, default: int = 0) -> int:
    for node in parent.findall("metadata"):
        if node.attrib.get("key") == key:
            try:
                return int(float(node.attrib.get("value", default)))
            except (TypeError, ValueError):
                return default
    return default


def _load_3mf_triangles(
    archive: zipfile.ZipFile,
    settings: dict[int, tuple[int, dict[int, int]]],
    warnings: list[str] | None = None,
    palette: dict[int, str] | None = None,
    *, cancel=None, part_callback=None,
) -> tuple[np.ndarray, np.ndarray]:
    roots: dict[str, ET.Element] = {}
    objects = {}
    materials = {}
    warnings = warnings if warnings is not None else []
    palette = palette if palette is not None else {}
    unit_scale = {'micron': .001, 'millimeter': 1., 'centimeter': 10., 'inch': 25.4, 'foot': 304.8, 'meter': 1000.}

    def material_slot(model_name, pid, index):
        key = (model_name, pid, index)
        return materials.get(key, 0)


    def root_for(name: str) -> ET.Element:
        normalized = str(PurePosixPath(name.lstrip("/")))
        check_cancel(cancel)
        if normalized not in roots:
            if normalized not in archive.namelist():
                raise ValueError(f"El 3MF referencia un componente inexistente: {normalized}")
            roots[normalized] = ET.fromstring(archive.read(normalized))
            root = roots[normalized]
            objects[id(root)] = {int(o.attrib['id']): o for o in root.findall('./m:resources/m:object', NS_3MF)}
            for resource in root.findall('./m:resources/*', NS_3MF):
                if resource.tag.rsplit('}', 1)[-1] not in ('basematerials', 'colorgroup'):
                    continue
                for index, item in enumerate(resource):
                    color = _normalize_hex(item.get('displaycolor', item.get('color', '')))
                    if color:
                        slot = next((k for k,v in palette.items() if v == color), max(palette, default=0)+1)
                        palette[slot] = color
                        materials[(normalized, resource.get('id'), str(index))] = slot
        return roots[normalized]

    main_name = "3D/3dmodel.model"
    main = root_for(main_name)
    pieces: list[np.ndarray] = []
    piece_slots: list[np.ndarray] = []

    def find_object(root: ET.Element, object_id: int) -> ET.Element | None:
        return objects[id(root)].get(object_id)

    def walk_object(
        model_name: str,
        object_id: int,
        transform: np.ndarray,
        default_slot: int,
        part_slots: dict[int, int],
        depth: int = 0,
    ) -> None:
        if depth > 12:
            raise ValueError("El 3MF contiene componentes recursivos demasiado profundos.")
        model_name = str(PurePosixPath(model_name.lstrip("/")))
        root = root_for(model_name)
        obj = find_object(root, object_id)
        if obj is None:
            raise ValueError(f"El 3MF referencia el objeto inexistente {object_id}.")
        mesh = obj.find("./m:mesh", NS_3MF)
        if mesh is not None:
            vertices = np.asarray([
                [float(v.attrib["x"]), float(v.attrib["y"]), float(v.attrib["z"])]
                for v in mesh.findall("./m:vertices/m:vertex", NS_3MF)
            ], dtype=np.float64)
            tris: list[list[int]] = []
            slots: list[int] = []
            mesh_default = part_slots.get(object_id, default_slot)
            for index, tri in enumerate(mesh.findall("./m:triangles/m:triangle", NS_3MF)):
                if index % 4096 == 0: check_cancel(cancel)
                try:
                    indices = [int(tri.attrib[k]) for k in ("v1", "v2", "v3")]
                except (KeyError, ValueError):
                    continue
                if min(indices) < 0 or max(indices) >= len(vertices):
                    raise ValueError("El 3MF contiene índices de vértice fuera de rango.")
                tris.append(indices)
                paint = next((v for k, v in tri.attrib.items() if k.endswith("paint_color")), "")
                painted_slot = _decode_bambu_whole_triangle_paint(paint)
                if paint and painted_slot is None and paint != '0':
                    warnings.append("El 3MF contiene pintura por caras subdivididas que no puede convertirse completamente a intervalos Z; se usará la asignación del objeto como aproximación.")
                pid = tri.get('pid', obj.get('pid'))
                p1 = tri.get('p1', obj.get('pindex', '0'))
                if any(tri.get(k, p1) != p1 for k in ('p2', 'p3')):
                    warnings.append("El 3MF contiene colores interpolados por vértice; la guía por Z es aproximada.")
                slots.append(painted_slot or material_slot(model_name, pid, p1) or mesh_default or 0)
            if tris and len(vertices):
                unit = root.get('unit', 'millimeter')
                if unit not in unit_scale:
                    raise ValueError(f"Unidad 3MF no compatible: {unit}")
                geometry = vertices[np.asarray(tris, dtype=np.int64)] * unit_scale[unit]
                geometry = _apply_transform(geometry, transform)
                pieces.append(geometry)
                piece_slots.append(np.asarray(slots, dtype=np.int32))
                if part_callback is not None:
                    part_callback(model_name, object_id, obj.get("name", ""), geometry,
                                  np.asarray(slots, dtype=np.int32), transform.copy())

        components = obj.find("./m:components", NS_3MF)
        if components is not None:
            for component in components.findall("./m:component", NS_3MF):
                try:
                    child_id = int(component.attrib.get("objectid", "0"))
                except ValueError:
                    continue
                child_path = next((v for k, v in component.attrib.items() if k.endswith("path")), model_name)
                child_name = str(PurePosixPath(child_path.lstrip("/")))
                if not child_path.startswith('/') and child_path != model_name:
                    child_name = str(PurePosixPath(model_name).parent / child_path)
                local = _matrix_3mf(component.attrib.get("transform", ""))
                local[:3, 3] *= unit_scale.get(root.get('unit', 'millimeter'), 1.)
                walk_object(
                    child_name,
                    child_id,
                    transform @ local,
                    default_slot,
                    part_slots,
                    depth + 1,
                )

    build = main.find("./m:build", NS_3MF)
    if build is not None:
        for item in build.findall("./m:item", NS_3MF):
            try:
                top_id = int(item.attrib.get("objectid", "0"))
            except ValueError:
                continue
            default_slot, part_slots = settings.get(top_id, (0, {}))
            if item.get('printable', '1') in ('0', 'false'):
                continue
            transform = _matrix_3mf(item.attrib.get("transform", ""))
            transform[:3, 3] *= unit_scale.get(main.get('unit', 'millimeter'), 1.)
            walk_object(main_name, top_id, transform, default_slot, part_slots)

    if not pieces:
        return np.empty((0, 3, 3), dtype=np.float64), np.empty((0,), dtype=np.int32)
    return np.concatenate(pieces, axis=0), np.concatenate(piece_slots, axis=0)


def _matrix_3mf(text: str) -> np.ndarray:
    if not text.strip():
        return np.eye(4, dtype=np.float64)
    values = [float(x) for x in text.split()]
    if len(values) != 12:
        raise ValueError(f"Transformación 3MF no válida: {text}")
    return np.asarray([
        [values[0], values[3], values[6], values[9]],
        [values[1], values[4], values[7], values[10]],
        [values[2], values[5], values[8], values[11]],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float64)


def _apply_transform(triangles: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    flat = triangles.reshape(-1, 3)
    transformed = flat @ matrix[:3, :3].T + matrix[:3, 3]
    return transformed[:, :3].reshape((-1, 3, 3))


def _decode_bambu_whole_triangle_paint(raw: str) -> int | None:
    """Decode Bambu paint_color only when it describes the whole triangle.

    Bambu's full format can encode recursively subdivided facets. Height-map
    guidance deliberately ignores those complex encodings rather than guessing.
    Whole-facet encodings are enough to recover the common 4/8/c0/c1/... cases.
    """
    raw = (raw or "").strip().lower()
    if not raw:
        return None
    try:
        first = int(raw[0], 16)
    except ValueError:
        return None
    if first & 0b11:  # split_sides != 0 => subdivided facet
        return None
    state = first >> 2
    if state < 3:
        return state or None
    if first != 0xC:
        return None
    extra = 0
    for char in raw[1:]:
        try:
            nibble = int(char, 16)
        except ValueError:
            return None
        extra += nibble
        if nibble != 0xF:
            return 3 + extra
    return None


def _detected_colors(
    triangles: np.ndarray,
    slots: np.ndarray,
    palette: dict[int, str],
) -> tuple[DetectedColor, ...]:
    if slots.size != len(triangles):
        return ()
    result: list[DetectedColor] = []
    centers = triangles[:, :, 2].mean(axis=1)
    for slot in sorted(int(x) for x in np.unique(slots) if int(x) > 0):
        mask = slots == slot
        if not np.any(mask):
            continue
        geometry = triangles[mask]
        values = centers[mask]
        result.append(DetectedColor(
            slot=slot,
            color=palette.get(slot, "#808080"),
            triangle_count=int(np.count_nonzero(mask)),
            z_min=round(float(geometry[:, :, 2].min()), 4),
            z_max=round(float(geometry[:, :, 2].max()), 4),
            median_z=round(float(np.median(values)), 4),
        ))
    return tuple(result)


def propose_color_guided_map(
    triangles: np.ndarray,
    slots: np.ndarray | None,
    colors: Sequence[DetectedColor],
    z_min: float,
    z_max: float,
) -> HeightMapProposal | None:
    if slots is None or len(colors) < 2 or len(slots) != len(triangles):
        return None
    # Ordered height bins retain repeated colours in disjoint Z ranges.
    z = triangles[:,:,2].mean(axis=1)
    bins = np.clip(((z-z_min)/(z_max-z_min)*180).astype(int), 0, 179)
    counts = np.zeros((len(colors), 180))
    area = np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0]), axis=1)
    for i, color in enumerate(colors):
        mask = slots == color.slot
        np.add.at(counts[i], bins[mask], area[mask])
    occupied = np.flatnonzero(counts.sum(axis=0) > 0)
    dominant = np.argmax(counts[:,occupied], axis=0)
    cuts = []
    for i in range(1, len(occupied)):
        if dominant[i] != dominant[i-1]:
            cuts.append(z_min+(occupied[i]+occupied[i-1]+1)/360*(z_max-z_min))
    cuts = normalize_cuts(cuts, z_min, z_max)
    if len(cuts) > 11:
        cuts = list(np.asarray(cuts)[np.linspace(0, len(cuts)-1, 11, dtype=int)])
    return HeightMapProposal('3mf_colors', f'Guiado por colores del 3MF · {len(colors)} colores',
        'Distribución por altura de las asignaciones conocidas. Revisa los avisos de aproximación.', tuple(cuts))


def color_height_warnings(triangles, slots):
    if slots is None or len(np.unique(slots[slots > 0])) < 2:
        return ()
    # Conservative test: different materials occupying the same Z bin cannot
    # be certified as a pure height change. Includes lateral painting.
    zlo = triangles[:,:,2].min(axis=1); zhi = triangles[:,:,2].max(axis=1)
    height = float(zhi.max()-zlo.min())
    if height <= 0:
        return ()
    edges = np.linspace(zlo.min(), zhi.max(), 257)
    occupied = []
    for slot in np.unique(slots[slots > 0]):
        mask = slots == slot
        start = np.clip(np.searchsorted(edges, zlo[mask], side='right')-1, 0, 255)
        end = np.clip(np.searchsorted(edges, zhi[mask], side='left')-1, start, 255)
        delta = np.zeros(257, dtype=int)
        np.add.at(delta, start, 1); np.add.at(delta, end+1, -1)
        occupied.append(np.cumsum(delta)[:256] > 0)
    if np.any(np.sum(occupied, axis=0) > 1):
        return ('El esquema de color de este 3MF contiene regiones que no pueden certificarse únicamente mediante cambios de color por altura. Hay materiales que comparten alturas; usa la propuesta como aproximación o edita los cortes manualmente.',)
    return ()


def geometry_profile(
    triangles: np.ndarray,
    z_min: float,
    z_max: float,
    sample_count: int = 180,
) -> np.ndarray:
    """Return columns z, crossing_count, projected_area_histogram, change_score."""
    sample_count = max(40, min(int(sample_count), 500))
    zs = np.linspace(z_min, z_max, sample_count)
    tz_min = triangles[:, :, 2].min(axis=1)
    tz_max = triangles[:, :, 2].max(axis=1)

    # Sorted interval endpoints avoid scanning/copying the mesh per sample.
    crossing = (np.searchsorted(np.sort(tz_min), zs, side='right') -
                np.searchsorted(np.sort(tz_max), zs, side='left')).astype(float)
    xy = triangles[:,:,:2]
    area = np.abs((xy[:,1,0]-xy[:,0,0])*(xy[:,2,1]-xy[:,0,1]) -
                  (xy[:,1,1]-xy[:,0,1])*(xy[:,2,0]-xy[:,0,0])) * .5
    span, _ = np.histogram(triangles[:,:,2].mean(axis=1),
                           bins=np.linspace(z_min,z_max,sample_count+1), weights=area)

    crossing_n = _normalize_signal(crossing)
    span_n = _normalize_signal(span)
    dc = np.abs(np.gradient(_smooth(crossing_n)))
    ds = np.abs(np.gradient(_smooth(span_n)))
    score = _smooth(0.68 * dc + 0.32 * ds, window=5)
    return np.column_stack((zs, crossing, span, score))


def _normalize_signal(values: np.ndarray) -> np.ndarray:
    lo = float(values.min())
    hi = float(values.max())
    if hi - lo <= 1e-12:
        return np.zeros_like(values)
    return (values - lo) / (hi - lo)


def _smooth(values: np.ndarray, window: int = 7) -> np.ndarray:
    if len(values) < 3:
        return values.copy()
    window = max(3, min(window, len(values) if len(values) % 2 else len(values) - 1))
    if window <= 1:
        return values.copy()
    kernel = np.ones(window, dtype=np.float64) / window
    padded = np.pad(values, (window // 2, window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: len(values)]


def propose_height_maps(profile: np.ndarray, z_min: float, z_max: float) -> tuple[HeightMapProposal, ...]:
    height = z_max - z_min
    zs = profile[:, 0]
    scores = profile[:, 3]
    spacing = max(height * 0.075, 0.35)

    candidates: list[tuple[float, float]] = []
    for i in range(2, len(scores) - 2):
        z = float(zs[i])
        if z - z_min < spacing or z_max - z < spacing:
            continue
        if scores[i] > 1e-12 and scores[i] >= scores[i - 1] and scores[i] >= scores[i + 1]:
            candidates.append((float(scores[i]), z))
    candidates.sort(reverse=True)

    def strongest(count: int) -> tuple[float, ...]:
        selected: list[float] = []
        for _score, z in candidates:
            if all(abs(z - existing) >= spacing for existing in selected):
                selected.append(z)
                if len(selected) >= count:
                    break
        return tuple(sorted(round(x, 3) for x in selected))

    simple = strongest(2)
    balanced = strongest(3)
    detailed = strongest(5)
    uniform = tuple(round(float(z_min + height * f), 3) for f in (0.25, 0.5, 0.75))

    return (
        HeightMapProposal(
            "simple",
            "Automático · Simple",
            "Pocas zonas; prioriza los cambios de geometría más fuertes.",
            simple,
        ),
        HeightMapProposal(
            "balanced",
            "Automático · Equilibrado",
            "Más detalle sin fragmentar excesivamente el modelo.",
            balanced,
        ),
        HeightMapProposal(
            "detailed",
            "Automático · Detallado",
            "Usa más transiciones detectadas para relieves complejos.",
            detailed,
        ),
        HeightMapProposal(
            "uniform",
            "Capas uniformes · 4 zonas",
            "Divide la altura total en cuatro zonas iguales.",
            uniform,
        ),
    )


def normalize_cuts(cuts: Iterable[float], z_min: float, z_max: float, min_gap: float = 0.02) -> list[float]:
    result: list[float] = []
    for value in sorted(float(x) for x in cuts if np.isfinite(float(x))):
        if value <= z_min + min_gap or value >= z_max - min_gap:
            continue
        if not result or value - result[-1] >= min_gap:
            result.append(value)
    return result


def export_height_map_json(
    destination: str | Path,
    height_map: STLHeightMap,
    cuts: Sequence[float],
    *,
    view: dict | None = None,
) -> Path:
    destination = Path(destination)
    payload = {
        "schema": "dsc.stl-height-map.v2",
        "source": height_map.summary.source_name,
        "source_type": height_map.source_type,
        "triangle_count": height_map.summary.triangle_count,
        "bounds": {
            "min": list(height_map.summary.bounds_min),
            "max": list(height_map.summary.bounds_max),
        },
        "height": round(height_map.summary.height, 4),
        "zones": [asdict(zone) for zone in height_map.zones(cuts)],
        "warnings": list(height_map.warnings),
        "detected_colors": [asdict(item) for item in height_map.detected_colors],
        "view": view or {"projection": "top"},
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def split_triangles_by_height_zones(
    triangles: np.ndarray,
    cuts: Sequence[float],
    z_min: float,
    z_max: float,
) -> list[tuple[int, np.ndarray]]:
    """Clip mesh triangles against horizontal bands."""
    bounds = [z_min, *normalize_cuts(cuts, z_min, z_max), z_max]
    output: list[tuple[int, np.ndarray]] = []
    eps = 1e-9
    for triangle in triangles:
        tri_min = float(triangle[:, 2].min())
        tri_max = float(triangle[:, 2].max())
        for zone in range(len(bounds) - 1):
            low, high = float(bounds[zone]), float(bounds[zone + 1])
            if tri_max < low - eps or tri_min > high + eps:
                continue
            polygon = [np.asarray(v, dtype=np.float64) for v in triangle]
            polygon = _clip_polygon_z(polygon, low, keep_above=True)
            polygon = _clip_polygon_z(polygon, high, keep_above=False)
            if len(polygon) < 3:
                continue
            anchor = polygon[0]
            for i in range(1, len(polygon) - 1):
                piece = np.vstack((anchor, polygon[i], polygon[i + 1]))
                if np.linalg.norm(np.cross(piece[1] - piece[0], piece[2] - piece[0])) > eps:
                    output.append((zone, piece))
    return output


def _clip_polygon_z(polygon: list[np.ndarray], z: float, *, keep_above: bool) -> list[np.ndarray]:
    if not polygon:
        return []

    def inside(point: np.ndarray) -> bool:
        return bool(point[2] >= z - 1e-9) if keep_above else bool(point[2] <= z + 1e-9)

    result: list[np.ndarray] = []
    previous = polygon[-1]
    previous_inside = inside(previous)
    for current in polygon:
        current_inside = inside(current)
        if current_inside != previous_inside:
            dz = current[2] - previous[2]
            if abs(dz) > 1e-12:
                t = (z - previous[2]) / dz
                t = max(0.0, min(1.0, float(t)))
                result.append(previous + (current - previous) * t)
        if current_inside:
            result.append(current)
        previous = current
        previous_inside = current_inside
    return result
