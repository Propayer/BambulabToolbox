from __future__ import annotations

import time
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..nesting_optimizer import NestingOptimizer
from ..optimizer_models import OptimizerOptions

logger = logging.getLogger(__name__)


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
    request_id: str = ""


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
    request_id = uuid.uuid4().hex
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
        optimizer.performance.as_dict(), result.generations, request_id,
    )
    logger.info(
        "Optimization completed request_id=%s input_path=%s output_path=%s "
        "improved=%s original_plate_count=%d final_plate_count=%d",
        request_id, structured.input_path, structured.output_path,
        structured.improved, structured.original_plate_count,
        structured.final_plate_count,
    )
    if progress_callback:
        progress_callback({"status": "finished", "result": structured})
    return structured
