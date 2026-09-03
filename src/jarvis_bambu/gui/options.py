from ..optimizer_models import OptimizerOptions


EFFORTS = {"Rápido": "low", "Medio": "medium", "Alto": "high"}
WORKERS = {"Auto": 0, "1": 1, "2": 2, "4": 4, "6": 6}


def build_optimizer_options(mode, effort, preview, preview_mode, workers):
    effort_key = effort.split(" —", 1)[0]
    return OptimizerOptions(
        mode="simple" if mode == "Simple" else "advanced",
        effort=EFFORTS.get(effort_key, effort_key), preview=bool(preview),
        preview_mode="improvements" if preview_mode == "normal" else "debug",
        optimizer_workers=WORKERS.get(str(workers), int(workers) if str(workers).isdigit() else 0),
    )


def effort_deadline_seconds(label):
    key = EFFORTS.get(label.split(" —", 1)[0], label)
    return OptimizerOptions("advanced", key).time_limit_seconds
