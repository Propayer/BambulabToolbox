from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import ConfigurationError


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def windows_downloads_folder() -> Path:
    """Obtiene Descargas sin asumir que esté en USERPROFILE/Downloads."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            guid = GUID(
                0x374DE290,
                0x123F,
                0x4565,
                (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B),
            )
            path_ptr = ctypes.c_void_p()
            result = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
            )
            if result == 0 and path_ptr.value:
                path = Path(ctypes.cast(path_ptr, ctypes.c_wchar_p).value)
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                return path
        except Exception:
            pass
    return Path.home() / "Downloads"


@dataclass(slots=True)
class AppConfig:
    raw: dict[str, Any]
    config_path: Path

    @property
    def downloads_folder(self) -> Path:
        configured = str(self.raw["general"].get("downloads_folder", "")).strip()
        return _expand(configured) if configured else windows_downloads_folder()

    @property
    def output_folder(self) -> Path:
        return _expand(self.raw["general"]["output_folder"])

    @property
    def extensions(self) -> tuple[str, ...]:
        return tuple(x.lower() for x in self.raw["general"]["include_extensions"])

    def workbook_path(self, day_text: str) -> Path:
        name = self.raw["general"]["workbook_name"].format(date=day_text)
        return self.output_folder / name


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise ConfigurationError(
            f"No existe {path}. Copia config.example.yaml como config.yaml."
        )
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    for section in ("general", "defaults", "bambu_studio", "mqtt"):
        if section not in raw:
            raise ConfigurationError(f"Falta la sección '{section}' en {path}")
    return AppConfig(raw=raw, config_path=path)
