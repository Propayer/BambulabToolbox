from __future__ import annotations

import re


WEIGHT_PATTERNS = [
    re.compile(r"(?i)(?:peso|weight|filament[^\n]{0,30})(?:\s*[:=]\s*)?(\d+(?:[.,]\d+)?)\s*g\b"),
    re.compile(r"(?i)\b(\d+(?:[.,]\d+)?)\s*g\b"),
]

TIME_PATTERNS = [
    re.compile(r"(?i)(?:(\d+)\s*h(?:oras?)?\s*)?(?:(\d+)\s*m(?:in(?:utos?)?)?\s*)?(?:(\d+)\s*s(?:eg(?:undos?)?)?)"),
    re.compile(r"(?i)(\d+)\s*:\s*(\d+)\s*:\s*(\d+)"),
]


def parse_weight_grams(text: str) -> float | None:
    for pattern in WEIGHT_PATTERNS:
        match = pattern.search(text)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def parse_time_minutes(text: str) -> float | None:
    colon = TIME_PATTERNS[1].search(text)
    if colon:
        hours, minutes, seconds = map(int, colon.groups())
        return hours * 60 + minutes + seconds / 60

    labelled = re.search(
        r"(?i)(?:tiempo|time)[^\n]{0,40}?(?:(\d+)\s*h[^\d]*)?(?:(\d+)\s*m[^\d]*)?(?:(\d+)\s*s)?",
        text,
    )
    if labelled and any(value is not None for value in labelled.groups()):
        hours, minutes, seconds = (int(value or 0) for value in labelled.groups())
        return hours * 60 + minutes + seconds / 60
    return None

