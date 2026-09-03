from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .models import ConfigurationError, PieceMetrics, PieceProcessingError


class BambuStudioCliController:
    """Laminate files through Bambu Studio's CLI without GUI automation."""

    def __init__(self, config: dict, defaults: dict, work_folder: Path):
        self.config = config
        self.defaults = defaults
        self.work_folder = work_folder
        self.work_folder.mkdir(parents=True, exist_ok=True)
        self.executable = self._find_executable()

    def _find_executable(self) -> Path:
        configured = str(self.config.get("executable", "")).strip()
        candidates = [Path(configured)] if configured else []
        candidates.extend(
            [
                Path(r"C:\Program Files\Bambu Studio\bambu-studio.exe"),
                Path(r"C:\Program Files\Bambu Studio\BambuStudio.exe"),
            ]
        )
        for path in candidates:
            if path.exists():
                return path
        raise ConfigurationError("No se encuentra Bambu Studio.")

    def process(self, source_path: Path) -> PieceMetrics:
        output_dir = self.work_folder / source_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        result_3mf = output_dir / "resultado.3mf"
        profile_root = self.executable.parent / "resources" / "profiles" / "BBL"
        machine = profile_root / "machine" / "Bambu Lab P2S 0.4 nozzle.json"
        process = profile_root / "process" / "0.20mm Standard @BBL P2S.json"
        filament = profile_root / "filament" / "Bambu PLA Basic @BBL P2S.json"
        for profile in (machine, process, filament):
            if not profile.exists():
                raise ConfigurationError(f"No se encuentra el perfil: {profile}")

        command = [
            str(self.executable),
            "--debug", "2",
            "--arrange", "1",
            "--ensure-on-bed",
            "--load-settings", f"{machine};{process}",
            "--load-filaments", str(filament),
            "--load-defaultfila",
            "--slice", "0",
            "--export-3mf", result_3mf.name,
            "--outputdir", str(output_dir),
            str(source_path),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=int(self.config.get("slicing_timeout_seconds", 900)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not result_3mf.exists():
            detail = (completed.stderr or completed.stdout)[-2000:]
            raise PieceProcessingError(f"Falló Bambu Studio CLI: {detail}")

        return self._read_result(source_path, result_3mf)

    def _read_result(self, source_path: Path, result_3mf: Path) -> PieceMetrics:
        try:
            with zipfile.ZipFile(result_3mf) as archive:
                root = ElementTree.fromstring(archive.read("Metadata/slice_info.config"))
                plate = root.find("plate")
                if plate is None:
                    raise ValueError("Falta la sección plate")
                metadata = {
                    item.attrib.get("key"): item.attrib.get("value", "")
                    for item in plate.findall("metadata")
                }
                filament = plate.find("filament")
                if filament is None:
                    raise ValueError("Faltan los datos de filamento")
                used_m = float(filament.attrib["used_m"])
                minutes = float(metadata["prediction"]) / 60.0
                grams = self._grams_from_length(used_m)
                preview = self.work_folder / f"{source_path.stem}_preview.png"
                preview.write_bytes(archive.read("Metadata/plate_1.png"))
        except Exception as exc:
            raise PieceProcessingError(f"No pude leer el resultado 3MF: {exc}") from exc

        return PieceMetrics(
            source_path=source_path,
            print_minutes=minutes,
            weight_grams=grams,
            preview_path=preview,
            machine=str(self.defaults["machine"]),
            material=str(self.defaults["material"]),
            profile=str(self.defaults["profile"]),
            sync_status="No requerido (CLI)",
        )

    def _grams_from_length(self, used_m: float) -> float:
        diameter_mm = float(self.defaults.get("filament_diameter_mm", 1.75))
        density = float(self.defaults.get("filament_density_g_cm3", 1.26))
        volume_cm3 = math.pi * (diameter_mm / 2) ** 2 * (used_m * 1000) / 1000
        return round(volume_cm3 * density, 2)

    def capture_error(self, source_path: Path) -> None:
        return None
