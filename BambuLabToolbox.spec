# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs


project_root = Path(SPECPATH)
icon_path = project_root / "assets" / "BambuLabToolbox.ico"

# Standard hooks handle PySide6/Qt, NumPy and openpyxl. Shapely ships native
# GEOS libraries, collected explicitly for reliable frozen execution.
binaries = collect_dynamic_libs("shapely")

a = Analysis(
    [str(project_root / "src" / "jarvis_bambu" / "gui" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=[(str(project_root / "Plantilla_Analisis_Piezas.xlsx"), "."), (str(project_root / "assets"), "assets")],
    hiddenimports=["numpy", "shapely", "yaml", "psutil", "openpyxl"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BambuLabToolbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BambuLabToolbox",
)
