from __future__ import annotations

import random
import os
import time
import warnings
import logging
import math
import hashlib
import multiprocessing
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from shapely.affinity import rotate, translate
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.wkb import loads as load_wkb
from PIL import Image, ImageDraw
import numpy as np

warnings.filterwarnings(
    "ignore", message="invalid value encountered in buffer", category=RuntimeWarning
)

from .optimizer_models import ModelItem, OptimizationResult, OptimizerOptions
from .three_mf_project import ThreeMFProject
from .preview_reporter import PreviewReporter

logger = logging.getLogger(__name__)

_WORKER_OPTIMIZER = None
_WORKER_ITEMS = None
_WORKER_INITIALIZED_AT = None
_WORKER_WARMUP_REPORTED = False


@dataclass(slots=True)
class Placement:
    item: ModelItem
    plate: int
    angle: float
    x: float
    y: float
    geometry: object
    buffered_geometry: object | None = None
    buffered_bounds: tuple[float, float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class FreeRegion:
    bounds: tuple[float, float, float, float]
    width: float
    height: float
    area: float


@dataclass(slots=True)
class NestingPerformanceMetrics:
    occupancy_rebuilds: int = 0
    occupancy_incremental_updates: int = 0
    raster_rejections: int = 0
    exact_collision_checks: int = 0
    spatial_candidates_returned: int = 0
    buffers_created: int = 0
    buffers_reused: int = 0
    occupancy_update_seconds: float = 0.0
    occupancy_rebuild_seconds: float = 0.0
    candidate_scan_seconds: float = 0.0
    exact_collision_seconds: float = 0.0
    scan_xy_positions_evaluated: int = 0
    scan_mask_rows_checked: int = 0
    scan_first_row_rejections: int = 0
    scan_multi_row_rejections: int = 0
    scan_valid_positions: int = 0
    scan_angles_evaluated: int = 0
    candidate_scan_piece_seconds: list[float] = field(default_factory=list)
    candidate_scan_angle_seconds: dict[float, float] = field(default_factory=dict)
    packing_seconds: float = 0.0
    solution_score_seconds: float = 0.0
    unary_union_seconds: float = 0.0
    convex_hull_seconds: float = 0.0
    free_space_seconds: float = 0.0
    fragmentation_seconds: float = 0.0
    fast_score_seconds: float = 0.0
    generation_seconds: float = 0.0
    genomes_evaluated: int = 0
    unique_genomes_evaluated: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    score_cache_hits: int = 0
    score_cache_misses: int = 0
    full_scores_executed: int = 0
    full_scores_avoided: int = 0
    selective_full_scores_avoided: int = 0
    time_to_first_solution: float = 0.0
    total_optimization_seconds: float = 0.0
    worker_startup_seconds: float = 0.0
    serialization_seconds: float = 0.0
    worker_tasks: int = 0
    worker_failures: int = 0
    parallel_fallbacks: int = 0
    worker_peak_memory_bytes: int = 0
    rotation_cache_hits: int = 0
    rotation_cache_misses: int = 0
    raster_cache_hits: int = 0
    raster_cache_misses: int = 0
    deadline_expirations: int = 0
    buffers_rotated_created: int = 0
    buffers_candidate_created: int = 0
    buffers_placement_created: int = 0
    buffers_collision_created: int = 0
    buffers_bed_created: int = 0
    buffers_fallback_created: int = 0
    buffer_rotated_seconds: float = 0.0
    buffer_candidate_seconds: float = 0.0
    buffer_collision_seconds: float = 0.0
    buffer_fallback_seconds: float = 0.0
    spatial_cells_queried: int = 0
    spatial_unique_candidates: int = 0
    spatial_max_neighbors: int = 0
    fallback_calls: int = 0
    fallback_candidates: int = 0
    fallback_seconds: float = 0.0
    fallback_buffers_created: int = 0
    fallback_exact_checks: int = 0
    frontier_candidates: int = 0
    frontier_successes: int = 0
    interval_candidates: int = 0
    interval_successes: int = 0
    exhaustive_fallback_calls: int = 0
    exhaustive_fallback_candidates: int = 0
    exhaustive_fallback_seconds: float = 0.0
    fallback_cache_hits: int = 0
    fallback_cache_misses: int = 0
    free_regions_detected: int = 0
    dimension_rejections: int = 0
    dimension_candidates: int = 0
    piece_gap_checks: int = 0
    piece_gap_matches: int = 0
    frontier_seconds: float = 0.0
    timeout_completion_used: int = 0
    timeout_remaining_items: int = 0
    timeout_existing_plate_attempts: int = 0
    timeout_new_plates_created: int = 0
    timeout_final_plate_count: int = 0
    fallback_call_profiles: list[dict] = field(default_factory=list)

    def as_dict(self, include_samples: bool = False) -> dict:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        if not include_samples:
            samples = result.pop("candidate_scan_piece_seconds")
            result["candidate_scan_pieces"] = len(samples)
            result["candidate_scan_max_piece_seconds"] = max(samples, default=0.0)
            profiles = result.pop("fallback_call_profiles")
            ordered = sorted(profiles, key=lambda value: value["seconds"], reverse=True)
            top_count = max(1, math.ceil(len(ordered) * .1)) if ordered else 0
            result["fallback_profile_calls"] = len(profiles)
            result["fallback_top_10_percent_seconds"] = sum(
                value["seconds"] for value in ordered[:top_count]
            )
            result["fallback_top_consumers"] = ordered[:10]
            grouped = {}
            for field_name in ("object_id", "angle", "plate"):
                totals = defaultdict(lambda: {"calls": 0, "seconds": 0.0, "candidates": 0})
                for value in profiles:
                    bucket = totals[value[field_name]]
                    bucket["calls"] += 1
                    bucket["seconds"] += value["seconds"]
                    bucket["candidates"] += value["total_candidates"]
                grouped[field_name] = [
                    {field_name: key, **summary}
                    for key, summary in sorted(
                        totals.items(), key=lambda pair: pair[1]["seconds"], reverse=True
                    )[:10]
                ]
            density_totals = defaultdict(lambda: {"calls": 0, "seconds": 0.0, "candidates": 0})
            for value in profiles:
                bucket_name = f"{math.floor(value['occupancy_density'] * 10) * 10}-{math.floor(value['occupancy_density'] * 10) * 10 + 10}%"
                bucket = density_totals[bucket_name]
                bucket["calls"] += 1; bucket["seconds"] += value["seconds"]
                bucket["candidates"] += value["total_candidates"]
            grouped["density"] = [{"density": key, **summary} for key, summary in
                                  sorted(density_totals.items(), key=lambda pair: pair[1]["seconds"], reverse=True)]
            result["fallback_profile_groups"] = grouped
        return result


@dataclass(frozen=True, slots=True)
class RasterScanMask:
    rows: tuple[int, ...]
    non_empty_rows: tuple[tuple[int, int], ...]
    row_arrays: tuple[tuple[int, np.ndarray], ...]
    width: int
    height: int
    set_bit_count: int
    first_non_empty_row: int
    last_non_empty_row: int
    width_bits: int
    bbox_raster: tuple[int, int, int, int]

    @classmethod
    def from_rows(cls, rows, width: int, height: int):
        packed_rows = tuple(rows)
        non_empty = tuple((index, row) for index, row in enumerate(packed_rows) if row)
        arrays = []
        byte_width = max(1, (width + 7) // 8)
        for index, row in non_empty:
            raw = np.frombuffer(int(row).to_bytes(byte_width, "little"), dtype=np.uint8)
            bits = np.unpackbits(raw, bitorder="little")[:width].astype(np.int16)
            arrays.append((index, bits))
        first = non_empty[0][0] if non_empty else 0
        last = non_empty[-1][0] if non_empty else -1
        return cls(
            packed_rows, non_empty, tuple(arrays), width, height,
            sum(row.bit_count() for _index, row in non_empty),
            first, last, width, (0, first, width, last + 1),
        )


class PlateOccupancyState:
    """Incremental raster and exact-collision metadata for one packed plate."""

    def __init__(self, optimizer, resolution: float, cell_size: float = 15.0):
        self.optimizer = optimizer
        self.resolution = resolution
        self.cell_size = cell_size
        self.minx, self.miny, self.maxx, self.maxy = optimizer.bed.bounds
        self.width = int((self.maxx - self.minx) // resolution)
        self.height = int((self.maxy - self.miny) // resolution)
        self.occupancy_rows = [0] * self.height
        self.occupancy_grid = np.zeros((self.height, self.width), dtype=np.int16)
        self.placements: list[Placement] = []
        self.bounds: list[tuple[float, float, float, float]] = []
        self.buffered_geometries: list[object] = []
        self.spatial_hash: dict[tuple[int, int], set[int]] = defaultdict(set)
        # Candidate axes and contact points are maintained once per placement.
        # They are only an accelerator: the exact exhaustive fallback remains
        # available whenever these points do not yield a solution.
        self.frontier_x: set[float] = {self.optimizer.safe_bed.bounds[0]}
        self.frontier_y: set[float] = {self.optimizer.safe_bed.bounds[1]}
        self.frontier_points: set[tuple[float, float]] = {
            (self.optimizer.safe_bed.bounds[0], self.optimizer.safe_bed.bounds[1])
        }
        self.fallback_cache: dict[tuple, Placement | None] = {}
        self.fallback_history: dict[tuple, dict[float, tuple[frozenset, frozenset]]] = {}
        self._free_regions_cache: tuple[FreeRegion, ...] | None = None
        self._free_geometry = None
        self.completion_regions: tuple[FreeRegion, ...] | None = None

    def _cells(self, bounds):
        minx, miny, maxx, maxy = bounds
        x0, x1 = math.floor(minx / self.cell_size), math.floor(maxx / self.cell_size)
        y0, y1 = math.floor(miny / self.cell_size), math.floor(maxy / self.cell_size)
        for cy in range(y0, y1 + 1):
            for cx in range(x0, x1 + 1):
                yield cx, cy

    def add(self, placement: Placement) -> None:
        started = time.perf_counter()
        # Any placement changes all collision answers. Negative answers are
        # otherwise reusable for repeated, geometrically identical models.
        self.fallback_cache.clear()
        self._free_regions_cache = None
        if placement.buffered_geometry is None:
            buffer_started = time.perf_counter()
            placement.buffered_geometry = placement.geometry.buffer(self.optimizer.padding)
            placement.buffered_bounds = placement.buffered_geometry.bounds
            metrics = self.optimizer.performance
            metrics.buffers_created += 1
            metrics.buffers_placement_created += 1
            metrics.buffer_collision_seconds += time.perf_counter() - buffer_started
        else:
            self.optimizer.performance.buffers_reused += 1
        if self._free_geometry is not None:
            self._free_geometry = self._free_geometry.difference(
                placement.buffered_geometry
            )
        index = len(self.placements)
        self.placements.append(placement)
        self.buffered_geometries.append(placement.buffered_geometry)
        self.bounds.append(placement.buffered_bounds)
        gap = self.optimizer.padding * 2
        pminx, pminy, pmaxx, pmaxy = placement.geometry.bounds
        new_x = (pminx - gap, pmaxx + gap)
        new_y = (pminy - gap, pmaxy + gap)
        bed_x, bed_y = self.optimizer.safe_bed.bounds[:2]
        for x in new_x:
            self.frontier_x.add(x)
            self.frontier_points.add((x, bed_y))
        for y in new_y:
            self.frontier_y.add(y)
            self.frontier_points.add((bed_x, y))
        # The two non-dominated bottom-left contacts of this obstacle.
        self.frontier_points.add((pmaxx + gap, pminy - gap))
        self.frontier_points.add((pminx - gap, pmaxy + gap))
        for cell in self._cells(placement.buffered_bounds):
            self.spatial_hash[cell].add(index)
        changed_rows = self.optimizer._paint_rows_incremental(
            placement.buffered_geometry, self.occupancy_rows,
            self.minx, self.miny, self.resolution, self.width, self.height,
        )
        byte_width = max(1, (self.width + 7) // 8)
        for row_index, row_bits in changed_rows:
            raw = np.frombuffer(
                int(row_bits).to_bytes(byte_width, "little"), dtype=np.uint8
            )
            self.occupancy_grid[row_index] = np.unpackbits(
                raw, bitorder="little"
            )[:self.width]
        metrics = self.optimizer.performance
        metrics.occupancy_incremental_updates += 1
        metrics.occupancy_update_seconds += time.perf_counter() - started

    def free_regions(self) -> tuple[FreeRegion, ...]:
        """Exact connected free-space components, cached until occupancy changes."""
        if self._free_regions_cache is not None:
            return self._free_regions_cache
        if self._free_geometry is None:
            if self.buffered_geometries:
                occupied = unary_union(self.buffered_geometries)
                self._free_geometry = self.optimizer.safe_bed.difference(occupied)
            else:
                self._free_geometry = self.optimizer.safe_bed
        free = self._free_geometry
        geometries = list(free.geoms) if hasattr(free, "geoms") else [free]
        regions = []
        for geometry in geometries:
            if geometry.is_empty or geometry.area <= 0:
                continue
            minx, miny, maxx, maxy = geometry.bounds
            regions.append(FreeRegion(
                (minx, miny, maxx, maxy), maxx - minx, maxy - miny, geometry.area
            ))
        self._free_regions_cache = tuple(regions)
        self.optimizer.performance.free_regions_detected += len(regions)
        return self._free_regions_cache

    def neighbor_indices(self, bounds) -> list[int]:
        indices: set[int] = set()
        cells = 0
        for cell in self._cells(bounds):
            cells += 1
            indices.update(self.spatial_hash.get(cell, ()))
        result = sorted(indices)
        metrics = self.optimizer.performance
        metrics.spatial_cells_queried += cells
        metrics.spatial_candidates_returned += len(result)
        metrics.spatial_unique_candidates += len(result)
        metrics.spatial_max_neighbors = max(metrics.spatial_max_neighbors, len(result))
        return result


@dataclass(frozen=True, slots=True)
class Genome:
    order: tuple[int, ...]
    preferred_angles: tuple[int, ...]


@dataclass(slots=True)
class SolutionEvaluation:
    genome: Genome
    solution: list[list[Placement]]
    fast_score: tuple
    signature: tuple
    exact_score: tuple | None = None


def _worker_initializer(payload: dict) -> None:
    """Build immutable geometry once per spawned worker process."""
    global _WORKER_OPTIMIZER, _WORKER_ITEMS, _WORKER_INITIALIZED_AT, _WORKER_WARMUP_REPORTED
    _WORKER_INITIALIZED_AT = time.perf_counter()
    _WORKER_WARMUP_REPORTED = False
    optimizer = object.__new__(NestingOptimizer)
    optimizer.options = OptimizerOptions(**payload["options"])
    optimizer.started = time.monotonic()
    optimizer.deadline = None
    optimizer.padding = payload["padding"]
    optimizer.bed_padding = payload["bed_padding"]
    optimizer.bed = load_wkb(payload["bed_wkb"])
    optimizer.safe_bed = load_wkb(payload["safe_bed_wkb"])
    optimizer._rotation_cache = {}
    optimizer._raster_cache = {}
    optimizer._buffered_rotation_cache = {}
    optimizer.performance = NestingPerformanceMetrics()
    optimizer.spatial_hash_cell_size = payload["spatial_hash_cell_size"]
    _WORKER_ITEMS = [
        ModelItem(
            raw["object_id"], raw["name"], raw["plate_index"],
            load_wkb(raw["footprint_wkb"]), tuple(raw["z_transform"]), None,
            raw["locked"],
        )
        for raw in payload["items"]
    ]
    items_by_id = {item.object_id: item for item in _WORKER_ITEMS}
    optimizer._original_reference_solution = []
    for compact_plate in payload.get("original_reference", []):
        restored = []
        for object_id, plate_id, angle, x, y in compact_plate:
            item = items_by_id[object_id]
            geometry = translate(optimizer._rotated(item, angle), xoff=x, yoff=y)
            buffered = translate(optimizer._buffered_rotated(item, angle), xoff=x, yoff=y)
            restored.append(Placement(item, plate_id, angle, x, y, geometry,
                                      buffered, buffered.bounds))
        optimizer._original_reference_solution.append(restored)
    _WORKER_OPTIMIZER = optimizer


def _worker_memory_bytes() -> int:
    try:
        import psutil
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        if os.name != "nt":
            return 0
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            handle = kernel32.GetCurrentProcess()
            get_memory = getattr(kernel32, "K32GetProcessMemoryInfo", None)
            if get_memory is None:
                get_memory = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
            get_memory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            get_memory.restype = wintypes.BOOL
            if get_memory(handle, ctypes.byref(counters), counters.cb):
                return int(counters.PeakWorkingSetSize)
        except (AttributeError, OSError):
            pass
        return 0


def _worker_evaluate(task: tuple) -> dict:
    """Pure CPU worker entrypoint returning only compact serializable data."""
    global _WORKER_WARMUP_REPORTED
    genome, generation, genome_index, seed, deadline_epoch = task
    optimizer = _WORKER_OPTIMIZER
    if optimizer is None or _WORKER_ITEMS is None:
        return {"ok": False, "error": "worker not initialized"}
    optimizer.performance = NestingPerformanceMetrics()
    optimizer.deadline = (time.monotonic() + max(0.0, deadline_epoch - time.time())
                          if deadline_epoch is not None else None)
    started = time.perf_counter()
    try:
        ordered = [_WORKER_ITEMS[index] for index in genome.order]
        angle_map = {
            id(_WORKER_ITEMS[index]): genome.preferred_angles[index]
            for index in range(len(_WORKER_ITEMS))
        }
        solution = optimizer._pack_minimum_plates(ordered, angle_map)
        fast_score = (optimizer._fast_solution_score(solution)
                      if optimizer.options.selective_scoring
                      else (len([plate for plate in solution if plate]), 0.0))
        compact = tuple(tuple(
            (p.item.object_id, p.plate, float(p.angle), float(p.x), float(p.y))
            for p in plate
        ) for plate in solution)
        warmup = 0.0
        if not _WORKER_WARMUP_REPORTED:
            _WORKER_WARMUP_REPORTED = True
        return {
            "ok": True, "genome": genome, "generation": generation,
            "genome_index": genome_index, "seed": seed,
            "placements": compact, "fast_score": fast_score,
            "packing_seconds": time.perf_counter() - started,
            "worker_startup_seconds": warmup,
            "worker_memory_bytes": _worker_memory_bytes(),
            "metrics": optimizer.performance.as_dict(),
        }
    except BaseException as exc:
        return {
            "ok": False, "genome": genome, "generation": generation,
            "genome_index": genome_index, "seed": seed,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


class NestingOptimizer:
    """Empaquetador 2D por contorno real con rotación libre sobre Z."""

    def __init__(
        self,
        source: Path,
        options: OptimizerOptions,
        preview_callback: Callable[[Path, dict], None] | None = None,
    ):
        self.started = time.monotonic()
        self.project = ThreeMFProject(source)
        self.options = options
        self.deadline = (
            self.started + options.time_limit_seconds
            if options.time_limit_seconds is not None else None
        )
        # Los brims de objetos cercanos pueden fusionarse. La distancia entre
        # modelos y el margen exterior del brim son restricciones distintas.
        self.padding = options.clearance_mm / 2.0
        # Independent constraints: padding separates pieces; bed padding keeps
        # every model inside the actual printable polygon.
        self.bed_padding = max(
            float(options.bed_edge_margin_mm), self.project.brim_extension
        )
        self.bed = self.project.printable_area
        self.safe_bed = self.bed.buffer(-self.bed_padding)
        self._rotation_cache = {}
        self._raster_cache = {}
        self._buffered_rotation_cache = {}
        self._dimension_cache = {}
        self.performance = NestingPerformanceMetrics()
        self.performance.buffers_bed_created = 1
        self.spatial_hash_cell_size = max(1.0, float(options.spatial_hash_cell_mm))
        self.preview_callback = preview_callback

    def optimize(self, output: Path) -> OptimizationResult:
        parse_finished = time.monotonic()
        plates = self.project.plates()
        original_count = len(plates)
        if self.project.by_object:
            # La envolvente del cabezal depende del modelo de máquina. Conservamos
            # un margen adicional seguro además de las áreas excluidas del perfil.
            self.padding += 18.0
            self.bed_padding += 18.0
            self.safe_bed = self.bed.buffer(-self.bed_padding)
        original_solution = [
            self._current_placements(plate.items, plate.index)
            for plate in plates if plate.items
        ]
        original_score = self._solution_score(original_solution)
        reporter = None
        if self.options.preview:
            reporter = PreviewReporter(
                output.parent / "preview_optimizacion.png",
                output.parent / "preview_optimizacion.json",
                self.bed,
                show_window=self.options.preview_target == "pc",
                on_update=self.preview_callback,
                update_interval_ms=self.options.preview_update_interval_ms,
            )

        if self.options.mode == "simple":
            assignments: list[list[Placement]] = []
            lock_states: list[bool] = []
            for plate in plates:
                if plate.locked:
                    assignments.append(self._current_placements(plate.items, plate.index))
                    lock_states.append(True)
                elif plate.items:
                    packed = self._pack_one_plate(plate.items, plate.index)
                    if packed is None:
                        raise ValueError(f"Las piezas de la plate {plate.index} no caben sin moverlas a otra plate")
                    assignments.append(packed)
                    lock_states.append(False)
                else:
                    assignments.append([])
                    lock_states.append(False)
        else:
            unlocked_items = [item for plate in plates if not plate.locked for item in plate.items]
            original_unlocked = [
                self._current_placements(plate.items, plate.index)
                for plate in plates if not plate.locked and plate.items
            ]
            self._original_reference_solution = original_unlocked
            packed_unlocked = self._search_advanced(unlocked_items, reporter) if unlocked_items else []
            # The original valid distribution is always a complete upper bound.
            # A timed-out search may improve quality, but may never expand it.
            packed_unlocked = self._respect_original_plate_limit(
                packed_unlocked, original_unlocked
            )
            assignments = []
            lock_states = []
            packed_index = 0
            for plate in plates:
                if plate.locked:
                    assignments.append(self._current_placements(plate.items, plate.index))
                    lock_states.append(True)
                elif packed_index < len(packed_unlocked):
                    assignments.append(packed_unlocked[packed_index])
                    lock_states.append(False)
                    packed_index += 1
                else:
                    assignments.append([])
                    lock_states.append(False)
            while packed_index < len(packed_unlocked):
                assignments.append(packed_unlocked[packed_index])
                lock_states.append(False)
                packed_index += 1
            while assignments and not assignments[-1] and not lock_states[-1]:
                assignments.pop()
                lock_states.pop()
            # Empty plates are not meaningful in an optimized project and must
            # not survive as gaps between non-empty/locked plates either.
            compacted = [
                (plate_assignments, locked)
                for plate_assignments, locked in zip(assignments, lock_states)
                if plate_assignments
            ]
            assignments = [value[0] for value in compacted]
            lock_states = [value[1] for value in compacted]

        self._validate_assignments(assignments)
        optimize_finished = time.monotonic()
        logger.info("Nesting performance: %s", self.performance.as_dict())
        moved = self._apply(assignments, lock_states)
        optimized_count = len(assignments)
        improved = moved > 0 and (
            optimized_count < original_count
            or self._solution_score(assignments) < original_score
        )
        if not improved:
            if self.options.preview and reporter is not None:
                reporter.update(assignments, getattr(self, "last_generation", 0),
                                self._solution_score(assignments), finished=True)
                if self.options.mode == "simple":
                    reporter.start()
            return OptimizationResult(
                source=self.project.source, output=output, original_plates=original_count,
                optimized_plates=original_count, moved_items=0, improved=False,
                message="La distribución actual ya es igual o mejor; no he cambiado el proyecto.",
                generations=getattr(self, "last_generation", 0),
            )
        write_started = time.monotonic()
        self.project.save(output)
        serialized_project = ThreeMFProject(output)
        serialized = serialized_project.serialized_layout_summary()
        serialized_object_count = sum(map(len, serialized.objects_by_plate.values()))
        expected_object_count = sum(map(len, assignments))
        logger.info(
            "Serialized 3MF validation: output=%s build_items=%d plate_ids=%s "
            "objects_by_plate=%s empty_plates=%s plate_metadata=%s orphan_metadata=%s",
            output, serialized.build_item_count, serialized.plate_ids,
            serialized.objects_by_plate, serialized.empty_plate_ids,
            serialized.plate_metadata, serialized.orphan_plate_metadata,
        )
        errors = []
        if serialized.plate_count != optimized_count:
            errors.append(
                f"plates lógicas={optimized_count}, serializadas={serialized.plate_count}"
            )
        if serialized_object_count != expected_object_count:
            errors.append(
                f"objetos esperados={expected_object_count}, serializados={serialized_object_count}"
            )
        if serialized.empty_plate_ids:
            errors.append(f"plates vacías={serialized.empty_plate_ids}")
        if serialized.orphan_plate_metadata:
            errors.append(f"metadata huérfana={serialized.orphan_plate_metadata}")
        if errors:
            raise RuntimeError(
                "El 3MF escrito no coincide con la solución optimizada: " + "; ".join(errors)
            )
        optimized_count = serialized.plate_count
        logger.debug(
            "Tiempos: parsing=%.3fs optimización=%.3fs escritura=%.3fs total=%.3fs",
            parse_finished - self.started, optimize_finished - parse_finished,
            time.monotonic() - write_started, time.monotonic() - self.started,
        )
        if self.options.preview and reporter is not None:
            reporter.update(assignments, getattr(self, "last_generation", 0),
                            self._solution_score(assignments), finished=True)
            if self.options.mode == "simple":
                reporter.start()
        return OptimizationResult(
            source=self.project.source, output=output, original_plates=original_count,
            optimized_plates=optimized_count, moved_items=moved, improved=True,
            message=(f"Optimización completada: {moved} piezas recolocadas; "
                     f"placas: {original_count} → {optimized_count}."),
            generations=getattr(self, "last_generation", 0),
        )

    def _expired(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline

    @staticmethod
    def _respect_original_plate_limit(candidate, original):
        return (original if len([plate for plate in candidate if plate])
                > len([plate for plate in original if plate]) else candidate)

    @staticmethod
    def _bounds_intersect(first, second) -> bool:
        return not (
            first[2] < second[0] or second[2] < first[0]
            or first[3] < second[1] or second[3] < first[1]
        )

    def _angles(self, preferred_angle: int | None = None):
        values = list(range(0, 180, self.options.angle_step))
        # Primero prueba las orientaciones más habituales.
        habitual = [x for x in (0, 90, 45, 135) if x in values]
        if preferred_angle is not None:
            normalized = int(preferred_angle) % 180
            # En una generación solo se evalúa el ángulo heredado y un pequeño
            # grupo de alternativas. Las mutaciones exploran el resto.
            nearby = ((normalized - self.options.angle_step) % 180,
                      (normalized + self.options.angle_step) % 180)
            return list(dict.fromkeys((normalized, *habitual, *nearby)))
        if self.options.mode == "simple":
            coarse = [x for x in range(0, 180, 15)]
            return list(dict.fromkeys((*habitual, *coarse)))
        return habitual + [x for x in values if x not in habitual]

    def _orientation_dimensions(self, item, preferred_angle=None):
        if not hasattr(self, "_dimension_cache"):
            self._dimension_cache = {}
        key = (id(item), None if preferred_angle is None else int(preferred_angle) % 180)
        cached = self._dimension_cache.get(key)
        if cached is None:
            cached = []
            for angle in self._angles(preferred_angle):
                minx, miny, maxx, maxy = self._rotated(item, angle).bounds
                cached.append((angle, maxx - minx, maxy - miny))
            cached = tuple(cached)
            self._dimension_cache[key] = cached
        return cached

    def _compatible_free_regions(self, item, state, preferred_angle=None):
        """Safe bbox rejection against exact connected free-space components."""
        regions = (state.completion_regions if state.completion_regions is not None
                   else state.free_regions())
        # A disconnected 2D footprint may legitimately occupy more than one
        # connected free component. Use the whole bed as a conservative region
        # in that case; this sacrifices rejection power, never correctness.
        if hasattr(item.footprint, "geoms"):
            minx, miny, maxx, maxy = self.safe_bed.bounds
            regions = (FreeRegion(self.safe_bed.bounds, maxx - minx, maxy - miny,
                                  self.safe_bed.area),)
        dimensions = self._orientation_dimensions(item, preferred_angle)
        matches = []
        for region in regions:
            for angle, width, height in dimensions:
                self.performance.piece_gap_checks += 1
                if width <= region.width + 1e-9 and height <= region.height + 1e-9:
                    self.performance.piece_gap_matches += 1
                    matches.append((region, angle, width, height,
                                    max(0.0, region.area - width * height)))
                else:
                    self.performance.dimension_rejections += 1
        self.performance.dimension_candidates += len(matches)
        return matches

    def _rotated(self, item: ModelItem, angle: float):
        key = (id(item), round(float(angle), 4))
        if key not in self._rotation_cache:
            self.performance.rotation_cache_misses += 1
            self._rotation_cache[key] = rotate(
                item.footprint, angle, origin=(0, 0), use_radians=False
            )
        else:
            self.performance.rotation_cache_hits += 1
        return self._rotation_cache[key]

    def _buffered_rotated(self, item: ModelItem, angle: float):
        if not hasattr(self, "_buffered_rotation_cache"):
            self._buffered_rotation_cache = {}
        key = (id(item), round(float(angle), 4), round(self.padding, 4))
        if key not in self._buffered_rotation_cache:
            started = time.perf_counter()
            self._buffered_rotation_cache[key] = self._rotated(item, angle).buffer(self.padding)
            self.performance.buffers_created += 1
            self.performance.buffers_rotated_created += 1
            self.performance.buffer_rotated_seconds += time.perf_counter() - started
        else:
            self.performance.buffers_reused += 1
        return self._buffered_rotation_cache[key]

    def _resolved_optimizer_workers(self, population_size: int) -> int:
        configured = max(0, int(self.options.optimizer_workers))
        if configured:
            return min(population_size, configured)
        logical_cores = os.cpu_count() or 2
        return min(population_size, max(1, logical_cores - 1))

    @staticmethod
    def _genome_seed(global_seed: int, generation: int, index: int, genome: Genome) -> int:
        raw = repr((int(global_seed), int(generation), int(index),
                    genome.order, genome.preferred_angles)).encode("ascii")
        return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")

    def _worker_payload(self, items: list[ModelItem]) -> dict:
        started = time.perf_counter()
        payload = {
            "options": asdict(self.options),
            "padding": self.padding,
            "bed_padding": self.bed_padding,
            "bed_wkb": self.bed.wkb,
            "safe_bed_wkb": self.safe_bed.wkb,
            "spatial_hash_cell_size": getattr(
                self, "spatial_hash_cell_size",
                max(1.0, float(self.options.spatial_hash_cell_mm)),
            ),
            "items": [{
                "object_id": item.object_id, "name": item.name,
                "plate_index": item.plate_index, "footprint_wkb": item.footprint.wkb,
                "z_transform": tuple(item.z_transform), "locked": item.locked,
            } for item in items],
            "original_reference": [
                [(p.item.object_id, p.plate, p.angle, p.x, p.y) for p in plate]
                for plate in getattr(self, "_original_reference_solution", [])
            ],
        }
        self.performance.serialization_seconds += time.perf_counter() - started
        return payload

    def _merge_worker_metrics(self, result: dict) -> None:
        metrics = result.get("metrics", {})
        excluded = {
            "candidate_scan_piece_seconds", "candidate_scan_angle_seconds",
            "candidate_scan_pieces", "candidate_scan_max_piece_seconds",
            "packing_seconds", "solution_score_seconds", "generation_seconds",
            "total_optimization_seconds", "time_to_first_solution",
            "timeout_final_plate_count",
        }
        for name, value in metrics.items():
            if name in excluded or not hasattr(self.performance, name):
                continue
            current = getattr(self.performance, name)
            if isinstance(current, (int, float)) and isinstance(value, (int, float)):
                setattr(self.performance, name, current + value)
        self.performance.worker_peak_memory_bytes = max(
            self.performance.worker_peak_memory_bytes,
            result.get("worker_memory_bytes", 0),
        )
        self.performance.timeout_final_plate_count = max(
            self.performance.timeout_final_plate_count,
            metrics.get("timeout_final_plate_count", 0),
        )

    def _restore_worker_solution(self, compact, items_by_id) -> list[list[Placement]]:
        started = time.perf_counter()
        solution = []
        for plate in compact:
            restored = []
            for object_id, plate_id, angle, x, y in plate:
                item = items_by_id[object_id]
                geometry = translate(self._rotated(item, angle), xoff=x, yoff=y)
                buffered = translate(
                    self._buffered_rotated(item, angle), xoff=x, yoff=y
                )
                restored.append(Placement(
                    item, plate_id, angle, x, y, geometry,
                    buffered_geometry=buffered, buffered_bounds=buffered.bounds,
                ))
            solution.append(restored)
        self.performance.serialization_seconds += time.perf_counter() - started
        return solution

    def _search_advanced(self, items: list[ModelItem], reporter=None) -> list[list[Placement]]:
        if not hasattr(self, "performance"):
            self.performance = NestingPerformanceMetrics()
        population_size, max_generations, stagnation_limit = self.options.evolutionary_profile
        rng = random.Random(self.options.global_seed)
        item_index = {id(item): index for index, item in enumerate(items)}
        base_orders = [
            sorted(items, key=lambda x: x.footprint.area, reverse=True),
            sorted(items, key=lambda x: max(x.footprint.bounds[2] - x.footprint.bounds[0],
                                            x.footprint.bounds[3] - x.footprint.bounds[1]), reverse=True),
            sorted(items, key=lambda x: x.footprint.length, reverse=True),
        ]

        def genome_for(order):
            return Genome(tuple(item_index[id(item)] for item in order), tuple(0 for _ in items))

        population = [genome_for(order) for order in base_orders]
        while len(population) < population_size:
            order = list(range(len(items)))
            rng.shuffle(order)
            angles = tuple(rng.randrange(0, 180, self.options.angle_step) for _ in items)
            population.append(Genome(tuple(order), angles))

        cache = {}
        evaluation_cache = {}
        score_cache = {}
        generation = 0
        attempt = 0
        best_score = None
        search_started = time.perf_counter()
        items_by_id = {item.object_id: item for item in items}
        worker_count = self._resolved_optimizer_workers(population_size)
        parallel_enabled = worker_count > 1 and not self.options.debug_sequential
        process_pool = None
        if parallel_enabled:
            try:
                payload = self._worker_payload(items)
                process_pool = ProcessPoolExecutor(
                    max_workers=worker_count,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_worker_initializer,
                    initargs=(payload,),
                )
            except (OSError, RuntimeError, ValueError) as exc:
                self.performance.parallel_fallbacks += 1
                parallel_enabled = False
                logger.warning("No se pudo iniciar el pool de nesting; fallback secuencial: %s", exc)

        if reporter is not None and self.options.preview_mode == "debug":
            reporter.update(
                [], 0, None, attempt=1, debug=True,
                progress={"placed": 0, "considered": 0, "total": len(items), "plate": 1},
                status="Construyendo intento",
            )
            reporter.start()

        def evaluate(genome):
            nonlocal attempt
            self.performance.genomes_evaluated += 1
            if genome not in cache:
                self.performance.cache_misses += 1
                self.performance.unique_genomes_evaluated += 1
                ordered = [items[index] for index in genome.order]
                angle_map = {id(items[index]): genome.preferred_angles[index] for index in range(len(items))}
                current_attempt = attempt + 1

                def report_progress(partial, placed, considered, total, plate_index):
                    if reporter is not None and self.options.preview_mode == "debug":
                        reporter.update(
                            partial, generation, None, attempt=current_attempt, debug=True,
                            progress={
                                "placed": placed, "considered": considered,
                                "total": total, "plate": plate_index,
                            },
                            status="Construyendo intento",
                        )

                packing_started = time.perf_counter()
                solution = self._pack_minimum_plates(
                    ordered, angle_map,
                    progress_callback=report_progress
                    if reporter is not None and self.options.preview_mode == "debug" else None,
                )
                self.performance.packing_seconds += time.perf_counter() - packing_started
                score = self._exact_score_cached(solution, score_cache)
                cache[genome] = (score, solution)
                attempt += 1
                if reporter is not None and self.options.preview_mode == "debug":
                    reporter.update(solution, generation, score, attempt=attempt, debug=True)
                if self.options.debug_verbose:
                    logger.debug(
                        "Intento=%d generación=%d score=%s plates=%d objetos=%d",
                        attempt, generation, score, len(solution), sum(map(len, solution)),
                    )
            else:
                self.performance.cache_hits += 1
            return cache[genome]

        def evaluate_population(genomes):
            """Construye soluciones y filtra el score exacto por lotes."""
            nonlocal attempt, process_pool, parallel_enabled
            if self.options.debug_sequential:
                return [(evaluate(genome)[0], genome) for genome in genomes]
            self.performance.genomes_evaluated += len(genomes)
            missing = list(dict.fromkeys(
                genome for genome in genomes
                if genome not in cache and genome not in evaluation_cache
            ))
            self.performance.cache_hits += len(genomes) - len(missing)
            self.performance.cache_misses += len(missing)
            self.performance.unique_genomes_evaluated += len(missing)
            if missing:
                def compute(genome):
                    ordered = [items[index] for index in genome.order]
                    angle_map = {
                        id(items[index]): genome.preferred_angles[index]
                        for index in range(len(items))
                    }
                    started = time.perf_counter()
                    solution = self._pack_minimum_plates(ordered, angle_map)
                    elapsed = time.perf_counter() - started
                    fast_score = (self._fast_solution_score(solution)
                                  if self.options.selective_scoring
                                  else (len([plate for plate in solution if plate]), 0.0))
                    return solution, fast_score, elapsed

                computed = None
                if parallel_enabled and process_pool is not None:
                    deadline_epoch = (time.time() + max(0.0, self.deadline - time.monotonic())
                                      if self.deadline is not None else None)
                    tasks = [
                        (genome, generation, index,
                         self._genome_seed(self.options.global_seed, generation, index, genome),
                         deadline_epoch)
                        for index, genome in enumerate(missing)
                    ]
                    try:
                        serialization_started = time.perf_counter()
                        worker_results = list(process_pool.map(_worker_evaluate, tasks))
                        worker_results.sort(key=lambda result: result.get("genome_index", -1))
                        overhead = max(
                            0.0, time.perf_counter() - serialization_started
                            - max((result.get("packing_seconds", 0.0)
                                   for result in worker_results), default=0.0)
                        )
                        if self.performance.worker_tasks == 0:
                            self.performance.worker_startup_seconds += overhead
                        else:
                            self.performance.serialization_seconds += overhead
                        self.performance.worker_tasks += len(worker_results)
                        failures = [result for result in worker_results if not result.get("ok")]
                        if failures:
                            raise RuntimeError(failures[0].get("error", "worker failed"))
                        restored = []
                        for result in worker_results:
                            self._merge_worker_metrics(result)
                            restored.append((
                                self._restore_worker_solution(result["placements"], items_by_id),
                                tuple(result["fast_score"]), result["packing_seconds"],
                            ))
                        computed = restored
                    except (BrokenProcessPool, OSError, RuntimeError, ValueError) as exc:
                        self.performance.worker_failures += 1
                        self.performance.parallel_fallbacks += 1
                        logger.warning(
                            "Fallo en workers de nesting; se repite el lote en secuencial: %s", exc
                        )
                        process_pool.shutdown(wait=True, cancel_futures=True)
                        process_pool = None
                        parallel_enabled = False
                if computed is None:
                    computed = []
                    completed_after_deadline = None
                    for genome in missing:
                        if completed_after_deadline is not None and self._expired():
                            solution, fast_score, _elapsed = completed_after_deadline
                            computed.append((solution, fast_score, 0.0))
                            continue
                        result = compute(genome)
                        computed.append(result)
                        if self._expired():
                            completed_after_deadline = result
                for genome, result in zip(missing, computed):
                    solution, fast_score, elapsed = result
                    self.performance.packing_seconds += elapsed
                    evaluation_cache[genome] = SolutionEvaluation(
                        genome, solution, fast_score, self._solution_signature(solution)
                    )
                    attempt += 1
            evaluations = []
            for genome in genomes:
                if genome in cache:
                    score, solution = cache[genome]
                    evaluations.append(SolutionEvaluation(
                        genome, solution, (score[0], score[1]),
                        self._solution_signature(solution), score,
                    ))
                else:
                    evaluations.append(evaluation_cache[genome])
            selected = self._select_full_score_candidates(evaluations, best_score)
            for index, evaluation in enumerate(evaluations):
                if evaluation.exact_score is not None:
                    continue
                if index not in selected:
                    self.performance.full_scores_avoided += 1
                    self.performance.selective_full_scores_avoided += 1
                    continue
                evaluation.exact_score = self._exact_score_cached(
                    evaluation.solution, score_cache
                )
                cache[evaluation.genome] = (evaluation.exact_score, evaluation.solution)
            rejected = (math.inf,) * 6
            return [((item.exact_score if item.exact_score is not None else rejected), item.genome)
                    for item in evaluations]

        initial_ranked = evaluate_population(population)
        initial_ranked.sort(key=lambda pair: (pair[0], pair[1].order,
                                              pair[1].preferred_angles))
        best_score, best_genome = initial_ranked[0]
        best_solution = cache[best_genome][1]
        self.performance.time_to_first_solution = time.perf_counter() - search_started
        failures = 0
        if reporter is not None:
            # La ventana se abre después de disponer de la primera imagen válida.
            if self.options.preview_mode != "debug":
                reporter.update(best_solution, 0, best_score, attempt=attempt)
            reporter.start()

        # Una sola placa es el mínimo matemático. En modo bajo se prioriza
        # entregar ese resultado inmediatamente en lugar de pulir unos pocos
        # milímetros de compacidad durante el resto del minuto.
        if self.options.effort == "low" and len(best_solution) == 1:
            self.last_generation = 0
            self.last_population = tuple(population)
            self.performance.total_optimization_seconds += time.perf_counter() - search_started
            if process_pool is not None:
                process_pool.shutdown(wait=True, cancel_futures=True)
            return best_solution

        while generation < max_generations and failures < stagnation_limit and not self._expired():
            generation_started = time.perf_counter()
            ranked = evaluate_population(population)
            ranked.sort(key=lambda pair: (pair[0], pair[1].order,
                                          pair[1].preferred_angles))
            generation_best_score, generation_best = ranked[0]
            generation_solution = cache[generation_best][1]
            if best_score is None or generation_best_score < best_score:
                best_score, best_solution = generation_best_score, generation_solution
                failures = 0
                if reporter is not None and self.options.preview_mode != "debug":
                    reporter.update(best_solution, generation, best_score, attempt=attempt)
            else:
                failures += 1

            elite_count = max(2, population_size // 4)
            next_population = [genome for _, genome in ranked[:elite_count]]
            parents = [genome for _, genome in ranked[:max(elite_count + 1, population_size // 2)]]
            while len(next_population) < population_size:
                first, second = rng.sample(parents, 2)
                child = self._crossover(first, second, rng)
                child = self._mutate(child, rng, generation)
                next_population.append(child)
            population = next_population
            generation += 1
            self.performance.generation_seconds += time.perf_counter() - generation_started

        self.last_generation = generation
        self.last_population = tuple(population)
        self.performance.total_optimization_seconds += time.perf_counter() - search_started
        if process_pool is not None:
            process_pool.shutdown(wait=True, cancel_futures=True)
        return best_solution

    def _crossover(self, first: Genome, second: Genome, rng: random.Random) -> Genome:
        size = len(first.order)
        if size < 2:
            return first
        left, right = sorted(rng.sample(range(size), 2))
        segment = first.order[left:right + 1]
        remainder = [value for value in second.order if value not in segment]
        order = tuple(remainder[:left] + list(segment) + remainder[left:])
        angles = tuple(first.preferred_angles[i] if rng.random() < .5 else second.preferred_angles[i]
                       for i in range(size))
        return Genome(order, angles)

    def _mutate(self, genome: Genome, rng: random.Random, generation: int = 0) -> Genome:
        order = list(genome.order)
        angles = list(genome.preferred_angles)
        if len(order) > 1 and rng.random() < .85:
            first, second = rng.sample(range(len(order)), 2)
            if rng.random() < .5:
                order[first], order[second] = order[second], order[first]
            else:
                value = order.pop(first)
                order.insert(second, value)
        if angles and rng.random() < .8:
            item = rng.randrange(len(angles))
            if self.options.effort == "low":
                steps = (-30, -15, -5, 5, 15, 30)
            elif self.options.effort == "medium":
                steps = (-15, -10, -4, -2, 2, 4, 10, 15)
            else:
                steps = (-15, -10, -5, -2, -1, 1, 2, 5, 10, 15)
            delta = rng.choice(steps)
            angles[item] = (angles[item] + delta) % 180
        return Genome(tuple(order), tuple(angles))

    def _solution_score(self, solution):
        if not hasattr(self, "performance"):
            self.performance = NestingPerformanceMetrics()
        score_started = time.perf_counter()
        self.performance.full_scores_executed += 1
        """Premia una gran región libre continua y penaliza huecos dispersos."""
        fragmented_free = 0.0
        internal_voids = 0.0
        hull_area = 0.0
        envelope_area = 0.0
        region_count = 0
        small_gap_area = 0.0
        largest_free_ratio_sum = 0.0
        # Los pasillos más estrechos que este radio no cuentan como una única
        # zona realmente aprovechable para colocar otra pieza.
        accessibility_radius = max(3.0, self.options.clearance_mm * 2.0)

        for plate in solution:
            if not plate:
                continue
            operation_started = time.perf_counter()
            buffered_plate = []
            for placement in plate:
                if placement.buffered_geometry is None:
                    buffer_started = time.perf_counter()
                    placement.buffered_geometry = placement.geometry.buffer(self.padding)
                    placement.buffered_bounds = placement.buffered_geometry.bounds
                    self.performance.buffers_created += 1
                    self.performance.buffers_collision_created += 1
                    self.performance.buffer_collision_seconds += (
                        time.perf_counter() - buffer_started
                    )
                else:
                    self.performance.buffers_reused += 1
                buffered_plate.append(placement.buffered_geometry)
            occupied = unary_union(buffered_plate).buffer(0)
            self.performance.unary_union_seconds += time.perf_counter() - operation_started
            operation_started = time.perf_counter()
            hull = occupied.convex_hull
            internal_voids += max(0.0, hull.area - occupied.area)
            hull_area += hull.area
            envelope_area += occupied.envelope.area
            self.performance.convex_hull_seconds += time.perf_counter() - operation_started

            operation_started = time.perf_counter()
            free = self.safe_bed.difference(occupied).buffer(0)
            accessible = free.buffer(-accessibility_radius)
            self.performance.free_space_seconds += time.perf_counter() - operation_started
            operation_started = time.perf_counter()
            if not accessible.is_empty:
                regions = (
                    list(accessible.geoms)
                    if hasattr(accessible, "geoms") else [accessible]
                )
                region_areas = [region.area for region in regions if region.area > 0]
                if region_areas:
                    fragmented_free += sum(region_areas) - max(region_areas)
                    region_count += len(region_areas)
                    small_gap_area += sum(
                        area for area in region_areas
                        if area < self.options.small_gap_area_mm2
                    )
                    largest_free_ratio_sum += max(region_areas) / sum(region_areas)
            self.performance.fragmentation_seconds += time.perf_counter() - operation_started

        fragmentation = fragmented_free + region_count * self.options.small_gap_area_mm2
        weighted_quality = (
            self.options.compactness_weight * (internal_voids + hull_area + envelope_area)
            + self.options.fragmentation_weight * fragmentation
            + self.options.small_gap_penalty * small_gap_area
            - self.options.largest_free_region_weight
            * largest_free_ratio_sum * self.safe_bed.area
        )

        result = (
            len([plate for plate in solution if plate]),
            round(weighted_quality, 3),
            round(fragmentation, 3),
            round(internal_voids, 3),
            round(hull_area, 3),
            round(envelope_area, 3),
        )
        self.performance.solution_score_seconds += time.perf_counter() - score_started
        return result

    def _solution_signature(self, solution) -> tuple:
        """Firma geométrica por valor; piezas idénticas intercambiadas puntúan igual."""
        return tuple(
            tuple(sorted(
                p.geometry.wkb_hex
                for p in plate
            ))
            for plate in solution if plate
        )

    @staticmethod
    def _free_region_summary(grid: np.ndarray) -> tuple[int, int, int]:
        free = ~grid
        seen = np.zeros_like(free, dtype=np.bool_)
        regions = largest = small = 0
        height, width = free.shape
        for y, x in zip(*np.nonzero(free)):
            if seen[y, x]:
                continue
            regions += 1
            stack = [(int(y), int(x))]
            seen[y, x] = True
            area = 0
            while stack:
                cy, cx = stack.pop()
                area += 1
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if (0 <= ny < height and 0 <= nx < width
                            and free[ny, nx] and not seen[ny, nx]):
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            largest = max(largest, area)
            if area <= 4:
                small += area
        return regions, largest, small

    def _fast_solution_score(self, solution) -> tuple:
        """Aproximación determinista barata basada en bounds y raster grueso."""
        started = time.perf_counter()
        resolution = max(2.0, float(self.options.fast_score_resolution_mm))
        bed_minx, bed_miny, bed_maxx, bed_maxy = self.safe_bed.bounds
        width = max(1, int(math.ceil((bed_maxx - bed_minx) / resolution)))
        height = max(1, int(math.ceil((bed_maxy - bed_miny) / resolution)))
        quality = 0.0
        for plate in solution:
            if not plate:
                continue
            bounds = [p.buffered_bounds or p.geometry.bounds for p in plate]
            minx = min(b[0] for b in bounds); miny = min(b[1] for b in bounds)
            maxx = max(b[2] for b in bounds); maxy = max(b[3] for b in bounds)
            envelope = max(0.0, maxx - minx) * max(0.0, maxy - miny)
            occupied_area = sum(float(p.geometry.area) for p in plate)
            grid = np.zeros((height, width), dtype=np.bool_)
            for x0, y0, x1, y1 in bounds:
                gx0 = max(0, int((x0 - bed_minx) // resolution))
                gy0 = max(0, int((y0 - bed_miny) // resolution))
                gx1 = min(width, int(math.ceil((x1 - bed_minx) / resolution)))
                gy1 = min(height, int(math.ceil((y1 - bed_miny) / resolution)))
                grid[gy0:gy1, gx0:gx1] = True
            regions, largest, small = self._free_region_summary(grid)
            free_cells = max(1, int((~grid).sum()))
            quality += envelope + max(0.0, envelope - occupied_area)
            quality += (regions + small) * resolution ** 2
            quality -= (largest / free_cells) * self.safe_bed.area
        result = (len([plate for plate in solution if plate]), round(quality, 6))
        self.performance.fast_score_seconds += time.perf_counter() - started
        return result

    def _select_full_score_candidates(self, evaluations, best_exact_score=None) -> set[int]:
        """Selecciona scores exactos manteniendo plates como prioridad estricta."""
        if not self.options.selective_scoring:
            return set(range(len(evaluations)))
        best_plates = best_exact_score[0] if best_exact_score is not None else math.inf
        selected = {i for i, item in enumerate(evaluations)
                    if item.fast_score[0] < best_plates}
        target_plates = best_plates
        if target_plates == math.inf:
            target_plates = min((item.fast_score[0] for item in evaluations), default=math.inf)
        same = [(i, item) for i, item in enumerate(evaluations)
                if item.fast_score[0] == target_plates]
        same.sort(key=lambda pair: (pair[1].fast_score, pair[1].genome.order,
                                    pair[1].genome.preferred_angles))
        if same:
            if self.options.preserve_exact_evolution:
                selected.update(i for i, _ in same)
                return selected
            best_fast = same[0][1].fast_score[1]
            allowance = max(1e-9, abs(best_fast) * self.options.fast_score_threshold_ratio)
            selected.update(
                i for i, item in same
                if 0.0 < item.fast_score[1] - best_fast <= allowance
            )
            selected.update(i for i, _ in same[:max(1, self.options.full_score_top_k)])
        return selected

    def _exact_score_cached(self, solution, score_cache: dict) -> tuple:
        if not self.options.score_cache_enabled:
            self.performance.score_cache_misses += 1
            return self._solution_score(solution)
        signature = self._solution_signature(solution)
        if signature in score_cache:
            self.performance.score_cache_hits += 1
            self.performance.full_scores_avoided += 1
            return score_cache[signature]
        self.performance.score_cache_misses += 1
        result = self._solution_score(solution)
        score_cache[signature] = result
        return result

    def _validate_assignments(self, assignments: list[list[Placement]]) -> None:
        """Reject invalid output before mutating or saving the project."""
        seen: set[int] = set()
        for plate_index, placements in enumerate(assignments, 1):
            for placement in placements:
                if placement.item.object_id in seen:
                    raise ValueError(f"Objeto duplicado en la solución: {placement.item.object_id}")
                seen.add(placement.item.object_id)
                if not self.safe_bed.covers(placement.geometry):
                    logger.error(
                        "Plate %d Object %d fuera de bounds: %s; bed=%s",
                        plate_index, placement.item.object_id,
                        placement.geometry.bounds, self.bed.bounds,
                    )
                    raise ValueError(
                        f"El objeto {placement.item.object_id} queda fuera de la plate {plate_index}"
                    )
            for index, first in enumerate(placements):
                for second in placements[index + 1:]:
                    first_buffered = (first.buffered_geometry if first.buffered_geometry is not None
                                      else first.geometry.buffer(self.padding))
                    second_buffered = (second.buffered_geometry if second.buffered_geometry is not None
                                       else second.geometry.buffer(self.padding))
                    if first_buffered.intersects(second_buffered):
                        raise ValueError(
                            f"Colisión/spacing inválido en plate {plate_index}: "
                            f"objetos {first.item.object_id} y {second.item.object_id}"
                        )

    def _pack_minimum_plates(
        self, ordered: list[ModelItem], preferred_angles=None, progress_callback=None,
    ) -> list[list[Placement]]:
        plates: list[list[Placement]] = []
        remaining = ordered
        total = len(ordered)
        while remaining:
            if self._expired():
                self.performance.deadline_expirations += 1
                reference = getattr(self, "_original_reference_solution", None)
                if reference:
                    expected = {item.object_id for item in ordered}
                    referenced = {p.item.object_id for plate in reference for p in plate}
                    if expected == referenced:
                        self.performance.timeout_completion_used += 1
                        self.performance.timeout_remaining_items += len(remaining)
                        self.performance.timeout_final_plate_count = len(reference)
                        return reference
                plates = self._fast_complete_remaining(
                    plates, list(remaining), preferred_angles
                )
                break
                for item in remaining:
                    preferred = preferred_angles.get(id(item)) if preferred_angles else None
                    placement = self._place_on_empty_plate(
                        item, len(plates) + 1, preferred
                    )
                    if placement is None:
                        raise ValueError(
                            f"La pieza {item.name} no cabe en una plate vacía"
                        )
                    plates.append([placement])
                break
            plate_index = len(plates) + 1

            def on_plate_progress(placed, considered):
                if progress_callback is not None:
                    partial = [*plates, list(placed)]
                    progress_callback(
                        partial, sum(map(len, partial)), considered, total, plate_index,
                    )

            packed, unplaced = self._fill_plate(
                remaining, plate_index, preferred_angles,
                progress_callback=on_plate_progress if progress_callback is not None else None,
            )
            if not packed:
                raise ValueError(f"La pieza {remaining[0].name} no cabe en la cama con el margen configurado")
            plates.append(packed)
            remaining = unplaced
        return plates

    def _fast_complete_remaining(self, plates, remaining, preferred_angles=None):
        """Complete a timed-out genome without creating one plate per item."""
        self.performance.timeout_completion_used += 1
        self.performance.timeout_remaining_items += len(remaining)
        states = []
        for plate in plates:
            state = PlateOccupancyState(self, self._raster_resolution(), self.spatial_hash_cell_size)
            for placement in plate:
                state.add(placement)
            state.completion_regions = state.free_regions()
            states.append(state)
        saved_deadline = self.deadline
        self.deadline = None
        self._fast_completion_active = True
        ranked = []
        for item in remaining:
            preferred = preferred_angles.get(id(item)) if preferred_angles else None
            flexibility = 0
            for state in states:
                flexibility += len(self._compatible_free_regions(item, state, preferred))
            ranked.append((flexibility, -item.footprint.area, item.object_id,
                           item, preferred))
        pending = sorted(ranked, key=lambda value: value[:3])
        try:
            while pending:
                _flex, _area, _oid, item, preferred = pending.pop(0)
                compatible = []
                for index, state in enumerate(states):
                    matches = self._compatible_free_regions(item, state, preferred)
                    if matches:
                        compatible.append((min(match[4] for match in matches), index))
                placement = None
                for _region_waste, index in sorted(compatible):
                    self.performance.timeout_existing_plate_attempts += 1
                    placement = self._place_item_completion_fast(
                        item, index + 1, plates[index], preferred, states[index]
                    )
                    if placement is not None:
                        plates[index].append(placement)
                        states[index].add(placement)
                        break
                if placement is None:
                    plate_index = len(plates) + 1
                    placement = self._place_on_empty_plate(item, plate_index, preferred)
                    if placement is None:
                        raise ValueError(f"Item {item.name} does not fit an empty plate")
                    plates.append([placement])
                    state = PlateOccupancyState(self, self._raster_resolution(), self.spatial_hash_cell_size)
                    minx, miny, maxx, maxy = self.safe_bed.bounds
                    state.completion_regions = (FreeRegion(
                        self.safe_bed.bounds, maxx - minx, maxy - miny, self.safe_bed.area
                    ),)
                    state.add(placement)
                    states.append(state)
                    self.performance.timeout_new_plates_created += 1
        finally:
            self._fast_completion_active = False
            self.deadline = saved_deadline
        self.performance.timeout_final_plate_count = len(plates)
        return plates

    def _place_item_completion_fast(self, item, plate_index, placed, preferred, state):
        """Try exact contact points before invoking the raster during completion."""
        started = time.perf_counter()
        bed = self.safe_bed.bounds
        for angle in self._angles(preferred):
            rotated = self._rotated(item, angle)
            buffered = self._buffered_rotated(item, angle)
            minx, miny, maxx, maxy = rotated.bounds
            width, height = maxx - minx, maxy - miny
            if width > bed[2] - bed[0] or height > bed[3] - bed[1]:
                continue
            points = set(state.frontier_points)
            points.add((bed[2] - width, bed[1]))
            points.add((bed[0], bed[3] - height))
            for x, y in sorted(points, key=lambda value: (value[1], value[0])):
                self.performance.frontier_candidates += 1
                candidate, _reason, _filtered = self._try_vector_candidate(
                    item, plate_index, angle, rotated, buffered, x, y,
                    state.buffered_geometries, state
                )
                if candidate is not None:
                    self.performance.frontier_seconds += time.perf_counter() - started
                    self.performance.frontier_successes += 1
                    return candidate
        self.performance.frontier_seconds += time.perf_counter() - started
        return self._place_item(item, plate_index, placed, preferred, state)

    def _place_on_empty_plate(self, item, plate_index, preferred_angle=None):
        """Bounded valid fallback used only after an evaluation deadline."""
        minx, miny, _maxx, _maxy = self.safe_bed.bounds
        for angle in self._angles(preferred_angle):
            rotated = self._rotated(item, angle)
            rminx, rminy, _rmaxx, _rmaxy = rotated.bounds
            xoff, yoff = minx - rminx, miny - rminy
            geometry = translate(rotated, xoff=xoff, yoff=yoff)
            if self.safe_bed.covers(geometry):
                buffered = translate(self._buffered_rotated(item, angle), xoff=xoff, yoff=yoff)
                return Placement(
                    item, plate_index, angle, xoff, yoff, geometry,
                    buffered_geometry=buffered, buffered_bounds=buffered.bounds,
                )
        saved_deadline = self.deadline
        try:
            self.deadline = None
            state = PlateOccupancyState(
                self, self._raster_resolution(), self.spatial_hash_cell_size
            )
            return self._place_item_raster(
                item, plate_index, [], preferred_angle, state
            )
        finally:
            self.deadline = saved_deadline

    def _pack_one_plate(self, items: list[ModelItem], plate_index: int) -> list[Placement] | None:
        packed, remaining = self._fill_plate(sorted(items, key=lambda x: x.footprint.area, reverse=True), plate_index)
        return packed if not remaining else None

    def _fill_plate(
        self, items: list[ModelItem], plate_index: int, preferred_angles=None,
        progress_callback=None,
    ):
        if not hasattr(self, "performance"):
            self.performance = NestingPerformanceMetrics()
        if not hasattr(self, "spatial_hash_cell_size"):
            self.spatial_hash_cell_size = max(
                1.0, float(getattr(self.options, "spatial_hash_cell_mm", 15.0))
            )
        placed: list[Placement] = []
        remaining: list[ModelItem] = []
        state = PlateOccupancyState(
            self, self._raster_resolution(), self.spatial_hash_cell_size
        )
        for considered, item in enumerate(items, 1):
            if self._expired() and placed:
                remaining.extend(items[considered - 1:])
                self.performance.deadline_expirations += 1
                break
            preferred = preferred_angles.get(id(item)) if preferred_angles else None
            placement = self._place_item(item, plate_index, placed, preferred, state)
            if placement is None:
                remaining.append(item)
            else:
                placed.append(placement)
                state.add(placement)
            if progress_callback is not None:
                progress_callback(placed, considered)
        return placed, remaining

    def _try_vector_candidate(
        self, item, plate_index, angle, rotated, rotated_buffered,
        target_x, target_y, buffered_placed, occupancy_state,
    ):
        """Validate one vector candidate; exact geometry remains authoritative."""
        bed_bounds = self.safe_bed.bounds
        rminx, rminy, rmaxx, rmaxy = rotated.bounds
        xoff, yoff = target_x - rminx, target_y - rminy
        geom_bounds = (rminx + xoff, rminy + yoff, rmaxx + xoff, rmaxy + yoff)
        rectangular_bed = self.safe_bed.equals(self.safe_bed.envelope)
        if rectangular_bed and not (
            bed_bounds[0] <= geom_bounds[0] and bed_bounds[1] <= geom_bounds[1]
            and geom_bounds[2] <= bed_bounds[2] and geom_bounds[3] <= bed_bounds[3]
        ):
            return None, "bounds", 0
        geom = None if rectangular_bed else translate(rotated, xoff=xoff, yoff=yoff)
        if geom is not None and not self.safe_bed.covers(geom):
            return None, "bounds", 0
        rb = rotated_buffered.bounds
        candidate_bounds = (rb[0] + xoff, rb[1] + yoff, rb[2] + xoff, rb[3] + yoff)
        if occupancy_state is not None:
            indices = occupancy_state.neighbor_indices(candidate_bounds)
            neighbors = [occupancy_state.buffered_geometries[index] for index in indices
                         if self._bounds_intersect(candidate_bounds, occupancy_state.bounds[index])]
            bbox_filtered = len(indices) - len(neighbors)
        else:
            neighbors = [neighbor for neighbor in buffered_placed
                         if self._bounds_intersect(candidate_bounds, neighbor.bounds)]
            bbox_filtered = max(0, len(buffered_placed) - len(neighbors))
        buffered = translate(rotated_buffered, xoff=xoff, yoff=yoff) if neighbors else None
        exact_started = time.perf_counter()
        for neighbor in neighbors:
            self.performance.exact_collision_checks += 1
            self.performance.fallback_exact_checks += 1
            if buffered.intersects(neighbor):
                self.performance.exact_collision_seconds += time.perf_counter() - exact_started
                return None, "exact", bbox_filtered
        self.performance.exact_collision_seconds += time.perf_counter() - exact_started
        if geom is None:
            geom = translate(rotated, xoff=xoff, yoff=yoff)
        if not self.safe_bed.covers(geom):
            return None, "bounds", bbox_filtered
        if buffered is None:
            buffered = translate(rotated_buffered, xoff=xoff, yoff=yoff)
        return Placement(item, plate_index, angle, xoff, yoff, geom,
                         buffered, buffered.bounds), "valid", bbox_filtered

    def _place_item(
        self, item: ModelItem, plate_index: int, placed: list[Placement],
        preferred_angle=None, occupancy_state: PlateOccupancyState | None = None,
    ) -> Placement | None:
        if occupancy_state is not None:
            rejected_before = self.performance.dimension_rejections
            matches = self._compatible_free_regions(item, occupancy_state, preferred_angle)
            self._last_feasibility = {
                "free_region_count": len(occupancy_state.free_regions()),
                "dimension_rejections": self.performance.dimension_rejections - rejected_before,
            }
            if not matches:
                return None
        raster = self._place_item_raster(item, plate_index, placed, preferred_angle, occupancy_state)
        if raster is not None:
            return raster
        if self._expired():
            self.performance.deadline_expirations += 1
            return None
        cache_key = None
        if occupancy_state is not None:
            cache_key = (
                hashlib.blake2b(item.footprint.wkb, digest_size=12).digest(),
                None if preferred_angle is None else int(preferred_angle) % 180,
            )
            if cache_key in occupancy_state.fallback_cache:
                self.performance.fallback_cache_hits += 1
                cached = occupancy_state.fallback_cache[cache_key]
                if cached is None:
                    return None
                return Placement(item, plate_index, cached.angle, cached.x, cached.y,
                                 cached.geometry, cached.buffered_geometry,
                                 cached.buffered_bounds)
            self.performance.fallback_cache_misses += 1
        started = time.perf_counter()
        self.performance.fallback_calls += 1
        if occupancy_state is not None:
            buffered_placed = occupancy_state.buffered_geometries
            axes_x, axes_y = set(occupancy_state.frontier_x), set(occupancy_state.frontier_y)
            base_points = set(occupancy_state.frontier_points)
            density = sum(row.bit_count() for row in occupancy_state.occupancy_rows) / max(
                1, occupancy_state.width * occupancy_state.height)
        else:
            buffered_placed, axes_x, axes_y = [], {self.safe_bed.bounds[0]}, {self.safe_bed.bounds[1]}
            base_points = {(self.safe_bed.bounds[0], self.safe_bed.bounds[1])}
            density = 0.0
            gap = self.padding * 2
            for placement in placed:
                buffered = placement.buffered_geometry
                if buffered is None:
                    buffered = placement.geometry.buffer(self.padding)
                buffered_placed.append(buffered)
                pminx, pminy, pmaxx, pmaxy = placement.geometry.bounds
                px, py = (pminx - gap, pmaxx + gap), (pminy - gap, pmaxy + gap)
                axes_x.update(px); axes_y.update(py)
                base_points.update((x, y) for x in px for y in py)
        bed = self.safe_bed.bounds
        best = best_score = None
        profiles = []
        previous_history = (
            occupancy_state.fallback_history.get(cache_key, {})
            if occupancy_state is not None and cache_key is not None else {}
        )
        current_history = {}
        for angle in self._angles(preferred_angle):
            angle_started = time.perf_counter()
            rotated, rotated_buffered = self._rotated(item, angle), self._buffered_rotated(item, angle)
            rminx, rminy, rmaxx, rmaxy = rotated.bounds
            width, height = rmaxx - rminx, rmaxy - rminy
            xs, ys = sorted(axes_x | {bed[2] - width}), sorted(axes_y | {bed[3] - height})
            current_history[float(angle)] = (frozenset(xs), frozenset(ys))
            old_xs, old_ys = previous_history.get(float(angle), (frozenset(), frozenset()))
            profile = {"object_id": item.object_id, "plate": plate_index, "angle": angle,
                       "entry_reason": "raster_no_candidate", "occupancy_density": round(density, 6),
                       "piece_bbox": tuple(round(v, 4) for v in rotated.bounds),
                       "x_positions": len(xs), "y_positions": len(ys), "total_candidates": 0,
                       "frontier_candidates": 0, "interval_candidates": 0,
                       "exhaustive_candidates": 0,
                       "rejected_bounds": 0, "rejected_bbox": 0,
                       "rejected_spatial_hash": 0, "exact_candidates": 0,
                       "path": "none", "seconds": 0.0}
            profile.update(getattr(self, "_last_feasibility", {}))
            if width > bed[2] - bed[0] or height > bed[3] - bed[1]:
                profile["path"] = "angle_rejected"
                profile["seconds"] = time.perf_counter() - angle_started
                profiles.append(profile)
                continue
            attempted = set()

            def evaluate(x, y, source):
                if (x, y) in attempted:
                    return None
                # A candidate rejected before the plate gained more obstacles
                # cannot become valid. Only axes introduced since then matter.
                if x in old_xs and y in old_ys:
                    return None
                attempted.add((x, y)); profile["total_candidates"] += 1
                self.performance.fallback_candidates += 1
                if source == "frontier":
                    self.performance.frontier_candidates += 1
                    profile["frontier_candidates"] += 1
                else:
                    self.performance.interval_candidates += 1
                    profile["interval_candidates"] += 1
                candidate, reason, bbox_filtered = self._try_vector_candidate(
                    item, plate_index, angle, rotated, rotated_buffered, x, y,
                    buffered_placed, occupancy_state)
                profile["rejected_bbox"] += bbox_filtered
                if reason == "bounds": profile["rejected_bounds"] += 1
                elif reason == "exact": profile["exact_candidates"] += 1
                elif reason == "valid" and not bbox_filtered: profile["rejected_spatial_hash"] += 1
                return candidate

            angle_best = None
            frontier_started = time.perf_counter()
            points = set(base_points)
            points.update((x, bed[3] - height) for x in xs)
            points.update((bed[2] - width, y) for y in ys)
            for x, y in sorted(points, key=lambda value: (value[1], value[0])):
                angle_best = evaluate(x, y, "frontier")
                if angle_best is not None:
                    self.performance.frontier_successes += 1; profile["path"] = "frontier"; break
            self.performance.frontier_seconds += time.perf_counter() - frontier_started
            # On dense plates bbox-free intervals almost never exist (the
            # raster has already rejected the piece). Avoid rebuilding them;
            # the exact exhaustive safety net remains below.
            if angle_best is None and density < .70:
                rb = rotated_buffered.bounds
                left_delta, right_delta = rb[0] - rminx, rb[2] - rminx
                obstacle_bounds = occupancy_state.bounds if occupancy_state is not None else [g.bounds for g in buffered_placed]
                for y in ys:
                    yoff = y - rminy
                    low_y, high_y = rb[1] + yoff, rb[3] + yoff
                    blocked = [(ominx - right_delta, omaxx - left_delta)
                               for ominx, ominy, omaxx, omaxy in obstacle_bounds
                               if high_y >= ominy and low_y <= omaxy]
                    for x in xs:
                        if any(low <= x <= high for low, high in blocked):
                            continue
                        angle_best = evaluate(x, y, "interval")
                        if angle_best is not None:
                            self.performance.interval_successes += 1; profile["path"] = "interval"; break
                    if angle_best is not None: break
            if angle_best is not None:
                score = (angle_best.geometry.bounds[3], angle_best.geometry.bounds[2],
                         angle not in (0, 90), angle)
                if best_score is None or score < best_score: best, best_score = angle_best, score
            profile["seconds"] = time.perf_counter() - angle_started
            profiles.append(profile)
        if (best is None and not self._expired()
                and not getattr(self, "_fast_completion_active", False)):
            exhaustive_started = time.perf_counter()
            candidates_before = self.performance.exhaustive_fallback_candidates
            exact_before = self.performance.fallback_exact_checks
            best = self._place_item_fallback_legacy(
                item, plate_index, placed, preferred_angle, occupancy_state,
                count_call=False,
                candidate_filter=lambda angle, x, y: not (
                    x in previous_history.get(float(angle), (frozenset(), frozenset()))[0]
                    and y in previous_history.get(float(angle), (frozenset(), frozenset()))[1]
                ),
            )
            if profiles:
                profiles[-1]["path"] = "exhaustive"
                profiles[-1]["total_candidates"] += (
                    self.performance.exhaustive_fallback_candidates - candidates_before
                )
                profiles[-1]["exhaustive_candidates"] += (
                    self.performance.exhaustive_fallback_candidates - candidates_before
                )
                profiles[-1]["exact_candidates"] += (
                    self.performance.fallback_exact_checks - exact_before
                )
                profiles[-1]["seconds"] += time.perf_counter() - exhaustive_started
        elapsed = time.perf_counter() - started
        self.performance.fallback_seconds += elapsed
        # One compact record per angle makes grouping deterministic and keeps
        # worker aggregation simple; as_dict only exposes the top consumers.
        self.performance.fallback_call_profiles.extend(profiles)
        if cache_key is not None:
            occupancy_state.fallback_cache[cache_key] = best
            if best is None:
                occupancy_state.fallback_history[cache_key] = current_history
        return best

    def _place_item_fallback_legacy(
        self, item: ModelItem, plate_index: int, placed: list[Placement],
        preferred_angle=None, occupancy_state: PlateOccupancyState | None = None,
        count_call: bool = True,
        candidate_filter=None,
    ) -> Placement | None:
        """Former exhaustive Cartesian fallback, retained as correctness net."""
        # Respaldo vectorial para camas no rectangulares o contornos patológicos.
        fallback_started = time.perf_counter()
        if count_call:
            self.performance.fallback_calls += 1
        self.performance.exhaustive_fallback_calls += 1
        if occupancy_state is not None:
            buffered_placed = occupancy_state.buffered_geometries
            self.performance.buffers_reused += len(buffered_placed)
        else:
            buffered_placed = []
            for placement in placed:
                if placement.buffered_geometry is None:
                    placement.buffered_geometry = placement.geometry.buffer(self.padding)
                    placement.buffered_bounds = placement.buffered_geometry.bounds
                    self.performance.buffers_created += 1
                else:
                    self.performance.buffers_reused += 1
                buffered_placed.append(placement.buffered_geometry)
        bed_bounds = self.safe_bed.bounds
        safe_bed_is_rectangle = self.safe_bed.equals(self.safe_bed.envelope)
        x_candidates = {bed_bounds[0]}
        y_candidates = {bed_bounds[1]}
        for p in placed:
            pminx, pminy, pmaxx, pmaxy = p.geometry.bounds
            gap = self.padding * 2
            x_candidates.update((pminx - gap, pmaxx + gap))
            y_candidates.update((pminy - gap, pmaxy + gap))

        best = None
        best_score = None
        for angle in self._angles(preferred_angle):
            if self._expired():
                self.performance.deadline_expirations += 1
                break
            rotated = self._rotated(item, angle)
            rotated_buffered = self._buffered_rotated(item, angle)
            rminx, rminy, rmaxx, rmaxy = rotated.bounds
            width, height = rmaxx - rminx, rmaxy - rminy
            if width > bed_bounds[2] - bed_bounds[0] or height > bed_bounds[3] - bed_bounds[1]:
                continue
            xs = sorted(x_candidates | {bed_bounds[2] - width})
            ys = sorted(y_candidates | {bed_bounds[3] - height})
            for target_y in ys:
                if self._expired():
                    self.performance.deadline_expirations += 1
                    break
                for candidate_index, target_x in enumerate(xs):
                    if candidate_index % 16 == 0 and self._expired():
                        self.performance.deadline_expirations += 1
                        break
                    if candidate_filter is not None and not candidate_filter(
                        angle, target_x, target_y
                    ):
                        continue
                    self.performance.fallback_candidates += 1
                    self.performance.exhaustive_fallback_candidates += 1
                    xoff, yoff = target_x - rminx, target_y - rminy
                    gminx, gminy, gmaxx, gmaxy = rotated.bounds
                    candidate_geom_bounds = (
                        gminx + xoff, gminy + yoff, gmaxx + xoff, gmaxy + yoff
                    )
                    if safe_bed_is_rectangle:
                        if not (bed_bounds[0] <= candidate_geom_bounds[0]
                                and bed_bounds[1] <= candidate_geom_bounds[1]
                                and candidate_geom_bounds[2] <= bed_bounds[2]
                                and candidate_geom_bounds[3] <= bed_bounds[3]):
                            continue
                        geom = None
                    else:
                        geom = translate(rotated, xoff=xoff, yoff=yoff)
                        if not self.safe_bed.covers(geom):
                            continue
                    rb = rotated_buffered.bounds
                    candidate_buffer_bounds = (
                        rb[0] + xoff, rb[1] + yoff, rb[2] + xoff, rb[3] + yoff
                    )
                    if occupancy_state is not None:
                        neighbor_indices = occupancy_state.neighbor_indices(
                            candidate_buffer_bounds
                        )
                        neighbors = [
                            occupancy_state.buffered_geometries[index]
                            for index in neighbor_indices
                            if self._bounds_intersect(
                                candidate_buffer_bounds, occupancy_state.bounds[index]
                            )
                        ]
                    else:
                        neighbors = [
                            neighbor for neighbor in buffered_placed
                            if self._bounds_intersect(candidate_buffer_bounds, neighbor.bounds)
                        ]
                    buffered = None
                    if neighbors:
                        buffered = translate(rotated_buffered, xoff=xoff, yoff=yoff)
                    if geom is None and not neighbors:
                        geom = translate(rotated, xoff=xoff, yoff=yoff)
                    if geom is not None and not self.safe_bed.covers(geom):
                        continue
                    exact_started = time.perf_counter()
                    collision = False
                    for neighbor in neighbors:
                        self.performance.exact_collision_checks += 1
                        self.performance.fallback_exact_checks += 1
                        if buffered.intersects(neighbor):
                            collision = True
                            break
                    self.performance.exact_collision_seconds += time.perf_counter() - exact_started
                    if collision:
                        continue
                    if geom is None:
                        geom = translate(rotated, xoff=xoff, yoff=yoff)
                    if buffered is None:
                        buffered = translate(rotated_buffered, xoff=xoff, yoff=yoff)
                    score = (geom.bounds[3], geom.bounds[2], angle not in (0, 90), angle)
                    if best_score is None or score < best_score:
                        best_score = score
                        best = Placement(
                            item=item, plate=plate_index, angle=angle,
                            x=target_x - rminx, y=target_y - rminy, geometry=geom,
                            buffered_geometry=buffered, buffered_bounds=buffered.bounds,
                        )
                        # xs is sorted and width is fixed for this angle: the
                        # first valid x is the lexicographic optimum for this y.
                        break
                if best is not None:
                    break
            if self._expired() and best is not None:
                break
        elapsed = time.perf_counter() - fallback_started
        self.performance.exhaustive_fallback_seconds += elapsed
        if count_call:
            self.performance.fallback_seconds += elapsed
        return best

    def _raster_resolution(self) -> float:
        # La comprobación geométrica final sigue siendo exacta; esta resolución
        # solo controla la separación entre posiciones candidatas del barrido.
        if self.options.mode == "simple":
            return 2.0
        if self.options.effort == "low":
            return 2.0
        if self.options.effort == "medium":
            return 1.5
        return 1.0

    @staticmethod
    def _legacy_raster_scan(
        occupancy_rows: list[int], mask: RasterScanMask, y_cell: int, x_count: int,
    ) -> np.ndarray:
        """Reference implementation of the former X/row Python loops."""
        rejection_stage = np.zeros(x_count, dtype=np.uint16)
        for x_cell in range(x_count):
            for ordinal, (row_index, row) in enumerate(mask.non_empty_rows, 1):
                if occupancy_rows[y_cell + row_index] & (row << x_cell):
                    rejection_stage[x_cell] = ordinal
                    break
        return rejection_stage

    @staticmethod
    def _numpy_raster_scan(
        occupancy_grid: np.ndarray, mask: RasterScanMask,
        y_cell: int, x_count: int,
    ) -> np.ndarray:
        """Check every X for one Y in C-backed NumPy operations."""
        rejection_stage = np.zeros(x_count, dtype=np.uint16)
        if not mask.row_arrays:
            return rejection_stage
        # Fast path for an empty band, common on nearly empty plates.
        row_indices = [y_cell + index for index, _bits in mask.row_arrays]
        if not np.any(occupancy_grid[row_indices]):
            return rejection_stage
        for ordinal, (row_index, bits) in enumerate(mask.row_arrays, 1):
            free = rejection_stage == 0
            if not np.any(free):
                break
            hits = np.correlate(
                occupancy_grid[y_cell + row_index], bits, mode="valid"
            )[:x_count] > 0
            rejection_stage[hits & free] = ordinal
        return rejection_stage

    @staticmethod
    def _bitset_raster_scan(
        occupancy_rows: list[int], mask: RasterScanMask,
        y_cell: int, x_count: int,
    ) -> np.ndarray:
        """Evaluate compact masks with big-int shifts and vector unpacking."""
        rejection_stage = np.zeros(x_count, dtype=np.uint16)
        if not mask.non_empty_rows:
            return rejection_stage
        allowed = (1 << x_count) - 1
        unresolved = allowed
        byte_width = max(1, (x_count + 7) // 8)
        for ordinal, (row_index, row_mask) in enumerate(mask.non_empty_rows, 1):
            occupied = occupancy_rows[y_cell + row_index]
            if not occupied:
                continue
            invalid = 0
            bits = row_mask
            while bits:
                lowest = bits & -bits
                invalid |= occupied >> (lowest.bit_length() - 1)
                bits ^= lowest
            newly_rejected = invalid & unresolved & allowed
            if newly_rejected:
                if newly_rejected == unresolved:
                    if unresolved == allowed:
                        rejection_stage.fill(ordinal)
                    else:
                        rejection_stage[rejection_stage == 0] = ordinal
                    break
                raw = np.frombuffer(
                    newly_rejected.to_bytes(byte_width, "little"), dtype=np.uint8
                )
                rejected = np.unpackbits(raw, bitorder="little")[:x_count].astype(bool)
                rejection_stage[rejected] = ordinal
                unresolved &= ~newly_rejected
                if not unresolved:
                    break
        return rejection_stage

    def _record_raster_scan(self, stages: np.ndarray, limit: int, row_count: int) -> None:
        if limit < 0:
            return
        evaluated = stages[:limit + 1]
        counts = np.bincount(evaluated, minlength=row_count + 1)
        valid_count = int(counts[0])
        first_rejections = int(counts[1]) if len(counts) > 1 else 0
        multi_rejections = len(evaluated) - valid_count - first_rejections
        metrics = self.performance
        metrics.scan_xy_positions_evaluated += len(evaluated)
        metrics.scan_first_row_rejections += first_rejections
        metrics.scan_multi_row_rejections += multi_rejections
        metrics.scan_valid_positions += valid_count
        metrics.raster_rejections += len(evaluated) - valid_count
        metrics.scan_mask_rows_checked += (
            valid_count * row_count
            + int(np.dot(np.arange(1, len(counts), dtype=np.int64), counts[1:]))
        )

    def _place_item_raster(
        self, item: ModelItem, plate_index: int, placed: list[Placement],
        preferred_angle=None, occupancy_state: PlateOccupancyState | None = None,
    ) -> Placement | None:
        scan_started = time.perf_counter()

        def finish(result):
            elapsed = time.perf_counter() - scan_started
            self.performance.candidate_scan_seconds += elapsed
            self.performance.candidate_scan_piece_seconds.append(elapsed)
            return result

        resolution = self._raster_resolution()
        minx, miny, maxx, maxy = self.bed.bounds
        bed_w = int((maxx - minx) // resolution)
        bed_h = int((maxy - miny) // resolution)
        if occupancy_state is None:
            rebuild_started = time.perf_counter()
            self.performance.occupancy_rebuilds += 1
            occupied_rows = [0] * bed_h
            for placement in placed:
                if placement.buffered_geometry is None:
                    placement.buffered_geometry = placement.geometry.buffer(self.padding)
                    placement.buffered_bounds = placement.buffered_geometry.bounds
                    self.performance.buffers_created += 1
                else:
                    self.performance.buffers_reused += 1
                self._paint_rows(
                    placement.buffered_geometry, occupied_rows,
                    minx, miny, resolution, bed_w, bed_h,
                )
            self.performance.occupancy_rebuild_seconds += (
                time.perf_counter() - rebuild_started
            )
        else:
            occupied_rows = occupancy_state.occupancy_rows
        if occupancy_state is not None:
            occupancy_grid = occupancy_state.occupancy_grid
        else:
            byte_width = max(1, (bed_w + 7) // 8)
            occupancy_grid = np.zeros((bed_h, bed_w), dtype=np.int16)
            for row_index, row in enumerate(occupied_rows):
                raw = np.frombuffer(int(row).to_bytes(byte_width, "little"), dtype=np.uint8)
                occupancy_grid[row_index] = np.unpackbits(raw, bitorder="little")[:bed_w]

        best = None
        best_score = None
        for angle in self._angles(preferred_angle):
            if self._expired():
                self.performance.deadline_expirations += 1
                return finish(best)
            angle_started = time.perf_counter()
            rotated = self._rotated(item, angle)
            buffered = self._buffered_rotated(item, angle)
            if buffered.is_empty:
                self.performance.candidate_scan_angle_seconds[float(angle)] = (
                    self.performance.candidate_scan_angle_seconds.get(float(angle), 0.0)
                    + time.perf_counter() - angle_started
                )
                continue
            bminx, bminy, bmaxx, bmaxy = buffered.bounds
            width = max(1, int(__import__("math").ceil((bmaxx - bminx) / resolution)))
            height = max(1, int(__import__("math").ceil((bmaxy - bminy) / resolution)))
            if width > bed_w or height > bed_h:
                self.performance.candidate_scan_angle_seconds[float(angle)] = (
                    self.performance.candidate_scan_angle_seconds.get(float(angle), 0.0)
                    + time.perf_counter() - angle_started
                )
                continue
            self.performance.scan_angles_evaluated += 1
            raster_key = (id(item), round(float(angle), 4), resolution, round(self.padding, 4))
            if raster_key not in self._raster_cache:
                self.performance.raster_cache_misses += 1
                rows = self._local_rows(
                    buffered, bminx, bminy, resolution, width, height
                )
                self._raster_cache[raster_key] = RasterScanMask.from_rows(
                    rows, width, height
                )
            else:
                self.performance.raster_cache_hits += 1
            mask = self._raster_cache[raster_key]
            for y_cell in range(0, bed_h - height + 1):
                if y_cell % 8 == 0 and self._expired():
                    self.performance.deadline_expirations += 1
                    return finish(best)
                x_count = bed_w - width + 1
                if getattr(self, "_use_legacy_candidate_scan", False):
                    stages = self._legacy_raster_scan(
                        occupied_rows, mask, y_cell, x_count
                    )
                elif mask.set_bit_count <= 256:
                    stages = self._bitset_raster_scan(
                        occupied_rows, mask, y_cell, x_count
                    )
                else:
                    stages = self._numpy_raster_scan(
                        occupancy_grid, mask, y_cell, x_count
                    )
                free_xs = np.flatnonzero(stages == 0)
                accepted_x = None
                for candidate_index, x_value in enumerate(free_xs):
                    if candidate_index % 32 == 0 and self._expired():
                        self.performance.deadline_expirations += 1
                        return finish(best)
                    x_cell = int(x_value)
                    xoff = minx + x_cell * resolution - bminx
                    yoff = miny + y_cell * resolution - bminy
                    geom = translate(rotated, xoff=xoff, yoff=yoff)
                    grown = translate(buffered, xoff=xoff, yoff=yoff)
                    if not self.safe_bed.covers(geom):
                        continue
                    if occupancy_state is not None:
                        neighbor_indices = occupancy_state.neighbor_indices(grown.bounds)
                        neighbors = [
                            occupancy_state.buffered_geometries[index]
                            for index in neighbor_indices
                        ]
                        self.performance.buffers_reused += len(neighbors)
                    else:
                        neighbors = []
                        for placement in placed:
                            if placement.buffered_geometry is None:
                                placement.buffered_geometry = placement.geometry.buffer(self.padding)
                                placement.buffered_bounds = placement.buffered_geometry.bounds
                                self.performance.buffers_created += 1
                            else:
                                self.performance.buffers_reused += 1
                            neighbors.append(placement.buffered_geometry)
                    exact_started = time.perf_counter()
                    collision = False
                    for neighbor in neighbors:
                        self.performance.exact_collision_checks += 1
                        if grown.intersects(neighbor):
                            collision = True
                            break
                    self.performance.exact_collision_seconds += time.perf_counter() - exact_started
                    if collision:
                        continue
                    score = (geom.bounds[3], geom.bounds[2], angle not in (0, 90), angle)
                    if best_score is None or score < best_score:
                        best_score = score
                        best = Placement(
                            item, plate_index, angle, xoff, yoff, geom,
                            buffered_geometry=grown, buffered_bounds=grown.bounds,
                        )
                    accepted_x = x_cell
                    break
                self._record_raster_scan(
                    stages, accepted_x if accepted_x is not None else x_count - 1,
                    len(mask.non_empty_rows),
                )
                if best is not None and best_score[0] <= miny + (y_cell + height) * resolution + resolution:
                    break
            self.performance.candidate_scan_angle_seconds[float(angle)] = (
                self.performance.candidate_scan_angle_seconds.get(float(angle), 0.0)
                + time.perf_counter() - angle_started
            )
            if self._expired() and best is not None:
                break
        return finish(best)

    @staticmethod
    def _draw_geometry(draw: ImageDraw.ImageDraw, geom, ox: float, oy: float, scale: float, value: int = 1):
        geoms = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
        for poly in geoms:
            if not hasattr(poly, "exterior"):
                continue
            exterior = [((x - ox) * scale, (y - oy) * scale) for x, y in poly.exterior.coords]
            draw.polygon(exterior, fill=value)
            for ring in poly.interiors:
                hole = [((x - ox) * scale, (y - oy) * scale) for x, y in ring.coords]
                draw.polygon(hole, fill=0)

    @classmethod
    def _local_rows(cls, geom, ox, oy, resolution, width, height):
        image = Image.new("1", (width, height), 0)
        cls._draw_geometry(ImageDraw.Draw(image), geom, ox, oy, 1.0 / resolution)
        array = np.asarray(image, dtype=np.uint8)
        return [int.from_bytes(np.packbits(row, bitorder="little").tobytes(), "little") for row in array]

    @classmethod
    def _paint_rows(cls, geom, rows, ox, oy, resolution, width, height):
        image = Image.new("1", (width, height), 0)
        cls._draw_geometry(ImageDraw.Draw(image), geom, ox, oy, 1.0 / resolution)
        array = np.asarray(image, dtype=np.uint8)
        for index, row in enumerate(array):
            rows[index] |= int.from_bytes(np.packbits(row, bitorder="little").tobytes(), "little")

    @classmethod
    def _paint_rows_incremental(cls, geom, rows, ox, oy, resolution, width, height):
        """Paint only the grid-aligned window touched by ``geom``."""
        minx, miny, maxx, maxy = geom.bounds
        x0 = max(0, math.floor((minx - ox) / resolution))
        y0 = max(0, math.floor((miny - oy) / resolution))
        x1 = min(width - 1, math.floor((maxx - ox) / resolution))
        y1 = min(height - 1, math.floor((maxy - oy) / resolution))
        if x1 < x0 or y1 < y0:
            return []
        local_width, local_height = x1 - x0 + 1, y1 - y0 + 1
        local_rows = cls._local_rows(
            geom, ox + x0 * resolution, oy + y0 * resolution,
            resolution, local_width, local_height,
        )
        changed_rows = []
        for offset, row in enumerate(local_rows):
            if row:
                row_index = y0 + offset
                rows[row_index] |= row << x0
                changed_rows.append((row_index, rows[row_index]))
        return changed_rows

    def _current_placements(self, items: list[ModelItem], plate_index: int) -> list[Placement]:
        result = []
        for item in items:
            t = item.z_transform
            x, y = self.project.local_position(item)
            geom = translate(item.footprint, xoff=x, yoff=y)
            result.append(Placement(item, plate_index, 0.0, x, y, geom))
        return result

    def _apply(self, assignments: list[list[Placement]], locks: list[bool]) -> int:
        moved = 0
        item_groups: list[list[ModelItem]] = []
        for plate_index, placements in enumerate(assignments, 1):
            item_groups.append([])
            for p in placements:
                old = p.item.z_transform
                old_plate = p.item.plate_index
                origin_x, origin_y = self.project.plate_origin(plate_index)
                if (old_plate != plate_index
                        or abs(old[9] - (p.x + origin_x)) > .01
                        or abs(old[10] - (p.y + origin_y)) > .01
                        or abs(float(p.angle) % 360.0) > .01):
                    moved += 1
                self.project.set_item_pose(p.item, plate_index, p.angle, p.x, p.y)
                item_groups[-1].append(p.item)
        self.project.assign_plates(item_groups, locks)
        return moved
