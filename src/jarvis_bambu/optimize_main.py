from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .core.api import optimize_project
from .optimizer_models import OptimizerOptions


def parse_args():
    parser = argparse.ArgumentParser(description="Optimizador de colocación para Bambu Studio")
    parser.add_argument("project", type=Path)
    parser.add_argument("--mode", choices=("simple", "advanced"), required=True)
    parser.add_argument("--effort", default="low", help="low, medium, high o minutos")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--preview-target", choices=("pc", "echo_show"), default="pc")
    parser.add_argument("--preview-mode", choices=("improvements", "debug"), default="improvements")
    parser.add_argument("--open", choices=("same", "separate", "none"), default="none")
    parser.add_argument("--bambu-exe", type=Path, default=Path(r"C:\Program Files\Bambu Studio\bambu-studio.exe"))
    return parser.parse_args()


def run() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    suffix = "optimizado_simple" if args.mode == "simple" else "optimizado_avanzado"
    output = args.project.with_name(f"{args.project.stem}_{suffix}.3mf")
    options = OptimizerOptions(
        mode=args.mode,
        effort=args.effort,
        preview=args.preview,
        preview_target=args.preview_target,
        preview_mode=args.preview_mode,
    )
    result = optimize_project(args.project, options, output)
    print(json.dumps({
        "ok": True, "improved": result.improved, "message": result.message,
        "output": str(result.output_path) if result.improved else "",
        "plates_before": result.original_plate_count, "plates_after": result.final_plate_count,
        "generations": result.generations,
    }, ensure_ascii=False))
    if result.improved and args.open != "none":
        subprocess.Popen([str(args.bambu_exe), str(output)])
    return 0


def main():
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
