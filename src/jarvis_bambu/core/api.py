from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..nesting_optimizer import NestingOptimizer
from ..optimizer_models import OptimizerOptions


@dataclass(slots=True)
class ProjectOptimizationResult:
    ok: bool
    improved: bool
    message: str
    input_path: Path
    output_path: Path | None
    original_plate_count: int
    final_plate_count: int
    score: tuple | None
    elapsed_seconds: float
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    generations: int = 0


def optimize_project(project_path: Path | str, options: OptimizerOptions,
                     output_path: Path | str | None = None,
                     progress_callback: Callable[[dict], None] | None = None,
                     preview_callback=None) -> ProjectOptimizationResult:
    """Run the existing engine without depending on MQTT, CLI or GUI."""
    source = Path(project_path).resolve()
    suffix = "optimizado_simple" if options.mode == "simple" else "optimizado_avanzado"
    output = (Path(output_path).resolve() if output_path else
              source.with_name(f"{source.stem}_{suffix}.3mf"))
    started = time.perf_counter()
    if progress_callback:
        progress_callback({"status": "starting", "input_path": str(source)})
    def report_preview(path, state):
        if preview_callback:
            preview_callback(path, state)
        if progress_callback:
            progress_callback({"status": "optimizing", "preview": str(path), **state})

    optimizer = NestingOptimizer(
        source, options,
        preview_callback=report_preview if (progress_callback or preview_callback) else None,
    )
    result = optimizer.optimize(output)
    elapsed = time.perf_counter() - started
    structured = ProjectOptimizationResult(
        True, result.improved, result.message, source,
        result.output if result.improved else None,
        result.original_plates, result.optimized_plates, None, elapsed, [],
        optimizer.performance.as_dict(), result.generations,
    )
    if progress_callback:
        progress_callback({"status": "finished", "result": structured})
    return structured
