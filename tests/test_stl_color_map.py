import os
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jarvis_bambu.core.stl_color_map import (
    analyze_model,
    analyze_stl,
    normalize_cuts,
    split_triangles_by_height_zones,
)


ASCII_TETRA = b"""solid tetra
facet normal 0 0 0
 outer loop
  vertex 0 0 0
  vertex 10 0 0
  vertex 0 10 0
 endloop
endfacet
facet normal 0 0 0
 outer loop
  vertex 0 0 0
  vertex 10 0 0
  vertex 0 0 10
 endloop
endfacet
facet normal 0 0 0
 outer loop
  vertex 10 0 0
  vertex 0 10 0
  vertex 0 0 10
 endloop
endfacet
facet normal 0 0 0
 outer loop
  vertex 0 10 0
  vertex 0 0 0
  vertex 0 0 10
 endloop
endfacet
endsolid tetra
"""


class STLColorMapCoreTests(unittest.TestCase):
    def test_ascii_stl_is_analyzed_and_proposals_stay_in_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tetra.stl"
            path.write_bytes(ASCII_TETRA)
            result = analyze_stl(path, sample_count=80)
        self.assertEqual(result.summary.triangle_count, 4)
        self.assertAlmostEqual(result.summary.height, 10.0)
        self.assertEqual(len(result.proposals), 4)
        for proposal in result.proposals:
            for cut in proposal.cuts:
                self.assertGreater(cut, result.z_min)
                self.assertLess(cut, result.z_max)

    def test_triangle_crossing_cut_is_physically_split(self):
        triangles = np.asarray([[[0.0, 0.0, 0.0], [10.0, 0.0, 10.0], [0.0, 10.0, 10.0]]])
        pieces = split_triangles_by_height_zones(triangles, [5.0], 0.0, 10.0)
        zones = {zone for zone, _ in pieces}
        self.assertEqual(zones, {0, 1})
        for zone, tri in pieces:
            if zone == 0:
                self.assertLessEqual(float(tri[:, 2].max()), 5.0 + 1e-7)
            else:
                self.assertGreaterEqual(float(tri[:, 2].min()), 5.0 - 1e-7)

    def test_cut_normalization_orders_and_deduplicates(self):
        self.assertEqual(normalize_cuts([8, 2, 2.001, 12, -1], 0, 10, min_gap=0.02), [2.0, 8.0])

    def test_multicolor_3mf_adds_color_guided_proposal_and_embedded_preview(self):
        main = b'''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p" unit="millimeter">
 <resources><object id="10" type="model"><components>
  <component p:path="/3D/Objects/parts.model" objectid="1"/>
  <component p:path="/3D/Objects/parts.model" objectid="2"/>
 </components></object></resources>
 <build><item objectid="10"/></build>
</model>'''
        parts = b'''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter"><resources>
 <object id="1" type="model"><mesh><vertices>
  <vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="1"/>
 </vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>
 <object id="2" type="model"><mesh><vertices>
  <vertex x="0" y="0" z="2"/><vertex x="10" y="0" z="3"/><vertex x="0" y="10" z="3"/>
 </vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>
</resources><build/></model>'''
        settings = b'''<config><object id="10"><metadata key="extruder" value="1"/>
 <part id="1"><metadata key="extruder" value="1"/></part>
 <part id="2"><metadata key="extruder" value="2"/></part>
</object></config>'''
        project = b'{"filament_colour":["#FF0000","#0000FF"]}'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "multi.3mf"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("3D/3dmodel.model", main)
                archive.writestr("3D/Objects/parts.model", parts)
                archive.writestr("Metadata/model_settings.config", settings)
                archive.writestr("Metadata/project_settings.config", project)
                archive.writestr("Metadata/plate_1.png", b"preview")
            result = analyze_model(path, sample_count=60)
        self.assertEqual(result.source_type, "3mf")
        self.assertEqual([c.color for c in result.detected_colors], ["#FF0000", "#0000FF"])
        self.assertEqual(result.proposals[0].id, "3mf_colors")
        self.assertEqual(result.embedded_preview, b"preview")
        self.assertEqual(len(result.triangles), 2)


    def test_3mf_whole_triangle_paint_color_overrides_part_extruder(self):
        main = b'''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p" unit="millimeter">
 <resources><object id="10" type="model"><components><component p:path="/3D/Objects/part.model" objectid="1"/></components></object></resources>
 <build><item objectid="10"/></build>
</model>'''
        part = b'''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter"><resources>
 <object id="1" type="model"><mesh><vertices>
  <vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="2"/><vertex x="0" y="10" z="2"/>
  <vertex x="0" y="0" z="4"/><vertex x="10" y="0" z="6"/><vertex x="0" y="10" z="6"/>
 </vertices><triangles>
  <triangle v1="0" v2="1" v3="2" paint_color="4"/>
  <triangle v1="3" v2="4" v3="5" paint_color="8"/>
 </triangles></mesh></object>
</resources><build/></model>'''
        settings = b'<config><object id="10"><metadata key="extruder" value="1"/><part id="1"><metadata key="extruder" value="1"/></part></object></config>'
        project = b'{"filament_colour":["#00FF00","#FF00FF"]}'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "painted.3mf"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("3D/3dmodel.model", main)
                archive.writestr("3D/Objects/part.model", part)
                archive.writestr("Metadata/model_settings.config", settings)
                archive.writestr("Metadata/project_settings.config", project)
            result = analyze_model(path, sample_count=60)
        self.assertEqual([c.slot for c in result.detected_colors], [1, 2])
        self.assertEqual(result.proposals[0].id, "3mf_colors")

    def test_tool_is_registered_modularly(self):
        source = (Path(__file__).parents[1] / "src" / "jarvis_bambu" / "gui" / "app.py").read_text(encoding="utf-8")
        self.assertIn('ToolDefinition("stl_color_map"', source)
        self.assertIn("STLColorMapWidget", source)

    def test_gui_keeps_3d_renderer_opt_in(self):
        source = (Path(__file__).parents[1] / "src" / "jarvis_bambu" / "gui" / "stl_color_map.py").read_text(encoding="utf-8")
        source += (Path(__file__).parents[1] / "src" / "jarvis_bambu" / "gui" / "color_map_layout.py").read_text(encoding="utf-8")
        self.assertIn("Empezar renderizado 3D", source)
        self.assertIn("Parar renderizado 3D", source)
        self.assertIn("Generar vista previa de alturas", source)
        self.assertIn("self.preview.hide()", source)


if __name__ == "__main__":
    unittest.main()
