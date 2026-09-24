"""Diagnostic entrypoint used to validate a frozen Windows build."""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


def run_build_smoke(report_path: Path) -> None:
    started = time.monotonic()

    import numpy
    import openpyxl
    import psutil
    import shapely
    import yaml
    from PySide6.QtCore import QLibraryInfo
    from PySide6.QtWidgets import QApplication
    from shapely.geometry import box

    from jarvis_bambu.bambu_session import BambuSession
    from jarvis_bambu.core.installation import InstallationSettingsStore
    from jarvis_bambu.gui.app import MainWindow
    from jarvis_bambu.nesting_optimizer import NestingOptimizer, NestingPerformanceMetrics
    from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions
    from jarvis_bambu.models import PieceMetrics
    from jarvis_bambu.price_analysis import GlobalPriceOptions, PriceAnalysisItem, analyze_price_files, export_price_analysis, recalculate_price_totals
    from jarvis_bambu.resources import resource_path

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page_names = sorted(window.tools)
    window.close()
    app.processEvents()

    optimizer = object.__new__(NestingOptimizer)
    optimizer.options = OptimizerOptions(
        "advanced", "low", optimizer_workers=2,
        preserve_exact_evolution=True, global_seed=8675309,
    )
    optimizer.started = time.monotonic()
    optimizer.deadline = None
    optimizer.padding = optimizer.bed_padding = 0.5
    optimizer.bed = box(0, 0, 55, 55)
    optimizer.safe_bed = optimizer.bed.buffer(-0.5)
    optimizer._rotation_cache = {}
    optimizer._buffered_rotation_cache = {}
    optimizer._raster_cache = {}
    optimizer._dimension_cache = {}
    optimizer.performance = NestingPerformanceMetrics()
    optimizer.spatial_hash_cell_size = 15.0

    transform = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    models = [
        ModelItem(i, str(i), 1, box(0, 0, 24, 24), transform, ET.Element("instance"))
        for i in range(5)
    ]
    solution = optimizer._search_advanced(models)

    pricing_folder=report_path.parent/"pricing-smoke"; pricing_folder.mkdir(parents=True,exist_ok=True)
    stl=pricing_folder/"smoke.stl"; stl.write_text("solid smoke\nendsolid smoke\n",encoding="ascii")
    three_mf=pricing_folder/"smoke.3mf"
    with ZipFile(three_mf,"w") as archive:
        archive.writestr("3D/3dmodel.model",'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/><build><item objectid="1"/></build></model>')
    price_items=[PriceAnalysisItem(stl),PriceAnalysisItem(three_mf)]; price_options=GlobalPriceOptions(work_folder=pricing_folder)
    price_result=analyze_price_files(price_items,price_options,processor=lambda path:PieceMetrics(path,60,25,None,"P2S","PLA","Standard"))
    price_output=export_price_analysis(price_result,price_options,pricing_folder/"smoke-prices.xlsx",resource_path("Plantilla_Analisis_Piezas.xlsx"))

    from jarvis_bambu.core.stl_color_map import _build_height_map
    from jarvis_bambu.core.dsc_export import export_dsc
    color_mesh = numpy.array([[[0,0,0],[10,0,0],[0,10,0]], [[0,0,2],[10,0,2],[0,10,2]]], dtype=float)
    color_model = _build_height_map(Path('build-smoke.stl'), color_mesh, sample_count=40, source_type='stl')
    color_export = export_dsc(pricing_folder/'color-map-smoke.zip', color_model, [1.0], size=256)
    with ZipFile(color_export) as archive:
        color_manifest = json.loads(archive.read('model-map.json'))
    color_map_ok = color_manifest['package_schema'] == 'dsc.preview-package.v2' and len(color_manifest['zones']) == 2

    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    settings = InstallationSettingsStore().load()
    bambu_window, _ = BambuSession._find_bambu_window()
    bambu_focus_verified = False
    if bambu_window is not None:
        session = BambuSession(Path(), "", report_path.parent, timeout=30)
        session.connect(launch_if_missing=False)
        bambu_focus_verified = True
    report = {
        "ok": bool(color_map_ok),
        "color_map": {"export_created": color_export.is_file(), "zones": len(color_manifest["zones"])},
        "versions": {
            "numpy": numpy.__version__, "shapely": shapely.__version__,
            "psutil": psutil.__version__, "openpyxl": openpyxl.__version__,
            "yaml": yaml.__version__,
        },
        "qt_windows_plugin": (plugins / "platforms" / "qwindows.dll").is_file(),
        "gui_pages": page_names,
        "device_id": settings.device_id,
        "multiprocessing": {
            "workers": 2,
            "worker_tasks": optimizer.performance.worker_tasks,
            "placements": sum(len(plate) for plate in solution),
        },
        "bambu_window_detected": bambu_window is not None,
        "bambu_focus_verified": bambu_focus_verified,
        "pricing": {"items": len(price_result.items), "formats": sorted(item.file_type for item in price_items), "analyzed": all(item.state == "analyzed" for item in price_items), "excel_created": price_output.is_file()},
        "elapsed_seconds": time.monotonic() - started,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
