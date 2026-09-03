from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .bambu_session import BambuSession
from .settings import load_config


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Localiza, restaura y enfoca Bambu Studio")
    parser.add_argument("--config", type=Path, default=root / "config.yaml")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config)
    bambu = config.raw["bambu_studio"]
    optimizer = config.raw.get("optimizer", {})
    executable = str(bambu.get("executable", "")).strip() or r"C:\Program Files\Bambu Studio\bambu-studio.exe"
    backup = Path(os.path.expandvars(str(optimizer.get(
        "project_backup_folder", r"%USERPROFILE%\Documents\Jarvis\Proyectos Bambu"
    ))))
    timeout = int(bambu.get("startup_timeout_seconds", 30))
    session = BambuSession(
        Path(executable), str(bambu.get("window_title_regex", ".*Bambu Studio.*")),
        backup, timeout,
    )
    window = session.ensure_bambu_studio_active()
    print(f"Bambu Studio activo: HWND={int(window.handle)}")


if __name__ == "__main__":
    main()
