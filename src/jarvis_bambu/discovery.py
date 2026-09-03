from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path


def file_identity(path: Path) -> str:
    stat = path.stat()
    seed = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:24]


def discover_pieces(
    folder: Path,
    extensions: tuple[str, ...],
    mode: str,
    target_date: date | None = None,
) -> list[Path]:
    if not folder.exists():
        raise FileNotFoundError(f"No existe la carpeta de descargas: {folder}")

    candidates = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in extensions
    ]
    candidates.sort(key=lambda path: path.stat().st_ctime)

    if mode == "latest":
        return candidates[-1:] if candidates else []
    if mode == "today":
        wanted = target_date or date.today()
        return [
            path
            for path in candidates
            if datetime.fromtimestamp(path.stat().st_ctime).date() == wanted
        ]
    if mode == "all":
        return candidates
    raise ValueError(f"Modo no compatible: {mode}")

