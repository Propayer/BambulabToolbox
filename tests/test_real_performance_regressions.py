import io
import os
import time
import unittest
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from shapely.affinity import rotate, translate
from shapely.geometry import box

from jarvis_bambu.nesting_optimizer import (
    NestingOptimizer, NestingPerformanceMetrics, Placement,
)
from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions
from jarvis_bambu.preview_reporter import PreviewReporter


def optimizer(workers=1):
    result = object.__new__(NestingOptimizer)
    result.options = OptimizerOptions("advanced", "low", optimizer_workers=workers)
    result.started = time.monotonic()
    result.deadline = None
    result.padding = result.bed_padding = .5
    result.bed = box(0, 0, 60, 60)
    result.safe_bed = result.bed.buffer(-.5)
    result._rotation_cache = {}
    result._buffered_rotation_cache = {}
    result._raster_cache = {}
    result.performance = NestingPerformanceMetrics()
    result.spatial_hash_cell_size = 10.0
    return result


def item(number, size=24):
    return ModelItem(number, str(number), 1, box(0, 0, size, size),
                     (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0), ET.Element("instance"))


class RealPerformanceRegressionTests(unittest.TestCase):
    def test_initial_population_uses_pool(self):
        instance = optimizer(2)
        instance._search_advanced([item(index) for index in range(6)])
        self.assertGreaterEqual(instance.performance.worker_tasks, 2)
        self.assertGreater(instance.performance.worker_startup_seconds, 0)

    def test_expired_search_without_candidate_returns_promptly(self):
        instance = optimizer()
        model = item(99, 20)
        blockers = [Placement(item(1, 60), 1, 0, 0, 0, box(0, 0, 60, 60))]
        instance.deadline = time.monotonic() - .001
        started = time.perf_counter()
        result = instance._place_item_raster(model, 1, blockers)
        self.assertIsNone(result)
        self.assertLess(time.perf_counter() - started, .1)

    def test_pack_deadline_has_small_overrun_and_valid_result(self):
        instance = optimizer()
        models = [item(index) for index in range(8)]
        instance.deadline = time.monotonic() - .001
        started = time.perf_counter()
        solution = instance._pack_minimum_plates(models)
        # Smart completion performs real collision-safe repacking instead of
        # the former one-item-per-plate shortcut, but remains tightly bounded.
        self.assertLess(time.perf_counter() - started, 1.0)
        instance._validate_assignments(solution)

    def test_prebuffer_then_translate_is_equivalent(self):
        geometry = rotate(box(-7, -3, 9, 5), 37, origin=(0, 0))
        expected = translate(geometry, 13.25, -4.75).buffer(.5)
        actual = translate(geometry.buffer(.5), 13.25, -4.75)
        self.assertTrue(expected.equals_exact(actual, 1e-9))

    def test_rotated_buffers_are_reused(self):
        instance = optimizer()
        model = item(1)
        first = instance._buffered_rotated(model, 30)
        second = instance._buffered_rotated(model, 30)
        self.assertIs(first, second)
        self.assertEqual(instance.performance.buffers_rotated_created, 1)
        self.assertGreater(instance.performance.buffers_reused, 0)

    def test_fallback_uses_exact_collision_authority(self):
        instance = optimizer()
        first_item = item(1, 20)
        first = Placement(first_item, 1, 0, .5, .5, box(.5, .5, 20.5, 20.5))
        first.buffered_geometry = first.geometry.buffer(.5)
        first.buffered_bounds = first.buffered_geometry.bounds
        from jarvis_bambu.nesting_optimizer import PlateOccupancyState
        state = PlateOccupancyState(instance, 2.0, 10.0)
        state.add(first)
        with patch.object(instance, "_place_item_raster", return_value=None):
            placed = instance._place_item(item(2, 20), 1, [first], 0, state)
        self.assertIsNotNone(placed)
        self.assertFalse(placed.buffered_geometry.intersects(first.buffered_geometry))
        self.assertGreater(instance.performance.fallback_calls, 0)

    def test_preview_retries_a_locked_target(self):
        source = Path("frame.tmp")
        target = Path("frame.png")
        with patch.object(Path, "replace", side_effect=[PermissionError(), None]) as replace:
            with patch("jarvis_bambu.preview_reporter.time.sleep"):
                self.assertTrue(PreviewReporter._replace_with_retry(source, target))
        self.assertEqual(replace.call_count, 2)

    def test_preview_handles_many_timeout_plates(self):
        with tempfile.TemporaryDirectory() as folder:
            reporter = object.__new__(PreviewReporter)
            reporter.image_path = Path(folder) / "preview.png"
            reporter.state_path = Path(folder) / "preview.json"
            reporter.bed = box(0, 0, 60, 60)
            reporter.started = time.monotonic()
            reporter.on_update = None
            reporter._render([[] for _ in range(100)], 0, None)
            self.assertTrue(reporter.image_path.exists())

    def test_utf8_reconfigure_accepts_arrow_on_cp1252_console(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        stream.write("4 -> 3 y 4 → 3")
        stream.flush()
        self.assertIn("→".encode("utf-8"), raw.getvalue())


if __name__ == "__main__":
    unittest.main()
