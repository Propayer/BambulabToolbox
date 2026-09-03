import random
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from shapely.geometry import box

from jarvis_bambu.nesting_optimizer import (
    NestingOptimizer, NestingPerformanceMetrics, Placement, PlateOccupancyState,
)
from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions


def make_optimizer():
    result = object.__new__(NestingOptimizer)
    result.options = OptimizerOptions("advanced", "low", optimizer_workers=1)
    result.padding = result.bed_padding = .25
    result.bed = box(0, 0, 30, 30)
    result.safe_bed = result.bed.buffer(-.25)
    result.deadline = None
    result._rotation_cache = {}
    result._buffered_rotation_cache = {}
    result._raster_cache = {}
    result.performance = NestingPerformanceMetrics()
    result.spatial_hash_cell_size = 5.0
    # The randomized test targets candidate generation, not rotation sampling.
    result._angles = lambda preferred=None: [0, 90]
    return result


def model(object_id, width, height):
    return ModelItem(object_id, str(object_id), 1, box(0, 0, width, height),
                     (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0), ET.Element("instance"))


class VectorFallbackPhase5Tests(unittest.TestCase):
    def test_dimension_rejects_piece_larger_than_every_free_region(self):
        optimizer = make_optimizer()
        optimizer.bed = box(0, 0, 5, 52)
        optimizer.safe_bed = box(.5, .5, 4.5, 51.5)
        state = PlateOccupancyState(optimizer, 1.0, 5.0)
        self.assertEqual(optimizer._compatible_free_regions(model(1, 20, 20), state, 0), [])
        self.assertGreater(optimizer.performance.dimension_rejections, 0)

    def test_dimension_filter_considers_ninety_degree_rotation(self):
        optimizer = make_optimizer()
        optimizer.bed = box(0, 0, 16, 26)
        optimizer.safe_bed = box(.5, .5, 15.5, 25.5)
        state = PlateOccupancyState(optimizer, 1.0, 5.0)
        matches = optimizer._compatible_free_regions(model(1, 20, 10), state, 0)
        self.assertTrue(any(angle == 90 for _region, angle, *_rest in matches))

    def test_dimension_filter_considers_intermediate_rotation(self):
        optimizer = make_optimizer()
        optimizer._angles = lambda preferred=None: [0, 45]
        optimizer.bed = box(0, 0, 16, 16)
        optimizer.safe_bed = box(.5, .5, 15.5, 15.5)
        state = PlateOccupancyState(optimizer, 1.0, 5.0)
        matches = optimizer._compatible_free_regions(model(1, 18, 2), state, 0)
        self.assertFalse(any(angle == 0 for _region, angle, *_rest in matches))
        self.assertTrue(any(angle == 45 for _region, angle, *_rest in matches))

    def test_bbox_feasibility_does_not_replace_exact_collision(self):
        optimizer = make_optimizer()
        obstacle_item = model(1, 10, 10)
        geometry = box(5, 5, 15, 15)
        buffered = geometry.buffer(.25)
        obstacle = Placement(obstacle_item, 1, 0, 5, 5, geometry, buffered, buffered.bounds)
        state = PlateOccupancyState(optimizer, 1.0, 5.0); state.add(obstacle)
        candidate = model(2, 8, 8)
        self.assertTrue(optimizer._compatible_free_regions(candidate, state, 0))
        rotated = optimizer._rotated(candidate, 0)
        result, reason, _filtered = optimizer._try_vector_candidate(
            candidate, 1, 0, rotated, optimizer._buffered_rotated(candidate, 0),
            6, 6, state.buffered_geometries, state)
        self.assertIsNone(result)
        self.assertEqual(reason, "exact")

    def test_timeout_completion_packs_existing_plates(self):
        optimizer = make_optimizer()
        pieces = [model(index, 4, 4) for index in range(192)]
        optimizer.deadline = 0.0
        solution = optimizer._pack_minimum_plates(pieces, {id(piece): 0 for piece in pieces})
        self.assertLess(len(solution), len(pieces))
        self.assertEqual(sum(map(len, solution)), len(pieces))
        optimizer._validate_assignments(solution)
        self.assertGreater(optimizer.performance.timeout_existing_plate_attempts, 0)
        self.assertEqual(optimizer.performance.timeout_final_plate_count, len(solution))

    def test_original_distribution_is_hard_plate_limit(self):
        original = [[1, 2], [3, 4]]
        candidate = [[1], [2], [3], [4]]
        self.assertIs(NestingOptimizer._respect_original_plate_limit(candidate, original), original)
        better = [[1, 2, 3, 4]]
        self.assertIs(NestingOptimizer._respect_original_plate_limit(better, original), better)

    def test_complete_reference_wins_when_deadline_is_already_expired(self):
        optimizer = make_optimizer()
        pieces = [model(1, 5, 5), model(2, 5, 5)]
        reference = []
        for index, piece in enumerate(pieces):
            geometry = box(1 + index * 6, 1, 6 + index * 6, 6)
            buffered = geometry.buffer(.25)
            reference.append(Placement(piece, 1, 0, 1 + index * 6, 1,
                                       geometry, buffered, buffered.bounds))
        optimizer._original_reference_solution = [reference]
        optimizer.deadline = 0.0
        self.assertIs(optimizer._pack_minimum_plates(pieces), optimizer._original_reference_solution)
        self.assertEqual(optimizer.performance.timeout_final_plate_count, 1)

    def test_2000_dense_random_scenarios_match_legacy_capability(self):
        rng = random.Random(20260902)
        exact_matches = 0
        for scenario in range(2000):
            optimizer = make_optimizer()
            state = PlateOccupancyState(optimizer, 1.0, 5.0)
            placed = []
            cells = [(x, y) for y in range(1, 26, 5) for x in range(1, 26, 5)]
            rng.shuffle(cells)
            for index, (x, y) in enumerate(cells[:rng.randint(14, 23)]):
                current = model(10_000 + scenario * 30 + index, 3.5, 3.5)
                geometry = box(x, y, x + 3.5, y + 3.5)
                buffered = geometry.buffer(.25)
                placement = Placement(current, 1, 0, x, y, geometry,
                                      buffered, buffered.bounds)
                placed.append(placement)
                state.add(placement)
            candidate = model(scenario + 1, rng.choice((2.5, 3.5, 4.5)),
                              rng.choice((2.5, 3.5, 4.5)))
            legacy = optimizer._place_item_fallback_legacy(
                candidate, 1, placed, 0, state)
            optimizer.performance = NestingPerformanceMetrics()
            with patch.object(optimizer, "_place_item_raster", return_value=None):
                hybrid = optimizer._place_item(candidate, 1, placed, 0, state)
            if legacy is not None:
                self.assertIsNotNone(hybrid, f"scenario {scenario}")
            if hybrid is not None:
                self.assertTrue(optimizer.safe_bed.covers(hybrid.geometry))
                self.assertFalse(any(hybrid.buffered_geometry.intersects(
                    existing.buffered_geometry) for existing in placed))
            if legacy is not None and hybrid is not None and (
                legacy.angle, round(legacy.x, 8), round(legacy.y, 8)
            ) == (hybrid.angle, round(hybrid.x, 8), round(hybrid.y, 8)):
                exact_matches += 1
        # A substantial deterministic subset retains the exact legacy choice;
        # other valid choices are allowed because frontier is intentionally first.
        self.assertGreaterEqual(exact_matches, 100)

    def test_frontier_metrics_and_profile_are_reported(self):
        optimizer = make_optimizer()
        state = PlateOccupancyState(optimizer, 1.0, 5.0)
        with patch.object(optimizer, "_place_item_raster", return_value=None):
            result = optimizer._place_item(model(1, 5, 5), 1, [], 0, state)
        self.assertIsNotNone(result)
        self.assertGreater(optimizer.performance.frontier_candidates, 0)
        self.assertGreater(optimizer.performance.frontier_successes, 0)
        report = optimizer.performance.as_dict()
        self.assertEqual(report["fallback_profile_calls"], 2)
        self.assertIn("fallback_profile_groups", report)


if __name__ == "__main__":
    unittest.main()
