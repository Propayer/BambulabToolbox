from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from shapely.geometry.base import BaseGeometry


Mode = Literal["simple", "advanced"]
Effort = str


@dataclass(slots=True)
class OptimizerOptions:
    mode: Mode
    effort: Effort
    ask_before_open: bool = True
    preview: bool = False
    preview_target: Literal["pc", "echo_show"] = "pc"
    preview_mode: Literal["improvements", "debug"] = "improvements"
    compactness_weight: float = 1.0
    fragmentation_weight: float = 2.0
    largest_free_region_weight: float = 1.0
    small_gap_penalty: float = 2.0
    small_gap_area_mm2: float = 400.0
    preview_update_interval_ms: int = 50
    debug_verbose: bool = False
    spatial_hash_cell_mm: float = 15.0
    selective_scoring: bool = True
    full_score_top_k: int = 2
    fast_score_threshold_ratio: float = 0.05
    fast_score_resolution_mm: float = 6.0
    preserve_exact_evolution: bool = True
    score_cache_enabled: bool = True
    optimizer_workers: int = 0
    debug_sequential: bool = False
    global_seed: int = 20260826
    bed_edge_margin_mm: float = 0.5

    @property
    def allow_cross_plate_moves(self) -> bool:
        return self.mode == "advanced"

    @property
    def remove_empty_plates(self) -> bool:
        return self.mode == "advanced"

    @property
    def clearance_mm(self) -> float:
        return 1.5 if self.mode == "simple" else 1.0

    @property
    def time_limit_seconds(self) -> float | None:
        presets = {"low": 60.0, "medium": 180.0, "high": None}
        if self.effort in presets:
            return presets[self.effort]
        try:
            minutes = float(self.effort)
        except ValueError as exc:
            raise ValueError("El esfuerzo debe ser low, medium, high o un número de minutos") from exc
        if minutes <= 0:
            raise ValueError("Los minutos de optimización deben ser mayores que cero")
        return minutes * 60.0

    @property
    def angle_step(self) -> int:
        if self.effort == "low":
            return 5
        if self.effort == "medium":
            return 2
        return 1

    @property
    def evolutionary_profile(self) -> tuple[int, int, int]:
        """Población, generaciones máximas y generaciones sin mejora."""
        if self.effort == "low":
            return 4, 6, 3
        if self.effort == "medium":
            return 6, 18, 6
        if self.effort == "high":
            return 8, 100, 15
        return 6, 100_000, 100_000


@dataclass(slots=True)
class ModelItem:
    object_id: int
    name: str
    plate_index: int
    footprint: BaseGeometry
    z_transform: tuple[float, ...]
    instance_xml: object
    locked: bool = False


@dataclass(slots=True)
class Plate:
    index: int
    locked: bool
    xml: object
    origin: tuple[float, float] = (0.0, 0.0)
    items: list[ModelItem] = field(default_factory=list)


@dataclass(slots=True)
class OptimizationResult:
    source: Path
    output: Path
    original_plates: int
    optimized_plates: int
    moved_items: int
    improved: bool
    message: str
    generations: int = 0
