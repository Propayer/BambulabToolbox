from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    id: str
    name: str
    description: str
    icon: str
    widget_factory: Callable
    enabled: bool = True
