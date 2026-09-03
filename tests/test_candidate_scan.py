import random
import unittest

import numpy as np
from shapely.geometry import box

from jarvis_bambu.nesting_optimizer import (
    NestingOptimizer,
    RasterScanMask,
)
from tests.test_nesting_incremental import make_item, make_optimizer


def rows_to_grid(rows, width):
    byte_width = max(1, (width + 7) // 8)
    grid = np.zeros((len(rows), width), dtype=np.int16)
    for index, row in enumerate(rows):
        raw = np.frombuffer(int(row).to_bytes(byte_width, "little"), dtype=np.uint8)
        grid[index] = np.unpackbits(raw, bitorder="little")[:width]
    return grid


class LegacyScanOptimizer(NestingOptimizer):
    _use_legacy_candidate_scan = True


class CandidateScanEquivalenceTests(unittest.TestCase):
    def test_1000_random_scans_match_legacy(self):
        rng = random.Random(20260901)
        for scenario in range(1000):
            bed_width = rng.randint(24, 256)
            bed_height = rng.randint(8, 80)
            mask_width = rng.randint(1, min(48, bed_width))
            mask_height = rng.randint(1, min(16, bed_height))
            density = rng.uniform(0.0, 0.75)
            occupancy_rows = []
            for _ in range(bed_height):
                row = sum(
                    1 << bit for bit in range(bed_width)
                    if rng.random() < density
                )
                occupancy_rows.append(row)
            mask_rows = []
            for _ in range(mask_height):
                row = sum(
                    1 << bit for bit in range(mask_width)
                    if rng.random() < rng.uniform(.05, .95)
                )
                mask_rows.append(row)
            if not any(mask_rows):
                mask_rows[rng.randrange(mask_height)] = 1
            mask = RasterScanMask.from_rows(mask_rows, mask_width, mask_height)
            y_cell = rng.randrange(bed_height - mask_height + 1)
            x_count = bed_width - mask_width + 1
            grid = rows_to_grid(occupancy_rows, bed_width)
            legacy = NestingOptimizer._legacy_raster_scan(
                occupancy_rows, mask, y_cell, x_count
            )
            numpy_result = NestingOptimizer._numpy_raster_scan(
                grid, mask, y_cell, x_count
            )
            bitset_result = NestingOptimizer._bitset_raster_scan(
                occupancy_rows, mask, y_cell, x_count
            )
            self.assertTrue(np.array_equal(legacy, numpy_result), scenario)
            self.assertTrue(np.array_equal(legacy, bitset_result), scenario)

    def test_end_to_end_placements_match_for_multiple_seeds(self):
        for seed in range(10):
            rng = random.Random(seed)
            legacy = make_optimizer()
            legacy._use_legacy_candidate_scan = True
            optimized = make_optimizer()
            legacy.bed = optimized.bed = box(0, 0, 60, 60)
            legacy.safe_bed = optimized.safe_bed = legacy.bed.buffer(-.5)
            legacy_items = [make_item(index, rng.uniform(2.0, 12.0)) for index in range(30)]
            sizes = [item.footprint.bounds[2] for item in legacy_items]
            optimized_items = [make_item(index, size) for index, size in enumerate(sizes)]
            preferred_legacy = {
                id(item): rng.randrange(0, 180, 2) for item in legacy_items
            }
            preferred_optimized = {
                id(item): preferred_legacy[id(old)]
                for old, item in zip(legacy_items, optimized_items)
            }
            first = legacy._pack_minimum_plates(legacy_items, preferred_legacy)
            second = optimized._pack_minimum_plates(optimized_items, preferred_optimized)

            def signature(solution):
                return [
                    (placement.item.object_id, placement.plate, placement.angle,
                     round(placement.x, 9), round(placement.y, 9))
                    for plate in solution for placement in plate
                ]

            self.assertEqual(signature(first), signature(second), seed)


if __name__ == "__main__":
    unittest.main()
