from __future__ import annotations

import json
import logging
import math
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

from shapely.affinity import affine_transform
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .optimizer_models import ModelItem, Plate

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SerializedLayoutSummary:
    build_item_count: int
    plate_ids: tuple[int, ...]
    objects_by_plate: dict[int, tuple[int, ...]]
    empty_plate_ids: tuple[int, ...]
    plate_metadata: tuple[str, ...]
    orphan_plate_metadata: tuple[str, ...]
    metadata_plate_ids: tuple[int, ...]

    @property
    def plate_count(self) -> int:
        # Bambu may materialize a plate from auxiliary metadata even when the
        # model-settings XML no longer contains that plate.
        return len(set(self.plate_ids) | set(self.metadata_plate_ids))


CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PRODUCTION = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
NS = {"m": CORE}
ET.register_namespace("", CORE)
ET.register_namespace("p", PRODUCTION)


def _metadata(parent: ET.Element, key: str, default: str = "") -> str:
    for node in parent.findall("./metadata"):
        if node.attrib.get("key") == key:
            return node.attrib.get("value", default)
    return default


def parse_transform(text: str) -> tuple[float, ...]:
    values = tuple(float(x) for x in text.split())
    if len(values) != 12:
        raise ValueError(f"Transformación 3MF no válida: {text}")
    return values


def transform_polygon(poly, values: tuple[float, ...]):
    # 3MF almacena una matriz 3x4 por columnas. Shapely usa [a,b,d,e,xoff,yoff].
    return affine_transform(poly, [values[0], values[3], values[1], values[4], values[9], values[10]])


class ThreeMFProject:
    def __init__(self, source: Path):
        self.source = source.resolve()
        self.files: dict[str, bytes] = {}
        with ZipFile(self.source) as archive:
            for name in archive.namelist():
                self.files[name] = archive.read(name)
        self.model_name = "3D/3dmodel.model"
        self.settings_name = "Metadata/model_settings.config"
        self.project_name = "Metadata/project_settings.config"
        self.model_root = ET.fromstring(self.files[self.model_name])
        self.settings_root = ET.fromstring(self.files[self.settings_name])
        self.project_settings = json.loads(self.files[self.project_name])
        self.build_items = {
            int(node.attrib["objectid"]): node
            for node in self.model_root.findall(".//m:build/m:item", NS)
        }
        self.object_names = {
            int(node.attrib["id"]): _metadata(node, "name", f"Objeto {node.attrib['id']}")
            for node in self.settings_root.findall("./object")
        }
        self._footprint_cache: dict[int, object] = {}
        self._plate_origins: dict[int, tuple[float, float]] = {}

    @property
    def printable_area(self):
        raw = self.project_settings.get("printable_area") or ["0x0", "256x0", "256x256", "0x256"]
        points = []
        for value in raw:
            x, y = str(value).lower().split("x", 1)
            points.append((float(x), float(y)))
        bed = Polygon(points)
        for area in self.project_settings.get("bed_exclude_area") or []:
            if isinstance(area, str):
                nums = [float(x) for x in area.replace("x", ",").split(",") if x.strip()]
            else:
                nums = [float(x) for x in area]
            if len(nums) >= 8:
                bed = bed.difference(Polygon(list(zip(nums[::2], nums[1::2]))))
        return bed

    @property
    def brim_extension(self) -> float:
        brim_type = str(self.project_settings.get("brim_type", "no_brim"))
        if brim_type in {"no_brim", "none"}:
            return 0.0
        try:
            return max(0.0, float(self.project_settings.get("brim_width", 0)))
        except (TypeError, ValueError):
            return 0.0

    @property
    def by_object(self) -> bool:
        return self.project_settings.get("print_sequence") == "by object"

    def plates(self) -> list[Plate]:
        result: list[Plate] = []
        for index, plate_node in enumerate(self.settings_root.findall("./plate"), 1):
            locked = _metadata(plate_node, "locked", "false").lower() == "true"
            plate = Plate(index=index, locked=locked, xml=plate_node)
            for instance in plate_node.findall("./model_instance"):
                object_id = int(_metadata(instance, "object_id", "-1"))
                build = self.build_items.get(object_id)
                if build is None:
                    continue
                transform = parse_transform(build.attrib["transform"])
                local = self._object_footprint(object_id)
                oriented = transform_polygon(
                    local,
                    transform[:9] + (0.0, 0.0, 0.0),
                )
                plate.items.append(ModelItem(
                    object_id=object_id,
                    name=self.object_names.get(object_id, f"Objeto {object_id}"),
                    plate_index=index,
                    footprint=oriented,
                    z_transform=transform,
                    instance_xml=instance,
                    locked=locked,
                ))
            plate.origin = self._read_plate_origin(plate)
            self._plate_origins[index] = plate.origin
            result.append(plate)
        return result

    def _read_plate_origin(self, plate: Plate) -> tuple[float, float]:
        """Return the plate origin in the global 3MF canvas.

        Bambu's per-plate JSON stores local bed coordinates, whereas build item
        transforms use the project's global canvas.  Comparing both bounds is
        an exact, project-owned reference and avoids assumptions about how the
        slicer lays plates out on that canvas.
        """
        if not plate.items:
            return (0.0, 0.0)
        plater_id = _metadata(plate.xml, "plater_id", str(plate.index))
        candidates = [f"Metadata/plate_{plater_id}.json", f"Metadata/plate_{plate.index}.json"]
        for name in candidates:
            raw = self.files.get(name)
            if raw is None:
                continue
            try:
                local_bounds = json.loads(raw).get("bbox_all")
                if not local_bounds or len(local_bounds) < 4:
                    continue
                global_geometry = unary_union([
                    transform_polygon(item.footprint, (1.0, 0.0, 0.0, 0.0, 1.0, 0.0,
                                                       0.0, 0.0, 1.0,
                                                       item.z_transform[9], item.z_transform[10], 0.0))
                    for item in plate.items
                ])
                gx1, gy1, gx2, gy2 = global_geometry.bounds
                lx1, ly1, lx2, ly2 = (float(value) for value in local_bounds[:4])
                # Centres tolerate bbox expansion caused by brim/support equally
                # on both sides better than comparing only the lower corner.
                return ((gx1 + gx2 - lx1 - lx2) / 2.0,
                        (gy1 + gy2 - ly1 - ly2) / 2.0)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

        # Unsliced projects may not contain plate JSON yet. If transforms are
        # already inside the printable area, their plate uses the model origin.
        global_geometry = unary_union([
            affine_transform(item.footprint, [1, 0, 0, 1,
                                               item.z_transform[9], item.z_transform[10]])
            for item in plate.items
        ])
        if self.printable_area.covers(global_geometry):
            return (0.0, 0.0)

        # Last-resort project-derived estimate: align the occupied bounds with
        # the printable-area centre. It remains independent of plate numbering
        # and, unlike the former constant, handles X and Y canvas layouts.
        bx1, by1, bx2, by2 = self.printable_area.bounds
        gx1, gy1, gx2, gy2 = global_geometry.bounds
        return ((gx1 + gx2 - bx1 - bx2) / 2.0,
                (gy1 + gy2 - by1 - by2) / 2.0)

    def plate_origin(self, plate_index: int) -> tuple[float, float]:
        if plate_index not in self._plate_origins:
            self.plates()
        return self._plate_origins.get(plate_index, (0.0, 0.0))

    def local_position(self, item: ModelItem) -> tuple[float, float]:
        ox, oy = self.plate_origin(item.plate_index)
        return item.z_transform[9] - ox, item.z_transform[10] - oy

    def _object_footprint(self, object_id: int):
        if object_id in self._footprint_cache:
            return self._footprint_cache[object_id]
        outer = next(
            x for x in self.model_root.findall(".//m:resources/m:object", NS)
            if int(x.attrib["id"]) == object_id
        )
        polygons = []
        mesh = outer.find("./m:mesh", NS)
        if mesh is not None:
            polygons.extend(self._mesh_polygons(mesh))
        for component in outer.findall("./m:components/m:component", NS):
            path = component.attrib.get(f"{{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}}path")
            if not path:
                continue
            path = str(PurePosixPath(path.lstrip("/")))
            root = ET.fromstring(self.files[path])
            inner_id = int(component.attrib["objectid"])
            inner = next(x for x in root.findall(".//m:object", NS) if int(x.attrib["id"]) == inner_id)
            inner_mesh = inner.find("./m:mesh", NS)
            if inner_mesh is None:
                continue
            part = unary_union(self._mesh_polygons(inner_mesh))
            if component.attrib.get("transform"):
                part = transform_polygon(part, parse_transform(component.attrib["transform"]))
            polygons.append(part)
        if not polygons:
            raise ValueError(f"El objeto {object_id} no contiene una malla utilizable")
        footprint = unary_union(polygons).buffer(0)
        self._footprint_cache[object_id] = footprint
        return footprint

    @staticmethod
    def _mesh_polygons(mesh: ET.Element) -> list[Polygon]:
        vertices = [
            (float(v.attrib["x"]), float(v.attrib["y"]))
            for v in mesh.findall("./m:vertices/m:vertex", NS)
        ]
        polygons = []
        for triangle in mesh.findall("./m:triangles/m:triangle", NS):
            points = [vertices[int(triangle.attrib[k])] for k in ("v1", "v2", "v3")]
            poly = Polygon(points)
            if poly.area > 1e-8:
                polygons.append(poly)
        return polygons

    def set_item_pose(self, item: ModelItem, plate_index: int, angle_deg: float, x: float, y: float) -> None:
        old = item.z_transform
        radians = math.radians(angle_deg)
        c, s = math.cos(radians), math.sin(radians)
        origin_x, origin_y = self.plate_origin(plate_index)
        values = (
            c * old[0] - s * old[1], s * old[0] + c * old[1], old[2],
            c * old[3] - s * old[4], s * old[3] + c * old[4], old[5],
            c * old[6] - s * old[7], s * old[6] + c * old[7], old[8],
            x + origin_x, y + origin_y, old[11],
        )
        logger.debug(
            "Plate %d Origin: X=%.3f Y=%.3f Object %d Local: X=%.3f Y=%.3f "
            "Global/final: X=%.3f Y=%.3f Rotation Z=%.3f",
            plate_index, origin_x, origin_y, item.object_id, x, y,
            values[9], values[10], angle_deg,
        )
        self.build_items[item.object_id].set("transform", " ".join(f"{v:.9g}" for v in values))

    def assign_plates(self, assignments: list[list[ModelItem]], locks: list[bool] | None = None) -> None:
        old_plates = self.settings_root.findall("./plate")
        template = old_plates[0]
        for node in old_plates:
            self.settings_root.remove(node)
        for index, items in enumerate(assignments, 1):
            if index <= len(old_plates):
                plate = old_plates[index - 1]
            else:
                plate = ET.fromstring(ET.tostring(template))
            for instance in list(plate.findall("./model_instance")):
                plate.remove(instance)
            for item in items:
                plate.append(item.instance_xml)
            for md in plate.findall("./metadata"):
                if md.attrib.get("key") == "plater_id":
                    md.set("value", str(index))
                elif md.attrib.get("key") == "locked":
                    md.set("value", "true" if locks and index <= len(locks) and locks[index - 1] else "false")
            self.settings_root.append(plate)

    def serialized_layout_summary(self) -> SerializedLayoutSummary:
        plate_nodes = self.settings_root.findall("./plate")
        plate_ids = tuple(
            int(_metadata(node, "plater_id", str(index)))
            for index, node in enumerate(plate_nodes, 1)
        )
        objects_by_plate = {
            plate_id: tuple(
                int(_metadata(instance, "object_id", "-1"))
                for instance in node.findall("./model_instance")
            )
            for plate_id, node in zip(plate_ids, plate_nodes)
        }
        metadata: set[str] = set()
        metadata_ids: dict[str, int] = {}
        file_pattern = re.compile(
            r"^Metadata/(?:plate_(?:no_light_)?|top_|pick_)(\d+)(?:\.[^/]+)?$",
            re.IGNORECASE,
        )
        for name in self.files:
            match = file_pattern.match(name)
            if match:
                metadata.add(name)
                metadata_ids[name] = int(match.group(1))
        sequence_name = "Metadata/filament_sequence.json"
        if sequence_name in self.files:
            try:
                sequence = json.loads(self.files[sequence_name])
                for key in sequence:
                    match = re.fullmatch(r"plate_(\d+)", str(key), re.IGNORECASE)
                    if match:
                        label = f"{sequence_name}:{key}"
                        metadata.add(label)
                        metadata_ids[label] = int(match.group(1))
            except (TypeError, json.JSONDecodeError):
                metadata.add(f"{sequence_name}:invalid")
        valid_ids = set(plate_ids)
        orphan = tuple(sorted(
            label for label, plate_id in metadata_ids.items()
            if plate_id not in valid_ids
        ))
        return SerializedLayoutSummary(
            build_item_count=len(self.build_items),
            plate_ids=plate_ids,
            objects_by_plate=objects_by_plate,
            empty_plate_ids=tuple(
                plate_id for plate_id, objects in objects_by_plate.items() if not objects
            ),
            plate_metadata=tuple(sorted(metadata)),
            orphan_plate_metadata=orphan,
            metadata_plate_ids=tuple(sorted(set(metadata_ids.values()))),
        )

    def _synchronize_plate_metadata(self) -> None:
        plate_nodes = self.settings_root.findall("./plate")
        valid_ids = {
            int(_metadata(node, "plater_id", str(index)))
            for index, node in enumerate(plate_nodes, 1)
        }
        # Per-plate bounds and renderings describe the old arrangement. Bambu
        # Studio safely regenerates them from model_settings.config.
        for name in list(self.files):
            if re.fullmatch(r"Metadata/plate_\d+\.json", name, re.IGNORECASE):
                self.files.pop(name, None)
        stale_reference_keys = {
            "thumbnail_file", "thumbnail_no_light_file", "top_file", "pick_file"
        }
        for plate in plate_nodes:
            for node in list(plate.findall("./metadata")):
                if node.attrib.get("key") in stale_reference_keys:
                    plate.remove(node)
        sequence_name = "Metadata/filament_sequence.json"
        if sequence_name in self.files:
            try:
                sequence = json.loads(self.files[sequence_name])
            except (TypeError, json.JSONDecodeError):
                sequence = {}
            if isinstance(sequence, dict):
                sequence = {
                    key: value for key, value in sequence.items()
                    if not (match := re.fullmatch(r"plate_(\d+)", str(key), re.IGNORECASE))
                    or int(match.group(1)) in valid_ids
                }
                self.files[sequence_name] = json.dumps(
                    sequence, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")

    def save(self, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        self._synchronize_plate_metadata()
        self.files[self.model_name] = ET.tostring(self.model_root, encoding="utf-8", xml_declaration=True)
        self.files[self.settings_name] = ET.tostring(self.settings_root, encoding="utf-8", xml_declaration=True)
        # Las miniaturas y los datos de laminado describen la distribución
        # anterior. Al quitarlos, Bambu Studio los reconstruye desde el modelo.
        stale = [
            name for name in self.files
            if name == "Metadata/slice_info.config"
            or (
                name.startswith("Metadata/")
                and name.lower().endswith(".png")
                and any(token in Path(name).name for token in ("plate_", "top_", "pick_"))
            )
        ]
        for name in stale:
            self.files.pop(name, None)
        temp = output.with_suffix(".tmp")
        with ZipFile(temp, "w", ZIP_DEFLATED) as archive:
            for name, content in self.files.items():
                archive.writestr(name, content)
        temp.replace(output)
