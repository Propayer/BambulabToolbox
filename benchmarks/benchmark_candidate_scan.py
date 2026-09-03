"""Phase-2 benchmark: legacy X/Y/row scan versus optimized hybrid scan."""

from __future__ import annotations

import random
import time
import tracemalloc

import numpy as np

from benchmark_nesting_incremental import items, measure, optimizer
from jarvis_bambu.nesting_optimizer import NestingOptimizer, RasterScanMask


class LegacyScanOptimizer(NestingOptimizer):
    _use_legacy_candidate_scan = True


def total_benchmark(count, kind):
    result = measure(kind, count)
    instance = optimizer(kind)
    models = items(count)
    tracemalloc.start()
    instance._pack_minimum_plates(models, {id(item): 0 for item in models})
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result["peak_traced_memory_bytes"] = peak
    return result


def isolated_scan_benchmark(iterations=5000):
    rng = random.Random(20260901)
    width, height = 170, 170
    occupancy_rows = [rng.getrandbits(width) for _ in range(height)]
    byte_width = (width + 7) // 8
    grid = np.zeros((height, width), dtype=np.int16)
    for index, row in enumerate(occupancy_rows):
        raw = np.frombuffer(row.to_bytes(byte_width, "little"), dtype=np.uint8)
        grid[index] = np.unpackbits(raw, bitorder="little")[:width]
    mask_rows = [rng.getrandbits(18) for _ in range(12)]
    mask = RasterScanMask.from_rows(mask_rows, 18, 12)
    x_count = width - mask.width + 1
    ys = [index % (height - mask.height + 1) for index in range(iterations)]

    started = time.perf_counter()
    legacy = [NestingOptimizer._legacy_raster_scan(
        occupancy_rows, mask, y, x_count
    ) for y in ys]
    legacy_seconds = time.perf_counter() - started
    started = time.perf_counter()
    optimized = [NestingOptimizer._bitset_raster_scan(
        occupancy_rows, mask, y, x_count
    ) for y in ys]
    optimized_seconds = time.perf_counter() - started
    assert all(np.array_equal(a, b) for a, b in zip(legacy, optimized))
    return {
        "iterations": iterations,
        "legacy_seconds": round(legacy_seconds, 4),
        "optimized_seconds": round(optimized_seconds, 4),
        "speedup": round(legacy_seconds / optimized_seconds, 2),
        "positions_per_second": round(iterations * x_count / optimized_seconds),
    }


def main():
    for count in (83, 172, 300):
        before = total_benchmark(count, LegacyScanOptimizer)
        after = total_benchmark(count, NestingOptimizer)
        print({
            "pieces": count,
            "before_phase_2": before,
            "after_phase_2": after,
            "total_speedup": round(
                before["seconds_to_first_solution"]
                / after["seconds_to_first_solution"], 2
            ),
            "candidate_scan_speedup": round(
                before["candidate_scan_seconds"]
                / after["candidate_scan_seconds"], 2
            ),
        }, flush=True)
    print({"isolated_place_item_raster_scan": isolated_scan_benchmark()}, flush=True)


if __name__ == "__main__":
    main()
