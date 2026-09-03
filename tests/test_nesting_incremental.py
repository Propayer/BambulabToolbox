import random
import time
import unittest
import xml.etree.ElementTree as ET

from shapely.geometry import box

from jarvis_bambu.nesting_optimizer import (
    NestingOptimizer,
    NestingPerformanceMetrics,
    Placement,
    PlateOccupancyState,
)
from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions


def make_optimizer():
    optimizer = object.__new__(NestingOptimizer)
    optimizer.options = OptimizerOptions("advanced", "medium")
    optimizer.started = time.monotonic()
    optimizer.deadline = None
    optimizer.padding = .5
    optimizer.bed_padding = .5
    optimizer.bed = box(0, 0, 200, 200)
    optimizer.safe_bed = optimizer.bed.buffer(-.5)
    optimizer._rotation_cache = {}
    optimizer._buffered_rotation_cache = {}
    optimizer._raster_cache = {}
    optimizer.performance = NestingPerformanceMetrics()
    optimizer.spatial_hash_cell_size = 15.0
    return optimizer


def make_item(index, size=5.0):
    return ModelItem(
        index, str(index), 1, box(0, 0, size, size),
        (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0), ET.Element("instance"),
    )


class IncrementalOccupancyTests(unittest.TestCase):
    def test_incremental_occupancy_matches_full_rebuild_for_100_placements(self):
        optimizer = make_optimizer()
        state = PlateOccupancyState(optimizer, 1.5, 15.0)
        for index in range(100):
            x, y = 1 + (index % 10) * 15, 1 + (index // 10) * 15
            geometry = box(x, y, x + 5, y + 5)
            state.add(Placement(make_item(index), 1, 0, x, y, geometry))

        rebuilt = [0] * state.height
        optimizer.performance.occupancy_rebuilds += 1
        for geometry in state.buffered_geometries:
            optimizer._paint_rows(
                geometry, rebuilt, state.minx, state.miny,
                state.resolution, state.width, state.height,
            )
        self.assertEqual(state.occupancy_rows, rebuilt)
        self.assertEqual(optimizer.performance.occupancy_incremental_updates, 100)

    def test_spatial_hash_collision_matches_exhaustive_check(self):
        optimizer = make_optimizer()
        state = PlateOccupancyState(optimizer, 1.5, 15.0)
        for index in range(50):
            x, y = 2 + (index % 10) * 18, 2 + (index // 10) * 18
            geometry = box(x, y, x + 7, y + 7)
            state.add(Placement(make_item(index, 7), 1, 0, x, y, geometry))

        rng = random.Random(20260901)
        for _ in range(500):
            x, y = rng.uniform(0, 192), rng.uniform(0, 192)
            candidate = box(x, y, x + 8, y + 8).buffer(optimizer.padding)
            exhaustive = any(candidate.intersects(item) for item in state.buffered_geometries)
            indexed = any(
                candidate.intersects(state.buffered_geometries[index])
                for index in state.neighbor_indices(candidate.bounds)
            )
            self.assertEqual(indexed, exhaustive)

    def _assert_large_solution(self, count):
        optimizer = make_optimizer()
        items = [make_item(index) for index in range(count)]
        solution = optimizer._pack_minimum_plates(items, {id(item): 0 for item in items})
        self.assertEqual(sum(map(len, solution)), count)
        optimizer._validate_assignments(solution)
        self.assertEqual(optimizer.performance.occupancy_rebuilds, 0)
        self.assertEqual(optimizer.performance.occupancy_incremental_updates, count)

    def test_172_piece_solution_is_valid(self):
        self._assert_large_solution(172)

    def test_300_piece_solution_is_valid(self):
        self._assert_large_solution(300)


if __name__ == "__main__":
    unittest.main()
