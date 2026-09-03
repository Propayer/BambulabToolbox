"""Diagnostic entrypoint used to validate a frozen Windows build."""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path


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

    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    settings = InstallationSettingsStore().load()
    bambu_window, _ = BambuSession._find_bambu_window()
    bambu_focus_verified = False
    if bambu_window is not None:
        session = BambuSession(Path(), "", report_path.parent, timeout=30)
        session.connect(launch_if_missing=False)
        bambu_focus_verified = True
    report = {
        "ok": True,
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
        "elapsed_seconds": time.monotonic() - started,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
