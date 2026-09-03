"""Reproducible Phase-3 full-flow benchmark (legacy versus selective scoring)."""

from __future__ import annotations

import json
import time
import argparse

from benchmark_nesting_incremental import items, optimizer
from jarvis_bambu.nesting_optimizer import NestingOptimizer


def run(count, selective):
    instance = optimizer(NestingOptimizer)
    instance.options.selective_scoring = selective
    instance.options.score_cache_enabled = selective
    instance.options.preview_mode = "debug"  # deterministic, single-thread comparison
    models = items(count)
    started = time.perf_counter()
    solution = instance._search_advanced(models)
    elapsed = time.perf_counter() - started
    exact = instance._solution_score(solution)
    metrics = instance.performance.as_dict()
    scored = metrics["full_scores_executed"] + metrics["full_scores_avoided"]
    metric_names = (
        "packing_seconds", "solution_score_seconds", "unary_union_seconds",
        "convex_hull_seconds", "free_space_seconds", "fragmentation_seconds",
        "fast_score_seconds", "generation_seconds", "genomes_evaluated",
        "unique_genomes_evaluated", "cache_hits", "cache_misses",
        "score_cache_hits", "score_cache_misses", "full_scores_executed",
        "full_scores_avoided", "selective_full_scores_avoided",
        "time_to_first_solution", "total_optimization_seconds",
    )
    return {
        "pieces": count,
        "mode": "selective" if selective else "legacy",
        "total_optimization_seconds": round(elapsed, 6),
        "solutions_per_second": round(metrics["unique_genomes_evaluated"] / elapsed, 3),
        "plates": len(solution),
        "final_exact_score": exact,
        "full_scores_avoided_percent": round(
            100 * metrics["full_scores_avoided"] / max(1, scored), 2
        ),
        "memory_note": "RSS no medido para no distorsionar el tiempo con tracemalloc",
        "metrics": {name: metrics[name] for name in metric_names},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=(83, 172, 300))
    args = parser.parse_args()
    for count in args.sizes:
        before = run(count, False)
        after = run(count, True)
        print(json.dumps({
            "before_phase_3": before,
            "after_phase_3": after,
            "speedup": round(before["total_optimization_seconds"] /
                             after["total_optimization_seconds"], 3),
            "same_plates": before["plates"] == after["plates"],
            "same_exact_score": before["final_exact_score"] == after["final_exact_score"],
        }), flush=True)


if __name__ == "__main__":
    main()
