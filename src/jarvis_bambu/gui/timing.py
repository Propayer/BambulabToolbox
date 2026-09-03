def format_duration(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def human_duration(seconds):
    if seconds is None:
        return "sin límite fijo"
    if seconds < 60:
        return f"{int(seconds)} s"
    minutes = seconds / 60
    return f"{int(minutes) if minutes.is_integer() else minutes:g} min"


def remaining_display(elapsed, deadline):
    if deadline is None:
        return "Sin límite fijo"
    if elapsed >= deadline:
        return "Finalizando..."
    return format_duration(max(0, deadline - elapsed))
