"""Benchmark a real 3MF without saving or opening an optimized project."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from pathlib import Path

from jarvis_bambu.nesting_optimizer import NestingOptimizer
from jarvis_bambu.optimizer_models import OptimizerOptions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cell-size", type=float, default=15.0)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    options = OptimizerOptions(
        "advanced", args.effort, preview=False,
        optimizer_workers=args.workers, spatial_hash_cell_mm=args.cell_size,
    )
    optimizer = NestingOptimizer(args.project, options)
    project_plates = optimizer.project.plates()
    optimizer._original_reference_solution = [
        optimizer._current_placements(plate.items, plate.index)
        for plate in project_plates if not plate.locked and plate.items
    ]
    models = [item for plate in project_plates if not plate.locked for item in plate.items]
    if args.limit is not None:
        models = models[:args.limit]
    started = time.perf_counter()
    solution = optimizer._search_advanced(models)
    elapsed = time.perf_counter() - started
    optimizer._validate_assignments(solution)
    score = optimizer._solution_score(solution)
    print(json.dumps({
        "pieces": len(models), "workers": args.workers,
        "cell_size": args.cell_size, "elapsed_seconds": elapsed,
        "plates": len(solution), "score": score,
        "metrics": optimizer.performance.as_dict(),
    }, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
