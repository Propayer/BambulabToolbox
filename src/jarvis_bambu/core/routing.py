from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass(slots=True)
class RoutedRequest:
    request_id: str
    source_id: str
    target_id: str
    action: str
    payload: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def route_request(request: RoutedRequest, local_device_id: str,
                  handler: Callable[[RoutedRequest], object]):
    if request.target_id != local_device_id:
        return None
    return handler(request)
