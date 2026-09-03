from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from .bambu_controller import BambuStudioController
from .cli_controller import BambuStudioCliController
from .discovery import discover_pieces
from .excel_report import ExcelReport
from .global_report import GlobalReportBuilder
from .models import ConfigurationError, PieceProcessingError
from .mqtt_status import MqttStatus
from .settings import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analizador Bambu para Proyecto JARVIS")
    parser.add_argument("--mode", choices=("latest", "today", "all"), default="latest")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--global-report", action="store_true")
    return parser.parse_args()


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run() -> int:
    args = parse_args()
    root = project_root()
    config_path = args.config or (root / "config.yaml")
    config = load_config(config_path)
    defaults = config.raw["defaults"]
    day_text = date.today().strftime("%Y-%m-%d")
    workbook_path = config.workbook_path(day_text)
    template_path = root / "Plantilla_Analisis_Piezas.xlsx"
    work_folder = config.output_folder / "capturas" / day_text

    global_builder = GlobalReportBuilder(
        config.output_folder,
        template_path,
        defaults,
        str(config.raw["general"].get("global_workbook_name", "Registro_global_piezas.xlsx")),
    )

    with MqttStatus(config.raw["mqtt"]) as mqtt:
        mqtt.publish("status", "iniciando")
        if args.global_report:
            global_path = global_builder.build()
            message = f"Registro global guardado en {global_path}."
            mqtt.publish("status", "registro global actualizado")
            mqtt.publish("result", message)
            print(message)
            return 0
        if args.diagnose:
            controller = BambuStudioController(
                config.raw["bambu_studio"], defaults, work_folder
            )
            diagnostic = controller.diagnose()
            mqtt.publish("status", "diagnóstico completado")
            mqtt.publish("result", f"Diagnóstico guardado en {diagnostic}")
            print(diagnostic)
            return 0

        pieces = discover_pieces(
            config.downloads_folder, config.extensions, args.mode
        )
        if not pieces:
            message = "No he encontrado piezas STL que cumplan el criterio."
            mqtt.publish("status", "sin archivos")
            mqtt.publish("result", message)
            print(message)
            return 2

        report = ExcelReport(workbook_path, template_path, defaults)
        controller_class = (
            BambuStudioCliController
            if config.raw["bambu_studio"].get("automation_mode", "cli") == "cli"
            else BambuStudioController
        )
        controller = None if args.dry_run else controller_class(
            config.raw["bambu_studio"], defaults, work_folder
        )
        processed = 0
        skipped = 0
        errors = []

        for source_path in pieces:
            mqtt.publish("current_piece", source_path.name)
            if config.raw["general"].get("skip_already_registered", True) and report.contains(source_path):
                skipped += 1
                continue
            if args.dry_run:
                print(source_path)
                continue
            try:
                mqtt.publish("status", "analizando")
                metrics = controller.process(source_path)
                report.append_success(metrics)
                processed += 1
            except (PieceProcessingError, Exception) as exc:
                screenshot = controller.capture_error(source_path) if controller else None
                report.append_error(source_path, str(exc), screenshot)
                errors.append(f"{source_path.name}: {exc}")
                if not config.raw["general"].get("continue_after_piece_error", True):
                    break

        if args.dry_run:
            return 0
        try:
            global_path = global_builder.build()
        except Exception as exc:
            errors.append(f"Registro global: {exc}")
        summary = (
            f"He analizado {processed} piezas, omitido {skipped} repetidas y "
            f"encontrado {len(errors)} errores. Excel guardado como {workbook_path.name} "
            f"en {workbook_path.parent}."
        )
        mqtt.publish("workbook", str(workbook_path))
        if 'global_path' in locals():
            mqtt.publish("global_workbook", str(global_path))
        mqtt.publish("result", summary)
        mqtt.publish("status", "completado con errores" if errors else "completado")
        print(summary)
        if errors:
            error_file = workbook_path.with_suffix(".errores.txt")
            error_file.write_text("\n".join(errors), encoding="utf-8")
            return 1
        return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except ConfigurationError as exc:
        print(f"ERROR DE CONFIGURACIÓN: {exc}", file=sys.stderr)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
