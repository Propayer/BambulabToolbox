"""Reproducible benchmark for incremental plate occupancy.

Run from the repository root:
    python benchmarks/benchmark_nesting_incremental.py
"""

from __future__ import annotations

import argparse
import time
import xml.etree.ElementTree as ET

from shapely.geometry import box

from jarvis_bambu.nesting_optimizer import NestingOptimizer, NestingPerformanceMetrics
from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions


class LegacyRebuildOptimizer(NestingOptimizer):
    """Same search, but deliberately omits PlateOccupancyState."""

    _use_legacy_candidate_scan = True

    def _fill_plate(self, items, plate_index, preferred_angles=None, progress_callback=None):
        placed, remaining = [], []
        for item in items:
            preferred = preferred_angles.get(id(item)) if preferred_angles else None
            placement = self._place_item(item, plate_index, placed, preferred, None)
            if placement is None:
                remaining.append(item)
            else:
                placed.append(placement)
        return placed, remaining


def optimizer(kind):
    instance = object.__new__(kind)
    instance.options = OptimizerOptions("advanced", "medium")
    instance.started = time.monotonic()
    instance.deadline = None
    instance.padding = .5
    instance.bed_padding = .5
    instance.bed = box(0, 0, 200, 200)
    instance.safe_bed = instance.bed.buffer(-.5)
    instance._rotation_cache = {}
    instance._buffered_rotation_cache = {}
    instance._raster_cache = {}
    instance.performance = NestingPerformanceMetrics()
    instance.spatial_hash_cell_size = 15.0
    return instance


def items(count):
    transform = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    return [
        ModelItem(index, str(index), 1, box(0, 0, 5, 5), transform, ET.Element("instance"))
        for index in range(count)
    ]


def measure(kind, count):
    instance = optimizer(kind)
    models = items(count)
    started = time.perf_counter()
    solution = instance._pack_minimum_plates(models, {id(item): 0 for item in models})
    elapsed = time.perf_counter() - started
    return {
        "seconds_to_first_solution": round(elapsed, 4),
        "pieces_per_second": round(count / elapsed, 2),
        "plates": len(solution),
        **instance.performance.as_dict(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=(83, 172, 300))
    args = parser.parse_args()
    for count in args.sizes:
        before = measure(LegacyRebuildOptimizer, count)
        after = measure(NestingOptimizer, count)
        print({
            "pieces": count,
            "before": before,
            "after": after,
            "speedup": round(
                before["seconds_to_first_solution"] / after["seconds_to_first_solution"], 2
            ),
        }, flush=True)


if __name__ == "__main__":
    main()
