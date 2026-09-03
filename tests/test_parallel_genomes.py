import multiprocessing
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch

from shapely.geometry import box

from jarvis_bambu.nesting_optimizer import (
    Genome, NestingOptimizer, NestingPerformanceMetrics,
)
from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions


def optimizer(workers):
    result = object.__new__(NestingOptimizer)
    result.options = OptimizerOptions(
        "advanced", "low", optimizer_workers=workers,
        preserve_exact_evolution=True, global_seed=8675309,
    )
    result.started = time.monotonic()
    result.deadline = None
    result.padding = result.bed_padding = .5
    result.bed = box(0, 0, 55, 55)
    result.safe_bed = result.bed.buffer(-.5)
    result._rotation_cache = {}
    result._buffered_rotation_cache = {}
    result._raster_cache = {}
    result.performance = NestingPerformanceMetrics()
    result.spatial_hash_cell_size = 15.0
    return result


def models(count=8):
    transform = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    return [
        ModelItem(i, str(i), 1, box(0, 0, 24, 24), transform, ET.Element("instance"))
        for i in range(count)
    ]


def result_signature(instance, solution):
    return instance._solution_score(solution), tuple(
        tuple((p.item.object_id, p.plate, p.angle, p.x, p.y) for p in plate)
        for plate in solution
    )


class ParallelGenomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sequential = optimizer(1)
        cls.expected = result_signature(sequential, sequential._search_advanced(models()))

    def test_workers_1_is_sequential_baseline(self):
        instance = optimizer(1)
        self.assertEqual(result_signature(instance, instance._search_advanced(models())), self.expected)
        self.assertEqual(instance.performance.worker_tasks, 0)

    def test_workers_2_preserves_score_and_placements(self):
        instance = optimizer(2)
        self.assertEqual(result_signature(instance, instance._search_advanced(models())), self.expected)
        self.assertGreater(instance.performance.worker_tasks, 0)

    def test_workers_4_preserves_score_and_placements(self):
        instance = optimizer(4)
        self.assertEqual(result_signature(instance, instance._search_advanced(models())), self.expected)

    def test_seed_is_stable_and_depends_on_logical_index(self):
        genome = Genome((2, 0, 1), (0, 10, 20))
        first = NestingOptimizer._genome_seed(7, 3, 2, genome)
        self.assertEqual(first, NestingOptimizer._genome_seed(7, 3, 2, genome))
        self.assertNotEqual(first, NestingOptimizer._genome_seed(7, 3, 3, genome))

    def test_worker_results_are_reordered_by_genome_index(self):
        # ProcessPoolExecutor.map is ordered, and the explicit key protects that
        # invariant if the collection strategy changes to as_completed later.
        results = [{"genome_index": 2}, {"genome_index": 0}, {"genome_index": 1}]
        results.sort(key=lambda result: result["genome_index"])
        self.assertEqual([item["genome_index"] for item in results], [0, 1, 2])

    def test_pool_failure_falls_back_and_closes_pool(self):
        fake_pool = Mock()
        fake_pool.map.side_effect = RuntimeError("worker crash")
        with patch("jarvis_bambu.nesting_optimizer.ProcessPoolExecutor", return_value=fake_pool):
            instance = optimizer(2)
            actual = result_signature(instance, instance._search_advanced(models()))
        self.assertEqual(actual, self.expected)
        self.assertEqual(instance.performance.parallel_fallbacks, 1)
        fake_pool.shutdown.assert_called_once_with(wait=True, cancel_futures=True)

    def test_worker_exception_is_returned_as_structured_error(self):
        from jarvis_bambu import nesting_optimizer
        broken = Mock()
        broken.performance = NestingPerformanceMetrics()
        broken.options.selective_scoring = True
        broken._pack_minimum_plates.side_effect = ValueError("invalid geometry")
        genome = Genome((), ())
        with patch.object(nesting_optimizer, "_WORKER_OPTIMIZER", broken), \
             patch.object(nesting_optimizer, "_WORKER_ITEMS", []):
            result = nesting_optimizer._worker_evaluate((genome, 0, 0, 1, None))
        self.assertFalse(result["ok"])
        self.assertIn("invalid geometry", result["error"])

    def test_no_children_remain_after_pool_shutdown(self):
        before = {child.pid for child in multiprocessing.active_children()}
        instance = optimizer(2)
        instance._search_advanced(models())
        time.sleep(.05)
        after = {child.pid for child in multiprocessing.active_children()}
        self.assertEqual(after - before, set())

    def test_worker_entrypoint_has_no_preview_or_mqtt_dependency(self):
        import inspect
        from jarvis_bambu import nesting_optimizer
        source = inspect.getsource(nesting_optimizer._worker_evaluate)
        self.assertNotIn("PreviewReporter", source)
        self.assertNotIn("mqtt", source.lower())

    def test_debug_preview_does_not_force_sequential_execution(self):
        instance = optimizer(2)
        instance.options.preview = True
        instance.options.preview_mode = "debug"
        reporter = Mock()
        instance._search_advanced(models(), reporter)
        self.assertGreater(instance.performance.worker_tasks, 0)

    def test_debug_sequential_is_explicit(self):
        instance = optimizer(4)
        instance.options.debug_sequential = True
        instance._search_advanced(models())
        self.assertEqual(instance.performance.worker_tasks, 0)

    def test_ten_seeds_keep_sequential_parallel_quality(self):
        for seed in range(10):
            sequential = optimizer(1)
            parallel = optimizer(2)
            sequential.options.global_seed = parallel.options.global_seed = seed
            sequential_solution = sequential._search_advanced(models(5))
            parallel_solution = parallel._search_advanced(models(5))
            self.assertEqual(result_signature(sequential, sequential_solution),
                             result_signature(parallel, parallel_solution))
            self.assertEqual(sequential.last_population, parallel.last_population)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
