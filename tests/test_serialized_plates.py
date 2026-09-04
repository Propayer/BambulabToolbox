import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from jarvis_bambu.core.api import optimize_project
from jarvis_bambu.optimizer_models import OptimizerOptions
from jarvis_bambu.three_mf_project import SerializedLayoutSummary, ThreeMFProject, NS


def two_plate_project(folder: str, pieces: int = 8) -> Path:
    resources, build, objects = [], [], []
    instances = [[], []]
    bounds = [[2.0, 2.0, 37.0, 37.0], [2.0, 2.0, 37.0, 37.0]]
    for index in range(pieces):
        object_id = index + 1
        plate = index % 2
        slot = index // 2
        x, y = 2 + (slot % 2) * 20, 2 + (slot // 2) * 20
        origin = 0 if plate == 0 else 300
        resources.append(f'''<object id="{object_id}" type="model"><mesh><vertices>
          <vertex x="0" y="0" z="0"/><vertex x="15" y="0" z="0"/>
          <vertex x="15" y="15" z="0"/><vertex x="0" y="15" z="0"/>
          </vertices><triangles><triangle v1="0" v2="1" v3="2"/>
          <triangle v1="0" v2="2" v3="3"/></triangles></mesh></object>''')
        build.append(f'<item objectid="{object_id}" transform="1 0 0 0 1 0 0 0 1 {origin+x} {y} 0"/>')
        objects.append(f'<object id="{object_id}"><metadata key="name" value="p{object_id}"/></object>')
        instances[plate].append(
            f'<model_instance><metadata key="object_id" value="{object_id}"/></model_instance>'
        )
    model = f'<model xmlns="{NS["m"]}"><resources>{"".join(resources)}</resources><build>{"".join(build)}</build></model>'
    plates = ''.join(
        f'''<plate><metadata key="plater_id" value="{i + 1}"/>
        <metadata key="thumbnail_file" value="Metadata/plate_{i + 1}.png"/>
        {"".join(values)}</plate>'''
        for i, values in enumerate(instances)
    )
    source = Path(folder) / "two-plates.3mf"
    with ZipFile(source, "w") as archive:
        archive.writestr("3D/3dmodel.model", model)
        archive.writestr("Metadata/model_settings.config", f'<config>{"".join(objects)}{plates}</config>')
        archive.writestr("Metadata/project_settings.config", json.dumps(
            {"printable_area": ["0x0", "100x0", "100x100", "0x100"]}
        ))
        archive.writestr("Metadata/filament_sequence.json", json.dumps({
            "plate_1": {"sequence": []}, "plate_2": {"sequence": []}
        }))
        for plate_id in (1, 2):
            archive.writestr(f"Metadata/plate_{plate_id}.json", json.dumps({"bbox_all": bounds[plate_id - 1]}))
            archive.writestr(f"Metadata/plate_{plate_id}.png", b"stale")
    return source


class SerializedPlateTests(unittest.TestCase):
    def test_logical_two_to_one_serializes_one_without_orphans(self):
        with tempfile.TemporaryDirectory() as folder:
            project = ThreeMFProject(two_plate_project(folder))
            plates = project.plates()
            project.assign_plates([[*plates[0].items, *plates[1].items]], [False])
            # This is the former failure: XML says one, auxiliary metadata two.
            self.assertEqual(project.serialized_layout_summary().plate_count, 2)
            output = Path(folder) / "output.3mf"
            project.save(output)
            reopened = ThreeMFProject(output)
            summary = reopened.serialized_layout_summary()
            self.assertEqual(summary.plate_count, 1)
            self.assertEqual(summary.plate_ids, (1,))
            self.assertEqual(len(summary.objects_by_plate[1]), 8)
            self.assertEqual(summary.empty_plate_ids, ())
            self.assertEqual(summary.orphan_plate_metadata, ())
            self.assertFalse(any(name.startswith("Metadata/plate_2") for name in reopened.files))

    def test_final_result_count_comes_from_validated_written_project(self):
        with tempfile.TemporaryDirectory() as folder:
            source = two_plate_project(folder)
            output = Path(folder) / "optimized.3mf"
            result = optimize_project(
                source, OptimizerOptions("advanced", "low", optimizer_workers=1), output
            )
            summary = ThreeMFProject(output).serialized_layout_summary()
            self.assertTrue(result.improved)
            self.assertEqual((result.original_plate_count, result.final_plate_count), (2, 1))
            self.assertEqual(result.final_plate_count, summary.plate_count)

    def test_serialized_mismatch_prevents_improved_result(self):
        with tempfile.TemporaryDirectory() as folder:
            source = two_plate_project(folder)
            invalid = SerializedLayoutSummary(
                8, (1,), {1: tuple(range(1, 9))}, (),
                ("Metadata/filament_sequence.json:plate_2",),
                ("Metadata/filament_sequence.json:plate_2",), (1, 2),
            )
            with patch.object(ThreeMFProject, "serialized_layout_summary", return_value=invalid):
                with self.assertRaisesRegex(RuntimeError, "no coincide"):
                    optimize_project(
                        source, OptimizerOptions("advanced", "low", optimizer_workers=1),
                        Path(folder) / "invalid.3mf",
                    )


if __name__ == "__main__":
    unittest.main()
