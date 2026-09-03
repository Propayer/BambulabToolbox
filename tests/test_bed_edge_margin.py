import unittest
import xml.etree.ElementTree as ET
from shapely.geometry import Polygon, box
from jarvis_bambu.nesting_optimizer import NestingOptimizer, NestingPerformanceMetrics, Placement, PlateOccupancyState
from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions

def optimizer(bed=None):
    value=object.__new__(NestingOptimizer); value.options=OptimizerOptions("advanced","low")
    value.padding=value.options.clearance_mm/2; value.bed=bed or box(0,0,100,100)
    value.bed_padding=value.options.bed_edge_margin_mm; value.safe_bed=value.bed.buffer(-value.bed_padding)
    value.deadline=None; value._rotation_cache={}; value._buffered_rotation_cache={}; value._raster_cache={}; value._dimension_cache={}
    value.performance=NestingPerformanceMetrics(); value.spatial_hash_cell_size=15
    return value
def item(size=10): return ModelItem(1,"piece",1,box(0,0,size,size),(1,0,0,0,1,0,0,0,1,0,0,0),ET.Element("instance"))
def placement_at(value,x,y,size=10):
    geometry=box(x,y,x+size,y+size); buffered=geometry.buffer(value.padding)
    return Placement(item(size),1,0,x,y,geometry,buffered,buffered.bounds)

class BedEdgeMarginTests(unittest.TestCase):
    def test_margin_source_is_independent_from_piece_spacing(self):
        simple=OptimizerOptions("simple","low"); advanced=OptimizerOptions("advanced","low")
        self.assertEqual(simple.bed_edge_margin_mm,.5); self.assertEqual(advanced.bed_edge_margin_mm,.5)
        self.assertNotEqual(simple.clearance_mm,advanced.clearance_mm)
    def test_zero_quarter_and_point49_are_rejected(self):
        value=optimizer()
        for distance in (0,.25,.49):
            with self.subTest(distance=distance), self.assertRaises(ValueError): value._validate_assignments([[placement_at(value,distance,5)]])
    def test_exact_half_and_greater_are_accepted(self):
        value=optimizer()
        for distance in (.5,.500001,.75): value._validate_assignments([[placement_at(value,distance,5)]])
    def test_corner_requires_margin_on_both_axes(self):
        value=optimizer()
        with self.assertRaises(ValueError): value._validate_assignments([[placement_at(value,.5,.49)]])
        value._validate_assignments([[placement_at(value,.5,.5)]])
    def test_non_rectangular_plate_uses_polygon_buffer(self):
        value=optimizer(Polygon([(0,0),(30,0),(30,20),(20,30),(0,30)]))
        with self.assertRaises(ValueError): value._validate_assignments([[placement_at(value,20,20,5)]])
        value._validate_assignments([[placement_at(value,10,10,5)]])
    def test_raster_uses_edge_margin(self):
        value=optimizer(); state=PlateOccupancyState(value,1,15)
        result=value._place_item_raster(item(),1,[],0,state)
        self.assertIsNotNone(result); self.assertTrue(value.safe_bed.covers(result.geometry)); self.assertGreaterEqual(result.geometry.bounds[0],.5)
    def test_vector_fallback_uses_edge_margin(self):
        value=optimizer(); state=PlateOccupancyState(value,1,15)
        result=value._place_item_fallback_legacy(item(),1,[],0,state)
        self.assertIsNotNone(result); self.assertTrue(value.safe_bed.covers(result.geometry))
    def test_timeout_completion_uses_edge_margin(self):
        value=optimizer(); value.deadline=0
        solution=value._pack_minimum_plates([item(10)])
        self.assertTrue(value.safe_bed.covers(solution[0][0].geometry)); value._validate_assignments(solution)

if __name__=="__main__": unittest.main()
