"""Reproducible isolated legacy-vs-hybrid vector fallback benchmark."""

from __future__ import annotations

import argparse
import random
import time
from unittest.mock import patch

from jarvis_bambu.nesting_optimizer import NestingPerformanceMetrics, Placement, PlateOccupancyState
from tests.test_vector_fallback_phase5 import make_optimizer, model
from shapely.geometry import box


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260902)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    legacy_seconds = hybrid_seconds = 0.0
    legacy_candidates = hybrid_candidates = found = exact_matches = 0
    for scenario in range(args.scenarios):
        optimizer = make_optimizer()
        state = PlateOccupancyState(optimizer, 1.0, 5.0)
        placed = []
        cells = [(x, y) for y in range(1, 26, 5) for x in range(1, 26, 5)]
        rng.shuffle(cells)
        for index, (x, y) in enumerate(cells[:rng.randint(14, 23)]):
            current = model(10000 + scenario * 30 + index, 3.5, 3.5)
            geometry = box(x, y, x + 3.5, y + 3.5)
            buffered = geometry.buffer(.25)
            placement = Placement(current, 1, 0, x, y, geometry, buffered, buffered.bounds)
            placed.append(placement); state.add(placement)
        candidate = model(scenario + 1, rng.choice((2.5, 3.5, 4.5)),
                          rng.choice((2.5, 3.5, 4.5)))
        started = time.perf_counter()
        legacy = optimizer._place_item_fallback_legacy(candidate, 1, placed, 0, state)
        legacy_seconds += time.perf_counter() - started
        legacy_candidates += optimizer.performance.exhaustive_fallback_candidates
        optimizer.performance = NestingPerformanceMetrics()
        started = time.perf_counter()
        with patch.object(optimizer, "_place_item_raster", return_value=None):
            hybrid = optimizer._place_item(candidate, 1, placed, 0, state)
        hybrid_seconds += time.perf_counter() - started
        hybrid_candidates += optimizer.performance.fallback_candidates
        found += hybrid is not None
        if legacy is not None and hybrid is None:
            raise AssertionError(f"hybrid lost scenario {scenario}")
        if legacy is not None and hybrid is not None and (
            legacy.angle, round(legacy.x, 8), round(legacy.y, 8)
        ) == (hybrid.angle, round(hybrid.x, 8), round(hybrid.y, 8)):
            exact_matches += 1
    print({"scenarios": args.scenarios, "found": found, "exact_matches": exact_matches,
           "legacy_seconds": round(legacy_seconds, 6),
           "hybrid_seconds": round(hybrid_seconds, 6),
           "speedup": round(legacy_seconds / max(hybrid_seconds, 1e-12), 3),
           "legacy_candidates": legacy_candidates,
           "hybrid_candidates": hybrid_candidates,
           "candidate_reduction": round(legacy_candidates / max(hybrid_candidates, 1), 3)})


if __name__ == "__main__":
    main()
