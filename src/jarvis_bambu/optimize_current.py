from __future__ import annotations

import argparse
import json
import os
import sys
import logging
from pathlib import Path

from .bambu_session import BambuSession, read_optimizer_state, write_optimizer_state
from .optimizer_models import OptimizerOptions
from .integrations.mqtt_optimizer import optimize_project_from_mqtt
from .mqtt_status import MqttStatus
from .settings import load_config


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _session(config):
    bambu = config.raw["bambu_studio"]
    opt = config.raw.get("optimizer", {})
    executable = str(bambu.get("executable", "")).strip() or r"C:\Program Files\Bambu Studio\bambu-studio.exe"
    backup = _expand(opt.get("project_backup_folder", r"%USERPROFILE%\Documents\Jarvis\Proyectos Bambu"))
    return BambuSession(
        Path(executable), bambu.get("window_title_regex", ".*Bambu Studio.*"), backup,
        int(opt.get("save_dialog_timeout_seconds", 30)),
    )


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("simple", "advanced"))
    parser.add_argument("--effort", help="low, medium, high o minutos")
    parser.add_argument("--after", choices=("ask", "same", "separate"), default="ask")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--preview-target", choices=("pc", "echo_show"))
    parser.add_argument("--preview-mode", choices=("improvements", "debug"))
    parser.add_argument(
        "--from-mqtt", action="store_true",
        help="Lee modo, esfuerzo, apertura y preview desde los topics retenidos de MQTT",
    )
    parser.add_argument("--open-ready", choices=("same", "separate"))
    parser.add_argument("--config", type=Path, default=_root() / "config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    opt_config = config.raw.get("optimizer", {})
    state_path = _expand(opt_config.get("state_file", r"%USERPROFILE%\Documents\Jarvis\Proyectos Bambu\ultima_optimizacion.json"))
    session = _session(config)
    try:
        if args.open_ready:
            state = read_optimizer_state(state_path)
            if not state.get("output"):
                raise RuntimeError("No hay una optimización pendiente de abrir")
            output = Path(state["output"])
            if args.open_ready == "same":
                session.open_same_window(output)
            else:
                session.open_separate(output)
            print(json.dumps({"ok": True, "message": f"He abierto {output.name}."}, ensure_ascii=False))
            return
        if not args.mode or not args.effort:
            if not args.from_mqtt:
                raise ValueError("Faltan --mode y --effort")
        with MqttStatus(config.raw["mqtt"]) as mqtt:
            mode = args.mode
            effort = args.effort
            after = args.after
            preview = args.preview
            if args.from_mqtt:
                mode = mqtt.read_retained("optimizer_config/mode", "simple")
                effort = mqtt.read_retained("optimizer_config/effort", "low")
                after = mqtt.read_retained("optimizer_config/after", "ask")
                preview = mqtt.read_retained(
                    "optimizer_config/preview", "off"
                ).lower() in ("1", "true", "on", "yes", "si", "sí")
            if mode not in ("simple", "advanced"):
                raise ValueError(f"Modo recibido no válido: {mode}")
            if after not in ("ask", "same", "separate"):
                raise ValueError(f"Política de apertura no válida: {after}")
            preview_target = args.preview_target or mqtt.read_retained(
                "preview_target", "pc"
            )
            preview_mode = args.preview_mode or mqtt.read_retained(
                "preview_mode", "improvements"
            )
            if preview_target not in ("pc", "echo_show"):
                preview_target = "pc"
            if preview_mode not in ("improvements", "debug"):
                preview_mode = "improvements"
            debug_verbose = bool(opt_config.get("debug_verbose", False))
            logging.basicConfig(
                level=logging.DEBUG if preview_mode == "debug" or debug_verbose else logging.INFO,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
            run_config = {
                "mode": mode, "effort": effort, "after": after,
                "preview": preview, "preview_target": preview_target,
                "preview_mode": preview_mode,
            }
            mqtt.publish("optimizer_run_config", json.dumps(run_config, ensure_ascii=False))
            print("Configuración recibida: " + json.dumps(run_config, ensure_ascii=False), flush=True)
            mqtt.publish("status", "guardando proyecto actual")
            source = session.save_snapshot()
            suffix = "optimizado_simple" if mode == "simple" else "optimizado_avanzado"
            output = source.with_name(f"{source.stem}_{suffix}.3mf")
            mqtt.publish("status", "optimizando colocación")
            options = OptimizerOptions(
                mode,
                effort,
                after == "ask",
                preview,
                preview_target,
                preview_mode,
                float(opt_config.get("compactness_weight", 1.0)),
                float(opt_config.get("fragmentation_weight", 2.0)),
                float(opt_config.get("largest_free_region_weight", 1.0)),
                float(opt_config.get("small_gap_penalty", 2.0)),
                float(opt_config.get("small_gap_area_mm2", 400.0)),
                int(opt_config.get("preview_update_interval_ms", 50)),
                debug_verbose,
            )
            result = optimize_project_from_mqtt(source, output, options, mqtt)
            payload = {
                "ok": True, "improved": result.improved, "message": result.message,
                "source": str(source), "output": str(output) if result.improved else "",
                "mode": mode, "effort": effort,
                "preview": preview,
                "preview_target": preview_target,
                "preview_mode": preview_mode,
                "generations": result.generations,
                "awaiting_open_choice": result.improved and after == "ask",
            }
            write_optimizer_state(state_path, payload)
            if result.improved:
                if after == "same":
                    mqtt.publish("status", "abriendo optimización")
                    session.open_same_window(output)
                elif after == "separate":
                    mqtt.publish("status", "abriendo optimización")
                    session.open_separate(output)
                else:
                    mqtt.publish("status", "listo para abrir")
            else:
                mqtt.publish("status", "sin mejoras")
            mqtt.publish("result", payload["message"])
        print(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        payload = {"ok": False, "message": str(exc), "awaiting_open_choice": False}
        if not args.open_ready:
            write_optimizer_state(state_path, payload)
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
