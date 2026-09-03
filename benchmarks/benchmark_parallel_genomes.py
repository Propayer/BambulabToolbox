"""Phase-4 benchmark. Run as a script so Windows spawn stays safe."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time

from benchmark_nesting_incremental import items, optimizer
from jarvis_bambu.nesting_optimizer import NestingOptimizer


def measure(piece_count: int, workers: int) -> dict:
    instance = optimizer(NestingOptimizer)
    instance.options.optimizer_workers = workers
    instance.options.preview = False
    models = items(piece_count)
    started = time.perf_counter()
    solution = instance._search_advanced(models)
    wall = time.perf_counter() - started
    score = instance._solution_score(solution)
    metrics = instance.performance
    effective_workers = instance._resolved_optimizer_workers(
        instance.options.evolutionary_profile[0]
    ) if workers == 0 else workers
    return {
        "pieces": piece_count,
        "workers": workers,
        "effective_workers": effective_workers,
        "plates": len(solution),
        "exact_score": score,
        "time_to_first_solution": round(metrics.time_to_first_solution, 6),
        "total_optimization_seconds": round(wall, 6),
        "genomes_per_second": round(metrics.unique_genomes_evaluated / wall, 3),
        "worker_startup_seconds": round(metrics.worker_startup_seconds, 6),
        "serialization_seconds": round(metrics.serialization_seconds, 6),
        "packing_cpu_seconds": round(metrics.packing_seconds, 6),
        "scoring_seconds": round(metrics.solution_score_seconds, 6),
        "cpu_utilization_approx_percent": round(
            100 * metrics.packing_seconds / max(wall, 1e-9), 1
        ),
        "peak_memory_per_worker_bytes": metrics.worker_peak_memory_bytes,
        "worker_tasks": metrics.worker_tasks,
        "parallel_fallbacks": metrics.parallel_fallbacks,
        "rotation_cache_hits": metrics.rotation_cache_hits,
        "rotation_cache_misses": metrics.rotation_cache_misses,
        "raster_cache_hits": metrics.raster_cache_hits,
        "raster_cache_misses": metrics.raster_cache_misses,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=(83, 172, 300))
    parser.add_argument("--workers", nargs="+", type=int, default=(1, 2, 4, 6))
    args = parser.parse_args()
    for size in args.sizes:
        baseline = None
        for workers in args.workers:
            result = measure(size, workers)
            if baseline is None:
                baseline = result["total_optimization_seconds"]
            result["speedup"] = round(
                baseline / result["total_optimization_seconds"], 3
            )
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
