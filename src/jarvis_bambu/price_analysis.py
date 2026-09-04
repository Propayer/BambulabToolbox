from __future__ import annotations

import json
import math
import struct
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from xml.etree import ElementTree

from .cli_controller import BambuStudioCliController
from .excel_report import DEFAULT_PRICE_COLUMNS, ExcelReport, MANDATORY_PRICE_COLUMNS
from .models import PieceMetrics

SUPPORTED_PRICE_EXTENSIONS = frozenset({".3mf", ".stl"})
DEFAULT_PRICE_DEFAULTS = {
    "machine": "P2S", "material": "PLA", "profile": "0.20 mm Standard",
    "filament_diameter_mm": 1.75, "filament_density_g_cm3": 1.26,
    "filament_cost_per_gram": 0.0115, "machine_wear_per_hour": 0.20,
    "filament_sale_multiplier": 3.0,
}


@dataclass(slots=True)
class PriceAnalysisItem:
    path: Path
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    display_name: str = ""
    file_type: str = ""
    quantity: int = 1
    price_multiplier: float = 1.0
    enabled: bool = True
    state: str = "imported"
    piece_count: int | None = None
    metrics: PieceMetrics | None = None
    error: str = ""

    def __post_init__(self):
        self.path = self.path.resolve()
        self.display_name = self.display_name or self.path.name
        self.file_type = self.file_type or self.path.suffix.lower().lstrip(".").upper()


@dataclass(slots=True)
class GlobalPriceOptions:
    global_multiplier: float = 1.0
    visible_categories: list[str] = field(default_factory=lambda: list(DEFAULT_PRICE_COLUMNS))
    defaults: dict = field(default_factory=lambda: dict(DEFAULT_PRICE_DEFAULTS))
    bambu_config: dict = field(default_factory=dict)
    work_folder: Path = field(default_factory=lambda: Path.cwd() / "pricing_work")


@dataclass(slots=True)
class PriceTotals:
    files: int = 0
    units: int = 0
    weight_grams: float | None = None
    print_minutes: float | None = None
    base_cost: float | None = None
    final_price: float | None = None


@dataclass(slots=True)
class PriceAnalysisResult:
    items: list[PriceAnalysisItem]
    totals: PriceTotals
    warnings: list[str]
    elapsed_seconds: float


def inspect_price_file(path: Path) -> int | None:
    path = path.resolve()
    if path.suffix.lower() == ".3mf":
        try:
            with zipfile.ZipFile(path) as archive:
                root = ElementTree.fromstring(archive.read("3D/3dmodel.model"))
                return len(root.findall(".//{*}build/{*}item"))
        except Exception:
            return None
    if path.suffix.lower() == ".stl":
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                header = handle.read(84)
            if len(header) == 84:
                triangles = struct.unpack("<I", header[80:84])[0]
                if 84 + triangles * 50 == size:
                    return 1
            return 1 if path.read_bytes().lstrip().lower().startswith(b"solid") else None
        except OSError:
            return None
    return None


def price_components(metrics: PieceMetrics, defaults: dict) -> tuple[float, float, float]:
    filament = metrics.weight_grams * float(defaults["filament_cost_per_gram"])
    wear = metrics.print_minutes / 60.0 * float(defaults["machine_wear_per_hour"])
    base = filament * float(defaults["filament_sale_multiplier"]) + wear
    return filament, wear, base


def read_embedded_3mf_metrics(path: Path, defaults: dict, work_folder: Path) -> PieceMetrics | None:
    if path.suffix.lower() != ".3mf":
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("Metadata/slice_info.config"))
            minutes = 0.0; grams = 0.0
            for plate in root.findall("plate"):
                metadata = {node.attrib.get("key"): node.attrib.get("value", "") for node in plate.findall("metadata")}
                minutes += float(metadata.get("prediction", 0)) / 60.0
                for filament in plate.findall("filament"):
                    if filament.attrib.get("used_g"):
                        grams += float(filament.attrib["used_g"])
                    elif filament.attrib.get("used_m"):
                        used_m=float(filament.attrib["used_m"]); diameter=float(defaults.get("filament_diameter_mm",1.75)); density=float(defaults.get("filament_density_g_cm3",1.26)); grams += math.pi*(diameter/2)**2*(used_m*1000)/1000*density
            if minutes <= 0 or grams <= 0:
                return None
            preview=None; preview_name="Metadata/plate_1.png"
            if preview_name in archive.namelist():
                work_folder.mkdir(parents=True,exist_ok=True); preview=work_folder/f"{path.stem}_preview.png"; preview.write_bytes(archive.read(preview_name))
        return PieceMetrics(path,minutes,round(grams,2),preview,str(defaults["machine"]),str(defaults["material"]),str(defaults["profile"]),"Datos incluidos en 3MF")
    except Exception:
        return None


def item_final_price(item: PriceAnalysisItem, options: GlobalPriceOptions) -> float | None:
    if item.metrics is None:
        return None
    base = price_components(item.metrics, options.defaults)[2]
    return base * max(1, item.quantity) * options.global_multiplier * item.price_multiplier


def recalculate_price_totals(items: Iterable[PriceAnalysisItem], options: GlobalPriceOptions) -> PriceTotals:
    enabled = [item for item in items if item.enabled]
    analyzed = [item for item in enabled if item.metrics is not None]
    return PriceTotals(
        files=len(enabled), units=sum(max(1, item.quantity) for item in enabled),
        weight_grams=(sum(item.metrics.weight_grams * item.quantity for item in analyzed) if analyzed else None),
        print_minutes=(sum(item.metrics.print_minutes * item.quantity for item in analyzed) if analyzed else None),
        base_cost=(sum(price_components(item.metrics, options.defaults)[2] * item.quantity for item in analyzed) if analyzed else None),
        final_price=(sum(item_final_price(item, options) or 0 for item in analyzed) if analyzed else None),
    )


def analyze_price_files(
    items: list[PriceAnalysisItem], options: GlobalPriceOptions,
    progress_callback: Callable[[dict], None] | None = None,
    processor: Callable[[Path], PieceMetrics] | None = None,
) -> PriceAnalysisResult:
    started = time.monotonic(); warnings = []
    controller = None
    for index, item in enumerate(items, 1):
        if not item.enabled:
            continue
        item.state = "analyzing"; item.error = ""
        if progress_callback:
            progress_callback({"current": index, "total": len(items), "item_id": item.id, "path": str(item.path), "state": item.state})
        try:
            if processor is None:
                metrics = read_embedded_3mf_metrics(item.path,options.defaults,options.work_folder)
                if metrics is None:
                    if controller is None:
                        controller = BambuStudioCliController(options.bambu_config, options.defaults, options.work_folder)
                    metrics = controller.process(item.path)
            else:
                metrics = processor(item.path)
            item.metrics = metrics; item.state = "analyzed"
        except Exception as exc:
            item.state = "error"; item.error = str(exc); warnings.append(f"{item.display_name}: {exc}")
        if progress_callback:
            progress_callback({"current": index, "total": len(items), "item_id": item.id, "path": str(item.path), "state": item.state, "error": item.error})
    return PriceAnalysisResult(items, recalculate_price_totals(items, options), warnings, time.monotonic() - started)


def export_price_analysis(
    result: PriceAnalysisResult, options: GlobalPriceOptions,
    output: Path, template: Path,
) -> Path:
    output = output.resolve()
    if output.exists():
        output.unlink()
    report = ExcelReport(output, template, options.defaults)
    for item in result.items:
        if item.enabled and item.metrics is not None:
            report.append_priced_success(item.metrics, item.quantity, item.price_multiplier, options.global_multiplier)
        elif item.enabled and item.error:
            report.append_error(item.path, item.error, None)
    selected = list(dict.fromkeys([*MANDATORY_PRICE_COLUMNS, *options.visible_categories]))
    report.configure_price_columns(selected)
    return output
