from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class SupportQuery:
    source_id: str
    sender: str
    category: str
    message: str
    timestamp: str


class QueryService:
    def __init__(self, transport=None):
        self.transport = transport

    def send(self, source_id, sender, category, message):
        query = SupportQuery(source_id, sender, category, message,
                             datetime.now(timezone.utc).isoformat())
        if self.transport is None:
            raise RuntimeError("Servicio JARVIS no configurado")
        return self.transport.send(query)
