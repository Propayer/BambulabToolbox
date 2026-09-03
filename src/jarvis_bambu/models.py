from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PieceMetrics:
    source_path: Path
    print_minutes: float
    weight_grams: float
    preview_path: Path | None
    machine: str
    material: str
    profile: str
    sync_status: str = "No requerido"
    notes: str = ""


class PieceProcessingError(RuntimeError):
    """Error recuperable limitado a una pieza."""


class ConfigurationError(RuntimeError):
    """Configuración incompleta o incompatible."""

