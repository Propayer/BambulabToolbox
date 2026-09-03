import time
import unittest
import xml.etree.ElementTree as ET

from shapely.geometry import box

from jarvis_bambu.nesting_optimizer import (
    Genome, NestingOptimizer, NestingPerformanceMetrics, Placement,
    SolutionEvaluation,
)
from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions


def make_optimizer(selective=True):
    optimizer = object.__new__(NestingOptimizer)
    optimizer.options = OptimizerOptions(
        "advanced", "medium", selective_scoring=selective,
        full_score_top_k=1, fast_score_threshold_ratio=0.0,
        preserve_exact_evolution=False,
    )
    optimizer.started = time.monotonic()
    optimizer.deadline = None
    optimizer.padding = optimizer.bed_padding = .5
    optimizer.bed = box(0, 0, 100, 100)
    optimizer.safe_bed = optimizer.bed.buffer(-.5)
    optimizer.performance = NestingPerformanceMetrics()
    optimizer._rotation_cache = {}
    optimizer._buffered_rotation_cache = {}
    optimizer._raster_cache = {}
    optimizer.spatial_hash_cell_size = 15.0
    return optimizer


def solution(count=1, plates=1):
    result = [[] for _ in range(plates)]
    for index in range(count):
        item = ModelItem(index + 1, str(index), 1, box(0, 0, 5, 5),
                         (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0), ET.Element("instance"))
        x, y = 2 + (index % 10) * 7, 2 + (index // 10) * 7
        plate = index % plates
        result[plate].append(Placement(item, plate + 1, 0, x, y, box(x, y, x + 5, y + 5)))
    return result


def evaluation(plates, quality, number):
    genome = Genome((number,), (0,))
    packed = solution(max(plates, 1), plates)
    return SolutionEvaluation(genome, packed, (plates, quality), (number,))


class Phase3ScoringTests(unittest.TestCase):
    def test_more_plates_is_rejected_before_full_score(self):
        optimizer = make_optimizer()
        selected = optimizer._select_full_score_candidates([evaluation(3, 1, 1)], (2, 10))
        self.assertEqual(selected, set())

    def test_fewer_plates_always_reaches_full_score(self):
        optimizer = make_optimizer()
        selected = optimizer._select_full_score_candidates([evaluation(1, 999, 1)], (2, 10))
        self.assertEqual(selected, {0})

    def test_same_plate_count_uses_fast_score_and_top_k(self):
        optimizer = make_optimizer()
        candidates = [evaluation(2, value, index) for index, value in enumerate((30, 10, 20))]
        self.assertEqual(optimizer._select_full_score_candidates(candidates, (2, 0)), {1})

    def test_stable_signature_cache_avoids_duplicate_full_score(self):
        optimizer = make_optimizer()
        packed = solution(3)
        cache = {}
        first = optimizer._exact_score_cached(packed, cache)
        duplicate = [[Placement(p.item, p.plate, p.angle, p.x, p.y, p.geometry)
                      for p in packed[0]]]
        second = optimizer._exact_score_cached(duplicate, cache)
        self.assertEqual(first, second)
        self.assertEqual(optimizer.performance.full_scores_executed, 1)
        self.assertEqual(optimizer.performance.score_cache_hits, 1)

    def test_legacy_mode_scores_every_candidate(self):
        optimizer = make_optimizer(selective=False)
        candidates = [evaluation(plates, index, index)
                      for index, plates in enumerate((1, 2, 3))]
        self.assertEqual(optimizer._select_full_score_candidates(candidates, (1, 0)), {0, 1, 2})

    def test_selective_and_legacy_keep_plate_priority_and_exact_quality(self):
        models = solution(12)[0]
        items = [placement.item for placement in models]
        legacy = make_optimizer(selective=False)
        selective = make_optimizer(selective=True)
        legacy.options.preserve_exact_evolution = True
        selective.options.preserve_exact_evolution = True
        legacy_solution = legacy._search_advanced(items)
        selective_solution = selective._search_advanced(items)
        self.assertEqual(len(legacy_solution), len(selective_solution))
        self.assertEqual(legacy._solution_score(legacy_solution),
                         selective._solution_score(selective_solution))


if __name__ == "__main__":
    unittest.main()
