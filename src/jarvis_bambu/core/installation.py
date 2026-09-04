from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class InstallationSettings:
    device_id: str
    display_name: str = "Mi equipo BambuLab"
    owner: str = ""
    location: str = ""
    default_workers: int = 0
    bambu_studio_executable: str = ""
    price_global_multiplier: float = 1.0
    price_visible_columns: list[str] = field(default_factory=list)
    price_column_order: list[str] = field(default_factory=list)
    price_last_import_folder: str = ""
    price_last_export_folder: str = ""


class InstallationSettingsStore:
    def __init__(self, path: Path | None = None):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
        self.path = path or base / "CajaHerramientasBambuLab" / "settings.json"

    def load(self) -> InstallationSettings:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return InstallationSettings(**raw)
        settings = InstallationSettings(device_id=str(uuid.uuid4()))
        self.save(settings)
        return settings

    def save(self, settings: InstallationSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
