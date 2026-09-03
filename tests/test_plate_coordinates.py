import json
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from jarvis_bambu.three_mf_project import NS, ThreeMFProject, parse_transform
from jarvis_bambu.nesting_optimizer import NestingOptimizer
from jarvis_bambu.optimizer_models import OptimizerOptions


class PlateCoordinateTests(unittest.TestCase):
    def _many_piece_project(self, folder, origins, total):
        resources, build, objects = [], [], []
        plate_instances = [[] for _ in origins]
        local_bounds = [[float("inf"), float("inf"), 0.0, 0.0] for _ in origins]
        for index in range(total):
            object_id = index + 1
            plate_index = index % len(origins)
            slot = index // len(origins)
            x, y = 2 + (slot % 20) * 9, 2 + (slot // 20) * 9
            ox, oy = origins[plate_index]
            resources.append(f'''<object id="{object_id}" type="model"><mesh><vertices>
              <vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>
              <vertex x="0" y="1" z="0"/></vertices><triangles>
              <triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>''')
            build.append(f'<item objectid="{object_id}" transform="1 0 0 0 1 0 0 0 1 {ox+x} {oy+y} 0"/>')
            objects.append(f'<object id="{object_id}"><metadata key="name" value="p{object_id}"/></object>')
            plate_instances[plate_index].append(
                f'<model_instance><metadata key="object_id" value="{object_id}"/></model_instance>'
            )
            bounds = local_bounds[plate_index]
            bounds[:] = [min(bounds[0], x), min(bounds[1], y), max(bounds[2], x + 1), max(bounds[3], y + 1)]
        model = f'''<model xmlns="{NS['m']}"><resources>{''.join(resources)}</resources>
                    <build>{''.join(build)}</build></model>'''
        plates = ''.join(
            f'<plate><metadata key="plater_id" value="{i+1}"/>{"".join(instances)}</plate>'
            for i, instances in enumerate(plate_instances)
        )
        source = Path(folder) / "many.3mf"
        with ZipFile(source, "w") as archive:
            archive.writestr("3D/3dmodel.model", model)
            archive.writestr("Metadata/model_settings.config", f'<config>{"".join(objects)}{plates}</config>')
            archive.writestr("Metadata/project_settings.config", json.dumps(
                {"printable_area": ["0x0", "200x0", "200x200", "0x200"]}
            ))
            for index, bounds in enumerate(local_bounds, 1):
                archive.writestr(f"Metadata/plate_{index}.json", json.dumps({"bbox_all": bounds}))
        return source

    def test_uses_plate_json_origin_and_preserves_non_z_pose(self):
        model = f'''<?xml version="1.0"?>
        <model xmlns="{NS['m']}" unit="millimeter"><resources>
          <object id="1" type="model"><mesh><vertices>
            <vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/>
            <vertex x="0" y="20" z="0"/>
          </vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>
        </resources><build><item objectid="1" transform="1 0 .2 0 1 .3 .4 .5 .6 610 420 7"/></build></model>'''
        settings = '''<config><object id="1"><metadata key="name" value="piece"/></object>
        <plate><metadata key="plater_id" value="9"/><model_instance>
        <metadata key="object_id" value="1"/></model_instance></plate></config>'''
        project_settings = {"printable_area": ["0x0", "200x0", "200x200", "0x200"]}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "input.3mf"
            with ZipFile(source, "w") as archive:
                archive.writestr("3D/3dmodel.model", model)
                archive.writestr("Metadata/model_settings.config", settings)
                archive.writestr("Metadata/project_settings.config", json.dumps(project_settings))
                archive.writestr("Metadata/plate_9.json", json.dumps({"bbox_all": [10, 20, 20, 40]}))

            project = ThreeMFProject(source)
            item = project.plates()[0].items[0]
            self.assertEqual(project.plate_origin(1), (600.0, 400.0))
            self.assertEqual(project.local_position(item), (10.0, 20.0))

            project.set_item_pose(item, 1, 90, 30, 40)
            result = parse_transform(project.build_items[1].attrib["transform"])
            self.assertAlmostEqual(result[9], 630.0)
            self.assertAlmostEqual(result[10], 440.0)
            self.assertEqual(result[11], 7.0)
            self.assertAlmostEqual(result[2], .2)
            self.assertAlmostEqual(result[5], .3)
            self.assertAlmostEqual(result[8], .6)

    def test_four_plates_use_their_own_xy_origins(self):
        origins = [(0, 0), (350, 25), (-40, 410), (725, -80)]
        with tempfile.TemporaryDirectory() as folder:
            project = ThreeMFProject(self._many_piece_project(folder, origins, 4))
            plates = project.plates()
            self.assertEqual([plate.origin for plate in plates], origins)
            self.assertTrue(all(project.local_position(plate.items[0]) == (2, 2) for plate in plates))

    def test_300_pieces_parse_to_local_plate_coordinates_quickly(self):
        origins = [(0, 0), (350, 25), (-40, 410), (725, -80)]
        with tempfile.TemporaryDirectory() as folder:
            started = time.monotonic()
            source = self._many_piece_project(folder, origins, 300)
            project = ThreeMFProject(source)
            plates = project.plates()
            elapsed = time.monotonic() - started
            self.assertEqual(sum(len(plate.items) for plate in plates), 300)
            self.assertTrue(all(0 <= x <= 200 and 0 <= y <= 200
                                for plate in plates for x, y in
                                [project.local_position(plate.items[0])]))
            self.assertLess(elapsed, 10.0)
            optimizer = NestingOptimizer(source, OptimizerOptions("simple", "low"))
            assignments = [
                optimizer._current_placements(plate.items, plate.index)
                for plate in optimizer.project.plates()
            ]
            optimizer._validate_assignments(assignments)


if __name__ == "__main__":
    unittest.main()
